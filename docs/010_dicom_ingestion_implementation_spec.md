# DICOM Ingestion Module — Implementation Spec

Documentation map: `001_dicom_ingestion_documentation_map.md`

## 1. Purpose

This is the build spec for v1.

If you are implementing the module, start here. The earlier docs explain why the design exists. This document states what to build.

If you are unsure which DICOM ingestion document owns a topic, read:

- `001_dicom_ingestion_documentation_map.md`

For exact keys, indexes, canonical-selection rules, and API payload contracts, continue with:

- `011_dicom_ingestion_schema_and_contracts.md`

---

## 2. V1 contract

The module must:

1. accept files, batches, folders, and ZIP uploads,
2. preserve original bytes before derived processing,
3. parse in explicit `header_only` mode by default,
4. produce neutral Study / Series / Instance records,
5. preserve raw tags, private tags, and reference edges,
6. detect duplicate facts without silent overwrite,
7. separate DICOM ingest from platform binding,
8. expose rebuildable fast projections,
9. report every item outcome explicitly,
10. support retry and replay from stored bytes,
11. aggregate SOP-level duplicate evidence into Series-level conflict summaries and expose a Series-level apply endpoint for canonical decisions.

Non-goals for v1:

- PACS networking
- full viewer
- full anonymization flow
- generic DAG engine
- full SEG / RTSTRUCT / SR enrichment
- pixel analytics

---

## 3. Architecture

```text
Upload API
  -> UploadPackage persistence
  -> IngestionJob
      -> scan
      -> persist raw item bytes
      -> parse(header_only)
      -> validate
      -> classify
      -> persist canonical model
      -> bind platform objects
      -> series_conflict_classify
      -> enqueue IndexJob
      -> finalize report
```

Core separation:

```text
canonical truth      = raw bytes + canonical relational records
normalized metadata  = interpreted DICOM header fields
query projection     = rebuildable fast-read shape
platform binding     = business-specific links to platform objects
```

---

## 4. Module boundaries

| Module | Owns |
| --- | --- |
| `upload` | request validation, package persistence, manifest |
| `scanner` | recursive traversal, ZIP expansion, safety limits |
| `parser` | header-only parse, raw tag extraction |
| `classifier` | object family, reference extraction |
| `repository` | transactional relational writes |
| `binding` | Asset / DatasetSample / Annotation mapping |
| `series_conflict` | Series ingestion attempt grouping, conflict classification, summary projection, Series-level apply |
| `indexer` | rebuildable projections |
| `reporting` | job/item summaries |

Required interfaces:

```text
UploadService.accept(input) -> UploadPackage
ScanService.scan(upload_package) -> ScanManifest
DicomParser.parse_header(item) -> ParsedDicomHeader
DicomClassifier.classify(parsed_header) -> ClassificationResult
IngestionRepository.persist(item_context) -> PersistedDicomEntities
SeriesIngestionAttemptBuilder.build_from_job(ingestion_job_id) -> [SeriesIngestionAttempt]
SeriesConflictClassifier.classify(series_ingestion_attempt_id) -> ConflictSummary
SeriesConflictSummaryWriter.write(conflict_summary) -> PersistedSummary
SeriesConflictResolver.resolve(series_conflict_summary_id, action:) -> ResolveResult
  -- action: 'keep_existing' | 'promote_uploaded'
DicomBindingPolicy.bind(persisted_entities, context) -> BindingResult
IndexScheduler.enqueue(scope) -> IndexJob
IngestionReporter.finalize(job_id) -> IngestionReport
```

---

## 5. Data model

### 5.1 Jobs

#### `dicom_ingestion_jobs`

- `id`
- `actor_id`
- `request_idempotency_key`
- `source_type`
- `status`
- `input_manifest_json`
- `started_at`
- `finished_at`
- `retry_count`
- `report_json`
- `failure_summary`

#### `dicom_ingestion_items`

- `id`
- `ingestion_job_id`
- `source_path`
- `byte_size`
- `whole_file_sha256`
- `item_fingerprint`
- `scan_status`
- `parse_status`
- `storage_status`
- `metadata_persistence_status`
- `validation_status`
- `binding_status`
- `index_status`
- `terminal_outcome`
- `storage_uri`
- `raw_object_status`
- `raw_object_sha256`
- `last_retryable_stage`
- `error_code`
- `error_detail`
- timestamps

#### `dicom_index_jobs`

- `id`
- `scope_type`
- `scope_id`
- `status`
- `report_json`
- `failed_items_json`
- timestamps

### 5.2 Canonical imaging model

#### `dicom_studies`

- `id`
- `study_instance_uid`
- normalized study fields
- `series_count`
- `instance_count`
- `ingestion_completeness_status`

#### `dicom_series`

- `id`
- `study_id`
- `series_instance_uid`
- `modality`
- `series_number`
- `frame_of_reference_uid`
- `object_class_family`

#### `dicom_instances`

- `id`
- `study_id`
- `series_id`
- `sop_instance_uid`
- `sop_class_uid`
- `instance_number`
- `transfer_syntax_uid`
- `pixel_data_present`
- `current_canonical_observation_id`
- `ingestion_status`

#### `dicom_instance_observations`

- `id`
- `instance_id`
- `ingestion_item_id`
- `raw_object_uri`
- `whole_file_sha256`
- `pixel_digest`
- `raw_tag_set_uri` or `raw_tag_set_json`
- `is_canonical`
- `observed_at`

### 5.3 Supporting records

#### `dicom_private_tags`

- `id`
- `observation_id`
- `private_creator`
- `tag`
- `vr`
- `raw_value`
- `interpreted_keyword`
- `interpreted_value`

#### `dicom_reference_edges`

- `id`
- `from_instance_id`
- `relationship_type`
- `to_study_instance_uid`
- `to_series_instance_uid`
- `to_sop_instance_uid`
- `referenced_frame_number`
- `resolved_target_instance_id`

#### `dicom_duplicate_findings`

- `id`
- `observation_id`
- `duplicate_type`
- `basis`
- `matched_instance_id`
- `matched_observation_id`
- `resolution_status`

#### `dicom_core_projections`

- `instance_id`
- hot query fields
- `duplicate_flags`
- `reference_resolution_status`
- `binding_status`
- `metadata_extractor_version`
- `projection_version`
- `projection_built_at`
- `projection_source_checksum`

### 5.4 Series conflict layer

#### `dicom_series_ingestion_attempts`

One row per Series recognized within a job. Bridges file-level items to Series-level conflict review.

- `id`
- `ingestion_job_id`
- `study_instance_uid`
- `series_instance_uid`
- `uploaded_sop_count`

#### `dicom_series_conflict_summaries`

User-facing projection over SOP-level findings. One row per `series_ingestion_attempt` that touches an existing Series.

- `series_ingestion_attempt_id`
- `existing_series_id` nullable
- `classification` = `exact_duplicate | partial_overlap | content_conflict | uid_conflict`
- `existing_sop_count`, `uploaded_sop_count`, `overlap_sop_count`, `new_sop_count`, `missing_sop_count`, `conflicting_sop_count`
- `status` = `open | kept_existing | promoted_uploaded | auto_deduped`

For classification rules and apply contract, see `011` §11.

---

## 6. Frozen rules

| Topic | Rule |
| --- | --- |
| SOP identity | `dicom_instances` is logical identity |
| Uploaded files | `dicom_instance_observations` stores physical occurrences |
| Raw/private tags | observation-scoped |
| Request idempotency | `request_idempotency_key` |
| Item idempotency | `(ingestion_job_id, source_path, byte_size, whole_file_sha256)` |
| Binding failure | valid DICOM may remain `accepted` while binding fails |
| Study completeness | default `unknown`; `partial` only for known batch failures; `complete` only with trusted manifest / explicit contract |
| Projection rebuild | manual rebuild plus version-triggered rebuild |

---

## 7. Pipeline

| Stage | Input | Output | Failure behavior |
| --- | --- | --- | --- |
| receive | request payload | package + job | reject if package cannot persist |
| scan | package | item rows | continue siblings where safe |
| raw store | item bytes | durable URI | retryable item failure |
| parse_header | stored item | parsed header + raw tags | invalid item, preserve bytes |
| validate | parsed header | usable / invalid | reject if required tags missing |
| classify | valid header | object family + refs | unresolved refs allowed |
| persist | item context | canonical rows + observation | transactional per item |
| duplicate_check | observation | duplicate findings | never silent overwrite |
| bind | canonical rows | platform links | binding status separate |
| index | canonical rows | projection rows | async retryable job |
| finalize | all item states | report | no item may disappear |

### 7.1 Raw-byte / DB ordering

```text
staged object
  -> durable object URI on item
  -> metadata persistence
  -> accepted terminal outcome
```

If DB persistence fails after raw bytes are durable:

- keep item row,
- mark metadata persistence failed,
- retry from stored URI,
- do not ask user to upload again.

---

## 8. State model

### 8.1 Job

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

### 8.2 Item axes

```text
scan_status       = seen | candidate | rejected_non_dicom
parse_status      = pending | parsed | failed
storage_status    = pending | stored | failed
validation_status = pending | valid | invalid | quarantined
binding_status    = pending | bound | failed | not_applicable
index_status      = pending | queued | indexed | failed
terminal_outcome  = accepted | quarantined | rejected | failed
```

---

## 9. Public API

```http
POST   /dicom-ingestions
GET    /dicom-ingestions/{jobId}
GET    /dicom-ingestions/{jobId}/items
POST   /dicom-ingestions/{jobId}/retry

GET    /dicom/studies
GET    /dicom/studies/{studyId}
GET    /dicom/series
GET    /dicom/series/{seriesId}
GET    /dicom/instances
GET    /dicom/instances/{instanceId}

POST   /dicom/index-jobs
GET    /dicom/index-jobs/{jobId}
POST   /dicom/index-jobs/{jobId}/retry

GET    /dicom/duplicates
GET    /dicom/references/unresolved

GET    /dicom/series-conflicts
GET    /dicom/series-conflicts/{id}
POST   /dicom/series-conflicts/{id}/resolve
```

Query APIs must read from projections, not scan raw tag payloads.

---

## 10. Error registry

| Failure | Response |
| --- | --- |
| `EmptyUploadRequest` | reject request |
| `UploadTooLarge` | reject request |
| `UploadPackageStoreFailed` | fail request/job visibly |
| `ZipExtractionFailed` | fail package visibly |
| `ZipBombDetected` | reject securely |
| `UnsafeArchivePath` | reject securely |
| `DicomParseFailed` | reject item, preserve bytes |
| `MissingRequiredDicomTag` | reject item |
| `RawObjectStoreFailed` | retry item |
| `MetadataPersistenceFailed` | retry from stored bytes |
| `LogicalIdentityConflict` | attach observation, create duplicate finding |
| `BindingPolicyFailed` | keep ingest accepted, mark binding failed |
| `IndexProjectionFailed` | retry index job |
| `ReportInvariantFailed` | fail loudly, alert |

No catch-all swallowing. Every named failure must be testable and visible.

---

## 11. Security

Must include:

- max expanded ZIP bytes
- max ZIP entry count
- max ZIP nesting depth
- path traversal protection
- input size limits
- temp cleanup guarantees
- PHI-safe logging
- audit events for upload, quarantine, duplicate resolution, remapping

Logs should use internal IDs, governed identifiers, counts, and error codes.  
Do not casually emit raw PHI-bearing metadata.

---

## 12. Observability

### Metrics

- `dicom_ingestion_jobs_total{status}`
- `dicom_ingestion_items_total{terminal_state}`
- `dicom_ingestion_stage_duration_seconds{stage}`
- `dicom_parse_failures_total{error_code}`
- `dicom_duplicate_findings_total{type}`
- `dicom_unresolved_references_total`
- `dicom_index_jobs_total{status}`
- `dicom_ingestion_orphaned_raw_objects_total`
- `dicom_binding_failures_total`
- `dicom_report_invariant_failures_total`
- `dicom_projection_stale_total`

### Logs

Required keys:

- `job_id`
- `item_id`
- `stage`
- UID fields when known
- `error_code`
- retry count

### Traces

One trace per ingestion job, spans for:

- receive
- scan
- raw store
- parse
- persist
- bind
- index

---

## 13. Required tests

### Unit

- scanner recursion and ZIP limits
- header-only parser
- required-tag validation
- classifier
- creator-aware private tags
- duplicate logic
- reference extraction
- binding status handling

### Integration

- mixed batch truthful report
- one bad item among many
- raw bytes stored, DB write fails
- duplicate SOP in separate jobs
- same job retried
- binding fails after ingest succeeds
- index fails after ingest succeeds
- unresolved reference preserved
- projection rebuild equivalence
- study completeness remains `unknown` without trusted manifest
- report invariant mismatch fails loudly

### Security

- ZIP bomb
- path traversal
- malformed parser input
- oversize upload
- temp cleanup after failure
- PHI-safe logging

### Confidence test

```text
mixed ZIP
  + one object-store failure
  + one DB failure after raw-store success
  + one duplicate SOP
  + one unresolved reference
  -> final report tells the truth for every item
  -> replay still works from preserved bytes
```

---

## 14. Build order

```text
M0 Foundation
  A1 schema + invariants
  A2 fixture corpus
  A3 raw storage contract

M1 Intake spine
  B1 upload API
  B2 package persistence
  B3 scanner + ZIP safety
  B4 job/item state engine
  B5 parser + validation
  B6 canonical persistence
  B7 terminal report

M2 Trust layer
  C1 duplicate facts
  C2 private tags
  C3 reference edges
  C4 binding policy
  C5 index jobs + projections
  C6 retry/replay
  C7 observability

M3 Release hardening
  D1 query APIs
  D2 security pack
  D3 replay/reindex validation
  D4 rollout + runbooks
```

Critical path:

```text
A1 -> A2 -> A3 -> B1/B2 -> B3 -> B4 -> B5 -> B6 -> B7 -> C5 -> D1
```

---

## 15. Acceptance

V1 is done when:

1. every uploaded file has an explicit outcome,
2. every accepted file preserves raw bytes,
3. retries do not create duplicate truth,
4. duplicate facts are visible,
5. unresolved references are visible,
6. projections rebuild without re-upload,
7. valid DICOM can outlive binding failure,
8. operators can locate a stuck batch in under five minutes,
9. security fixtures pass,
10. rollback does not require deleting medical data.

---

## 16. Still intentionally deferred

- metadata-only byte-prefix artifact
- exact private creators for first real users
- whether future derived-object enrichment needs more than typed staged jobs

These are workload decisions, not blockers for v1.
