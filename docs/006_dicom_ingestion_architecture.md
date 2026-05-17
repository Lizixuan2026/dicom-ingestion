# DICOM Ingestion Module Architecture

Documentation map: `001_dicom_ingestion_documentation_map.md`

## 1. Product framing

This module is **not a PACS** and not just a DICOM parser.

It is the data platform's **medical imaging intake layer**:

> byte-preserving, replayable, queryable, duplicate-aware, and ready for derived objects.

The user should be able to upload a folder or ZIP of DICOM files and trust that the platform will:

1. keep the original bytes,
2. tell them exactly what succeeded or failed,
3. organize the data into a useful imaging model,
4. let downstream tools query it quickly,
5. avoid painting the platform into a corner when SEG / RTSTRUCT / SR arrive later.

That is the job. Not “read a few tags.”

---

## 2. Scope decision

### 2.1 V1 must do

1. Accept single files, multi-file batches, folders, and ZIP uploads.
2. Persist original uploaded bytes durably before derived processing.
3. Recursively scan and identify candidate DICOM files.
4. Parse DICOM in explicit `header_only` mode by default.
5. Store:
   - full raw tag map,
   - normalized core metadata,
   - creator-aware private tag records,
   - reference graph fields needed for derived objects.
6. Build neutral `Study / Series / Instance` ingestion records without hard-coding platform business ownership.
7. Run ingestion and indexing as explicit jobs with status, report, retries, and failed items.
8. Separate:
   - canonical storage,
   - normalized metadata,
   - fast query projection.
9. Detect and classify:
   - identity duplicates,
   - content duplicates.
10. Aggregate SOP-level duplicate evidence into Series-level conflict summaries that users can review and resolve without inspecting individual DICOM files.
11. Expose a clean handoff into platform objects such as `Asset`, `DatasetSample`, and `Annotation` through a separate mapping layer.

### 2.2 Architecture must leave room for, but v1 does not fully implement

1. Branch-specific enrichment for SEG / RTSTRUCT / SR.
2. Vendor-specific private-tag interpretation beyond a small configured starter set.
3. Full curation workflows for duplicate resolution.
4. Advanced pixel-derived analytics such as intensity histograms or voxel volumes.
5. A physically stored `bytes_until_pixel_data` artifact if workload later justifies it.

### 2.3 Deliberately not in scope

1. PACS networking as a product surface.
2. Full viewer implementation.
3. Full anonymization workflow.
4. Generic pluggable workflow engine in v1.
5. Reproducing Orthanc, XNAT, or Dicoogle wholesale inside the platform.

The scope line is intentional. A parser-only version is too small. A PACS clone is the wrong product.

---

## 3. Source-backed design principles

| Principle | Why it exists | Source basis |
| --- | --- | --- |
| Separate receive, store, index, and query projection | One synchronous write path becomes unobservable and hard to replay | Dicoogle execution split, Orthanc store/index split |
| `header_only` is explicit | Metadata reads should not accidentally drag pixel payloads through the hot path | XNAT `getMaxStopTagInputHandler`, dcm4che `readDatasetUntilPixelData()` |
| Raw bytes are canonical | Every projection should be rebuildable from the source of truth | Orthanc full attachment + reconstructable `MainDicomTags` |
| Fast projections are derived state | Query shape changes over time | Orthanc `MainDicomTags`, Dicoogle post-query `DIMGeneric` read model |
| Private tags are creator-aware | Numeric private tags alone are not stable identities | dcm4che `ElementDictionary(privateCreator)` |
| Platform mapping is separate from DICOM parsing | “what this file is” and “what business object it belongs to” are different questions | XNAT identifier / routing layer |
| Derived objects need a reference graph from day one | Viewers and labels fail later if references are lost during intake | OHIF SEG / RTSTRUCT / SR consumption paths |
| Duplicates are multi-axis | Same SOP UID and same pixel content are different facts | Posda duplicate SOP vs pixel digest flows |
| Workflow should be branch-capable | Image and derived-object pipelines eventually diverge | Kaapana advanced metadata DAG |

---

## 4. System architecture

```text
                         ┌──────────────────────┐
                         │      Upload API      │
                         └──────────┬───────────┘
                                    │
                                    ▼
                         ┌──────────────────────┐
                         │  Upload Package Store │
                         │  raw ZIP / folder set │
                         └──────────┬───────────┘
                                    │
                                    ▼
                         ┌──────────────────────┐
                         │    Ingestion Job      │
                         └──────────┬───────────┘
                                    │
              ┌─────────────────────┼─────────────────────┐
              ▼                     ▼                     ▼
      ┌──────────────┐      ┌──────────────┐      ┌────────────────┐
      │   Scanner    │      │  Parser       │      │ Duplicate Check │
      │ fast filter  │      │ header_only   │      │ SOP + digest    │
      └──────┬───────┘      └──────┬───────┘      └────────┬───────┘
             │                     │                      │
             └──────────────┬──────┴──────────────┬───────┘
                            ▼                     ▼
                  ┌──────────────────┐   ┌──────────────────┐
                  │ Canonical Record │   │ Reference Graph   │
                  │ Study/Series/Inst│   │ SOP/Series refs    │
                  └─────────┬────────┘   └─────────┬────────┘
                            │                      │
                            └──────────┬───────────┘
                                       ▼
                         ┌────────────────────────┐
                         │  Mapping / Binding      │
                         │ Asset / Sample / Ann.   │
                         └──────────┬─────────────┘
                                    │
              ┌─────────────────────┼─────────────────────┐
              ▼                     ▼                     ▼
      ┌──────────────┐      ┌──────────────┐      ┌────────────────┐
      │ Object Store │      │ Primary DB   │      │ Index Job       │
      │ raw bytes    │      │ canonical    │      │ fast projection │
      └──────────────┘      └──────────────┘      └────────────────┘
```

### 4.1 The key separation

```text
canonical truth      = immutable original bytes + canonical ingestion records
normalized metadata  = structured interpretation of DICOM headers
query projection     = fast rebuildable fields for search, filters, UI, joins
platform binding     = business-specific mapping into platform domain objects
```

Do not merge these four just because v1 is small. That shortcut is where six months of rework comes from.

---

## 5. Core domain model

### 5.1 Jobs

#### `IngestionJob`

Represents one user-initiated intake run.

Suggested fields:

- `id`
- `actor_id`
- `source_type` = `file | folder | zip | api`
- `status`
- `input_manifest`
- `started_at`, `finished_at`
- `report`
- `retry_count`
- `failure_summary`

#### `IngestionItem`

Represents one scanned file or ZIP entry.

Suggested fields:

- `id`
- `ingestion_job_id`
- `source_path`
- `byte_size`
- `sha256`
- `scan_status`
- `parse_status`
- `validation_status`
- `storage_uri`
- `error_code`
- `error_detail`

#### `IndexJob`

Separate from ingestion. Rebuildable.

Suggested fields:

- `id`
- `scope_type` = `instance | series | study | batch`
- `scope_id`
- `status`
- `report`
- `failed_items`

This follows Dicoogle's strongest idea: index work is a domain object, not a side effect.

---

### 5.2 Canonical imaging records

#### `DicomStudy`

- `study_instance_uid`
- study-level normalized fields
- denormalized counts
- ingestion completeness markers

#### `DicomSeries`

- `series_instance_uid`
- `study_instance_uid`
- `modality`
- `series_number`
- `frame_of_reference_uid`
- derived-object classification markers

#### `DicomInstance`

- `sop_instance_uid`
- `sop_class_uid`
- `study_instance_uid`
- `series_instance_uid`
- `instance_number`
- `transfer_syntax_uid`
- `pixel_data_present`
- `current_canonical_observation_id`
- `ingestion_status`

These are neutral records. They describe the DICOM world before platform business meaning is attached.

#### `DicomInstanceObservation`

Represents one physical occurrence of a logical SOP identity.

- `instance_id`
- `ingestion_item_id`
- `raw_object_uri`
- `whole_file_sha256`
- `pixel_digest` nullable
- `raw_tag_map_uri` or structured payload reference
- `is_canonical`
- `observed_at`

One logical `DicomInstance` may have multiple uploaded observations. This keeps repeated uploads, duplicate SOPs, provenance, and canonical-file selection from collapsing into one overloaded row.

---

### 5.3 Metadata layers

#### `DicomRawTagSet`

Full parsed tag retention for replay and forensic use.

- `observation_id`
- full raw tag payload

#### `DicomPrivateTag`

Minimum identity:

- `observation_id`
- `private_creator`
- `tag`
- `vr`
- `raw_value`
- `interpreted_keyword` nullable
- `interpreted_value` nullable

#### `DicomCoreProjection`

Fast fields optimized for query and UI:

- patient identifiers needed by platform policy
- study / series / instance UID fields
- modality
- dates
- counts
- file size
- duplicate classification
- derived-object flags

This is intentionally rebuildable.

---

### 5.4 Reference graph

#### `DicomReferenceEdge`

Suggested fields:

- `from_instance_id`
- `relationship_type`
- `to_study_instance_uid` nullable
- `to_series_instance_uid` nullable
- `to_sop_instance_uid` nullable
- `referenced_frame_number` nullable
- `resolved_target_instance_id` nullable

The graph is sparse in v1. That is fine. The point is not to fully support every object type on day one. The point is not to lose the edges.

---

### 5.5 Duplicate facts

#### `DicomDuplicateFinding`

Suggested fields:

- `observation_id`
- `duplicate_type` = `identity | content`
- `matched_instance_id`
- `matched_observation_id` nullable
- `basis` = `sop_instance_uid | pixel_digest | whole_file_digest`
- `resolution_status` = `unreviewed | accepted | quarantined | ignored`

Keep this separate from ingestion state. A file can be ingested successfully and still deserve quarantine.

---

### 5.6 Three-tier processing model

The ingestion system operates at three distinct granularities. These are not implementation details — they are the core conceptual split that makes the user model and the system model coherent.

```text
File / IngestionItem
  = processing unit
  = one scanned file or ZIP entry
  = one physical occurrence of bytes
  = unit of retry idempotency

SOP / DicomInstanceObservation
  = evidence unit
  = one parsed DICOM object observation
  = basis for duplicate detection and canonical selection
  = keyed by (ingestion_item_id, sop_instance_uid)

Series / SeriesIngestionAttempt
  = user review unit
  = one Series recognized within a job
  = the unit users upload, review, and make decisions about
  = bridges file-level items to SOP-level evidence
```

Users do not think in files or SOP instances. They upload folders of DICOM images one Series at a time and expect to see results at the Series level. The system must speak that language at the interface while maintaining SOP-level precision internally.

### 5.7 SeriesIngestionAttempt

Represents one Series recognized within one ingestion job.

A 300-file Series upload produces 300 `IngestionItems` but exactly one `SeriesIngestionAttempt`. The attempt aggregates SOP-level evidence into the summary a user can review and act on.

Suggested fields:

- `id`
- `ingestion_job_id`
- `study_instance_uid`
- `series_instance_uid`
- `uploaded_sop_count`

Uniqueness: one attempt per `(ingestion_job_id, series_instance_uid)`.

`IngestionItem` has a nullable FK to `SeriesIngestionAttempt`. Non-DICOM items have no attempt; accepted DICOM items must have one.

### 5.8 SeriesConflictSummary

A persistent, user-facing projection that aggregates SOP-level duplicate findings into a single reviewable record per Series upload attempt.

Suggested fields:

- `series_ingestion_attempt_id` — FK, one summary per attempt
- `existing_series_id` — nullable, the platform Series this conflicts with
- `classification` = `exact_duplicate | partial_overlap | content_conflict | uid_conflict`
- SOP count breakdowns: `existing`, `uploaded`, `overlap`, `new`, `missing`, `conflicting`
- `status` = `open | kept_existing | promoted_uploaded | auto_deduped`

This is not raw evidence. It is an aggregated decision-support record. Raw evidence lives in `DicomDuplicateFinding`.

### 5.9 Status axes and idempotency

#### `IngestionItem` status axes

Use orthogonal state fields instead of one overloaded enum:

- `scan_status`
- `parse_status`
- `storage_status`
- `validation_status`
- `binding_status`
- `index_status`
- `terminal_outcome`

User-facing terminal outcomes are:

- `accepted`
- `quarantined`
- `rejected`
- `failed`

#### Idempotency

Use two keys for two different jobs:

```text
request_idempotency_key
  = caller-provided key for POST /dicom-ingestions

item_fingerprint
  = (ingestion_job_id, source_path, byte_size, whole_file_sha256)
```

The same user intentionally uploading the same package again creates a new job and new observations. Retrying the same job reuses the same item records.

---

## 6. Pipeline design

### 6.1 V1 pipeline

```text
RECEIVE
  -> persist original upload package
  -> create IngestionJob

SCAN
  -> expand ZIP / recurse folder
  -> fast-filter candidates
  -> create IngestionItems

PARSE
  -> header_only parse
  -> final DICOM validation
  -> store raw tag set + normalized metadata

CLASSIFY
  -> base image vs derived object
  -> extract available references
  -> compute duplicate facts

PERSIST
  -> create/update Study, Series, Instance records
  -> save raw bytes
  -> save reference edges

BIND
  -> invoke platform mapping policy
  -> create Asset / Sample / Annotation links where applicable

INDEX
  -> enqueue IndexJob
  -> write fast query projection

FINALIZE
  -> produce job report
  -> cleanup temp workspace
```

### 6.2 Future branch-ready shape

```text
COMMON TRUNK
receive -> scan -> header parse -> classify

BASE IMAGE BRANCH
geometry / image-derived enrichment

DERIVED OBJECT BRANCH
reference resolution / segmentation / report enrichment

MERGE
shared persistence + index contracts
```

We do **not** need a full generic workflow engine in v1. We do need the code structure to avoid assuming every object walks the same path forever.

---

## 7. State machines

### 7.1 `IngestionJob`

```text
created
  -> receiving
  -> scanning
  -> parsing
  -> persisting
  -> indexing
  -> completed

Any active state
  -> failed
  -> cancelled

completed
  -> reindexing
  -> completed
```

### 7.2 `IngestionItem`

`IngestionItem` is modeled as multiple orthogonal axes rather than one overloaded state ladder:

```text
scan_status       = seen | candidate | rejected_non_dicom
parse_status      = pending | parsed | failed
storage_status    = pending | stored | failed
validation_status = pending | valid | invalid | quarantined
binding_status    = pending | bound | failed | not_applicable
index_status      = pending | queued | indexed | failed
terminal_outcome  = accepted | quarantined | rejected | failed
```

Important distinction:

- `stored` answers: did we preserve the file?
- `accepted` answers: is it eligible for ordinary downstream use?

That is Posda's lesson translated into our system.

---

## 8. Failure model

### 8.1 Named failures

| Failure | Trigger | User impact | System response |
| --- | --- | --- | --- |
| `ZipExtractionFailed` | malformed archive | upload cannot be processed | job fails visibly, preserve package |
| `ZipBombDetected` | expansion ratio / entry count exceeds limits | upload rejected | job fails visibly, security log |
| `UnsupportedFileType` | fast scan rejects file | item skipped | include in report |
| `DicomParseFailed` | parser cannot read valid DICOM | item invalid | preserve raw file, item failure |
| `MissingRequiredDicomTag` | e.g. missing `SOPClassUID` | item invalid | reject as DICOM candidate |
| `ObjectStorageWriteFailed` | raw bytes cannot be durably saved | no safe ingest | retry, then job failure |
| `MetadataPersistenceFailed` | DB write fails | partial ingest risk | transaction rollback / retry |
| `DuplicateIdentityDetected` | same SOP UID | possible replacement conflict | store finding, no silent overwrite |
| `DuplicateContentDetected` | same digest | redundant data | store finding |
| `ReferenceResolutionPending` | derived object points to unseen target | deferred completeness | keep unresolved edge, no data loss |
| `IndexProjectionFailed` | secondary index write fails | search lag | source remains valid, IndexJob retry |
| `BindingPolicyFailed` | platform mapping fails after ingest succeeds | business linkage absent | keep ingest accepted, mark binding failed |
| `ReportInvariantFailed` | item counts do not reconcile at finalize time | false user report risk | fail loudly, alert, never silently omit item |

### 8.2 User-visible rule

No silent failure. Every item lands in one of:

- accepted
- quarantined
- rejected with reason
- still processing

If a user uploads 800 files and 37 fail, the UI / API report must say **which 37 and why**. A log line is not a product feature.

---

## 9. Data flow with shadow paths

```text
UPLOAD
  │
  ├─ nil input .............. reject request
  ├─ empty archive .......... complete with zero accepted, explicit warning
  └─ valid payload
        │
        ▼
SCAN
  │
  ├─ non-DICOM .............. preserve manifest result, skip parse
  ├─ corrupt ZIP entry ...... item failure, continue siblings
  └─ candidate
        │
        ▼
PARSE
  │
  ├─ malformed dataset ...... invalid_dicom
  ├─ missing SOPClassUID .... reject as non-usable DICOM
  └─ valid header
        │
        ▼
PERSIST
  │
  ├─ object store fails ..... retry, then fail safely
  ├─ DB write fails ......... rollback item transaction
  └─ success
        │
        ▼
INDEX
  │
  ├─ projection fails ....... IndexJob failed, canonical record stays valid
  └─ success
```

---

## 10. Mapping boundary

### 10.1 Why it exists

DICOM says what the file is. The platform decides what it means.

Those are different layers.

### 10.2 Suggested interface

```text
DicomBindingPolicy.bind(ingestion_context) -> BindingResult
```

Where `BindingResult` may include:

- `asset_id`
- `dataset_sample_id`
- `annotation_id`
- `binding_status`
- `reason`

### 10.3 Why not hard-code now

The same DICOM series might mean:

- a training sample,
- a source asset,
- an annotation input,
- or all three,

depending on the surrounding workflow. If parser code owns that decision, every future product change becomes a data migration.

XNAT's routing layer is the warning flare here.

---

## 11. Query and index strategy

### 11.1 V1 recommendation

Use a **relational primary model + rebuildable fast projection** first.

Why:

- the platform likely already needs joins into `Asset` / `DatasetSample` / `Annotation`;
- early query shapes are still evolving;
- one more external search system before usage is proven is ornamental architecture.

### 11.2 Rebuild rule

Any projection should be regenerable from:

- raw object bytes,
- raw parsed tags,
- normalized canonical records.

If a projection cannot be rebuilt, it is not a projection. It is hidden canonical state. Bad smell.

### 11.3 Rebuild versioning

Persist:

- `metadata_extractor_version`
- `projection_version`
- `projection_built_at`
- `projection_source_checksum`

Rebuilds are triggered by:

1. manual operator action,
2. `projection_version` bump,
3. `metadata_extractor_version` bump when affected fields changed.

---

## 12. Security and governance

### V1 must include

1. ZIP bomb protections:
   - max expanded bytes
   - max entry count
   - max nesting depth
2. Path traversal protection during extraction.
3. Input size limits and per-user quota hooks.
4. Immutable source bytes with provenance.
5. Explicit retention policy hooks for PHI-bearing fields.
6. Audit events for:
   - upload started
   - upload completed
   - quarantine decision
   - duplicate resolution
   - remapping action

### Do not pretend this is “just file upload”

DICOM often contains PHI. Once the module exists, mistakes in logging, exports, or temp cleanup are not cute bugs. They are data incidents.

---

## 13. Observability

### 13.1 Metrics

- jobs created / completed / failed
- files scanned / parsed / rejected
- parse latency p50 / p95 / p99
- object-store write failures
- duplicate findings by type
- unresolved reference edges
- index lag
- temp cleanup failures

### 13.2 Logs

Every job needs a traceable ID through:

```text
upload -> scan -> parse -> persist -> bind -> index
```

### 13.3 Day-1 dashboard

- active jobs
- failure reasons
- duplicate rate
- quarantine backlog
- unresolved references
- projection lag

### 13.4 Operational runbooks

Need explicit playbooks for:

- failed upload package
- stuck parsing job
- storage write failures
- index rebuild
- duplicate review backlog

---

## 14. V1 implementation posture

### 14.1 Build now

- staged job runner, not generic workflow engine
- relational canonical model
- rebuildable fast projection
- reference graph persistence
- duplicate fact persistence
- small binding-policy interface

### 14.2 Defer deliberately

- generic plugin marketplace
- full vendor dictionary zoo
- full SEG / RTSTRUCT / SR enrichment
- pixel-derived analytics
- `bytes_until_pixel_data` physical derivative unless measurements prove the need

### 14.3 Deliberately unresolved product / workload decisions

1. **Storage optimization:** should we persist a metadata-only byte prefix in v1?
2. **Private tag scope:** which private creators matter for first real users?
3. **Branch mechanism:** how far beyond staged jobs do we need to go in the first derived-object release?

These are intentionally deferred because they depend on real workload evidence, not because the architecture is incomplete.

---

## 15. Recommended build sequence

### Phase 1: Intake spine

- uploads
- durable package storage
- scanner
- `IngestionJob` / `IngestionItem`
- header-only parser
- canonical Study / Series / Instance records
- raw bytes
- basic report

### Phase 2: Trust layer

- duplicate findings (SOP-level)
- Series ingestion attempts
- Series conflict classification and summaries
- Series-level canonical apply (batched transaction, all-or-nothing)
- quarantine vs accepted
- reference edges
- binding-policy interface
- index jobs
- dashboards / alerts

### Phase 3: Imaging depth

- derived-object branches
- vendor-aware private interpretations
- viewer / annotation integration hardening
- optional metadata-prefix artifact if justified

That sequence gives users value early without lying to the future system.

---

## 16. Why this is the right shape

A smaller design would ingest faster on paper and cost more later.

A bigger design would be a PACS in disguise and spend months solving problems this platform does not have yet.

This design keeps the spine complete while leaving the muscles to grow with real use.

That is the sweet spot.
