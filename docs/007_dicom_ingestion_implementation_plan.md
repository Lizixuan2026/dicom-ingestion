# DICOM Ingestion Module — V1 Implementation Plan

## 1. Executive decision

The right v1 is **not** “support the most DICOM object types.”

The right v1 is:

> **prove that the platform has a trustworthy imaging intake spine.**

If a user uploads a folder or ZIP of DICOM files, the system must reliably:

1. preserve the original bytes,
2. explain exactly what happened to every file,
3. produce a neutral Study / Series / Instance model,
4. keep enough metadata and references to avoid future re-ingestion,
5. expose a fast query surface that can be rebuilt,
6. detect duplicate facts without silently overwriting or discarding data.

That is the product wedge. Once this spine is real, support for SEG / RTSTRUCT / SR becomes an extension problem. Without it, every later feature sits on sand.

---

## 2. CEO review: what to freeze now, what to defer on purpose

### 2.1 Freeze now

| Decision | Why it must be frozen in v1 |
| --- | --- |
| Raw uploaded bytes are canonical truth | If this is wrong, replay, re-parse, audit, and future enrichment all become fragile |
| `header_only` is the default parse mode | Prevents pixel payload from leaking into the hot path and gives predictable cost |
| Ingestion and indexing are separate jobs | Required for retries, observability, and rebuildable projections |
| Canonical records and query projections are separate | Query needs will evolve faster than ingest truth |
| Platform binding is separate from DICOM parsing | Avoids hard-coding current business semantics into parser code |
| Private tags are creator-aware | Numeric private tags alone are not stable identifiers |
| Reference edges are preserved from day one | Future derived-object support depends on it |
| Identity duplicates and content duplicates are separate facts | They answer different questions and need different governance |
| Item-level terminal outcomes are explicit | “800 uploaded, 37 failed” must be visible, not buried in logs |

### 2.2 Deliberately defer

| Decision | Why defer |
| --- | --- |
| Generic workflow engine | Typed stages are enough for v1; a generic engine is premature product theater |
| Physical `bytes_until_pixel_data` artifact | Useful later if read patterns justify it, not required to prove the spine |
| Rich vendor private-tag interpretation | Need real customer/dataset evidence before choosing dictionaries |
| Full duplicate curation UI | Store the facts now; build review workflows once user behavior is known |
| Pixel-derived analytics | Valuable, but not part of proving intake trustworthiness |
| Full SEG / RTSTRUCT / SR enrichment | Preserve refs now; branch-specific enrichment can come after the trunk is sound |

### 2.3 The product trap to avoid

There are two tempting but wrong first implementations:

1. **Parser-only MVP**
   - fast to demo,
   - weak in production,
   - forces rework when retries, provenance, or derived objects appear.

2. **Mini-PACS**
   - impressive surface area,
   - wrong product boundary,
   - bloats the build before the platform-native workflow is understood.

The correct middle path is a **platform-native intake subsystem**.

---

## 3. V1 architecture in implementation terms

```text
Upload API
  -> upload package persistence
  -> IngestionJob
      -> scan
      -> parse(header_only)
      -> classify
      -> persist canonical records
      -> bind platform objects
      -> enqueue IndexJob
      -> finalize report
```

### 3.1 Required module boundaries

| Module | Owns | Must not own |
| --- | --- | --- |
| `upload` | request handling, package persistence, manifest creation | DICOM semantics |
| `scanner` | folder recursion, ZIP expansion, candidate enumeration, safety limits | final DICOM validation |
| `parser` | header-only parse, normalized extraction, raw tag retention | platform business mapping |
| `classifier` | base vs derived object classification, reference extraction | object persistence |
| `repository` | canonical records, transactional writes, duplicate facts | transport concerns |
| `binding` | mapping from neutral DICOM records to platform objects | low-level parsing |
| `indexer` | rebuildable fast query projection | canonical source of truth |
| `reporting` | job/item summaries, counters, failure reason shaping | processing logic |

### 3.2 Suggested internal service interfaces

```text
UploadService.accept(input) -> UploadPackage
ScanService.scan(upload_package) -> ScanManifest
DicomParser.parse_header(item) -> ParsedDicomHeader
DicomClassifier.classify(parsed_header) -> ClassificationResult
IngestionRepository.persist(item_context) -> PersistedDicomEntities
DicomBindingPolicy.bind(persisted_entities, context) -> BindingResult
IndexScheduler.enqueue(scope) -> IndexJob
IngestionReporter.finalize(job_id) -> IngestionReport
```

Important boundary:

```text
parser tells us what the DICOM is
binding decides what the platform should do with it
```

---

## 4. Initial relational schema

The schema below is intentionally boring. That is a feature. Boring tables are easier to reason about, migrate, replay, and query than one giant semi-structured blob.

### 4.1 Job tables

#### `dicom_ingestion_jobs`

| Column | Notes |
| --- | --- |
| `id` | primary key |
| `actor_id` | uploader / initiator |
| `request_idempotency_key` | caller-provided request replay key |
| `source_type` | `file`, `folder`, `zip`, `api` |
| `status` | lifecycle state |
| `input_manifest_json` | uploaded package summary |
| `started_at`, `finished_at` | timings |
| `retry_count` | whole-job retries |
| `report_json` | terminal summary |
| `failure_summary` | concise user-facing failure |

#### `dicom_ingestion_items`

| Column | Notes |
| --- | --- |
| `id` | primary key |
| `ingestion_job_id` | foreign key |
| `source_path` | relative source path or ZIP entry |
| `byte_size` | raw bytes |
| `whole_file_sha256` | duplicate/content support |
| `item_fingerprint` | `(ingestion_job_id, source_path, byte_size, whole_file_sha256)` |
| `scan_status` | seen / candidate / rejected |
| `parse_status` | parsed / failed |
| `storage_status` | pending / stored / failed |
| `metadata_persistence_status` | pending / persisted / failed |
| `validation_status` | valid / invalid / quarantined |
| `binding_status` | pending / bound / failed / not_applicable |
| `index_status` | pending / queued / indexed / failed |
| `terminal_outcome` | accepted / quarantined / rejected / failed |
| `storage_uri` | raw object location |
| `raw_object_status` | staged / durable / failed |
| `raw_object_sha256` | checksum of persisted bytes |
| `last_retryable_stage` | stage from which retry may resume |
| `error_code`, `error_detail` | per-item diagnosis |
| `created_at`, `updated_at` | auditability |

#### `dicom_index_jobs`

| Column | Notes |
| --- | --- |
| `id` | primary key |
| `scope_type` | instance / series / study / batch |
| `scope_id` | scope foreign key or external ID |
| `status` | queued / running / failed / completed |
| `report_json` | rebuild report |
| `failed_items_json` | retry basis |
| `created_at`, `finished_at` | timings |

### 4.2 Canonical imaging tables

#### `dicom_studies`

| Column | Notes |
| --- | --- |
| `id` | primary key |
| `study_instance_uid` | unique natural key |
| `study_date` | normalized |
| `accession_number` | nullable |
| `patient_key` | platform-governed normalized identifier |
| `series_count`, `instance_count` | denormalized but derived |
| `ingestion_completeness_status` | partial / complete / unknown |

#### `dicom_series`

| Column | Notes |
| --- | --- |
| `id` | primary key |
| `study_id` | foreign key |
| `series_instance_uid` | unique natural key |
| `modality` | normalized |
| `series_number` | nullable |
| `frame_of_reference_uid` | nullable |
| `object_class_family` | image / segmentation / structure / report / other |

#### `dicom_instances`

| Column | Notes |
| --- | --- |
| `id` | primary key |
| `study_id`, `series_id` | foreign keys |
| `sop_instance_uid` | natural key within DICOM universe |
| `sop_class_uid` | required for usable DICOM |
| `instance_number` | nullable |
| `transfer_syntax_uid` | nullable |
| `pixel_data_present` | boolean |
| `current_canonical_observation_id` | selected physical occurrence |
| `ingestion_status` | accepted / quarantined / rejected |

#### `dicom_instance_observations`

| Column | Notes |
| --- | --- |
| `id` | primary key |
| `instance_id` | logical SOP identity |
| `ingestion_item_id` | physical provenance |
| `raw_object_uri` | bytes for this observed occurrence |
| `whole_file_sha256` | content fingerprint |
| `pixel_digest` | nullable future duplicate basis |
| `raw_tag_set_uri` or `raw_tag_set_json` | full parsed retention for this observation |
| `is_canonical` | selected observation for default reads |
| `observed_at` | audit timestamp |

### 4.3 Supporting tables

#### `dicom_private_tags`

| Column | Notes |
| --- | --- |
| `id` | primary key |
| `observation_id` | foreign key to physical uploaded occurrence |
| `private_creator` | required |
| `tag` | required |
| `vr` | required |
| `raw_value` | preserved |
| `interpreted_keyword` | nullable |
| `interpreted_value` | nullable |

#### `dicom_reference_edges`

| Column | Notes |
| --- | --- |
| `id` | primary key |
| `from_instance_id` | source object |
| `relationship_type` | references / derives_from / annotates / other |
| `to_study_instance_uid` | nullable |
| `to_series_instance_uid` | nullable |
| `to_sop_instance_uid` | nullable |
| `referenced_frame_number` | nullable |
| `resolved_target_instance_id` | nullable |

#### `dicom_duplicate_findings`

| Column | Notes |
| --- | --- |
| `id` | primary key |
| `observation_id` | physical occurrence that triggered the finding |
| `duplicate_type` | identity / content |
| `basis` | sop_instance_uid / whole_file_sha256 / pixel_digest |
| `matched_instance_id` | nullable until matched |
| `matched_observation_id` | nullable until exact occurrence matched |
| `resolution_status` | unreviewed / accepted / quarantined / ignored |

#### `dicom_core_projections`

| Column | Notes |
| --- | --- |
| `instance_id` | foreign key |
| `study_instance_uid`, `series_instance_uid`, `sop_instance_uid` | indexed |
| `modality`, `study_date`, `series_number`, `instance_number` | indexed |
| `object_class_family` | indexed |
| `duplicate_flags` | indexed |
| `reference_resolution_status` | indexed |
| `binding_status` | indexed |
| `metadata_extractor_version` | extractor used to build canonical metadata |
| `projection_version` | projection schema / logic version |
| `projection_built_at` | rebuild timestamp |
| `projection_source_checksum` | source state checksum |

### 4.4 What should **not** be one table

Do **not** collapse these into a single `dicom_files` table:

- upload item,
- canonical instance,
- duplicate facts,
- platform binding,
- query projection.

Also do **not** collapse logical SOP identity and physical uploaded occurrences into one row. `dicom_instances` is the logical identity. `dicom_instance_observations` is where repeated uploads, provenance, raw bytes, and canonical selection live.

They change at different rates and answer different questions.

---

## 5. Public API surface

### 5.1 Upload and jobs

```http
POST   /dicom-ingestions
GET    /dicom-ingestions/{jobId}
GET    /dicom-ingestions/{jobId}/items
POST   /dicom-ingestions/{jobId}/retry
```

`POST /dicom-ingestions` accepts:

- single file,
- multi-file form upload,
- ZIP upload,
- existing object-store manifest reference.

Response should return:

- `job_id`
- initial `status`
- accepted input count if known
- links for polling/report retrieval

### 5.2 Query surface

```http
GET    /dicom/studies
GET    /dicom/studies/{studyId}
GET    /dicom/series
GET    /dicom/series/{seriesId}
GET    /dicom/instances
GET    /dicom/instances/{instanceId}
```

Query endpoints should be backed by the projection layer, not raw tag scans.

### 5.3 Operational APIs

```http
POST   /dicom/index-jobs
GET    /dicom/index-jobs/{jobId}
POST   /dicom/index-jobs/{jobId}/retry
```

Optional but useful in v1:

```http
GET    /dicom/duplicates
GET    /dicom/references/unresolved
```

These two endpoints are cheap confidence multipliers. They make hidden ingestion debt visible early.

---

## 6. Exact v1 pipeline

### 6.1 Stage sequence

| Stage | Inputs | Outputs | Failure rule |
| --- | --- | --- | --- |
| `receive` | request payload | upload package, job row | reject whole request if package persistence fails |
| `scan` | package | item rows, manifest | continue siblings if one entry fails |
| `parse_header` | candidate item | parsed header, raw tag set | mark item invalid; preserve raw bytes |
| `validate` | parsed header | usable / invalid | reject if required tags missing, esp. `SOPClassUID` |
| `classify` | validated header | object family, refs | unresolved refs are allowed |
| `persist` | item context | canonical study/series/instance records | transactional per item |
| `duplicate_check` | persisted instance | duplicate findings | no silent overwrite |
| `bind` | persisted entities | platform links | binding failure should not destroy ingest truth |
| `index` | persisted entities | projection rows | separate retryable job |
| `finalize` | all item states | report | every item has a terminal or active state |

### 6.2 Per-item transaction rule

Each item should be idempotent around a stable content key:

```text
source item
  -> raw byte persistence
  -> metadata extraction
  -> canonical upsert
  -> side records
```

Do not require the whole batch to be one DB transaction. That turns one bad file into a 2,000-file failure.

### 6.3 Raw-byte / DB failure rule

Object storage and the relational DB are not one transaction. Model that explicitly:

```text
staged upload object
  -> durable object pointer persisted on IngestionItem
  -> canonical records written
  -> item marked stored / accepted
```

If raw bytes are durable but metadata persistence fails:

- keep the `IngestionItem`,
- mark `metadata_persistence_status = failed`,
- preserve `raw_object_uri`,
- retry from the stored object,
- do not require the user to re-upload.

### 6.4 V1 object classification

Minimal classifier:

- `image`
- `segmentation`
- `structured_report`
- `rt_structure`
- `other`

The classifier only needs to do enough to:

1. preserve useful reference edges,
2. set future routing hooks,
3. expose coarse object-family query filters.

It does **not** need to complete all object-specific enrichment in v1.

---

## 7. Delivery plan

## Phase 1 — Intake spine

### Goal

Upload bytes, preserve them, explain outcomes, and build neutral canonical records.

### Build

1. `UploadService`
2. safe ZIP extraction and recursive scanner
3. `dicom_ingestion_jobs`
4. `dicom_ingestion_items`
5. raw object storage
6. header-only parser
7. usable-DICOM validation
8. study / series / instance persistence
9. terminal job report

### Exit criteria

- a user can upload a ZIP/folder batch,
- every file appears in the report,
- every accepted DICOM has preserved raw bytes,
- malformed and non-DICOM files do not poison sibling items,
- re-running the same package is safe and explainable.

## Phase 2 — Trust layer

### Goal

Make the system auditable, queryable, and operationally sane.

### Build

1. `dicom_index_jobs`
2. `dicom_core_projections`
3. duplicate detection
4. private-tag persistence
5. reference-edge persistence
6. retry flows
7. unresolved-reference and duplicate query endpoints
8. baseline metrics / tracing / structured logs

### Exit criteria

- users can query accepted studies / series / instances efficiently,
- index projection can be rebuilt without re-upload,
- duplicates are visible as facts,
- unresolved references are visible instead of silently lost,
- operators can see where a job is slow or failing.

## Phase 3 — Imaging depth

### Goal

Extend the trusted spine into richer medical-imaging behavior.

### Build

1. branch-specific enrichment dispatcher
2. SEG / RTSTRUCT / SR enrichment
3. selected vendor private-tag dictionaries
4. curation workflow for duplicate findings
5. optional metadata-prefix artifact if workload proves need
6. optional pixel-derived analytics

### Exit criteria

- derived objects have first-class enrichment paths,
- private-tag interpretation is evidence-driven,
- operational data shows whether extra storage optimizations are justified.

---

## 8. Testing plan

### 8.1 Unit tests

| Area | Must cover |
| --- | --- |
| scanner | recursion, nested ZIPs, non-DICOM files, extraction limits |
| parser | header-only behavior, malformed datasets, missing `SOPClassUID` |
| classifier | supported object-family routing |
| private tags | creator-aware identity |
| duplicate detection | identity duplicate vs content duplicate |
| reference extraction | referenced SOP / frame capture |
| binding | parser neutrality, mapping result handling |

### 8.2 Integration tests

| Scenario | Expected result |
| --- | --- |
| mixed upload batch | accepted + rejected + invalid all reported correctly |
| one bad item among many | siblings continue |
| object-store failure | safe retry, no phantom acceptance |
| DB failure after bytes saved | no corrupt canonical state |
| duplicate upload | duplicate finding, no silent overwrite |
| projection rebuild | same query result after reindex |
| unresolved reference | edge stored, resolution pending visible |

### 8.3 Golden fixtures

Create a fixture set with:

1. valid CT/MR base image,
2. missing required UID,
3. malformed file,
4. duplicate SOP UID pair,
5. duplicate-content pair,
6. private tags from at least two creators,
7. one SEG or SR with references,
8. ZIP with mixed payload.

Do this early. Fixtures will become the fastest regression detector in the project.

### 8.4 Performance tests

Track:

- parse throughput in `header_only` mode,
- upload-to-report latency for 100 / 1,000 / 10,000 files,
- projection rebuild time,
- duplicate-check cost,
- memory profile on large ZIP inputs.

---

## 9. Observability plan

### 9.1 Metrics

| Metric | Purpose |
| --- | --- |
| `dicom_ingestion_jobs_total{status}` | volume and failure rate |
| `dicom_ingestion_items_total{terminal_state}` | user-visible outcomes |
| `dicom_ingestion_stage_duration_seconds{stage}` | bottleneck detection |
| `dicom_parse_failures_total{error_code}` | data quality diagnosis |
| `dicom_duplicate_findings_total{type}` | curation pressure |
| `dicom_unresolved_references_total` | derived-object readiness |
| `dicom_index_jobs_total{status}` | projection health |

### 9.2 Logs

Structured logs must include:

- `job_id`
- `item_id`
- `stage`
- `study_instance_uid` / `series_instance_uid` / `sop_instance_uid` where known
- `error_code`
- retry count

### 9.3 Traces

One trace per ingestion job, child spans for:

- receive
- scan
- parse
- persist
- bind
- index

### 9.4 Product-visible reporting

The report is not just an ops artifact. It is part of the product.

Minimum report:

- uploaded count
- candidate count
- accepted count
- quarantined count
- rejected count
- duplicate findings
- unresolved references
- per-item failure list

---

## 10. Security and governance requirements

### 10.1 Mandatory v1 controls

| Control | Reason |
| --- | --- |
| max expanded ZIP bytes | prevent archive abuse / resource exhaustion |
| max ZIP entry count | prevent pathological fan-out |
| max nesting depth | prevent decompression bombs and parser abuse |
| path traversal protection | prevent extraction outside the intended workspace |
| input size limits | keep tenant and system cost bounded |
| temp-file cleanup guarantees | avoid PHI leakage on workers |
| immutable source-byte provenance | support audit and replay |
| retention-policy hooks for PHI-bearing fields | separate ingestion mechanics from governance policy |
| audit events for upload, quarantine, duplicate resolution, and remapping | make sensitive state changes reconstructable |

### 10.2 Logging rule

Do not log raw PHI-bearing metadata casually.

Logs should favor:

- internal IDs,
- hashed or governed identifiers,
- error codes,
- stage names,
- counts.

If a raw DICOM field must appear in logs for diagnosis, that should be an explicit policy choice, not an accidental `debug(obj)`.

### 10.3 First-release threat cases to test

1. ZIP bomb,
2. path traversal entry,
3. malformed DICOM designed to crash parser flow,
4. oversize upload,
5. temp cleanup after mid-pipeline failure,
6. accidental PHI emission in logs or reports.

---

## 11. Frozen implementation decisions

These are now part of the v1 contract:

| Decision | Frozen rule |
| --- | --- |
| Duplicate SOP storage | `dicom_instances` is logical identity, `dicom_instance_observations` stores physical uploaded occurrences |
| Raw tag / private tag ownership | observation-scoped, because different physical occurrences may carry different raw metadata |
| Request idempotency | `request_idempotency_key` deduplicates repeated API submissions |
| Item idempotency | `item_fingerprint = (ingestion_job_id, source_path, byte_size, whole_file_sha256)` |
| Raw bytes vs DB failure | keep durable raw bytes, mark metadata persistence failed, retry from stored object |
| Binding failure | valid ingest remains `accepted`; separate `binding_status = pending | bound | failed | not_applicable` |
| Projection rebuild | versioned by extractor/projection versions, rebuildable manually or on relevant version bump |
| Study completeness | default `unknown`; `partial` when known failures exist; `complete` only with trusted external manifest / explicit completeness contract |

---

## 12. Migration and rollout order

### 12.1 Database migration order

1. job tables
2. canonical Study / Series / Instance tables
3. physical observation table
4. support tables: private tags, reference edges, duplicate findings
5. projection tables
6. binding tables or link tables into platform objects

### 12.2 Deployment order

1. ship schema,
2. ship intake pipeline dark,
3. ingest internal fixture dataset,
4. verify reports and projections,
5. expose upload endpoint to limited users,
6. enable index retries and dashboards,
7. only then widen rollout.

### 12.3 Backfill / replay posture

Because raw bytes are canonical, replay should support:

- re-parse with newer extraction logic,
- rebuild projections,
- re-run duplicate checks,
- re-run future derived-object enrichment.

This is one of the strongest reasons to preserve bytes first.

---

## 13. Acceptance criteria

### 13.1 Product acceptance

V1 is successful when:

1. a user can upload a mixed DICOM batch and get a truthful report,
2. every accepted file has preserved original bytes,
3. every rejected or quarantined file has a user-visible reason,
4. Study / Series / Instance browsing works without scanning raw tag blobs,
5. duplicate facts are visible,
6. unresolved derived-object references are not lost,
7. a projection rebuild does not require re-upload.

### 13.2 Engineering acceptance

V1 is not done unless:

1. ingest is idempotent at item level,
2. index failures do not corrupt canonical records,
3. retries are explicit and observable,
4. the parser has a true header-only path,
5. private tags preserve creator identity,
6. fixture-backed tests cover the major failure modes,
7. operators can answer “where is this batch stuck?” without database spelunking.

---

## 14. Deliberately deferred product / workload decisions

These remain open on purpose because they require real usage evidence:

1. **Storage optimization**  
   Should v1 physically persist a metadata-only byte prefix, or wait until read patterns prove the need?

2. **Private-tag scope**  
   Which private creators matter for the first real users or datasets?

3. **Branch mechanism**  
   Is a typed staged runner enough for the first derived-object release, or do we need something more general sooner?

---

## 15. “Not now” list

Do not let these pull the team off the critical path during v1:

- viewer implementation,
- PACS networking,
- auto-anonymization workflow,
- advanced image analytics,
- generic DAG engine,
- broad vendor dictionary catalog,
- rich curation UX,
- full derived-object post-processing.

These are legitimate later investments. They are simply not the first proof point.

---

## 16. Traceability back to the research

| Implementation choice | Research basis |
| --- | --- |
| Separate ingest and index jobs | Dicoogle |
| Explicit header-only parse | XNAT, dcm4che |
| Raw bytes canonical, projections rebuildable | Orthanc |
| Creator-aware private tags | dcm4che |
| Separate platform binding layer | XNAT |
| Preserve reference graph early | OHIF |
| Separate identity/content duplicates | Posda |
| Branch-capable future workflow | Kaapana |

This plan is therefore not just internally coherent. It is anchored in the mature systems we inspected.

---

## 17. Final recommendation

If we want the **10-star** version rather than the merely adequate version, build in this order:

1. **trust the ingest**
2. **trust the query**
3. **then deepen the imaging semantics**

That order gives the platform something valuable early, while preserving the path to the richer product later.
