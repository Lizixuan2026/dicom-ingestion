# Phase 2.5 Engineering Checklist: Curated Upload Manifest Adapter

**日期**: 2026-05-20  
**输入设计**: `phase2_5_curated_manifest_adapter_design.md`  
**目标**: 给实现 AI 的工程执行清单与 review gate  
**模式**: reviewer-authored implementation checklist, no code changes in this document

---

## 0. One-line scope

实现一个 curated `data_manifest.json` source adapter，把用户整理好的 `data` 与 `annotation` 关系转成 existing pipeline 可消费的 `IngestSourceItem + AnnotationRef`。

不要实现 Dataset、annotation parser、API/UI、Redis/RMQ。

---

## 1. Required implementation tasks

### T1. Add source-layer `AnnotationRef`

**Files likely touched**:

- `backend/src/dicom_ingestion/sources/base.py`

**Shape**:

```python
@dataclass(frozen=True)
class AnnotationRef:
    source_relative_path: str
    task_type: str | None = None
    label_name: str | None = None
    required: bool = False
    status: str = "referenced"
    metadata: dict[str, Any] = field(default_factory=dict)
```

**Rules**:

- This belongs in source layer, not domain models.
- `task_type` is a free-form tag.
- Do not create `Dataset`, `DatasetSample`, `AnnotationObject`, or persistence models.
- Do not include internal absolute paths in report-facing fields.

**Review gate**:

- Existing sources can omit annotations without behavior changes.
- `AnnotationRef` has no parser/semantic methods.

---

### T2. Extend `IngestSourceItem`

**Files likely touched**:

- `backend/src/dicom_ingestion/sources/base.py`
- Source implementations if constructor call sites need explicit compatibility fixes.

**Required change**:

```python
annotations: list[AnnotationRef] = field(default_factory=list)
```

**Rules**:

- Default must be empty list.
- Existing `LocalFolderSource`, `ZipArchiveSourceAdapter`, `FileListManifestSource` should not need semantic changes.

**Review gate**:

- Existing source tests pass unchanged except imports if needed.
- No source starts emitting annotation files as data items.

---

### T3. Add `SourceKind.CURATED_MANIFEST`

**Files likely touched**:

- `backend/src/dicom_ingestion/sources/base.py`

**Required value**:

```python
CURATED_MANIFEST = "curated_manifest"
```

**Rules**:

- Do not reuse `file_list_manifest`.
- Do not call it `dataset_manifest`.

**Review gate**:

- Report source type for curated manifest is `curated_manifest`.

---

### T4. Implement `CuratedUploadManifestSource`

**Files likely touched**:

- `backend/src/dicom_ingestion/sources/curated_manifest.py`
- `backend/src/dicom_ingestion/sources/__init__.py`

**Constructor**:

```python
class CuratedUploadManifestSource:
    def __init__(
        self,
        manifest_path: str | Path,
        *,
        allowed_roots: Iterable[str | Path],
        source_label: str = "curated_manifest",
    ) -> None:
        ...
```

**Required behavior**:

1. Read JSON from `manifest_path`.
2. Accept minimal shape:

   ```json
   { "data": "/path/to/data", "annotation": [{ "path": "/path/to/label1", "task_type": "segmentation" }] }
   ```

3. Accept versioned shape:

   ```json
   { "version": 1, "type": "curated_upload_manifest", "data": { "path": "data" }, "annotation": [...] }
   ```

4. Resolve relative paths against manifest file parent.
5. Resolve absolute paths directly.
6. Validate data and annotation paths under allowed roots after `resolve()`.
7. Enumerate data payload files only.
8. Attach annotation refs by deterministic sample id matching.
9. Return `SourceEnumerationResult`.

**Forbidden behavior**:

- Do not emit annotation files/folders as standalone data items.
- Do not read annotation contents.
- Do not parse annotation format.
- Do not infer task behavior from `task_type`.

**Review gate**:

- Implementation has explicit helper methods for path resolution and sample matching.
- No catch-all swallowing of manifest validation errors without report visibility.

---

## 2. Matching policy to implement

### File data sample

```text
data/sample_001.dcm → sample_id = sample_001
label1/sample_001.json → annotation ref match
label2/sample_001/     → annotation ref match
```

### Folder data sample

```text
data/sample_001/image_1.dcm → sample_id = sample_001
label1/sample_001/          → annotation ref match
```

### Mixed file/folder data root

Allowed, but duplicate sample ids must be visible.

Example duplicate:

```text
data/sample_001.dcm
data/sample_001/image_1.dcm
```

This should not silently merge.

Recommended behavior:

- mark duplicate affected data entries as rejected source items, or
- emit deterministic source error with `DuplicateCuratedSampleId` and skip ambiguous entries.

Pick one behavior and test it.

---

## 3. Error policy to implement

### Fatal source errors

These may raise and become job-level failed result via scheduler's existing fatal path:

| Condition | Error code |
|---|---|
| manifest unreadable | `CuratedManifestUnreadable` |
| invalid JSON | `CuratedManifestInvalidJson` |
| missing data path | `CuratedManifestMissingDataPath` |
| data path outside allowed roots | `CuratedManifestDataPathOutsideAllowedRoot` |
| data path missing/not directory | `CuratedManifestDataPathInvalid` |

### Non-fatal source errors

These should appear in `SourceEnumerationResult.errors`:

| Condition | Error code | Behavior |
|---|---|---|
| optional annotation path missing | `AnnotationPathMissing` | do not attach refs |
| annotation path outside root | `AnnotationPathOutsideAllowedRoot` | do not attach refs |
| annotation path not file/dir | `AnnotationPathInvalid` | do not attach refs |
| duplicate sample id | `DuplicateCuratedSampleId` | deterministic skip/reject |

### Required annotation missing

This is the one subtle case. The implementation must choose one of two explicit designs:

**Preferred**: represent as item-level rejection metadata before parse/storage.

```text
data/sample_001.dcm has required label1 missing
→ item terminal_outcome = rejected
→ error_code = RequiredAnnotationMissing
→ DICOM parser/storage not run for that item
```

If current scheduler cannot cleanly reject before parse, then Phase 2.5 must add a small source-item precheck hook or encode a clear source error and test that the report exposes it. Do not silently accept the item.

**Review gate**:

- Required missing annotation is visible in report rejections.
- Optional missing annotation does not reject item.

---

## 4. Scheduler and report integration

### Scheduler

**Files likely touched**:

- `backend/src/dicom_ingestion/pipeline/scheduler.py`

**Required behavior**:

- Copy `source_item.annotations` into item metadata for report use.
- If implementation supports pre-parse item rejection for missing required annotation, do it before DICOM read/parse/storage.
- Existing LocalFolder/Zip/FileList behavior must remain unchanged.

### Report

**Files likely touched**:

- `backend/src/dicom_ingestion/pipeline/report.py`

**Required report additions**:

```json
{
  "annotation_summary": {
    "referenced_items": 0,
    "items_with_annotations": 0,
    "items_missing_required_annotations": 0,
    "task_type_counts": {}
  }
}
```

For non-curated sources, `annotation_summary` should still exist with zero counts, or be absent by stable documented choice. Pick one and test it.

**Recommended**: include zero-count `annotation_summary` for all Batch 7 reports to keep shape stable.

Per item:

```json
"annotation_refs": [
  {
    "source_relative_path": "label1/sample_001.json",
    "task_type": "segmentation",
    "label_name": "label1",
    "status": "referenced"
  }
]
```

**Security rules**:

- No absolute paths.
- No annotation contents.
- No full parsed DICOM tags.
- Preserve existing `dicom_identity` PHI-safe behavior.

---

## 5. Required tests

### Source tests

Add to `backend/tests/sources/test_ingest_sources.py` or a new focused file:

- `test_curated_manifest_file_samples_attach_annotation_refs`
- `test_curated_manifest_folder_samples_attach_annotation_refs`
- `test_curated_manifest_relative_paths_resolve_from_manifest_dir`
- `test_curated_manifest_rejects_data_path_outside_allowed_roots`
- `test_curated_manifest_reports_annotation_path_outside_allowed_root`
- `test_curated_manifest_missing_optional_annotation_is_warning_not_fatal`
- `test_curated_manifest_duplicate_sample_id_is_visible`
- `test_curated_manifest_preserves_task_type_as_tag`

### Pipeline/report tests

Add to `backend/tests/pipeline/test_batch7_pipeline.py` or new focused file:

- `test_curated_manifest_valid_dicom_with_annotation_is_accepted`
- `test_curated_manifest_annotation_files_are_not_parsed_as_dicom_items`
- `test_curated_manifest_report_includes_annotation_refs`
- `test_curated_manifest_report_includes_annotation_summary`
- `test_curated_manifest_report_excludes_absolute_annotation_paths`
- `test_curated_manifest_required_annotation_missing_rejects_item`
- `test_curated_manifest_optional_annotation_missing_does_not_reject_item`

### Regression tests

Existing tests must still pass:

```bash
cd backend
./venv/bin/python -m pytest tests/sources/test_ingest_sources.py tests/pipeline/test_batch7_pipeline.py -q
./venv/bin/python -m pytest -q
```

---

## 6. Anti-scope-creep checklist

Reject the implementation if it adds any of these:

- `Dataset` model.
- `DatasetSample` persistence.
- `AnnotationObject` persistence.
- Annotation file parser.
- segmentation/localization/detection logic.
- REST API / FastAPI / HTTP endpoint.
- UI.
- Redis/RMQ/Celery.
- PACS compatibility.
- hospital integration.
- generic DICOMweb.
- OHIF workflow beyond a future explicitly approved minimal bridge.

Also reject if:

- annotation files are treated as DICOM parse candidates.
- report exposes annotation absolute paths.
- report exposes annotation contents.
- `task_type` becomes an enum that rejects unknown values.
- curated manifest is named `DatasetManifestSource`.

---

## 7. Review checklist after implementation

Use this to review the AI implementation:

```text
[ ] SourceKind.CURATED_MANIFEST exists and is distinct from FILE_LIST_MANIFEST.
[ ] AnnotationRef lives in source layer only.
[ ] IngestSourceItem annotations default to empty list.
[ ] CuratedUploadManifestSource validates manifest path, data path, annotation paths.
[ ] Relative paths resolve relative to manifest parent.
[ ] All resolved paths are checked against allowed roots.
[ ] Data files are emitted as source items.
[ ] Annotation payloads are refs only, not source items.
[ ] sample_id matching is deterministic and tested.
[ ] required annotation missing is visible and rejects affected item.
[ ] optional annotation missing is visible but not fatal.
[ ] task_type is preserved as tag, not semantic behavior.
[ ] Report has annotation refs and annotation_summary.
[ ] Report contains no internal absolute paths.
[ ] Report contains no annotation contents.
[ ] Existing LocalFolder/Zip/FileList tests still pass.
[ ] Full backend tests pass.
[ ] No REST/API/UI/Redis/RMQ/Dataset work slipped in.
```

---

## 8. Suggested implementation prompt

```text
Please implement Phase 2.5 Curated Upload Manifest Adapter.

Use these files as source of truth:
- docs/superpowers/plans/phase_designs/phase2_5_curated_manifest_adapter_design.md
- docs/superpowers/plans/phase_designs/phase2_5_curated_manifest_eng_checklist.md

Implement only the adapter/ref/report work:
1. Add AnnotationRef in source layer.
2. Extend IngestSourceItem with annotations defaulting to empty list.
3. Add SourceKind.CURATED_MANIFEST.
4. Add CuratedUploadManifestSource for user data_manifest.json.
5. Validate data and annotation paths under allowed roots.
6. Enumerate data payloads only.
7. Attach annotation refs by deterministic sample id matching.
8. Extend scheduler/report to carry refs and annotation_summary.
9. Add focused source/pipeline/report tests.
10. Run focused and full backend tests.

Do not add Dataset, DatasetSample, AnnotationObject, annotation parser, API/UI, Redis/RMQ/Celery, PACS/hospital/generic DICOMweb support.
```

---

## 9. Reviewer recommendation

Implementation can start after this checklist is accepted.

Recommended mode: **small vertical slice first**.

First implementation should support:

```text
minimal manifest + file data samples + annotation file/folder refs + report coverage
```

Then add folder data samples and edge cases. This keeps the first patch reviewable without weakening the final acceptance gate.
