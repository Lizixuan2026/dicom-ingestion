# DICOM Ingestion — Migration-First Backlog

Documentation map: `001_dicom_ingestion_documentation_map.md`

## 0. How to use this document

Each item in this backlog is the smallest shippable unit that a single engineer can complete, verify, and commit before the next item starts.

- **Depends on** lists the item IDs that must be merged first.
- **Acceptance** is a checklist. The item is done when every line passes.
- File paths use `app/` as the module root. Adjust to your project's actual layout.

Reading order before touching this backlog:

1. `001_dicom_ingestion_documentation_map.md`
2. `010_dicom_ingestion_implementation_spec.md`
3. `011_dicom_ingestion_schema_and_contracts.md`
4. `013_dicom_ingestion_full_feature_implementation_roadmap.md`
5. this document

---

## M0 — Foundation

### A1-a — `dicom_studies` migration

**File:** `db/migrate/YYYYMMDD_create_dicom_studies.rb` (or equivalent)

**Depends on:** nothing

**Creates:**

```sql
dicom_studies
  id                          bigserial primary key
  study_instance_uid          text      not null
  patient_name                text
  patient_id                  text
  study_date                  date
  study_time                  text
  accession_number            text
  study_description           text
  series_count                integer   not null default 0
  instance_count              integer   not null default 0
  ingestion_completeness_status text    not null default 'unknown'
  created_at                  timestamptz not null
  updated_at                  timestamptz not null

UNIQUE(study_instance_uid)
```

**Acceptance:**

- [ ] migration runs forward without error
- [ ] migration rolls back without error
- [ ] `UNIQUE(study_instance_uid)` rejects a second row with the same UID
- [ ] `ingestion_completeness_status` default is `unknown`

---

### A1-b — `dicom_series` migration

**File:** `db/migrate/YYYYMMDD_create_dicom_series.rb`

**Depends on:** A1-a

**Creates:**

```sql
dicom_series
  id                    bigserial primary key
  study_id              bigint    not null references dicom_studies(id) on delete restrict
  series_instance_uid   text      not null
  modality              text
  series_number         integer
  series_description    text
  frame_of_reference_uid text
  object_class_family   text
  created_at            timestamptz not null
  updated_at            timestamptz not null

UNIQUE(series_instance_uid)
INDEX(study_id)
```

**Acceptance:**

- [ ] migration runs forward / rolls back
- [ ] `UNIQUE(series_instance_uid)` enforced
- [ ] FK to `dicom_studies` with `ON DELETE RESTRICT`
- [ ] `study_id` index present

---

### A1-c — `dicom_instances` migration

**File:** `db/migrate/YYYYMMDD_create_dicom_instances.rb`

**Depends on:** A1-b

**Creates:**

```sql
dicom_instances
  id                              bigserial primary key
  study_id                        bigint not null references dicom_studies(id)   on delete restrict
  series_id                       bigint not null references dicom_series(id)    on delete restrict
  sop_instance_uid                text   not null
  sop_class_uid                   text
  instance_number                 integer
  transfer_syntax_uid             text
  pixel_data_present              boolean not null default false
  current_canonical_observation_id bigint  -- FK added after observations table
  ingestion_status                text   not null default 'pending'
  created_at                      timestamptz not null
  updated_at                      timestamptz not null

UNIQUE(sop_instance_uid)
INDEX(study_id)
INDEX(series_id)
```

Note: `current_canonical_observation_id` FK is added in A1-d after `dicom_instance_observations` exists.

**Acceptance:**

- [ ] migration runs forward / rolls back
- [ ] `UNIQUE(sop_instance_uid)` enforced
- [ ] `study_id` and `series_id` indexes present

---

### A1-d — `dicom_instance_observations` migration + canonical FK

**File:** `db/migrate/YYYYMMDD_create_dicom_instance_observations.rb`

**Depends on:** A1-c

**Creates:**

```sql
dicom_instance_observations
  id                  bigserial primary key
  instance_id         bigint not null references dicom_instances(id) on delete restrict
  ingestion_item_id   bigint not null  -- FK to items added in A1-f
  raw_object_uri      text
  whole_file_sha256   text
  pixel_digest        text
  raw_tag_set_uri     text
  raw_tag_set_json    jsonb
  is_canonical        boolean not null default false
  observed_at         timestamptz not null
  created_at          timestamptz not null
  updated_at          timestamptz not null

UNIQUE(instance_id, ingestion_item_id)            -- retry idempotency key: same item re-running cannot
                                                  -- produce a second observation for the same SOP
UNIQUE(id, instance_id)                          -- enables composite FK from dicom_instances
UNIQUE(instance_id) WHERE is_canonical = true    -- at most one canonical per instance, DB-enforced
INDEX(ingestion_item_id)
INDEX(whole_file_sha256)
INDEX(pixel_digest)
```

Then in the same migration or a follow-up:

```sql
-- Simple FK for existence check (deferrable for circular insert order)
ALTER TABLE dicom_instances
  ADD CONSTRAINT fk_canonical_observation
  FOREIGN KEY (current_canonical_observation_id)
  REFERENCES dicom_instance_observations(id)
  ON DELETE RESTRICT
  DEFERRABLE INITIALLY DEFERRED;

-- Composite FK to guarantee the canonical observation belongs to THIS instance
ALTER TABLE dicom_instances
  ADD CONSTRAINT fk_canonical_observation_owns_instance
  FOREIGN KEY (current_canonical_observation_id, id)
  REFERENCES dicom_instance_observations(id, instance_id)
  DEFERRABLE INITIALLY DEFERRED;
```

The composite FK requires the `UNIQUE(id, instance_id)` index on observations. Together these two constraints close the loop: the canonical observation must (a) exist and (b) have `instance_id` equal to the instance that points to it.

DB guarantees "at most one canonical" (partial unique index + composite FK). Repository must guarantee "exactly one canonical after successful persist" — the lower bound the DB cannot enforce. Full invariant specification: `011` §3.

**Acceptance:**

- [ ] migration runs forward / rolls back
- [ ] `UNIQUE(instance_id, ingestion_item_id)` enforced
- [ ] partial unique `UNIQUE(instance_id) WHERE is_canonical = true` rejects a second `is_canonical = true` row for the same instance at commit time
- [ ] composite FK `(current_canonical_observation_id, id)` rejects a row where `current_canonical_observation_id` points to an observation belonging to a different instance
- [ ] both FKs are deferrable; a transaction inserting instance then observation (or reverse order) commits successfully
- [ ] `whole_file_sha256` and `pixel_digest` indexes present
- [ ] the distinction between "at most one" (DB) and "exactly one" (repository) is documented in a migration comment so the next engineer does not conflate them

---

### A1-e — `dicom_ingestion_jobs` migration

**File:** `db/migrate/YYYYMMDD_create_dicom_ingestion_jobs.rb`

**Depends on:** nothing (can run parallel to A1-a..d)

**Creates:**

```sql
dicom_ingestion_jobs
  id                        bigserial primary key
  actor_id                  text      not null
  request_idempotency_key   text
  source_type               text      not null
  status                    text      not null default 'created'
  input_manifest_json       jsonb
  started_at                timestamptz
  finished_at               timestamptz
  retry_count               integer   not null default 0
  report_json               jsonb
  failure_summary           text
  created_at                timestamptz not null
  updated_at                timestamptz not null

UNIQUE(actor_id, request_idempotency_key) WHERE request_idempotency_key IS NOT NULL
INDEX(status, created_at)
```

**Acceptance:**

- [ ] partial unique index (`WHERE request_idempotency_key IS NOT NULL`) enforced
- [ ] two rows with `request_idempotency_key = NULL` for the same `actor_id` are both accepted
- [ ] two rows with the same `actor_id` + same non-null `request_idempotency_key` are rejected

---

### A1-f — `dicom_ingestion_items` migration

**File:** `db/migrate/YYYYMMDD_create_dicom_ingestion_items.rb`

**Depends on:** A1-e

**Creates:**

```sql
dicom_ingestion_items
  id                          bigserial primary key
  ingestion_job_id            bigint not null references dicom_ingestion_jobs(id) on delete restrict
  source_path                 text
  byte_size                   bigint
  whole_file_sha256           text
  item_fingerprint            text   not null
  scan_status                 text   not null default 'seen'
  parse_status                text   not null default 'pending'
  storage_status              text   not null default 'pending'
  metadata_persistence_status text   not null default 'pending'
  validation_status           text   not null default 'pending'
  binding_status              text   not null default 'pending'
  index_status                text   not null default 'pending'
  terminal_outcome            text
  storage_uri                 text
  raw_object_status           text
  raw_object_sha256           text
  last_retryable_stage        text
  error_code                  text
  error_detail                text
  created_at                  timestamptz not null
  updated_at                  timestamptz not null

UNIQUE(item_fingerprint)
INDEX(ingestion_job_id, terminal_outcome)
INDEX(last_retryable_stage)
```

Now add the deferred FK from observations to items:

```sql
ALTER TABLE dicom_instance_observations
  ADD CONSTRAINT fk_ingestion_item
  FOREIGN KEY (ingestion_item_id)
  REFERENCES dicom_ingestion_items(id)
  ON DELETE RESTRICT;
```

**Acceptance:**

- [ ] `UNIQUE(item_fingerprint)` enforced
- [ ] composite index `(ingestion_job_id, terminal_outcome)` present
- [ ] FK from `dicom_instance_observations.ingestion_item_id` valid

---

### A1-g — `dicom_index_jobs` migration

**File:** `db/migrate/YYYYMMDD_create_dicom_index_jobs.rb`

**Depends on:** A1-f

**Creates:**

```sql
dicom_index_jobs
  id                bigserial primary key
  scope_type        text not null
  scope_id          bigint not null
  status            text not null default 'pending'
  report_json       jsonb
  failed_items_json jsonb
  created_at        timestamptz not null
  updated_at        timestamptz not null

INDEX(status, created_at)
```

**Acceptance:**

- [ ] migration runs forward / rolls back
- [ ] `(status, created_at)` index present

---

### A1-h — `dicom_private_tags` migration

**File:** `db/migrate/YYYYMMDD_create_dicom_private_tags.rb`

**Depends on:** A1-d

**Creates:**

```sql
dicom_private_tags
  id                   bigserial primary key
  observation_id       bigint not null references dicom_instance_observations(id) on delete cascade
  private_creator      text   not null
  tag                  text   not null
  vr                   text
  raw_value            bytea    -- stores raw bytes regardless of VR; if you later need text-searchable
                                -- vendor strings, add a generated column or a separate text field
  interpreted_keyword  text
  interpreted_value    text
  created_at           timestamptz not null

UNIQUE(observation_id, private_creator, tag)
```

**Acceptance:**

- [ ] `UNIQUE(observation_id, private_creator, tag)` enforced
- [ ] `ON DELETE CASCADE` from observation verified: deleting an observation removes its private tags

---

### A1-i — `dicom_reference_edges` migration

**File:** `db/migrate/YYYYMMDD_create_dicom_reference_edges.rb`

**Depends on:** A1-c

**Creates:**

```sql
dicom_reference_edges
  id                          bigserial primary key
  from_instance_id            bigint not null references dicom_instances(id) on delete restrict
  relationship_type           text   not null
  to_study_instance_uid       text
  to_series_instance_uid      text
  to_sop_instance_uid         text
  referenced_frame_number     integer
  resolved_target_instance_id bigint references dicom_instances(id) on delete restrict
  created_at                  timestamptz not null
  updated_at                  timestamptz not null

INDEX(to_sop_instance_uid)
INDEX(to_series_instance_uid)
INDEX(resolved_target_instance_id)
```

The natural key for an edge is the tuple that uniquely describes one reference declared in a DICOM header:

```sql
(from_instance_id, relationship_type,
 to_study_instance_uid, to_series_instance_uid,
 to_sop_instance_uid, referenced_frame_number)
```

All of `to_*` and `referenced_frame_number` are nullable (partial references exist in real DICOM). Standard `UNIQUE` breaks on NULLs for the same reason as `dicom_duplicate_findings`.

Use the same strategy:

```sql
-- PostgreSQL 15+: single constraint, NULLs treated as equal
CREATE UNIQUE INDEX udx_reference_edges_natural
  ON dicom_reference_edges(from_instance_id, relationship_type,
                            to_study_instance_uid, to_series_instance_uid,
                            to_sop_instance_uid, referenced_frame_number)
  NULLS NOT DISTINCT;
```

If running PostgreSQL < 15, create partial indexes per observed reference shape (same pattern as A1-j). Document which version is assumed before merging this migration.

`resolved_target_instance_id` is intentionally excluded from the natural key. Resolution is a derived fact written later; the same edge should not appear twice regardless of resolution state.

**Acceptance:**

- [ ] indexes on `to_sop_instance_uid`, `to_series_instance_uid`, `resolved_target_instance_id` present
- [ ] `resolved_target_instance_id` nullable (unresolved references allowed)
- [ ] re-extracting reference edges from the same instance (e.g., on index rebuild) does not insert duplicate rows — verified by DB constraint, not application logic
- [ ] two edges from the same instance with different `relationship_type` but identical target UIDs are both stored (different natural keys)
- [ ] PostgreSQL version assumption is documented in a migration comment

---

### A1-j — `dicom_duplicate_findings` migration

**File:** `db/migrate/YYYYMMDD_create_dicom_duplicate_findings.rb`

**Depends on:** A1-d

**Creates:**

```sql
dicom_duplicate_findings
  id                      bigserial primary key
  observation_id          bigint not null references dicom_instance_observations(id) on delete restrict
  duplicate_type          text   not null  -- 'identity' | 'content'
  basis                   text   not null  -- 'sop_instance_uid' | 'whole_file_sha256' | 'pixel_digest'
  matched_instance_id     bigint references dicom_instances(id)             on delete restrict
  matched_observation_id  bigint references dicom_instance_observations(id) on delete restrict
  resolution_status       text   not null default 'open'
  created_at              timestamptz not null
  updated_at              timestamptz not null

INDEX(observation_id)
INDEX(matched_instance_id)
INDEX(matched_observation_id)
```

Do NOT use a single `UNIQUE(... matched_instance_id, matched_observation_id)`. PostgreSQL treats NULL as unknown in standard unique indexes, so two rows with the same non-null columns but `matched_observation_id = NULL` are both accepted — breaking idempotency exactly where it matters most.

Instead, create one partial unique index per valid finding shape:

```sql
-- Shape 1: identity finding — both matched columns present
CREATE UNIQUE INDEX udx_dup_findings_identity
  ON dicom_duplicate_findings(observation_id, duplicate_type, basis,
                               matched_instance_id, matched_observation_id)
  WHERE matched_instance_id IS NOT NULL
    AND matched_observation_id IS NOT NULL;

-- Shape 2: content finding matched to observation only
CREATE UNIQUE INDEX udx_dup_findings_content_obs
  ON dicom_duplicate_findings(observation_id, duplicate_type, basis,
                               matched_observation_id)
  WHERE matched_instance_id IS NULL
    AND matched_observation_id IS NOT NULL;

-- Shape 3: content finding matched to instance only (rare but possible)
CREATE UNIQUE INDEX udx_dup_findings_content_inst
  ON dicom_duplicate_findings(observation_id, duplicate_type, basis,
                               matched_instance_id)
  WHERE matched_instance_id IS NOT NULL
    AND matched_observation_id IS NULL;
```

If the project runs PostgreSQL 15+, a single `UNIQUE NULLS NOT DISTINCT (...)` is equivalent and simpler. Use whichever your production version supports. Confirm before choosing.

**Acceptance:**

- [ ] retry of an identity finding (both matched columns set) does not insert a duplicate row
- [ ] retry of a content finding with only `matched_observation_id` set does not insert a duplicate row
- [ ] retry of a content finding with only `matched_instance_id` set does not insert a duplicate row
- [ ] a finding row where both matched columns are NULL is rejected by a `CHECK` constraint or application validation — that shape is never valid
- [ ] all three FK relations use `ON DELETE RESTRICT`

---

### A1-k — `dicom_core_projections` migration

**File:** `db/migrate/YYYYMMDD_create_dicom_core_projections.rb`

**Depends on:** A1-c

**Creates:**

```sql
dicom_core_projections
  instance_id                  bigint primary key references dicom_instances(id) on delete restrict
  study_instance_uid           text
  series_instance_uid          text
  sop_instance_uid             text
  modality                     text
  study_date                   date
  object_class_family          text
  binding_status               text
  duplicate_flags              jsonb
  reference_resolution_status  text
  metadata_extractor_version   text   not null
  projection_version           text   not null
  projection_built_at          timestamptz not null
  projection_source_checksum   text   not null

INDEX(study_instance_uid)
INDEX(series_instance_uid)
INDEX(sop_instance_uid)
INDEX(modality)
INDEX(study_date)
INDEX(object_class_family)
INDEX(binding_status)
```

**Acceptance:**

- [ ] all seven hot-path indexes present (see `011` §4.5)
- [ ] `instance_id` is both PK and FK to `dicom_instances`

---

### A1-l — `dicom_series_ingestion_attempts` migration

**File:** `db/migrate/YYYYMMDD_create_dicom_series_ingestion_attempts.rb`

**Depends on:** A1-e, A1-f

Three-tier model rationale: `006` §5.6–5.8. This is the entity that bridges file-level items to Series-level conflict review.

**Creates:**

```sql
dicom_series_ingestion_attempts
  id                      bigserial primary key
  ingestion_job_id        bigint not null references dicom_ingestion_jobs(id) on delete restrict
  study_instance_uid      text   not null
  series_instance_uid     text   not null
  uploaded_sop_count      integer not null default 0
  created_at              timestamptz not null
  updated_at              timestamptz not null

UNIQUE(ingestion_job_id, series_instance_uid)
INDEX(ingestion_job_id)
INDEX(series_instance_uid)
```

Then add `series_ingestion_attempt_id` to `dicom_ingestion_items`:

```sql
ALTER TABLE dicom_ingestion_items
  ADD COLUMN series_ingestion_attempt_id bigint
    REFERENCES dicom_series_ingestion_attempts(id)
    ON DELETE RESTRICT;

CREATE INDEX ON dicom_ingestion_items(series_ingestion_attempt_id);
```

The column is nullable: items that are not DICOM (e.g. scan-rejected non-DICOM files) will have no series attempt. Items that are accepted DICOM must have `series_ingestion_attempt_id` set before `terminal_outcome = accepted`.

**Acceptance:**

- [ ] migration runs forward / rolls back
- [ ] `UNIQUE(ingestion_job_id, series_instance_uid)` enforced: one attempt per Series per job
- [ ] `dicom_ingestion_items.series_ingestion_attempt_id` is nullable and FK-constrained
- [ ] non-DICOM items with `scan_status = rejected_non_dicom` may have `series_ingestion_attempt_id = NULL`
- [ ] accepted DICOM items must have `series_ingestion_attempt_id` set — verified by a `CHECK` constraint or application assertion

---

### A1-z — Invariant test suite for schema

**File:** `spec/db/dicom_schema_invariants_spec.rb` (or equivalent)

**Depends on:** A1-a through A1-l

This test file runs against the actual database. It does not test application logic.

DB-level invariants (what the schema alone enforces):

- [ ] each UNIQUE constraint rejects the exact duplicate case
- [ ] each `ON DELETE RESTRICT` FK prevents orphan deletion
- [ ] `dicom_private_tags ON DELETE CASCADE` fires correctly
- [ ] canonical upper-bound: inserting a second `is_canonical = true` observation for the same instance is rejected by the partial unique index at commit time — this is "at most one"
- [ ] canonical cross-instance: setting `current_canonical_observation_id` to an observation belonging to a different instance is rejected by the composite FK — a `NULL` pointer is still accepted by the DB at this layer
- [ ] canonical FK deferral: a transaction that inserts `dicom_instances` and `dicom_instance_observations` in either order and commits with a valid `current_canonical_observation_id` succeeds
- [ ] `dicom_ingestion_jobs` partial unique: null key allows duplicates, non-null key does not
- [ ] `dicom_duplicate_findings`: identity finding retry (both matched columns set) does not insert a duplicate row
- [ ] `dicom_duplicate_findings`: content finding retry (only `matched_observation_id` set) does not insert a duplicate row
- [ ] `dicom_reference_edges`: re-inserting an identical edge tuple does not insert a duplicate row
- [ ] `dicom_series_ingestion_attempts`: `UNIQUE(ingestion_job_id, series_instance_uid)` rejects a second attempt for the same Series in the same job
- [ ] an accepted DICOM item with `series_ingestion_attempt_id = NULL` is rejected by the application assertion (DB allows NULL; enforcement is at repository layer)

Repository-level invariants (what the application layer must enforce — tested in B6, not here):

- [ ] note: the schema does not and cannot prevent `current_canonical_observation_id = NULL` after a failed or partial transaction; that gap belongs to B6's post-commit assertion tests

---

### A2 — Fixture corpus

**Files:**

```
spec/fixtures/dicom/
  valid_ct_single.dcm
  valid_ct_multi_frame.dcm
  valid_seg.dcm
  valid_rtstruct.dcm
  valid_sr.dcm
  missing_required_tag.dcm       -- no SOPInstanceUID
  truncated.dcm                   -- cut off mid-header
  not_dicom.txt
  valid_zip_42_files.zip
  zip_bomb.zip
  zip_path_traversal.zip
  zip_nested_3_deep.zip
```

**Depends on:** nothing

**Acceptance:**

- [ ] all files committed to the repo test fixture path
- [ ] `zip_bomb.zip` is a crafted small file (< 1 MB) whose metadata claims a total expanded size above the configured byte limit; do not commit a file that actually expands to gigabytes — CI nodes will thank you
- [ ] `zip_bomb.zip` is verified locally with `python3 -c "import zipfile; z=zipfile.ZipFile('zip_bomb.zip'); print(sum(i.file_size for i in z.infolist()))"` to confirm claimed expansion exceeds the limit before committing
- [ ] `zip_path_traversal.zip` contains an entry whose path starts with `../`
- [ ] each fixture is documented in a `spec/fixtures/dicom/README.md` with: expected parse outcome, reason it exists

---

### A3 — Raw storage contract

**Files:**

```
app/services/dicom/storage/
  raw_object_store.rb            -- or raw_object_store.py, etc.
  raw_object_store_spec.rb
```

**Depends on:** nothing

**Interface:**

```
RawObjectStore.put(bytes, content_hash:) -> { uri: String }
RawObjectStore.get(uri) -> bytes
RawObjectStore.exists?(uri) -> bool
RawObjectStore.delete(uri)   -- only for test cleanup and temp GC
```

**Acceptance:**

- [ ] `put` is idempotent: same `content_hash` returns same URI
- [ ] `put` followed by `get` returns identical bytes
- [ ] `exists?` returns false for an unknown URI
- [ ] storage backend is injected (not hardcoded); test uses a local temp-dir adapter
- [ ] unit tests pass with the temp-dir adapter
- [ ] no application code outside this module calls object storage directly

---

## M1 — Intake spine

### B1 — Upload API endpoint

**Files:**

```
app/controllers/dicom/ingestions_controller.rb
spec/requests/dicom/ingestions_create_spec.rb
```

**Depends on:** A1-e, A1-f, B2

**Implements:** `POST /dicom-ingestions`

**Acceptance:**

- [ ] accepts `multipart/form-data` with one or more files
- [ ] accepts `application/json` with a manifest reference
- [ ] optional `Idempotency-Key` header is read and stored
- [ ] same `actor_id + Idempotency-Key` + same body returns existing job (200, not 201)
- [ ] same `actor_id + Idempotency-Key` + different body returns `409 IdempotencyConflict`
- [ ] no key creates a new job (always)
- [ ] response shape matches `011` §9.1
- [ ] `EmptyUploadRequest` and `UploadTooLarge` return structured error, not 500

---

### B2 — Package persistence

**Files:**

```
app/services/dicom/upload/upload_service.rb
spec/services/dicom/upload/upload_service_spec.rb
```

**Depends on:** A3

**Interface:**

```
UploadService.accept(input) -> UploadPackage
```

**Acceptance:**

- [ ] writes raw bytes to object store before returning
- [ ] returns a package with `uri` pointing to stored bytes
- [ ] ZIP input: raw ZIP is stored before expansion
- [ ] if storage fails, raises `UploadPackageStoreFailed` (no partial state left)

---

### B3 — Scanner and ZIP safety

**Files:**

```
app/services/dicom/scanner/scan_service.rb
spec/services/dicom/scanner/scan_service_spec.rb
```

**Depends on:** A2, A3, B2

**Interface:**

```
ScanService.scan(upload_package) -> ScanManifest
  ScanManifest#items -> [{source_path, byte_size, item_bytes_or_uri}]
```

**Acceptance:**

- [ ] recursively lists DICOM candidates from folder or ZIP
- [ ] non-DICOM files are listed with `scan_status = rejected_non_dicom`
- [ ] ZIP expansion enforces max bytes, max entry count, max nesting depth
- [ ] `ZipBombDetected` raised and logged before full extraction when limits exceeded
- [ ] `UnsafeArchivePath` raised on path traversal entries (`../`)
- [ ] scanner with the `zip_bomb.zip` fixture raises before writing > safety limit bytes to disk
- [ ] scanner with `zip_path_traversal.zip` raises before extracting any file

---

### B4 — Job and item state engine

**Files:**

```
app/models/dicom/ingestion_job.rb
app/models/dicom/ingestion_item.rb
app/services/dicom/pipeline/state_machine.rb
spec/models/dicom/ingestion_job_spec.rb
spec/models/dicom/ingestion_item_spec.rb
```

**Depends on:** A1-e, A1-f

**Acceptance:**

- [ ] job transitions: `created -> receiving -> scanning -> processing -> finalizing -> completed`
- [ ] any active state can transition to `failed` or `cancelled`
- [ ] `completed -> reindexing -> completed` is valid
- [ ] invalid transitions raise, not silently no-op
- [ ] item: all seven axes listed in `010` §8.2 are stored columns, not computed
- [ ] item `terminal_outcome` is null until one of: accepted, quarantined, rejected, failed
- [ ] `last_retryable_stage` is set before `terminal_outcome = failed`

---

### B5 — Parser and validation

**Files:**

```
app/services/dicom/parser/dicom_parser.rb
app/services/dicom/parser/tag_validator.rb
spec/services/dicom/parser/dicom_parser_spec.rb
spec/services/dicom/parser/tag_validator_spec.rb
```

**Depends on:** A2

**Interface:**

```
DicomParser.parse_header(item) -> ParsedDicomHeader
  ParsedDicomHeader#required_tags -> Hash
  ParsedDicomHeader#raw_tags     -> Hash
  ParsedDicomHeader#private_tags -> Array[{creator, tag, vr, raw_value}]

TagValidator.validate(parsed_header) -> :valid | :invalid
  TagValidator#missing_tags -> Array[String]
```

**Acceptance:**

- [ ] parse mode is `header_only` by default; pixel data is not read into memory
- [ ] `valid_ct_single.dcm` fixture parses without error
- [ ] `missing_required_tag.dcm` fixture is parsed and tagged `invalid` with `MissingRequiredDicomTag`
- [ ] `truncated.dcm` raises `DicomParseFailed`; item bytes are preserved
- [ ] private tags are returned with raw bytes, not interpreted
- [ ] integration over `B2` through `B5` with the mixed-ZIP fixture proves every source entry reaches an explicit tracked state; malformed and non-DICOM siblings do not prevent the remaining candidates from being scanned and parsed

---

### B6 — Canonical persistence

**Files:**

```
app/services/dicom/repository/ingestion_repository.rb
spec/services/dicom/repository/ingestion_repository_spec.rb
```

**Depends on:** A1-a through A1-l, B5

**Interface:**

```
IngestionRepository.persist(item_context) -> PersistedDicomEntities
  PersistedDicomEntities#instance
  PersistedDicomEntities#observation
  PersistedDicomEntities#study
  PersistedDicomEntities#series
```

New upload vs retry distinction: `006` §5.6 (idempotency). Repository upsert path: look up existing observation by `(ingestion_item_id, instance_id)`; reuse if found; create if not. `UNIQUE(instance_id, ingestion_item_id)` in A1-d is the DB-level guard.

**Acceptance:**

- [ ] study, series, instance are upserted by natural UID; no duplicate rows created on second run
- [ ] a new physical upload item (new `ingestion_item_id`) for a previously unseen SOP creates a new observation
- [ ] a new physical upload item for a SOP that already exists creates a new observation and a duplicate finding; it does not reuse the prior observation
- [ ] retry of the same `ingestion_item_id` for an already-created observation reuses that observation; no second observation row is created
- [ ] the DB `UNIQUE(instance_id, ingestion_item_id)` constraint is the enforcement mechanism, not an application-layer fingerprint check
- [ ] first observation sets `is_canonical = true` and `current_canonical_observation_id` on the instance — in one transaction
- [ ] second observation for the same SOP UID (from a new physical upload) sets `is_canonical = false`; does not modify instance's `current_canonical_observation_id`
- [ ] if DB write fails after raw bytes are stored, item row is kept with `metadata_persistence_status = failed` and `last_retryable_stage` set

Post-commit invariant — the repository owns this, the DB does not:

- [ ] after a successful `persist` call, `current_canonical_observation_id` is never NULL
- [ ] after a successful `persist` call, exactly one linked observation has `is_canonical = true`
- [ ] if the transaction is rolled back or interrupted, no partially-written instance row remains with `current_canonical_observation_id = NULL` and `is_canonical` observations: the rollback leaves the DB in the pre-call state, not a half-state
- [ ] a dedicated post-commit assertion method (e.g. `assert_canonical_invariant!(instance_id)`) is callable in tests and raises if the invariant is violated — this is the lower-bound check that the DB partial unique index does not provide

---

### B7 — Terminal report

**Files:**

```
app/services/dicom/reporting/ingestion_reporter.rb
spec/services/dicom/reporting/ingestion_reporter_spec.rb
```

**Depends on:** B4, B6

**Interface:**

```
IngestionReporter.finalize(job_id) -> IngestionReport
```

**Acceptance:**

- [ ] every item in the job appears in the report with an explicit `terminal_outcome`
- [ ] counts in report match sum of item `terminal_outcome` values — no arithmetic shortcut
- [ ] if counts do not balance, `ReportInvariantFailed` is raised and observable (not swallowed)
- [ ] response shape for `GET /dicom-ingestions/{jobId}` matches `011` §9.2
- [ ] mixed batch fixture with one malformed item still produces terminal outcomes for all sibling items; one bad item cannot poison the rest of the batch

---

## M2 — Trust layer

### M2 design note — Series as the user-facing review unit

Design references:

- Three-tier processing model (file / SOP / Series): `006` §5.6
- `SeriesIngestionAttempt` domain object: `006` §5.7
- `SeriesConflictSummary` domain object: `006` §5.8
- Series conflict classification rules: `011` §11.3
- Apply endpoint contract and transaction semantics: `011` §11.4
- Module boundaries and new interfaces: `010` §4

Key constraints for tasks C1, C1b, C3, D1:

```text
C1  writes SOP-level findings.
C1b reads those findings and writes one SeriesConflictSummary per attempt.
D1  reads summaries; never aggregates findings at query time.
resolve endpoint supports two actions: `keep_existing` and `promote_uploaded`. Same action repeated returns 200. Different action on already-resolved summary returns 409. Full contract: `011` §11.4.
```

---

### C1 — Duplicate detection

**Files:**

```
app/services/dicom/duplicates/duplicate_detector.rb
spec/services/dicom/duplicates/duplicate_detector_spec.rb
```

**Depends on:** A1-j, B6

**Acceptance:**

- [ ] identity duplicate: second SOP UID creates finding with `duplicate_type = identity`, `basis = sop_instance_uid`
- [ ] content duplicate: same `whole_file_sha256` for different SOP UID creates finding with `duplicate_type = content`
- [ ] finding row is idempotent on retry (unique constraint, not application logic)
- [ ] canonical observation on the original instance is unchanged
- [ ] DB-level uniqueness constraints reject duplicate finding rows for every valid retry shape (see A1-j partial indexes)

---

### C1b — Series-level Conflict Classifier and Summary Projection

**Files:**

```
db/migrate/YYYYMMDD_create_dicom_series_conflict_summaries.rb
app/services/dicom/duplicates/series_conflict_classifier.rb
app/services/dicom/duplicates/series_conflict_summary_writer.rb
spec/services/dicom/duplicates/series_conflict_classifier_spec.rb
spec/services/dicom/duplicates/series_conflict_summary_writer_spec.rb
spec/requests/dicom/series_conflicts_spec.rb
```

**Depends on:** C1, B6, A1-l

**Design references:** `006` §5.7–5.8, `010` §4 (series_conflict module), `011` §11.1–11.5

**Migration — `dicom_series_conflict_summaries`:**

```sql
dicom_series_conflict_summaries
  id                          bigserial primary key
  series_ingestion_attempt_id bigint not null
    references dicom_series_ingestion_attempts(id) on delete restrict
  study_instance_uid          text   not null
  series_instance_uid         text   not null
  existing_series_id          bigint references dicom_series(id) on delete restrict
  classification              text   not null
    -- 'exact_duplicate' | 'partial_overlap' | 'content_conflict' | 'uid_conflict'
  existing_sop_count          integer not null default 0
  uploaded_sop_count          integer not null default 0
  overlap_sop_count           integer not null default 0
  new_sop_count               integer not null default 0
  missing_sop_count           integer not null default 0
  conflicting_sop_count       integer not null default 0
  status                      text   not null default 'open'
    -- 'open' | 'kept_existing' | 'promoted_uploaded' | 'auto_deduped'
  created_at                  timestamptz not null
  updated_at                  timestamptz not null

UNIQUE(series_ingestion_attempt_id)   -- one summary per Series upload attempt
INDEX(series_instance_uid)
INDEX(status)
```

`dicom_duplicate_findings` remains the source of SOP-level evidence. This table is the user-facing projection. It is written once per `series_ingestion_attempt` that touches an existing SeriesInstanceUID, and updated when the user resolves the conflict.

**Classification rules:** `011` §11.3 (priority order, threshold configurability, exact conditions)

**Interface:**

```
SeriesConflictClassifier.classify(series_ingestion_attempt_id) -> ConflictSummary
  ConflictSummary#classification
  ConflictSummary#sop_counts  -- {existing, uploaded, overlap, new, missing, conflicting}

SeriesConflictSummaryWriter.write(conflict_summary) -> PersistedSummary
```

The classifier receives a `series_ingestion_attempt_id` and internally aggregates:

```text
- all ingestion_items belonging to this series attempt
- all SOPInstanceUIDs and content hashes parsed from those items
- all existing instances in dicom_instances for the same SeriesInstanceUID
- all existing observations and their content hashes
```

**Acceptance:**

- [ ] C1 still writes SOP-level duplicate findings; C1b reads those findings and does not modify them
- [ ] C1b runs after C1 for every `series_ingestion_attempt` whose `series_instance_uid` already exists in `dicom_series`
- [ ] exactly one `dicom_series_conflict_summaries` row is created per `series_ingestion_attempt_id`; the `UNIQUE(series_ingestion_attempt_id)` constraint prevents a second row on retry
- [ ] a 300-file Series upload produces exactly one conflict summary row, not 300
- [ ] `exact_duplicate` classification: auto-sets `status = auto_deduped`; canonical unchanged; upload provenance row still recorded
- [ ] `partial_overlap`, `content_conflict`, `uid_conflict`: status remains `open` until user acts
- [ ] `conflicting_sop_count` equals the number of SOP-level `content_conflict` findings for this series attempt
- [ ] `uid_conflict` fires when overlap ratio is below the configured threshold (default 10%); threshold is configurable without a code deploy
- [ ] all four classification cases are covered by unit tests with fixture data covering single-file and multi-file Series uploads
- [ ] `GET /dicom/series-conflicts` returns summaries; `GET /dicom/series-conflicts/{id}` returns one summary with a link to the underlying SOP-level findings, scoped by `series_ingestion_attempt_id`
- [ ] `POST /dicom/series-conflicts/{id}/resolve` with `action: promote_uploaded` triggers the batched canonical transaction; all-or-nothing; on success, status becomes `promoted_uploaded`; on failure, status stays `open`
- [ ] `POST /dicom/series-conflicts/{id}/resolve` with `action: keep_existing` records the decision without modifying canonical pointers; status becomes `kept_existing`
- [ ] any action on an `auto_deduped` summary returns 409
- [ ] same action repeated on an already-resolved summary returns 200; different action returns 409

---

### C2 — Private tag storage

**Files:**

```
app/services/dicom/private_tags/private_tag_writer.rb
spec/services/dicom/private_tags/private_tag_writer_spec.rb
```

**Depends on:** A1-h, B5

**Acceptance:**

- [ ] private tags from `ParsedDicomHeader#private_tags` are written to `dicom_private_tags`
- [ ] known private creator tags carry interpreted keyword and value where mapping exists
- [ ] unknown creators store `raw_value` only, no `interpreted_keyword` or `interpreted_value`
- [ ] retry does not produce duplicate rows (unique index on `observation_id, private_creator, tag`)

---

### C3 — Reference edge extraction and resolution

**Files:**

```
app/services/dicom/references/reference_extractor.rb
app/services/dicom/references/reference_resolver.rb
spec/services/dicom/references/reference_extractor_spec.rb
spec/services/dicom/references/reference_resolver_spec.rb
```

**Depends on:** A1-i, B6

**Acceptance:**

- [ ] `dicom_reference_edges` rows are written from parsed header reference fields
- [ ] resolver attempts to fill `resolved_target_instance_id` if target SOP UID exists in `dicom_instances`
- [ ] unresolved references remain in the table with `resolved_target_instance_id = null`
- [ ] `GET /dicom/references/unresolved` returns items where `resolved_target_instance_id IS NULL`
- [ ] resolution is retried on index rebuild without creating duplicate edge rows

---

### C4 — Binding policy

**Files:**

```
app/services/dicom/binding/dicom_binding_policy.rb
spec/services/dicom/binding/dicom_binding_policy_spec.rb
```

**Depends on:** B6

**Interface:**

```
DicomBindingPolicy.bind(persisted_entities, context) -> BindingResult
  BindingResult#status  -- :bound | :failed | :not_applicable
  BindingResult#links   -- platform object references
```

**Acceptance:**

- [ ] binding failure sets item `binding_status = failed`; item `terminal_outcome` stays `accepted`
- [ ] a valid DICOM instance with `terminal_outcome = accepted` and `binding_status = failed` is queryable
- [ ] binding success sets `binding_status = bound`
- [ ] `BindingPolicyFailed` is logged with `job_id`, `item_id`, `error_code`

---

### C5 — Index jobs and projections

**Files:**

```
app/services/dicom/indexer/index_scheduler.rb
app/services/dicom/indexer/projection_builder.rb
spec/services/dicom/indexer/projection_builder_spec.rb
```

**Depends on:** A1-k, B6

**Interface:**

```
IndexScheduler.enqueue(scope) -> IndexJob
ProjectionBuilder.build(instance_id) -> ProjectionRow
```

**Acceptance:**

- [ ] `dicom_index_jobs` row is created with correct `scope_type` and `scope_id`
- [ ] `ProjectionBuilder.build` reads from canonical observation only
- [ ] projection row contains all seven hot-path fields from `011` §4.5
- [ ] staleness detection: if `projection_version`, `metadata_extractor_version`, or `projection_source_checksum` do not match current values, projection is marked stale
- [ ] rebuilding a projection twice produces identical rows
- [ ] query APIs (`GET /dicom/instances`, etc.) read from projections; no raw tag scan in hot path

---

### C6 — Retry and replay

**Files:**

```
app/services/dicom/pipeline/retry_orchestrator.rb
spec/services/dicom/pipeline/retry_orchestrator_spec.rb
spec/integration/dicom/retry_spec.rb
```

**Depends on:** A3, B4, B6

**Implements:** `POST /dicom-ingestions/{jobId}/retry`

Idempotency contract: `006` §5.9, `011` §6. Pipeline is idempotent at `(ingestion_item_id, dicom_instance_id)` level. User re-upload gets a new `ingestion_item_id` — that is not a retry.

**Acceptance:**

- [ ] only items with `last_retryable_stage` set are retried
- [ ] retry reuses stored `storage_uri`; does not re-upload from client
- [ ] retry of the same `ingestion_item_id` reuses existing observations — the DB `UNIQUE(instance_id, ingestion_item_id)` constraint is the guard, not a fingerprint check
- [ ] item that failed at `metadata_persistence_status` is retried from stored bytes, not re-scanned
- [ ] partial failure retry: if a multi-SOP item persisted observations for I1 and I2 before failing on I3, retry reuses the observations for I1 and I2 and only creates the missing observation for I3
- [ ] integration test: same job retried three times produces identical row counts in `dicom_instance_observations`

Test cases required in `spec/integration/dicom/retry_spec.rb`:

```text
Test 1 — same ingestion item retry
  Given ingestion_item_id = X and dicom_instance_id = I1
  When the first persistence attempt creates observation O1
  And the worker retries ingestion_item_id = X
  Then the repository reuses O1
  And the observation count for (X, I1) remains 1.

Test 2 — user re-uploads the same Series (new physical upload)
  Given user uploads Series SE1 as ingestion_item_id = X
  And later uploads the same Series SE1 again as ingestion_item_id = Y
  When content hashes are identical
  Then the system records Y as a separate physical upload event
  And may deduplicate raw bytes in object store
  And creates new observations keyed to Y
  And canonical selection remains unchanged.

Test 3 — same SeriesUID, conflicting content
  Given an existing Series SE1 with SOP I1 having hash H1
  When user uploads Series SE1 again with SOP I1 having hash H2 (H1 != H2)
  Then the system creates new observations for the new ingestion item
  And records a content duplicate finding
  And does not silently overwrite the canonical observation.

Test 4 — partial failure retry across a Series
  Given series_ingestion_attempt_id = A belonging to ingestion_job J
  And the attempt contains ingestion_items X1 (SOP I1), X2 (SOP I2), X3 (SOP I3)
  And the first run persists observations for I1 (via X1) and I2 (via X2) but fails before I3 (via X3)
  When the job is retried (POST /dicom-ingestions/{J}/retry)
  Then observations for (X1, I1) and (X2, I2) are reused without modification
  And only the missing observation for (X3, I3) is created
  And the final state has exactly one observation per (ingestion_item_id, instance_id).
```

---

### C7 — Observability

**Batch-1 prep artifact:** the observability owner drafts a provisional stage / event vocabulary before `B2` starts. `C7` is where that vocabulary becomes final and executable once the full flow exists.

**Files:**

```
docs/observability/dicom_ingestion_event_vocabulary.md
app/services/dicom/observability/metrics.rb
app/services/dicom/observability/structured_logger.rb
config/initializers/dicom_tracing.rb
spec/services/dicom/observability/phi_safe_logging_spec.rb
```

**Depends on:** B1 through C6, C1b

**Acceptance:**

- [ ] `docs/observability/dicom_ingestion_event_vocabulary.md` exists and the final implementation matches its stage / event naming
- [ ] all ten metrics from `010` §12 are emitted at the correct stage
- [ ] Series conflict metrics are added:
  - `dicom_series_conflicts_total{classification}` — emitted when a conflict summary is written
  - `dicom_series_conflicts_status_total{status}` — emitted when status changes; `status` is one of `kept_existing`, `promoted_uploaded`, `auto_deduped`
  - `dicom_series_conflict_resolve_total{action,result}` — emitted on each `/resolve` call; `action` is `keep_existing` or `promote_uploaded`; `result` is `success`, `failure`, or `conflict`
- [ ] log lines include `job_id`, `item_id`, `series_ingestion_attempt_id`, `stage`, `error_code` as structured keys where applicable
- [ ] log lines do not include raw PHI fields: patient name, patient ID, raw tag values
- [ ] PHI-safe logging spec verifies: a log entry for a failed item with `PatientName` in the DICOM header does not emit `PatientName` in any log key or value
- [ ] one trace per ingestion job; spans for receive, scan, raw store, parse, persist, bind, index, series_conflict_classify
- [ ] dashboard panels exist for ingest throughput, failures, duplicate pressure, Series conflict resolution, and indexing lag
- [ ] audit events emitted for: upload, quarantine decision, canonical observation switch, duplicate resolution, Series conflict resolve (including `series_ingestion_attempt_id`, action taken, actor, timestamp)

---

## M3 — Release hardening

### D1 — Query APIs

**Files:**

```
app/controllers/dicom/studies_controller.rb
app/controllers/dicom/series_controller.rb
app/controllers/dicom/instances_controller.rb
app/controllers/dicom/duplicates_controller.rb
app/controllers/dicom/references_controller.rb
app/controllers/dicom/series_conflicts_controller.rb
spec/requests/dicom/query_apis_spec.rb
spec/requests/dicom/series_conflicts_spec.rb
```

**Depends on:** C1, C1b, C3, C5

**Implements:**

```
GET  /dicom/studies
GET  /dicom/studies/{studyId}
GET  /dicom/series
GET  /dicom/series/{seriesId}
GET  /dicom/instances
GET  /dicom/instances/{instanceId}
GET  /dicom/duplicates
GET  /dicom/references/unresolved
GET  /dicom/series-conflicts
GET  /dicom/series-conflicts/{id}
POST /dicom/series-conflicts/{id}/resolve
```

Example response for `GET /dicom/series-conflicts/{id}`:

```json
{
  "id": "scf_456",
  "series_instance_uid": "1.2.840.10008.5.1.4.1.1.2",
  "classification": "content_conflict",
  "existing_sop_count": 300,
  "uploaded_sop_count": 300,
  "overlap_sop_count": 300,
  "new_sop_count": 0,
  "missing_sop_count": 0,
  "conflicting_sop_count": 3,
  "status": "open",
  "links": {
    "sop_findings": "/dicom/duplicates?series_ingestion_attempt_id=A",
    "resolve": "/dicom/series-conflicts/scf_456/resolve"
  }
}
```

**Acceptance:**

- [ ] all study/series/instance endpoints read from `dicom_core_projections`; no raw tag scan
- [ ] query by `modality`, `study_date`, `sop_instance_uid` uses indexed columns
- [ ] stale projections are labeled in the response (not silently served as fresh)
- [ ] `GET /dicom/duplicates` returns SOP-level findings with `resolution_status`
- [ ] `GET /dicom/references/unresolved` returns only rows with `resolved_target_instance_id IS NULL`
- [ ] `GET /dicom/series-conflicts` reads from `dicom_series_conflict_summaries`; no per-finding aggregation at query time
- [ ] `GET /dicom/series-conflicts/{id}` includes a link to the underlying SOP-level findings
- [ ] `POST /dicom/series-conflicts/{id}/resolve` accepts `{"action": "keep_existing"}` or `{"action": "promote_uploaded"}`; full contract in `011` §11.4
- [ ] `promote_uploaded`: executes batched canonical transaction; returns 200 with status `promoted_uploaded` on success
- [ ] `keep_existing`: records decision without touching canonical pointers; returns 200 with status `kept_existing`
- [ ] same action repeated on already-resolved summary: returns 200, no-op
- [ ] different action on already-resolved summary: returns 409
- [ ] any action on `auto_deduped` summary: returns 409

---

### D2 — Security pack

**Files:**

```
spec/security/dicom/
  zip_bomb_spec.rb
  path_traversal_spec.rb
  malformed_input_spec.rb
  oversize_upload_spec.rb
  temp_cleanup_spec.rb
  phi_safe_logging_spec.rb
```

**Depends on:** A2, B2, B3, C7

**Acceptance:**

- [ ] `zip_bomb.zip` fixture: scanner raises `ZipBombDetected` before extracting more than the byte limit; no temp files left behind
- [ ] `zip_path_traversal.zip` fixture: scanner raises `UnsafeArchivePath`; no files extracted
- [ ] `truncated.dcm` fixture: parser raises `DicomParseFailed`; item bytes are preserved; no unhandled exception
- [ ] upload exceeding size limit: `UploadTooLarge` returned before body is fully read
- [ ] after any failure path in B2 or B3: no temp files remain in the temp directory
- [ ] PHI-safe logging verified for all error paths that log DICOM metadata

---

### D3 — Replay and reindex validation

**Files:**

```
spec/integration/dicom/replay_spec.rb
spec/integration/dicom/reindex_spec.rb
```

**Depends on:** C5, C6

**Confidence test (from `010` §13):**

```
mixed ZIP
  + one object-store failure
  + one DB failure after raw-store success
  + one duplicate SOP UID
  + one unresolved reference
  -> final report tells the truth for every item
  -> retry from stored bytes succeeds without re-upload
  -> projection rebuild matches original projection
```

**Acceptance:**

- [ ] confidence test passes end-to-end
- [ ] projection rebuilt from scratch equals projection built incrementally (column-by-column comparison)
- [ ] reindex does not require re-uploading any file
- [ ] `study completeness` remains `unknown` when no trusted manifest is provided
- [ ] retry idempotency: all four test cases from C6 pass as integration tests against a real database, not just unit tests

---

### D4 — Rollout and runbooks

**Files:**

```
docs/runbooks/dicom_ingestion_stuck_batch.md
docs/runbooks/dicom_ingestion_replay.md
docs/runbooks/dicom_projection_rebuild.md
```

**Depends on:** D1, D2, D3

**Acceptance:**

- [ ] runbook for stuck batch: operator can locate a stuck batch and identify the blocking stage in under five minutes using only documented queries and metrics
- [ ] runbook for replay: operator can re-run a failed job from stored bytes without asking the user to re-upload
- [ ] runbook for projection rebuild: operator can trigger a full rebuild for a study or instance without downtime
- [ ] rollback procedure documented: no step requires deleting accepted DICOM records

---

## Technical dependency graph

The graph below shows the minimum dependency ordering required for implementation correctness. It is not the recommended release path; use `013` for sequencing and `014` for day-to-day execution order.

```text
A1-a -> A1-b -> A1-c -> A1-d -> A1-f -> A1-g -> A1-z
A1-e -> A1-f (parallel with A1-a..d)
A1-e + A1-f -> A1-l (series_ingestion_attempts + alter items)
A2    (parallel, no deps)
A3    (parallel, no deps)

A1-z + A1-l + A2 + A3
  -> B2
  -> B1 + B3 (parallel, both depend on B2)
  -> B1 and B3 merge independently
  -> B4 + B5 (parallel)
  -> B6
  -> B7

post-B6 branches:
  B6 -> C1 + C2 + C3 + C4 + C5 + C6 (parallel where contracts allow)
  C1 + A1-l -> C1b

release-close dependencies:
  C1 + C1b + C3 + C5 -> D1
  B1..C6 + C1b -> C7 -> D2
  C5 + C6 -> D3
  D1 + D2 + D3 -> D4
```

Any item whose listed dependencies are already merged can be started by a second engineer, even if it is not on the recommended release path in `013`.

---

## Open decisions (do not block M0–M1)

| # | Question | Needed by |
| - | -------- | --------- |
| 1 | Persist metadata-only byte prefix in v1 or not | C2 |
| 2 | Which private creators matter for first real users | C2 |
| 3 | Whether future derived-object enrichment needs more than typed staged jobs | post-v1 |
