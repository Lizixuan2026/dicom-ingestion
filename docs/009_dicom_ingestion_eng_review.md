# DICOM Ingestion Module — Engineering Review

## 1. Review verdict

The architecture is directionally right. The execution plan is good enough to start from.

But it is **not yet safe to start coding** without first resolving several implementation-level decisions that currently sit between the lines:

1. duplicate SOP persistence semantics,
2. raw-byte write vs DB transaction ordering,
3. item idempotency key,
4. binding failure semantics,
5. exact state machines,
6. projection rebuild triggers,
7. study completeness semantics.

These are not polish. They change schema, retry behavior, and user-visible truth.

### Current verdict

> **Proceed after tightening the implementation contract below.**

No strategic rewrite needed. Several engineering decisions still need to be frozen.

### Resolution status

The recommended decisions in this review were subsequently folded into:

- `006_dicom_ingestion_architecture.md`
- `007_dicom_ingestion_implementation_plan.md`
- `008_dicom_ingestion_execution_breakdown.md`

The review findings below remain useful as rationale, but they are no longer open implementation questions.

One follow-on refinement was also folded into the main docs during resolution:

- raw tag sets and private tags are **observation-scoped**, not instance-scoped,
- duplicate findings identify the triggering observation as well as the matched logical instance / observation.

---

## 2. What is already strong

| Area | Assessment |
| --- | --- |
| product boundary | clear, non-PACS, platform-native |
| receive / store / index split | correct |
| raw bytes as canonical source | correct |
| explicit `header_only` path | correct |
| binding boundary | correct |
| duplicate facts vs ingest state | correct |
| reference preservation | correct |
| staged rollout | sensible |
| fixture-first posture | strong |

This is not a plan that needs to be thrown out. It needs the last hard edges filed down before implementation.

---

## 3. Critical architecture issues

## Issue 1 — Duplicate SOP identity is still underspecified

### Why this matters

The docs say:

- `dicom_instances.sop_instance_uid` is the natural key,
- duplicate SOPs are stored as findings,
- no silent overwrite.

Those three statements are not yet enough to implement the write path.

You still need to choose whether:

1. one logical `DicomInstance` can have many physical observations/files,
2. or each uploaded physical file becomes its own instance row even when SOP UID collides.

Those are very different models.

### Recommended decision

Use:

```text
dicom_instances              = logical DICOM identity
dicom_instance_observations  = physical uploaded occurrences
```

Where:

- `dicom_instances.sop_instance_uid` stays unique,
- every upload item can create an observation row,
- duplicate facts compare observations against the canonical logical instance,
- canonical selection policy is explicit and revisable.

### Why this is better

- preserves the neutral DICOM identity model,
- avoids fake uniqueness violations on repeated uploads,
- keeps provenance for each uploaded file,
- gives duplicate governance somewhere to live without corrupting `dicom_instances`.

### Plan gap

Current docs lack `dicom_instance_observations`.

### Severity

**CRITICAL**

---

## Issue 2 — The system currently has a hidden dual-write problem

### Why this matters

The desired flow is:

```text
persist raw bytes
  -> parse
  -> write DB rows
```

But object storage and the relational DB do not share a transaction.

So this can happen:

```text
object write succeeds
DB write fails
```

Now you have durable bytes with no canonical row, or worse, the retry uploads another copy because there is no persisted pointer.

### Recommended decision

Use a **staged object lifecycle**:

```text
staged upload object
  -> durable object pointer persisted on IngestionItem
  -> canonical records written
  -> item marked stored/accepted
```

If DB persistence fails after object storage succeeds:

- keep the `IngestionItem`,
- mark it `metadata_persistence_failed`,
- allow retry from the already-written object URI,
- do not re-upload or re-read user input.

### Required fields

Add or make explicit:

- `raw_object_status`
- `raw_object_uri`
- `raw_object_sha256`
- `metadata_persistence_status`
- `last_retryable_stage`

### Severity

**CRITICAL**

---

## Issue 3 — Item idempotency is named, not defined

### Why this matters

Without a hard idempotency rule, retries can:

- duplicate observations,
- duplicate duplicate-findings,
- create duplicate index work,
- make terminal reports lie.

### Recommended decision

Use two keys, because they solve two different problems:

```text
request_idempotency_key
  = caller-provided key for POST /dicom-ingestions

item_fingerprint
  = (ingestion_job_id, source_path, byte_size, whole_file_sha256)
```

If the same user intentionally uploads the same package again, that is a **new job** with new observations.  
If the same job retries, it must reuse the same item records.

### Why not checksum-only

Checksum-only collapses distinct user submissions into one operational identity. That is convenient for storage, wrong for provenance.

### Severity

**CRITICAL**

---

## Issue 4 — Binding failure semantics are still ambiguous

### Why this matters

The docs say binding failure should not destroy ingest truth. Correct.

But the product still needs to answer:

> If DICOM ingestion succeeds and binding fails, what does the user see?

Right now there is no exact answer.

### Recommended decision

Separate:

```text
ingestion_status = accepted | quarantined | rejected
binding_status   = pending | bound | failed | not_applicable
```

An item with valid DICOM and failed binding should be:

```text
ingestion_status = accepted
binding_status   = failed
```

unless a platform policy explicitly says failed binding is quarantine-worthy.

### Why

Otherwise “this file is valid DICOM” gets conflated with “our product workflow did not yet know what to do with it.”

### Severity

**HIGH**

---

## Issue 5 — The current item state model is not yet implementable

### Why this matters

`006` gives this:

```text
seen -> candidate -> parsed -> validated -> stored -> accepted
candidate -> rejected_non_dicom
parsed -> invalid_dicom
validated -> quarantined
stored -> duplicate_detected
```

But the execution plan also needs:

- object storage failure,
- metadata persistence failure,
- binding failure,
- index pending,
- retryable transient error,
- cancelled,
- permanently failed.

The current model is a product sketch, not a serviceable state machine.

### Recommended decision

Split item state into orthogonal axes:

```text
scan_status
parse_status
storage_status
validation_status
binding_status
index_status
terminal_outcome
```

And reserve `terminal_outcome` for what the user ultimately needs:

```text
accepted | quarantined | rejected | failed
```

### Why

A single overloaded status enum becomes a junk drawer. Every retry and every support case gets worse.

### Severity

**HIGH**

---

## Issue 6 — Projection rebuild is promised, but versioning is missing

### Why this matters

The docs correctly say projections are rebuildable. But they do not say when rebuild is required.

You need to know:

- which extraction version produced the canonical metadata,
- which projection schema version produced the query row,
- whether current projection is stale relative to current code.

### Recommended decision

Add:

- `metadata_extractor_version`
- `projection_version`
- `projection_built_at`
- `projection_source_checksum`

And define rebuild triggers:

1. manual rebuild,
2. projection-version bump,
3. extractor-version bump where affected fields changed.

### Severity

**HIGH**

---

## Issue 7 — Study completeness is currently decorative

### Why this matters

The schema includes `ingestion_completeness_status`, but no rule defines when a study is:

- `partial`
- `complete`
- `unknown`

For arbitrary uploads, “complete” is often unknowable. Pretending otherwise creates false confidence.

### Recommended decision

For v1:

```text
unknown = default
partial = known failures within this ingestion package
complete = only when a trusted external manifest or explicit upload contract says this package is complete
```

Do not infer “complete” merely because one batch finished without parser errors.

### Severity

**MEDIUM**

---

## 4. Recommended architecture adjustments

### 4.1 Revised write model

```text
UploadPackage
  └─ IngestionJob
      └─ IngestionItem
          └─ DicomInstanceObservation
                ├─ raw bytes
                ├─ parser result
                └─ duplicate facts

DicomInstance
  ├─ one logical SOP identity
  ├─ current canonical observation
  └─ reference edges / private tags / projections
```

### 4.2 Revised persistence path

```text
request
  -> persist upload package
  -> create job/items
  -> persist item bytes
  -> parse from stored bytes
  -> upsert logical identity
  -> create observation
  -> create side records
  -> bind
  -> enqueue projection
```

### 4.3 Revised core tables

Add:

#### `dicom_instance_observations`

| Column | Why |
| --- | --- |
| `id` | physical occurrence identity |
| `instance_id` | logical SOP identity |
| `ingestion_item_id` | provenance |
| `raw_object_uri` | bytes for this occurrence |
| `whole_file_sha256` | duplicate/content support |
| `pixel_digest` nullable | future richer duplicate analysis |
| `is_canonical` | selected observation |
| `observed_at` | audit |

Move from `dicom_instances` to observations where appropriate:

- `raw_object_uri`
- `first_seen_item_id`
- perhaps `whole_file_sha256`

Keep on `dicom_instances`:

- SOP identity,
- normalized logical metadata,
- current canonical observation pointer.

---

## 5. Error and rescue map

| Codepath | What can go wrong | Named failure | Rescue / behavior | User sees |
| --- | --- | --- | --- | --- |
| upload accept | nil body | `EmptyUploadRequest` | reject request | clear 4xx |
| upload accept | oversize body | `UploadTooLarge` | reject request | clear 4xx |
| package store | object write fails | `UploadPackageStoreFailed` | retry, then fail job | upload failed |
| scan | malformed ZIP | `ZipExtractionFailed` | fail package, preserve raw upload | job failed with reason |
| scan | ZIP bomb | `ZipBombDetected` | reject securely | job failed with reason |
| scan | path traversal | `UnsafeArchivePath` | reject securely | job failed with reason |
| parse | unreadable DICOM | `DicomParseFailed` | mark item invalid | item rejected |
| validate | missing SOP class | `MissingRequiredDicomTag` | reject item | item rejected |
| raw item store | write fails | `RawObjectStoreFailed` | retry item | item failed/retryable |
| metadata write | DB failure after raw store | `MetadataPersistenceFailed` | preserve item, retry from object URI | processing failed/retryable |
| canonical upsert | UID conflict | `LogicalIdentityConflict` | attach observation, create duplicate finding | duplicate visible |
| binding | policy error | `BindingPolicyFailed` | keep ingest accepted, binding failed | accepted with binding issue |
| index | projection write fails | `IndexProjectionFailed` | retry index job | search lag visible |
| finalize | report assembly mismatch | `ReportInvariantFailed` | fail loudly, alert | job incomplete |

### Critical gaps if not added to plan

1. `MetadataPersistenceFailed`
2. `LogicalIdentityConflict`
3. `BindingPolicyFailed`
4. `ReportInvariantFailed`

These are not currently first-class enough in `007` or `008`.

---

## 6. Failure-mode registry

| Codepath | Failure mode | Rescued? | Test? | User sees? | Logged? |
| --- | --- | --- | --- | --- | --- |
| upload | empty request | yes | yes | yes | yes |
| upload | package persistence fail | yes | yes | yes | yes |
| scan | malformed ZIP | yes | yes | yes | yes |
| scan | ZIP bomb | yes | yes | yes | yes |
| parse | malformed dataset | yes | yes | yes | yes |
| validate | missing required tag | yes | yes | yes | yes |
| raw storage | object write fail | must add | must add | must add | must add |
| DB write | raw saved, metadata write fails | must add | must add | must add | must add |
| duplicate handling | same SOP UID uploaded twice | must clarify | must add | must add | must add |
| binding | platform map fails | must clarify | must add | must add | must add |
| index | projection write fails | yes | yes | yes | yes |
| finalize | count mismatch / orphan item | must add | must add | must add | must add |

Rows marked “must add” are the real engineering review findings.

---

## 7. State-machine corrections

### 7.1 Job state

Recommended:

```text
created
  -> receiving
  -> scanning
  -> processing
  -> finalizing
  -> completed

any active state
  -> failed
  -> cancelled

completed
  -> reindexing
  -> completed
```

Do not use `indexing` as a required inline stage if indexing is explicitly async and retryable. The job can complete with:

- ingestion complete,
- index pending / lagging.

Otherwise a projection outage makes every intake job look like a failed upload. Wrong abstraction.

### 7.2 Item outcome model

Recommended axes:

```text
scan_status
parse_status
storage_status
validation_status
binding_status
index_status
terminal_outcome
```

Recommended user-facing terminal outcomes:

```text
accepted
quarantined
rejected
failed
```

---

## 8. Test review

### 8.1 Tests already implied by the plan

- valid mixed upload,
- malformed file among good siblings,
- missing `SOPClassUID`,
- duplicate SOP,
- duplicate content,
- unresolved reference,
- projection rebuild,
- ZIP bomb,
- path traversal.

### 8.2 Tests that must be added before implementation starts

1. **Raw bytes stored, DB write fails**
   - expected: retry reuses stored bytes, no phantom acceptance.

2. **Same SOP UID uploaded in two separate jobs**
   - expected: one logical instance, two observations, duplicate fact visible.

3. **Same job retried**
   - expected: no duplicated item rows or duplicate observations.

4. **Binding fails after canonical ingest succeeds**
   - expected: accepted ingest, failed binding, no rollback of DICOM truth.

5. **Index job fails after ingest completes**
   - expected: ingest report truthful, projection lag visible.

6. **Study without trusted completeness signal**
   - expected: remains `unknown`, not `complete`.

7. **Report invariant mismatch**
   - expected: fail loudly, never silently omit an item.

### 8.3 Friday 2 a.m. confidence test

The one test that gives the most confidence is:

> upload a mixed ZIP, inject object-store failure on one item, DB failure after raw-byte storage on another, duplicate SOP on a third, unresolved reference on a fourth, then verify the final report tells the truth for all of them and every successful raw object is still replayable.

If that passes, most of the architecture is real.

---

## 9. Performance review

### Likely slow paths

1. ZIP expansion on large packages
2. per-item header parsing
3. duplicate lookup if indexes are weak
4. projection rebuild across large batches

### Must-have indexes

- `dicom_instances(sop_instance_uid)`
- `dicom_series(series_instance_uid)`
- `dicom_studies(study_instance_uid)`
- `dicom_instance_observations(instance_id)`
- `dicom_instance_observations(whole_file_sha256)`
- `dicom_reference_edges(to_sop_instance_uid)`
- projection lookup indexes on hot filters

### Main performance judgment

The architecture is fine. The risk is not parser throughput first. The risk is accidentally doing relational lookup work inside per-file loops without batched access or proper unique indexes.

---

## 10. Observability review

### Already good

- job metrics,
- item outcome metrics,
- stage duration,
- duplicate counts,
- unresolved refs,
- index health.

### Missing or worth adding

| Metric / signal | Why |
| --- | --- |
| `dicom_ingestion_orphaned_raw_objects_total` | catches dual-write failure residue |
| `dicom_binding_failures_total` | distinguishes platform mapping pain from DICOM pain |
| `dicom_report_invariant_failures_total` | catches silent accounting bugs |
| `dicom_projection_stale_total` | reveals rebuild debt |
| `dicom_replay_jobs_total{status}` | proves replay path is real |

---

## 11. Deployment review

### Safe rollout order

```text
1. schema migrations
2. write path behind feature flag
3. dark ingest of fixture corpus
4. shadow projection rebuild
5. limited users
6. widen rollout
```

### Rollback posture

The safest rollback is:

- disable ingestion entrypoint,
- keep stored raw bytes and canonical rows,
- stop new index work if projections misbehave,
- do **not** delete data written during the experiment.

If rollback requires deleting partially ingested medical data, the rollout design failed.

---

## 12. Recommended doc updates before coding

### Update `007`

Add:

1. `dicom_instance_observations`
2. exact binding statuses
3. extractor/projection version fields
4. raw-object vs metadata-persistence failure split
5. study completeness semantics

### Update `008`

Add or revise tickets:

1. `A1` to freeze duplicate SOP + observation model,
2. `A3` to include staged object lifecycle,
3. `B4` to use orthogonal status axes,
4. `C4` to define binding failure result,
5. `C5` to include projection versioning,
6. new test bullets for dual-write and report-invariant cases.

---

## 13. Final engineering recommendation

Do **not** start with service implementation tomorrow morning.

Start with one short contract-locking pass:

1. add `dicom_instance_observations`,
2. freeze duplicate semantics,
3. freeze item idempotency,
4. freeze dual-write recovery,
5. freeze binding status semantics,
6. freeze projection versioning.

That is maybe one extra day of thinking for a human team. With CC + gstack, it is cheap.

It will save the expensive kind of refactor, the one where every test passes and the model is still wrong.
