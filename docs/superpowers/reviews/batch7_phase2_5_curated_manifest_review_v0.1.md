# Batch 7 Phase 2.5 Curated Manifest Review v0.1

**评审日期**: 2026-05-20  
**评审对象**: commit `fd39f1e feat(batch7): implement Phase 2.5 curated upload manifest adapter`  
**评审角色**: reviewer only  
**依据文档**:

- `docs/superpowers/plans/phase_designs/phase2_5_curated_manifest_adapter_design.md`
- `docs/superpowers/plans/phase_designs/phase2_5_curated_manifest_eng_checklist.md`

---

## 一、结论

**状态建议**: `DONE_WITH_CONCERNS`  
**是否建议保留方向**: 是  
**是否建议直接合入**: 否，先修 P1  
**是否发生 scope creep**: 没有明显 scope creep

这版实现方向是对的：新增了 `CuratedUploadManifestSource`、`AnnotationRef`、`SourceKind.CURATED_MANIFEST`，并把 annotation refs 带入 report。它没有引入 Dataset model、annotation parser、API/UI、Redis/RMQ、PACS/hospital/generic DICOMweb，这点很好。

验证结果：

```text
Focused Phase 2 / 2.5 tests: 28 passed
Full backend tests: 509 passed, 13 skipped, 1 warning
```

但当前实现还有两个 P1：

1. folder sample 下多个 DICOM 文件会被误判为 duplicate sample，导致合法 folder sample 被整体跳过。
2. curated manifest 的 path validation 错误会在 report/source errors 中泄露内部绝对路径，并且 job-level fatal error 丢失具体 curated manifest error code。

这两个都与 Phase 2.5 的核心契约相关，建议修完后再进入合入状态。

---

## 二、What already exists / reuse 判断

当前实现复用了：

- Phase 2A `IngestSourceItem` / `SourceEnumerationResult` source abstraction。
- `Batch7PipelineScheduler` 现有 item processing pipeline。
- `Batch7ReportBuilder` 现有 report-safe DICOM identity projection。
- allowed roots / `is_relative_to()` path safety helper。

没有引入新的持久化模型，也没有把 Dataset/Annotation 做成 domain object。这符合 Phase 2.5 adapter-only 的边界。

---

## 三、P1 问题

### P1-1: folder sample 多文件被误判为 duplicate sample

**位置**: `backend/src/dicom_ingestion/sources/curated_manifest.py`

相关逻辑：

```python
sample_id = self._sample_id_for_relative(rel_to_data)
...
return {sample_id for sample_id, group in by_id.items() if len(group) > 1}
```

对于 folder sample：

```text
data/sample_001/image_1.dcm
data/sample_001/image_2.dcm
```

`_sample_id_for_relative()` 都返回 `sample_001`，于是 `_duplicate_sample_ids()` 把它当成 duplicate。实际这是合法的 folder sample：一个 sample 下可以有多个 data files。

我用一个临时脚本验证，当前结果是：

```text
items 0
errors DuplicateCuratedSampleId for image_1.dcm and image_2.dcm
```

这违反了设计文档中的 folder sample 规则：

```text
data/sample_001/... → sample_id = sample_001
label1/sample_001/  → match
```

**影响**

- 多 slice / 多文件组成的样本无法通过 curated manifest ingest。
- 医学影像里一个 sample 对应多个 DICOM 文件并不少见。
- 当前测试只覆盖了 folder sample 中一个 DICOM 文件，所以没抓住。

**建议修复**

duplicate 判断不能简单按 `sample_id` 下文件数量判断。建议先建 sample-level group：

```text
file sample:
  data/sample_001.dcm → sample_id sample_001, sample_container = file:data/sample_001.dcm

folder sample:
  data/sample_001/image_1.dcm
  data/sample_001/image_2.dcm
  → sample_id sample_001, sample_container = dir:data/sample_001
```

只有当同一个 sample_id 同时来自多个不同 sample container 时才算 duplicate，例如：

```text
data/sample_001.dcm
data/sample_001/image_1.dcm
```

或：

```text
data/sample_001.dcm
data/sample_001.nii.gz
```

如果当前 pipeline 仍以 file 为 ingest item，可以继续 emit 每个 data file，但 duplicate 判断必须以 sample container 而不是 file count 为准。

**需要新增测试**

```text
test_curated_manifest_folder_sample_allows_multiple_data_files
```

断言：

- `data/sample_001/image_1.dcm` 与 `data/sample_001/image_2.dcm` 都被枚举。
- 两个 item 都挂同一个 `label1/sample_001` annotation ref。
- 没有 `DuplicateCuratedSampleId`。

---

### P1-2: path validation 错误泄露绝对路径，且 fatal error code 被吞成 JobFatalError

**位置**:

- `backend/src/dicom_ingestion/sources/curated_manifest.py`
- `backend/src/dicom_ingestion/pipeline/scheduler.py`
- `backend/src/dicom_ingestion/pipeline/report.py`

当前 `_resolve_validated_path()` 生成 detail：

```python
f"path outside allowed roots: {resolved}"
f"path does not exist: {resolved}"
```

`resolved` 是内部绝对路径。对于 annotation warning，它会进入 `SourceEnumerationResult.errors`，然后 report builder 原样输出到 `rejections`：

```python
{"relative_path": err.get("path", ""), "reason": err.get("error_code", "SourceError"), "detail": err.get("error_detail", "")}
```

我验证了 missing optional annotation：

```text
error_detail: path does not exist: /private/var/folders/.../package/missing_label
```

这违反 Phase 2.5 report 规则：

```text
No internal absolute paths in report.
```

另外，data path outside allowed roots 这类 fatal `CuratedManifestError` 会被 scheduler 顶层 `except Exception` 捕获为：

```text
reason: JobFatalError
 detail: path outside allowed roots: /private/...
```

这里两个问题叠加：

- 具体 `CuratedManifestDataPathOutsideAllowedRoot` 错误码丢失。
- 内部绝对路径泄露到 report。

**影响**

- report 不再是安全输出面。
- operator / API consumer 看不到准确 error code。
- allowed root / temp / local NAS path 可能泄露。

**建议修复**

1. `CuratedManifestError.detail` 不应包含 resolved absolute path。可以改为安全 detail：

   ```text
   path outside allowed roots
   path does not exist
   path is not a directory
   ```

   如果调试需要 absolute path，只放 internal metadata/log，不进 report。

2. `SourceEnumerationResult.errors` 的 `path` 字段只放 manifest-relative path 或用户输入 path 的 sanitized form，不放 resolved absolute path。

3. scheduler 应识别带 `error_code` 的 exception：

   ```python
   error_code = getattr(exc, "error_code", "JobFatalError")
   error_detail = getattr(exc, "detail", str(exc))
   ```

   对 curated manifest fatal error，report reason 应保留：

   ```text
   CuratedManifestDataPathOutsideAllowedRoot
   CuratedManifestInvalidJson
   CuratedManifestMissingDataPath
   ```

4. report builder 对 `source_errors` 的 detail 也应 sanitize，不能只 sanitize `source_summary`。

**需要新增测试**

```text
test_curated_manifest_source_errors_do_not_leak_absolute_paths
test_curated_manifest_fatal_error_preserves_specific_error_code_in_report
test_curated_manifest_optional_missing_annotation_report_excludes_absolute_path
```

---

## 四、P2 问题

### P2-1: annotation matching 只支持 `.json` 文件和同名目录

当前：

```python
file_candidate = annotation_root / f"{sample_id}.json"
dir_candidate = annotation_root / sample_id
```

这符合当前最小实现，但设计里提到 annotation 可能是文件或文件夹，例子包括 `.nii.gz`。当前 `label1/sample_001.nii.gz` 不会匹配。

建议不一定现在扩，但要明确：Phase 2.5 v1 支持：

```text
label/sample_id.json
label/sample_id/
```

如果要支持 `.nii.gz` / `.txt` / arbitrary extension，应新增 deterministic matching policy：同 stem 唯一文件可匹配，多文件同 stem 报 ambiguity。

当前不阻断，因为 checklist 推荐先做 small vertical slice，但文档/测试最好锁定支持范围。

---

### P2-2: invalid annotation shape 被当成 source warning，而不是 fatal

`annotation` 不是 list、entry 不是 object、missing path 时当前只是 `result.errors`。这可接受，但要意识到：manifest 结构错误不会 fail job，只会导致无 annotation refs。

如果产品上希望 curated manifest 更严格，后续可以把 malformed annotation entry 升级为 fatal。当前不阻断。

---

## 五、测试评价

已有测试覆盖了大量正确方向：

- file data sample attaches annotation refs
- folder sample attaches annotation ref
- relative paths
- data path outside allowed root source-level error
- annotation outside allowed root warning
- optional missing annotation warning
- duplicate sample id visibility
- task_type preserved as tag
- pipeline accepted item with annotation
- annotation files not parsed as DICOM
- report includes refs and summary
- report excludes absolute paths on happy path
- required annotation missing rejects item
- optional annotation missing does not reject item

缺口：

1. folder sample with multiple data files。
2. report excludes absolute paths on error paths。
3. fatal curated manifest error preserves specific error code。
4. optional missing annotation report does not leak absolute path。

这几个缺口正好对应 P1。

---

## 六、Scope 检查

本 commit 没有新增：

- Dataset model
- DatasetSample persistence
- AnnotationObject persistence
- annotation parser
- segmentation/localization/detection semantic behavior
- REST API / FastAPI / HTTP endpoint
- UI
- Redis/RMQ/Celery
- PACS compatibility
- hospital integration
- generic DICOMweb
- OHIF workflow

Scope 控制是好的。

---

## 七、Recommended next actions

建议按顺序修：

1. **修 P1-1 folder sample duplicate 判断**
   - 允许同一个 folder sample 下多个 data files。
   - 只把同 sample_id 的不同 sample containers 视为 duplicate。
   - 增加 `test_curated_manifest_folder_sample_allows_multiple_data_files`。

2. **修 P1-2 error path report 安全**
   - curated manifest errors 不输出 absolute path。
   - scheduler 保留 `CuratedManifestError.error_code`。
   - report builder sanitize source error detail/path。
   - 增加 error path no absolute path tests。

3. 重新跑：

```bash
cd backend
./venv/bin/python -m pytest tests/sources/test_curated_manifest.py tests/pipeline/test_curated_manifest_pipeline.py tests/sources/test_ingest_sources.py tests/pipeline/test_batch7_pipeline.py -q
./venv/bin/python -m pytest -q
```

---

## 八、状态建议

当前 commit：`DONE_WITH_CONCERNS`

修完 P1 后可升级为：

```text
READY_WITH_MINOR_CONCERNS
```

如果同时明确 annotation extension matching policy，可进一步升级为：

```text
READY_FOR_PHASE2_5_PR
```
