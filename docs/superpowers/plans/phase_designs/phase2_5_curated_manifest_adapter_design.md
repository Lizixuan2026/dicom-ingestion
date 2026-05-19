# Phase 2.5: Curated Upload Manifest Adapter Design

**日期**: 2026-05-19  
**状态**: Draft for implementation planning  
**前置条件**: Phase 2A pipeline core 已完成 closeout  
**目标读者**: 后续实现 AI / reviewer / 产品决策者

---

## 1. Executive Summary

Phase 2.5 的目标是支持一种新的上传入口：用户在上传前已经整理好数据目录，并用 `data_manifest.json` 描述 data 与 annotation 的组织关系。

这一阶段只做 adapter，不做 Dataset 产品模型。

```text
curated data_manifest.json
        │
        ▼
CuratedManifestSource / Adapter
        │
        ▼
IngestSourceItem(data payload)
        └── annotation_refs[]
        │
        ▼
existing Phase 2 pipeline core
        │
        ▼
ingest report with annotation coverage
```

Phase 2.5 要交付的是：

- 读取并验证用户侧 `data_manifest.json`。
- 枚举 `data` 下的数据样本或数据文件。
- 验证 annotation 路径存在且在 allowed roots 下。
- 将 annotation 作为 reference 挂到 data item 上。
- 在 report 中输出 annotation coverage。

Phase 2.5 不交付：

- Dataset model / DatasetSample model。
- Annotation object / Annotation version。
- annotation 文件内容解析。
- `task_type` 语义行为。
- API / UI。
- Redis/RMQ/Celery。
- PACS / hospital integration / generic DICOMweb。

---

## 2. Product Framing

用户场景：

> 用户已经在上传前整理好一个数据集目录。`data/` 里是原始数据样本；`label1/`、`label2/` 等目录里是对应标注。用户用 `data_manifest.json` 告诉系统这些目录在哪里，以及标注目录大概属于什么任务类型。

系统当前不需要理解标注内容。系统只需要知道：

```text
这个 data payload 有哪些 annotation payload 跟它相关。
```

所以 Phase 2.5 的价值不是“创建 Dataset”，而是：

- 让整理好的数据包可以进入摄入管道。
- 保留 data 与 annotation 的对应关系。
- 让后续 Dataset / annotation product surface 有可靠来源。

---

## 3. Manifest Input Contract

### 3.1 Minimal supported JSON

```json
{
  "data": "/path/to/data",
  "annotation": [
    { "path": "/path/to/label1/", "task_type": "segmentation" },
    { "path": "/path/to/label2/", "task_type": "localization" },
    { "path": "/path/to/label3/", "task_type": "detection" }
  ]
}
```

### 3.2 Recommended versioned shape

Phase 2.5 可以接受 minimal shape，但内部 validator 应兼容未来 versioned shape：

```json
{
  "version": 1,
  "type": "curated_upload_manifest",
  "data": { "path": "data" },
  "annotation": [
    { "name": "label1", "path": "label1", "task_type": "segmentation", "required": false }
  ]
}
```

### 3.3 Path policy

支持：

- absolute path，只要在 allowed roots 下。
- relative path，相对于 manifest 文件所在目录解析。

禁止：

- path traversal 逃出 allowed roots。
- symlink escape 逃出 allowed roots。
- missing data path。
- annotation path 不存在但标记为 required。

建议：所有路径进入系统前都 `resolve()`，然后用 existing `is_relative_to()` 验证 allowed roots。

---

## 4. Sample Matching Rule

Phase 2.5 不做 fuzzy matching。规则必须简单、可解释、可测试。

### 4.1 data sample 是文件

```text
root/
  data/
    sample_001.dcm
    sample_002.dcm
  label1/
    sample_001.json
    sample_002.json
  label2/
    sample_001/
    sample_002/
```

匹配 key：data 文件 stem。

```text
data/sample_001.dcm → sample_id = sample_001
label1/sample_001.json → match
label2/sample_001/     → match
```

### 4.2 data sample 是文件夹

```text
root/
  data/
    sample_001/
      image_1.dcm
      image_2.dcm
  label1/
    sample_001/
      mask.nii.gz
```

匹配 key：`data/` 的 immediate child name。

```text
data/sample_001/... → sample_id = sample_001
label1/sample_001/  → match
```

### 4.3 Mixed mode

如果 `data/` 下同时存在文件和文件夹，Phase 2.5 可以支持，但要明确 sample id 规则：

```text
file   → stem
folder → folder name
```

如果同一个 sample id 同时来自文件和文件夹，应该产生 manifest validation warning 或 rejection，避免隐式合并。

---

## 5. Internal Data Shape

### 5.1 AnnotationRef

建议新增到 source layer，而不是 models/domain layer：

```python
@dataclass(frozen=True)
class AnnotationRef:
    source_relative_path: str
    task_type: str | None = None
    label_name: str | None = None
    required: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)
```

注意：

- `task_type` 是 tag，不是 enum，不驱动行为。
- `source_relative_path` 是相对路径，不输出内部绝对路径。
- `metadata` 不应包含 absolute_path，除非仅作为内部字段且 report sanitize 会移除。

### 5.2 IngestSourceItem extension

建议扩展 existing `IngestSourceItem`：

```python
@dataclass(frozen=True)
class IngestSourceItem:
    source_kind: str
    original_relative_path: str
    size_bytes: int
    open_bytes: Callable[[], bytes]
    metadata: dict[str, Any] = field(default_factory=dict)
    annotations: list[AnnotationRef] = field(default_factory=list)
```

这不会改变普通 folder/zip/file-list source 的行为，因为 annotations 默认为空。

### 5.3 Source kind

新增：

```python
SourceKind.CURATED_MANIFEST = "curated_manifest"
```

不要复用 `file_list_manifest`，因为二者语义不同。

---

## 6. Proposed Component

### 6.1 Class name

推荐：

```text
CuratedManifestSource
```

或更明确：

```text
CuratedUploadManifestSource
```

不推荐：

```text
DatasetManifestSource
```

原因：Phase 2.5 仍不引入 Dataset 系统类型。

### 6.2 Constructor

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

### 6.3 enumerate() behavior

```text
1. read manifest JSON
2. normalize manifest shape
3. resolve data path
4. validate data path under allowed roots
5. resolve annotation paths
6. validate annotation paths under allowed roots
7. enumerate data payload files
8. derive sample_id for each data payload
9. attach matching annotation refs
10. return SourceEnumerationResult
```

Annotation files/folders themselves are not emitted as standalone `IngestSourceItem` unless they are also under `data/`. They are references, not DICOM parse candidates.

---

## 7. Pipeline Behavior

### 7.1 Existing DICOM pipeline remains unchanged

Each emitted data item still goes through existing Phase 2 pipeline:

```text
scan/classify → parser → storage → axes → report
```

### 7.2 Annotation refs do not go through parser

The adapter must ensure annotation payloads are not accidentally enumerated as data items.

Bad:

```text
label1/sample_001.json → DICOM parser → rejected NotDicomFile
```

Good:

```text
data/sample_001.dcm → DICOM parser
  └── annotation_refs: [label1/sample_001.json]
```

### 7.3 Item metadata

For each item, scheduler can copy refs into item metadata:

```python
item.metadata["annotation_refs"] = [ref.to_report_dict() for ref in source_item.annotations]
```

No annotation content should be read except for path existence/stat validation.

---

## 8. Report Shape

Extend Batch 7 report with annotation coverage. Keep it stable and safe.

```json
{
  "source": {
    "type": "curated_manifest",
    "root_label": "curated_manifest",
    "manifest_type": "curated_upload_manifest"
  },
  "summary": {
    "total_items": 2,
    "accepted_instances": 1,
    "rejected_items": 1,
    "failed_items": 0
  },
  "annotation_summary": {
    "referenced_items": 2,
    "items_with_annotations": 2,
    "items_missing_required_annotations": 0,
    "task_type_counts": {
      "segmentation": 2,
      "localization": 1
    }
  },
  "items": [
    {
      "relative_path": "data/sample_001.dcm",
      "terminal_outcome": "accepted",
      "annotation_refs": [
        {
          "source_relative_path": "label1/sample_001.json",
          "task_type": "segmentation",
          "label_name": "label1",
          "status": "referenced"
        }
      ]
    }
  ]
}
```

Rules:

- No internal absolute paths in report.
- No annotation file contents in report.
- No PHI fields from parsed tags beyond existing `dicom_identity` projection.
- Missing optional annotations appear as coverage warnings, not item failure.
- Missing required annotations reject only affected data item or manifest enumeration entry, not whole job, unless data root itself is invalid.

---

## 9. Error Policy

### 9.1 Job-level fatal errors

These should fail the whole job:

| Error | Suggested code | User/report impact |
|---|---|---|
| manifest JSON unreadable | `CuratedManifestUnreadable` | job failed |
| manifest JSON invalid | `CuratedManifestInvalidJson` | job failed |
| missing `data` field | `CuratedManifestMissingDataPath` | job failed |
| data path outside allowed roots | `CuratedManifestDataPathOutsideAllowedRoot` | job failed |
| data path missing/not directory | `CuratedManifestDataPathInvalid` | job failed |

Reason: without valid data root, source enumeration cannot proceed safely.

### 9.2 Source warnings / item-level rejections

These should not fail the whole job:

| Error | Suggested code | Behavior |
|---|---|---|
| optional annotation path missing | `AnnotationPathMissing` | source warning / coverage missing |
| annotation path outside root | `AnnotationPathOutsideAllowedRoot` | source warning, do not attach refs |
| required annotation for sample missing | `RequiredAnnotationMissing` | reject affected data item |
| duplicate sample id | `DuplicateCuratedSampleId` | reject affected entries or source warning |
| annotation has unknown task_type | no error | keep as tag |

### 9.3 `task_type` policy

`task_type` is free-form string tag in Phase 2.5.

Validation only:

- must be string if present
- empty string normalized to null or rejected as manifest warning
- no semantic enum enforcement

---

## 10. Security & Privacy

Threats to cover:

1. Path traversal from manifest paths.
2. Symlink escape from allowed roots.
3. Manifest pointing to arbitrary system files.
4. Annotation refs leaking absolute paths into report.
5. Annotation contents accidentally parsed or serialized.
6. PHI leakage from DICOM parsed tags in report.

Required controls:

- Resolve every path before validation.
- Enforce allowed roots for data and annotation paths.
- Preserve only source-relative paths in report.
- Reuse report sanitizer.
- Do not read annotation bytes except optional stat/existence checks.
- Keep existing `dicom_identity` safe projection.

---

## 11. Test Plan

### 11.1 Source tests

Required:

1. Minimal manifest with file data samples attaches matching annotation refs.
2. Minimal manifest with folder data samples attaches matching annotation refs.
3. Relative manifest paths resolve relative to manifest file directory.
4. Absolute manifest paths are accepted only under allowed roots.
5. Data path outside allowed root fails enumeration/job.
6. Annotation path outside allowed root is reported and not attached.
7. Missing optional annotation path reports warning but does not fail job.
8. Missing required annotation rejects affected item.
9. Duplicate sample id is reported deterministically.
10. `task_type` is preserved as tag and not enum-validated.

### 11.2 Pipeline tests

Required:

1. Curated manifest with valid DICOM data item reaches accepted outcome.
2. Annotation files are not emitted as DICOM parse candidates.
3. Non-DICOM file under data is rejected as data item, not fatal.
4. Accepted item report includes annotation refs.
5. Report excludes internal absolute paths.
6. Report excludes annotation contents.
7. Report includes annotation coverage summary.
8. Missing required annotation appears in rejections with clear reason.

### 11.3 Regression tests

Required:

1. Existing LocalFolderSource tests still pass.
2. Existing ZipArchiveSourceAdapter tests still pass.
3. Existing FileListManifestSource tests still pass.
4. Full backend tests pass.

Commands:

```bash
cd backend
./venv/bin/python -m pytest tests/sources/test_ingest_sources.py tests/pipeline/test_batch7_pipeline.py -q
./venv/bin/python -m pytest -q
```

---

## 12. Acceptance Gate

Phase 2.5 is ready when:

- `CuratedUploadManifestSource` or equivalent adapter exists.
- It reads minimal `data_manifest.json` shape.
- It supports relative and absolute paths under allowed roots.
- It emits only data payloads as `IngestSourceItem`.
- It attaches annotation refs to data items.
- It does not parse annotation contents.
- It does not introduce Dataset model.
- It does not introduce REST API/UI/Redis/RMQ/Celery.
- Report includes annotation coverage and no absolute paths.
- Focused and full backend tests pass.

---

## 13. Implementation Order

```text
1. Add AnnotationRef to source layer
2. Extend IngestSourceItem with annotations: list[AnnotationRef]
3. Add CuratedUploadManifestSource
4. Add source-level tests for manifest parsing/path validation/matching
5. Wire scheduler/report to carry annotation refs into item metadata/report
6. Add pipeline/report tests
7. Run focused tests
8. Run full backend tests
9. Review for scope creep
```

Keep each step small. Do not combine this with Dataset/API/UI work.

---

## 14. NOT in scope

Explicitly not in Phase 2.5:

- Dataset model
- DatasetSample persistence
- Annotation object persistence
- Annotation file parser
- segmentation/localization/detection behavior
- Dataset versioning
- Dataset builder UI
- REST API / FastAPI / HTTP endpoint
- conflict UI
- Redis/RMQ/Celery external queue
- PACS compatibility
- hospital system integration
- generic DICOMweb
- OHIF viewer/annotation workflow, unless a future minimal bridge is explicitly needed

---

## 15. Short prompt for implementation AI

```text
Implement Phase 2.5 Curated Upload Manifest Adapter only.

Use docs/superpowers/plans/phase_designs/phase2_5_curated_manifest_adapter_design.md as the source of truth.

Do:
- Add AnnotationRef in source layer.
- Extend IngestSourceItem with annotation refs defaulting to empty list.
- Add CuratedUploadManifestSource for user data_manifest.json.
- Validate data and annotation paths under allowed roots.
- Enumerate data payloads only.
- Attach annotation refs by deterministic sample id matching.
- Extend report with annotation refs and annotation_summary.
- Add focused source/pipeline/report tests.

Do not:
- Add Dataset model.
- Parse annotation contents.
- Treat task_type as enum behavior.
- Add API/UI.
- Add Redis/RMQ/Celery.
- Add PACS/hospital/generic DICOMweb support.

Run:
cd backend
./venv/bin/python -m pytest tests/sources/test_ingest_sources.py tests/pipeline/test_batch7_pipeline.py -q
./venv/bin/python -m pytest -q
```
