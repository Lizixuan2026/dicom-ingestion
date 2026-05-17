# DICOM Ingestion Module — Schema and Contracts

Documentation map: `001_dicom_ingestion_documentation_map.md`

## 1. Purpose

This document freezes the implementation details that usually get rediscovered in week one:

1. primary keys,
2. foreign keys,
3. uniqueness rules,
4. hot indexes,
5. canonical-observation selection,
6. idempotency semantics,
7. API request / response shapes.

If `010` says what to build, this document says how the first migration and service contracts should behave.

Recommended reading order for implementation:

1. `001_dicom_ingestion_documentation_map.md`
2. `010_dicom_ingestion_implementation_spec.md`
3. `011_dicom_ingestion_schema_and_contracts.md`
4. `012_migration_first_backlog.md`

---

## 2. Identity rules

### 2.1 Logical vs physical

```text
dicom_instances
  = one logical SOP identity

dicom_instance_observations
  = one physical uploaded occurrence
```

### 2.2 Natural uniqueness

| Table | Unique rule |
| --- | --- |
| `dicom_studies` | `study_instance_uid` |
| `dicom_series` | `series_instance_uid` |
| `dicom_instances` | `sop_instance_uid` |
| `dicom_ingestion_jobs` | `(actor_id, request_idempotency_key)` when key present |
| `dicom_ingestion_items` | `item_fingerprint` |
| `dicom_instance_observations` | `(instance_id, ingestion_item_id)` |
| `dicom_private_tags` | `(observation_id, private_creator, tag)` |

### 2.3 What is intentionally **not** unique

- `whole_file_sha256`
- `pixel_digest`
- `source_path`

Those values help classify duplicates. They do not define global identity.

---

## 3. Canonical observation policy

### 3.1 Rule

Each logical instance has exactly one current canonical observation.

### 3.2 Selection order

For v1:

1. first accepted observation becomes canonical,
2. later observations do **not** silently replace it,
3. explicit curation may switch the canonical observation later,
4. every switch must be audited.

### 3.3 Why this rule

It is boring, explainable, and safe.

If a second file arrives with the same SOP UID but different bytes, auto-replacing the first one is a data-governance decision disguised as convenience. Not great.

### 3.4 Required fields

`dicom_instances`

- `current_canonical_observation_id`

`dicom_instance_observations`

- `is_canonical`
- `observed_at`

### 3.5 Consistency invariant

```text
For every dicom_instances row:
  exactly one linked observation has is_canonical = true
  and its id = current_canonical_observation_id
```

---

## 4. Recommended indexes

### 4.1 Identity and joins

```text
dicom_studies(study_instance_uid) UNIQUE
dicom_series(series_instance_uid) UNIQUE
dicom_series(study_id)
dicom_instances(sop_instance_uid) UNIQUE
dicom_instances(study_id)
dicom_instances(series_id)
dicom_instance_observations(instance_id)
dicom_instance_observations(ingestion_item_id)
```

### 4.2 Duplicate detection

```text
dicom_instance_observations(whole_file_sha256)
dicom_instance_observations(pixel_digest)
dicom_duplicate_findings(observation_id)
dicom_duplicate_findings(matched_instance_id)
dicom_duplicate_findings(matched_observation_id)
```

### 4.3 Reference resolution

```text
dicom_reference_edges(to_sop_instance_uid)
dicom_reference_edges(to_series_instance_uid)
dicom_reference_edges(resolved_target_instance_id)
```

### 4.4 Job monitoring

```text
dicom_ingestion_jobs(status, created_at)
dicom_ingestion_items(ingestion_job_id, terminal_outcome)
dicom_ingestion_items(last_retryable_stage)
dicom_index_jobs(status, created_at)
```

### 4.5 Projection hot paths

At minimum:

```text
dicom_core_projections(study_instance_uid)
dicom_core_projections(series_instance_uid)
dicom_core_projections(sop_instance_uid)
dicom_core_projections(modality)
dicom_core_projections(study_date)
dicom_core_projections(object_class_family)
dicom_core_projections(binding_status)
```

Use composite indexes only after actual query shapes are known. Do not invent a twelve-column “future-proof” index. That is a tax with a database logo.

---

## 5. Referential rules

| Relationship | On delete |
| --- | --- |
| job -> items | restrict |
| item -> observation | restrict |
| study -> series | restrict |
| series -> instance | restrict |
| instance -> observations | restrict |
| observation -> private tags | cascade acceptable |
| observation -> duplicate findings | restrict |
| instance -> reference edges | restrict |

Reason:

- medical-ingest history should not disappear casually,
- derived side records can follow their owning observation where safe,
- top-level clinical-ish identity rows should favor auditability over cleanup convenience.

---

## 6. Idempotency contract

### 6.1 Request level

`POST /dicom-ingestions` accepts optional `Idempotency-Key`.

Behavior:

- same `actor_id + Idempotency-Key` + same request body -> return existing job,
- same `actor_id + Idempotency-Key` + different body -> `409 IdempotencyConflict`,
- no key -> always create a new job.

### 6.2 Item level

```text
item_fingerprint =
  hash(ingestion_job_id, source_path, byte_size, whole_file_sha256)
```

Behavior:

- retry inside same job reuses same item,
- same file in a later job creates a new item and a new observation,
- checksum alone never deduplicates user intent.

---

## 7. Duplicate contract

### 7.1 Identity duplicate

Triggered when:

```text
incoming SOPInstanceUID already exists in dicom_instances
```

Result:

- attach new observation to existing logical instance,
- create identity duplicate finding,
- keep canonical observation unchanged,
- keep ingestion accepted unless policy says quarantine.

### 7.2 Content duplicate

Triggered when:

```text
whole_file_sha256 or future pixel_digest matches prior observation
```

Result:

- create content duplicate finding,
- do not merge jobs,
- do not erase provenance,
- do not auto-quarantine.

### 7.3 Non-duplication rule for findings

Suggested uniqueness:

```text
(observation_id, duplicate_type, basis, matched_instance_id, matched_observation_id)
```

This keeps retries from creating duplicate duplicate-findings. A perfect little absurdity if left out.

---

## 8. Projection contract

### 8.1 Projection source

Projection is rebuilt from:

- logical canonical records,
- current canonical observation,
- supporting facts such as duplicates and reference resolution.

### 8.2 Versioning

Projection rows store:

- `metadata_extractor_version`
- `projection_version`
- `projection_built_at`
- `projection_source_checksum`

### 8.3 Staleness

A projection is stale if:

1. its `projection_version` differs from current code,
2. its `metadata_extractor_version` differs where affected fields changed,
3. its `projection_source_checksum` no longer matches current source state.

---

## 9. API contracts

### 9.1 Create ingestion

```http
POST /dicom-ingestions
Idempotency-Key: <optional>
Content-Type: multipart/form-data | application/json
```

Accepted input forms:

- direct file upload,
- multi-file upload,
- ZIP upload,
- manifest reference.

Example response:

```json
{
  "job_id": "ing_123",
  "status": "created",
  "source_type": "zip",
  "accepted_input_count": 842,
  "links": {
    "self": "/dicom-ingestions/ing_123",
    "items": "/dicom-ingestions/ing_123/items"
  }
}
```

### 9.2 Get ingestion job

```json
{
  "job_id": "ing_123",
  "status": "completed",
  "counts": {
    "uploaded": 842,
    "candidate": 800,
    "accepted": 763,
    "quarantined": 4,
    "rejected": 33,
    "failed": 0
  },
  "duplicate_findings": 12,
  "unresolved_references": 2,
  "report_ready": true
}
```

### 9.3 Get ingestion items

Minimum fields:

- `item_id`
- `source_path`
- `terminal_outcome`
- `error_code`
- `error_detail`
- `instance_id`
- `observation_id`
- `binding_status`
- `index_status`

### 9.4 Retry ingestion job

```http
POST /dicom-ingestions/{jobId}/retry
```

Behavior:

- only retries retryable failed work,
- reuses existing durable raw bytes where available,
- does not duplicate existing observations.

### 9.5 Query APIs

All Study / Series / Instance query APIs read from projections.

No endpoint may satisfy a hot query by scanning raw tag payloads.

---

## 10. Open product questions that remain intentionally deferred

1. Persist metadata-only byte prefixes in v1 or not.
2. Which private creators matter for first real users.
3. Whether future derived-object enrichment needs more than typed staged jobs.

Everything else above is implementation contract, not suggestion.

---

## 11. Series conflict contract

### 11.1 Natural uniqueness for new tables

| Table | Unique rule |
| --- | --- |
| `dicom_series_ingestion_attempts` | `(ingestion_job_id, series_instance_uid)` |
| `dicom_series_conflict_summaries` | `(series_ingestion_attempt_id)` |

### 11.2 Referential rules for new tables

| Relationship | On delete |
| --- | --- |
| series_attempt -> ingestion_job | restrict |
| ingestion_item -> series_attempt | restrict (nullable FK; non-DICOM items may be NULL) |
| series_conflict_summary -> series_attempt | restrict |
| series_conflict_summary -> existing_series | restrict |

### 11.3 Classification contract

Classification is determined once, after all SOP-level findings for the attempt are written. The rules are mutually exclusive and applied in priority order:

```text
1. content_conflict (highest priority)
   Condition: conflicting_sop_count > 0
   At least one SOPInstanceUID is shared with the existing Series
   and its content hash differs.

2. uid_conflict
   Condition: overlap_ratio < threshold
   overlap_ratio = overlap_sop_count / max(uploaded_sop_count, existing_sop_count)
   Default threshold: 0.10 (10%)
   Threshold must be configurable without a code deploy.
   Triggered when SOPInstanceUID sets are nearly disjoint — suggests UID reuse.

3. partial_overlap
   Condition: 0 < overlap_sop_count < max(uploaded_sop_count, existing_sop_count)
   and conflicting_sop_count = 0
   SOP sets intersect but are not identical; no content conflicts.

4. exact_duplicate (lowest priority)
   Condition: overlap_sop_count = uploaded_sop_count = existing_sop_count
   and conflicting_sop_count = 0
   SOP sets are identical and all content hashes match.
```

`exact_duplicate` auto-sets `status = auto_deduped` at write time. All other classifications set `status = open`.

### 11.4 Conflict resolution action model

v1 supports exactly two manual actions. `merge` is explicitly deferred.

```http
POST /dicom/series-conflicts/{id}/resolve
Content-Type: application/json

{ "action": "keep_existing" }
```

or:

```json
{ "action": "promote_uploaded" }
```

#### Action: `keep_existing`

The user has reviewed the conflict and chooses to keep the current canonical Series unchanged. The newly uploaded Series is acknowledged but not promoted.

- no canonical pointers are modified
- `status` becomes `kept_existing`
- an audit event is written: actor, timestamp, action
- same action repeated on an already-`kept_existing` summary: returns 200 with current state, no-op
- different action on an already-resolved summary: returns 409 with a body indicating the current `status` and the conflicting action

#### Action: `promote_uploaded`

The user has reviewed the conflict and chooses to promote the newly uploaded Series as canonical.

- executes one batched transaction: `is_canonical = false` on all prior observations for every SOP in this Series attempt; `is_canonical = true` on the new observations
- the transaction is all-or-nothing: either every SOP switches canonical, or none do
- on success: `status` becomes `promoted_uploaded`; returns 200 with updated summary body
- on failure: `status` stays `open`; DB is unchanged; returns 500 with error detail
- same action repeated on an already-`promoted_uploaded` summary: returns 200, no-op
- different action on an already-resolved summary: returns 409

#### `auto_deduped` status

Set automatically at classification time when `classification = exact_duplicate`. No user action is needed or accepted. The `/resolve` endpoint returns 409 for any manual action on an `auto_deduped` summary.

#### Status vocabulary

```text
open             — conflict detected, awaiting user decision
kept_existing    — user chose to keep the existing canonical Series
promoted_uploaded — user chose to promote the uploaded Series as canonical
auto_deduped     — exact duplicate detected; no manual review needed; physical upload provenance is still retained
```

`ignored` is not used. The status name must be self-explaining without consulting documentation.

Object storage may deduplicate identical byte payloads, but every physical upload still produces its own ingestion item and observation.

#### Deferred: `merge`

`merge` is not a v1 action. It requires separate design for: which SOPs to include, how to handle content conflicts within the merge, canonical pointer updates for partial overlap, rollback semantics, and audit policy. Do not add a `merge` code path in v1, even as a stub.

### 11.5 Series-level query contract

```http
GET  /dicom/series-conflicts
GET  /dicom/series-conflicts/{id}
```

Both endpoints read from `dicom_series_conflict_summaries` directly. Neither may aggregate SOP-level findings at query time. If the summary row does not exist, the Series had no conflicts to report.

`GET /dicom/series-conflicts/{id}` response must include a link to the scoped SOP-level findings:

```json
"links": {
  "sop_findings": "/dicom/duplicates?series_ingestion_attempt_id={attempt_id}",
  "resolve": "/dicom/series-conflicts/{id}/resolve"
}
```
