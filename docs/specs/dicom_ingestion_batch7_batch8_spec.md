# DICOM Ingestion Batch 7 / Batch 8 Spec

Date: 2026-05-19
Status: DRAFT
Source design: `docs/designs/dicom_ingestion_batch7_batch8_product_wedge.md`

## Product Boundary

This platform is a medical-imaging data management intake layer.

It is explicitly not:

- PACS
- external hospital system integration
- generic DICOMweb conformance
- STOW-RS / QIDO-RS / WADO-RS implementation as product goals

The only allowed future exception is a narrow OHIF bridge if a concrete viewer or annotation workflow needs it.

## Strategic Split

```text
Batch 7 = Local/NAS Folder Ingest Wedge
Batch 8 = Product Surface + Review Workflow
Batch 9 = OHIF Bridge, only if needed
```

Batch 7 proves the platform can ingest and organize real imaging data.
Batch 8 makes that capability usable by people and downstream services.

---

# Batch 7 Spec: Local/NAS Folder Ingest Wedge

## Batch 7 Goal

Batch 7 must prove this scenario:

```text
Given a realistic folder/tree input,
when the ingest job runs,
then the platform preserves original DICOM bytes,
extracts configured standard and private tags,
places data through the selected object-storage or local/NAS backend,
tracks async parse state,
and produces an ingest report that explains accepted files, rejected files, duplicates, missing tags, fallback paths, and storage destinations.
```

The user-visible result is not an API surface yet. The result is trust:

> “I can hand the platform a messy imaging folder, and it will preserve, organize, explain, and not silently lose data.”

## Batch 7 Non-Goals

Batch 7 must not introduce:

- public product API freeze
- PACS compatibility vocabulary
- generic DICOMweb endpoints
- OHIF bridge
- full UI workflow for conflict resolution
- external hospital integration

## Batch 7 System Diagram

```text
Folder / ZIP / Manifest Input
        |
        v
Ingest Source Enumerator
        |
        |-- non-DICOM / unreadable file -----------> rejected file record
        |
        v
Raw Byte Preservation
        |
        v
Parse Task Created
        |
        v
Async Parse Worker Boundary
        |
        v
Parser Adapter
        |
        v
Tag Extraction + Tag Schema Resolution
        |
        v
Canonical Study / Series / Instance Persistence
        |
        +--> Duplicate Detection
        |
        +--> Storage Backend Router
                 |
                 |-- Object Storage Backend
                 |
                 `-- Local/NAS Path Generator + Backend
        |
        v
Ingest Report
```

---

## 7A. Parser Seam + Configurable Tag Schema

### Goal

Separate DICOM parsing from platform semantics.

The parser should produce structured facts. The platform decides which facts matter, how they map to storage, and what to do when they are missing. Private tag interpretation must be external-configuration driven, not hardcoded into the parser or storage path generator.

### Required Behavior

The platform must support an external configurable tag schema containing:

- standard DICOM tags
- private tags keyed by private creator plus tag identity
- storage-relevant tags
- required vs optional flags
- fallback labels for missing values
- normalization rules for path-safe values
- optional extractor names for vendor-specific payload interpretation

The parser may expose raw private tags. The schema layer maps those raw tags into platform fields such as `MeasUID`.

### Proposed Schema Shape

```yaml
version: 1
schema_name: default_mr_intake
modality: MR
fields:
  patient_id:
    tag: "0010,0020"
    name: PatientID
    required: false
    storage_path: false
    fallback: UNKNOWN_PATIENT

  study_uid:
    tag: "0020,000D"
    name: StudyInstanceUID
    required: true
    storage_path: true
    fallback: ERROR

  series_uid:
    tag: "0020,000E"
    name: SeriesInstanceUID
    required: true
    storage_path: true
    fallback: ERROR

  sop_instance_uid:
    tag: "0008,0018"
    name: SOPInstanceUID
    required: true
    storage_path: true
    fallback: ERROR

  manufacturer:
    tag: "0008,0070"
    name: Manufacturer
    required: false
    storage_path: true
    fallback: UNKNOWN_VENDOR
    normalize: path_segment

  device_name:
    tag: "0008,1010"
    name: StationName
    required: false
    storage_path: true
    fallback: UNKNOWN_DEVICE
    normalize: path_segment

  meas_uid:
    private_tag:
      creator: "SIEMENS CSA HEADER"
      tag: "0029,1020"
      extractor: siemens_meas_uid
    name: MeasUID
    required: false
    storage_path: true
    fallback: NO_MEAS_UID
    normalize: path_segment
```

### Acceptance Criteria

- A parser adapter can extract both standard and configured private tags.
- Missing required identity tags produce a rejected DICOM item, not a silent partial record.
- Missing optional storage tags use deterministic fallback labels.
- Extracted tag values are stored in a normalized platform-facing structure.
- Tests cover standard tag extraction, private tag extraction, missing required tags, missing optional tags, and invalid private tag payloads.

### Failure Modes

| Failure | Required Handling |
|---|---|
| DICOM unreadable | reject file, include reason in ingest report |
| required UID missing | reject DICOM item, preserve raw bytes if already stored |
| private tag missing | use configured fallback, record warning |
| private tag malformed | use fallback, record parser warning |
| parser throws unexpected error | mark parse task failed with exception class and context |

---

## 7B. Dual Storage Backend Abstraction

### Goal

Make object storage and local/NAS storage two backends under one platform storage contract.

### Required Behavior

Storage must answer:

```text
Given raw DICOM bytes + resolved metadata + ingest context,
where should the file be stored,
how is the storage location recorded,
and how can the system later retrieve or audit it?
```

### Proposed Interface

```python
class DicomStorageBackend:
    def store_original(self, *, bytes, metadata, ingest_context) -> StoredObject:
        ...

@dataclass
class StoredObject:
    backend: Literal["object", "local_nas"]
    uri: str  # e.g. s3://... or local-nas://storage-root-id/path/to/file.dcm
    path: str | None  # internal absolute path allowed only inside storage backend/admin context
    checksum: str
    size_bytes: int
    storage_metadata: dict
```

### Acceptance Criteria

- Existing object storage behavior remains valid.
- Local/NAS backend can write to configured root safely.
- Storage result is persisted with backend, opaque URI, checksum, and size.
- For local/NAS, platform-facing references use `local-nas://...`; absolute filesystem paths stay internal/admin-only.
- Storage write failure fails visibly and is present in ingest report.
- Tests cover object backend, local/NAS backend, path collision, permission failure, and checksum mismatch.

### Security Requirements

- Local/NAS paths must be generated by the platform, not accepted raw from user input.
- Path segments must be normalized and must reject `..`, absolute paths, shell metacharacter abuse, and empty identity segments when required.
- Backend root must be configured, not passed ad hoc by request.

---

## 7C. Deterministic Local/NAS Path Generator

### Goal

Create a deterministic, human-browsable path layout from resolved DICOM metadata.

### Default Path Rule

```text
DICOM_{MODALITY}/{VENDOR}/{DEVICE}/{StudyUID}/{MeasUID}/{SeriesUID}/{SOPInstanceUID}.dcm
```

### Fallback Example

```text
DICOM_MR/UNKNOWN_VENDOR/UNKNOWN_DEVICE/1.2.840.113619.../NO_MEAS_UID/1.2.840.../1.2.840....dcm
```

### Required Behavior

- Required UID fields missing means reject, not fallback.
- Optional descriptive fields missing means fallback.
- Every fallback must be recorded in the ingest report.
- Path generation must be deterministic for the same metadata.
- Collision handling must not overwrite existing files silently.

### Collision Policy

If generated path already exists:

1. Compare checksum.
2. If checksum matches, treat as same original bytes and record duplicate storage reference.
3. If checksum differs, write to conflict suffix path:

```text
{SOPInstanceUID}__conflict_{short_checksum}.dcm
```

and record a storage conflict warning.

### Acceptance Criteria

- Same input metadata produces same path.
- Optional missing tags produce documented fallback segments.
- Required missing tags reject the DICOM item.
- Same checksum collision is safe and idempotent.
- Different checksum collision is visible and non-destructive.

---

## 7D. Folder/Tree Ingest Model

### Goal

Treat a folder/tree as a first-class ingest source, not a side effect of upload implementation.

### Input Types

Current implementation already has ZIP scanning and ZIP safety. Batch 7 should not rebuild ZIP. It should make all source types flow through a common source abstraction:

```text
IngestSource
  - ZipArchiveSource(existing scanner/ZIP safety path)
  - LocalFolderSource(root_path)
  - ManifestSource(entries[])
```

The new Batch 7 work is mainly `LocalFolderSource` and `ManifestSource`, plus making ZIP, folder, and manifest share the same downstream item contract. The service should consume an abstract enumerator, not directly depend on local filesystem walking or ZIP internals.

### Proposed Item Shape

```python
@dataclass
class IngestSourceItem:
    source_kind: Literal["local_folder", "zip", "manifest"]
    original_relative_path: str
    size_bytes: int
    content_type_guess: str | None
    open_bytes: Callable[[], bytes]
```

### Required Behavior

- Preserve original relative path in ingest metadata.
- Skip directories.
- Detect non-DICOM files and include them in report.
- Continue processing after bad file unless job-level fatal error occurs.
- Enforce maximum file size and maximum item count configuration.

### Acceptance Criteria

- Nested folder input works.
- Manifest input works and preserves source-relative paths.
- Existing ZIP scanner output can be adapted into the same `IngestSourceItem` contract.
- Mixed DICOM and non-DICOM input works.
- Empty folder produces completed job with zero accepted and clear report.
- Unreadable file is reported and does not kill the entire job.
- ZIP, local folder, and manifest share the same downstream ingest pipeline.

---

## 7E. Async Parse Worker Boundary

### Goal

Make async parsing observable and replaceable. Celery may be the adapter, but the domain model must not be Celery-shaped.

### Parse Task States

```text
PENDING
  -> IN_PROGRESS
  -> COMPLETED
  -> FAILED
  -> CANCELLED
  -> RETRY_WAITING
```

### State Machine

```text
             +--------------+
             |   PENDING    |
             +------+-------+
                    |
                    v
             +--------------+
             | IN_PROGRESS  |
             +---+------+---+
                 |      |
         success |      | recoverable error
                 v      v
        +-------------+  +---------------+
        | COMPLETED   |  | RETRY_WAITING |
        +-------------+  +-------+-------+
                                |
                                v
                           IN_PROGRESS

IN_PROGRESS -> FAILED     on non-recoverable error or retry exhaustion
PENDING     -> CANCELLED  before worker starts
```

### Required Behavior

- Every parse task has visible state.
- Worker retry must be idempotent: rerunning a task cannot duplicate canonical records or overwrite files silently.
- Task failure stores exception class, message, item path, ingest id, and attempt count.
- Job-level status derives from item-level states.

### Acceptance Criteria

- State transitions are enforced.
- Retry does not duplicate records.
- Failed item appears in ingest report with reason.
- Stuck `IN_PROGRESS` tasks can be detected by timeout.
- Tests cover success, parser failure, storage failure, retry success, retry exhaustion, and duplicate worker execution.

---

## 7F. Ingest Report

### Goal

Make Batch 7 explain itself without requiring UI or database spelunking.

### Report Shape

```json
{
  "ingest_id": "...",
  "source": {
    "type": "local_folder",
    "root_label": "example_batch"
  },
  "summary": {
    "total_items": 1200,
    "dicom_candidates": 1180,
    "accepted_instances": 1160,
    "rejected_items": 20,
    "duplicates": 12,
    "storage_conflicts": 1,
    "warnings": 45
  },
  "storage": {
    "backend": "local_nas",
    "root": "/data/dicom",
    "generated_paths": 1160
  },
  "fallbacks": [
    {
      "field": "manufacturer",
      "fallback": "UNKNOWN_VENDOR",
      "count": 32
    }
  ],
  "rejections": [
    {
      "relative_path": "notes/readme.txt",
      "reason": "NON_DICOM"
    }
  ],
  "failed_tasks": [],
  "duplicates_by_series": []
}
```

### Acceptance Criteria

- Report can be generated after completed, partially failed, or failed jobs.
- Report includes fallback usage and rejected files.
- Report includes storage destination counts.
- Report is stable enough for Batch 8 API response reuse.

---

## 7G. Binding Vocabulary Cleanup

### Goal

Remove ambiguous `BindingTargetType.STUDY` before it contaminates API semantics.

### Required Behavior

- Do not use `STUDY` if it can be confused with DICOM Study.
- If platform business study is needed, name it explicitly:
  - `RESEARCH_STUDY`
  - `PROJECT_STUDY`
  - or another domain-specific term
- DICOM identity should remain `DICOM_STUDY` or explicit `StudyInstanceUID` concept.

### Acceptance Criteria

- Existing ambiguous enum removed or renamed.
- Tests and docs clarify DICOM Study vs platform study/project concept.
- Batch 8 APIs do not inherit ambiguous naming.

---

# Batch 8 Spec: Product Surface + Review Workflow

## Batch 8 Goal

Batch 8 exposes the proven Batch 7 capability as a usable product surface.

The core scenario:

```text
A user or downstream service can start an ingest job,
monitor progress,
query Study / Series / Instance results,
understand duplicate and conflict state at Series level,
resolve conflicts safely,
and recover operationally without reading internal service code.
```

## Batch 8 Non-Goals

Batch 8 must not introduce:

- PACS compatibility
- generic DICOMweb promise
- external hospital integration
- OHIF bridge unless separately approved
- UI-heavy viewer workflow

---

## 8A. Upload / Ingest Job APIs

### Goal

Expose a stable way to create and observe ingest work.

### Proposed Endpoints

```http
POST /api/ingest/jobs
GET  /api/ingest/jobs/{job_id}
GET  /api/ingest/jobs/{job_id}/report
POST /api/ingest/jobs/{job_id}/cancel
POST /api/ingest/jobs/{job_id}/retry_failed
```

### POST /api/ingest/jobs Request

```json
{
  "source_type": "local_folder",
  "source": {
    "root_path": "/incoming/batch_001"
  },
  "storage_backend": "local_nas",
  "tag_schema": "default_mr_intake",
  "dry_run": false
}
```

### Response

```json
{
  "job_id": "...",
  "status": "PENDING",
  "created_at": "...",
  "links": {
    "self": "/api/ingest/jobs/...",
    "report": "/api/ingest/jobs/.../report"
  }
}
```

### Acceptance Criteria

- Job creation validates source type, storage backend, and tag schema.
- Job status exposes item counts and failure counts.
- Report endpoint reuses Batch 7 ingest report.
- Cancel only works before or during allowed states.
- Retry failed only retries failed/retryable items.

---

## 8B. Study / Series / Instance Query APIs

### Goal

Allow users and downstream services to inspect ingested data without exposing internal tables.

### Proposed Endpoints

```http
GET /api/dicom/studies
GET /api/dicom/studies/{study_uid}
GET /api/dicom/studies/{study_uid}/series
GET /api/dicom/series/{series_uid}
GET /api/dicom/series/{series_uid}/instances
GET /api/dicom/instances/{sop_instance_uid}
```

### Query Requirements

- filter by ingest job
- filter by modality
- filter by storage backend
- filter by duplicate/conflict state
- paginate series and instances

### Acceptance Criteria

- Query response uses DICOM identity clearly.
- Pagination is required for series and instances.
- Storage references are visible but do not expose unsafe local absolute paths unless authorized.
- Missing records return typed not-found response.

---

## 8C. Series-Level Duplicate Summary

### Goal

Show duplicate/conflict information at the level users can reason about: Series.

SOP-level evidence remains internal detail. Series-level summary is the product abstraction.

### Proposed Summary Shape

```json
{
  "series_uid": "...",
  "study_uid": "...",
  "duplicate_state": "HAS_DUPLICATES",
  "instance_count": 320,
  "duplicate_instance_count": 12,
  "conflict_count": 2,
  "evidence": {
    "same_sop_same_checksum": 10,
    "same_sop_different_checksum": 2
  },
  "recommended_action": "REVIEW_CONFLICTS"
}
```

### Acceptance Criteria

- Duplicate summaries group by Series.
- SOP-level evidence can be inspected when needed.
- Conflict state is stable and queryable.
- Tests cover same checksum duplicates, different checksum conflicts, and mixed clean/conflict Series.

---

## 8D. Conflict Resolution Workflow

### Goal

Allow safe, auditable resolution of Series-level conflicts.

Here “actor/permission model” means: who is allowed to resolve conflicts, how the system records that person/service, and what guardrails prevent anonymous or accidental data-changing actions. For Batch 8, this does not need to become a full RBAC system. The minimum rule is:

> Whoever created/uploaded the ingest job owns conflict resolution for conflicts produced by that job.

That means the conflict resolver must be the job owner/uploader, or an explicitly internal admin/operator acting with a reason.

### Proposed Actions

```text
KEEP_EXISTING
ACCEPT_NEW
KEEP_BOTH
MARK_REJECTED
DEFER
```

### Proposed Endpoint

```http
POST /api/dicom/series/{series_uid}/conflicts/resolve
```

```json
{
  "action": "KEEP_BOTH",
  "reason": "same SOP UID but different source bytes; preserve both for review",
  "actor_id": "..."
}
```

### Acceptance Criteria

- Every resolution action creates audit log.
- Only the ingest job owner/uploader can resolve normal conflicts for that job.
- Internal admin/operator override requires explicit actor, actor type, and reason.
- Resolution is idempotent for same action and conflict version.
- Stale conflict version is rejected.
- User can inspect previous resolution reason.
- Resolution updates projections or marks them for rebuild.

---

## 8E. Platform Binding Response Envelope

### Goal

Expose ingestion results in a form that downstream dataset / annotation / review workflows can consume.

### Proposed Envelope

```json
{
  "resource_type": "dicom_series",
  "resource_id": "series_uid",
  "identity": {
    "study_uid": "...",
    "series_uid": "..."
  },
  "storage": {
    "backend": "local_nas",
    "uri": "local-nas://..."
  },
  "status": {
    "ingest_status": "COMPLETED",
    "duplicate_state": "CLEAN"
  },
  "links": {
    "instances": "/api/dicom/series/.../instances",
    "ingest_report": "/api/ingest/jobs/.../report"
  }
}
```

### Acceptance Criteria

- Envelope does not use ambiguous `STUDY` binding vocabulary.
- Dataset/review workflows can reference Study/Series/Instance without direct table coupling.
- Envelope can later support a narrow OHIF bridge without making DICOMweb a product goal.

---

## 8F. Operator Runbooks and Recovery Commands

### Goal

Make common operational failures recoverable without source-code spelunking.

The API-vs-CLI question means: should recovery actions be exposed as HTTP admin endpoints, CLI/admin commands, or both? For this project stage, the safer default is CLI/admin commands first. They are easier to permission, easier to keep internal, and avoid making operational controls part of the public product API too early.

### Required Runbooks

- stuck ingest job
- stuck parse task
- retry failed items
- replay ingest report
- rebuild projection
- inspect storage mismatch
- inspect duplicate/conflict summary

### Recommended Admin Commands

```text
dicom-ingest rebuild-report --job-id <job_id> --actor <actor_id> --reason <reason>
dicom-ingest rebuild-projection --job-id <job_id> --actor <actor_id> --reason <reason>
dicom-ingest retry-failed --job-id <job_id> --actor <actor_id> --reason <reason>
dicom-ingest mark-task-failed --task-id <task_id> --actor <actor_id> --reason <reason>
```

HTTP admin endpoints can be added later if there is a real UI/admin-console need.

### Acceptance Criteria

- Each runbook names symptoms, diagnosis query, action, and verification.
- Recovery actions are logged.
- Dangerous actions require explicit actor/reason.

---

# Cross-Batch Acceptance

## End-to-End Demo After Batch 7

```text
1. Prepare folder with:
   - valid DICOM files
   - nested directories
   - non-DICOM files
   - DICOM missing optional vendor/device tags
   - DICOM missing required UID tags
   - duplicate SOP with same checksum
   - duplicate SOP with different checksum

2. Run ingest using local/NAS backend.

3. Verify:
   - original bytes preserved
   - valid files persisted canonically
   - bad files rejected with reasons
   - optional missing tags use fallback paths
   - required missing tags are rejected
   - duplicates are detected
   - async states are visible
   - ingest report explains the whole run
```

## End-to-End Demo After Batch 8

```text
1. Create ingest job through API.
2. Poll job status.
3. Fetch ingest report.
4. Query studies and series.
5. Inspect Series-level duplicate summary.
6. Resolve a conflict with reason.
7. Verify audit log and updated projection.
8. Run recovery path for a failed parse item.
```

---

# Implementation Order

## Batch 7 Suggested Order

1. Tag schema + parser adapter contract
2. Local/NAS path generator
3. Storage backend abstraction
4. Folder/tree source enumerator
5. Async parse task state machine
6. Ingest report generator
7. Binding vocabulary cleanup
8. Batch 7 end-to-end fixture and test

## Batch 8 Suggested Order

1. Ingest job API and report API
2. Query APIs for Study / Series / Instance
3. Series duplicate summary API
4. Conflict resolution workflow
5. Binding response envelope
6. Operator runbooks and recovery commands
7. Batch 8 end-to-end API workflow test

---

# Decisions Resolved In CEO Discussion

1. ZIP is already supported by the current scanner/ZIP safety path. Batch 7 focuses on folder + manifest as missing first-class source abstractions, while adapting existing ZIP output into the same downstream contract.
2. Private tag interpretation is external-configuration driven. Parser preserves raw private tags; schema configuration maps private creator/tag identities into platform fields such as `MeasUID`.
3. Local/NAS platform-facing storage references use `local-nas://...`. Absolute filesystem paths remain backend/admin-internal.
4. Batch 8 recovery should default to CLI/admin commands first, not public HTTP admin APIs, unless a concrete admin UI requires endpoints.
5. Conflict resolution uses the minimum ownership rule: whoever created/uploaded the ingest job resolves conflicts for that job. Keep `actor_id`, actor type, permission check, reason, timestamp, and audit record. Admin/operator override is allowed only with an explicit reason.

# Open Decisions Before Implementation

1. Exact manifest JSON shape for folder/tree input.
2. Exact external tag schema file format and loading mechanism.
3. Which first real private tag config should be shipped as the reference example, likely Siemens MR `MeasUID`.
4. Exact local/NAS root configuration and URI format, including storage-root identifier naming.
5. Exact representation of job owner/uploader identity in the current auth/user model.

