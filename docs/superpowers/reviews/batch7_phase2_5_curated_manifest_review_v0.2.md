# Batch 7 Phase 2.5 Curated Manifest Review v0.2

**评审日期**: 2026-05-20
**评审对象**: commit `ff4c3dd fix(batch7): address Phase 2.5 curated manifest review P1 findings`
**继承自**: `batch7_phase2_5_curated_manifest_review_v0.1.md`
**评审角色**: reviewer only

---

## 一、结论

**状态建议**: `DONE_WITH_CONCERNS`
**是否修复 v0.1 两个 P1**: 基本是
**是否建议直接合入**: 否，仍有一个新的 P1 input-contract gap
**是否发生 scope creep**: 否

这轮更新修掉了 v0.1 的两个主要问题：

1. folder sample 下多个 data files 不再被误判为 duplicate。
2. curated manifest path errors 不再直接输出 resolved absolute path，并且 fatal curated error code 会进入 report。

验证结果：

```text
Focused Phase 2 / 2.5 tests: 32 passed
Full backend tests: 513 passed, 13 skipped, 1 warning
```

但是我额外复核了 Phase 2.5 设计中明确支持的 absolute path 输入，发现 `data` 使用 allowed-root 内的绝对路径但不在 manifest 文件目录下时仍会崩成 `ValueError`。这违反 manifest input contract，也贴近用户最初给的示例：

```json
{
  "data": "/path/to/data",
  "annotation": [ ... ]
}
```

因此当前仍不建议直接合入。

---

## 二、v0.1 P1 复核

### P1-1: folder sample 多文件被误判 duplicate

**状态**: Fixed

当前 `_DataFileEntry` 增加了 `sample_container`：

```python
sample_id, sample_container = self._sample_identity(rel_to_data)
```

并将 duplicate 判断改成同一 sample_id 下是否出现多个 sample containers：

```python
containers_by_id.setdefault(entry.sample_id, set()).add(entry.sample_container)
return {sample_id for sample_id, containers in containers_by_id.items() if len(containers) > 1}
```

新增测试：

```text
test_curated_manifest_folder_sample_allows_multiple_data_files
```

评估：

- 合法的 `data/sample_001/image_1.dcm` + `image_2.dcm` 可以通过。
- `data/sample_001.dcm` 和 `data/sample_001/...` 这种真正 ambiguous container 仍可报 duplicate。
- 这符合设计。

---

### P1-2: error report 泄露 absolute path，fatal error code 被吞

**状态**: Mostly fixed

修复点：

- `CuratedManifestError.detail` 不再包含 resolved absolute path。
- scheduler 顶层 fatal path 使用 `getattr(exc, "error_code", "JobFatalError")`。
- report builder 增加 `sanitize_source_error()`。

新增测试：

```text
test_curated_manifest_source_errors_do_not_leak_absolute_paths
test_curated_manifest_fatal_error_preserves_specific_error_code_in_report
test_curated_manifest_optional_missing_annotation_report_excludes_absolute_path
```

评估：

- v0.1 指出的 curated manifest path error 泄露基本修掉了。
- fatal curated manifest error code 现在能进入 report。
- 这符合 report 安全边界。

剩余注意：

- `sanitize_source_error()` 是通用兜底，但主要安全性应来自 source 层不要生成 absolute-path detail。当前 curated source 已这么做。

---

## 三、新 P1 问题

### P1-3: allowed-root 内 absolute data path 不在 manifest_dir 下时会崩

**位置**: `backend/src/dicom_ingestion/sources/curated_manifest.py`

相关代码：

```python
rel_to_manifest = normalize_relative_path(path.relative_to(manifest_dir))
```

Phase 2.5 设计明确支持：

```text
absolute path，只要在 allowed roots 下。
relative path，相对于 manifest 文件所在目录解析。
```

但当前 `_enumerate_data_files()` 假设 data file 一定可以 relative to `manifest_dir`。如果 manifest 在：

```text
/base/pkg/data_manifest.json
```

而 data 使用 allowed-root 内的 absolute path：

```text
/base/data_root
```

则 `path.relative_to(manifest_dir)` 抛出：

```text
ValueError: '/base/data_root/sample_001.dcm' is not in the subpath of '/base/pkg'
```

我用临时脚本验证，当前输出：

```text
ValueError ... is not in the subpath of .../pkg
```

这会在 scheduler 中变成 generic `JobFatalError` 或未分类 fatal，且不符合用户原始 manifest 示例。

**影响**

- 用户使用 absolute `data` path 的合法 manifest 会失败。
- 这不是边缘情况，用户最初给的例子就是 absolute path。
- 当前测试只覆盖 absolute path outside allowed root，没有覆盖 absolute path under allowed root。

**建议修复**

需要引入安全的 source-relative display path policy：

1. 如果 data path 在 manifest_dir 下：

   ```text
   relative_path = path.relative_to(manifest_dir)
   ```

2. 如果 data path 不在 manifest_dir 下但在某个 allowed root 下：

   ```text
   relative_path = path.relative_to(matched_allowed_root)
   ```

3. 不要 fallback 到 absolute path。

可以加 helper：

```python
def _safe_relative_path(self, path: Path, preferred_root: Path) -> str:
    if is_relative_to(path, preferred_root):
        return normalize_relative_path(path.relative_to(preferred_root))
    root = next((r for r in self.allowed_roots if is_relative_to(path, r)), None)
    if root is not None:
        return normalize_relative_path(path.relative_to(root))
    return path.name
```

annotation ref relative path 也建议统一走这个 helper，避免未来同类问题。

**需要新增测试**

```text
test_curated_manifest_accepts_absolute_data_path_under_allowed_root
```

断言：

- 不抛 `ValueError`。
- item 被枚举。
- `original_relative_path` 是 allowed-root-relative 或 manifest-safe relative path。
- report 不包含 absolute path。

如果 annotation root 也支持 absolute path under allowed root 且不在 manifest_dir 下，建议补：

```text
test_curated_manifest_accepts_absolute_annotation_path_under_allowed_root
```

---

## 四、P2 / hygiene 问题

### P2-1: diff whitespace check 当前失败在 review v0.1 文档

运行：

```bash
git diff --check fd39f1e..HEAD
```

当前失败位置是：

```text
docs/superpowers/reviews/batch7_phase2_5_curated_manifest_review_v0.1.md trailing whitespace
```

这不是功能问题，但会影响严格 pre-commit / review hygiene。

建议清理该文档 trailing whitespace。

---

### P2-2: annotation matching 仍只支持 `.json` 文件和同名目录

当前仍是：

```python
annotation_root / f"{sample_id}.json"
annotation_root / sample_id
```

可以接受为 Phase 2.5 v1 的 small vertical slice，但文档或测试应明确当前支持范围。如果后续要支持 `.nii.gz` 等，需要单独设计 deterministic extension matching。

---

## 五、测试评价

本轮新增测试有效覆盖了 v0.1 两个 P1：

- folder sample 多 data files。
- source error 不泄露 absolute paths。
- fatal curated error code preserved。
- optional missing annotation report 不泄露 absolute path。

仍缺：

- absolute `data` path under allowed root。
- absolute annotation path under allowed root 且不在 manifest_dir 下。
- `git diff --check` clean。

---

## 六、Scope 检查

本轮仍没有引入：

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

Scope 控制仍然很好。

---

## 七、Recommended next actions

建议按顺序修：

1. **修 P1-3 absolute data path under allowed root**
   - 引入 safe relative path helper。
   - data item `original_relative_path` 不得使用 absolute path。
   - 补 absolute data path test。

2. **可选同修 absolute annotation path under allowed root**
   - annotation ref path 也用 safe relative helper。
   - 补 absolute annotation path test。

3. **清理 review v0.1 trailing whitespace**
   - 让 `git diff --check fd39f1e..HEAD` 或最终 PR diff check clean。

4. 重新跑：

```bash
cd backend
./venv/bin/python -m pytest tests/sources/test_curated_manifest.py tests/pipeline/test_curated_manifest_pipeline.py tests/sources/test_ingest_sources.py tests/pipeline/test_batch7_pipeline.py -q
./venv/bin/python -m pytest -q
git diff --check <base>..HEAD
```

---

## 八、状态建议

当前 commit `ff4c3dd`：`DONE_WITH_CONCERNS`

修完 P1-3 后可升级为：

```text
READY_WITH_MINOR_CONCERNS
```

如果同时让 diff hygiene clean，并明确 annotation extension matching 是 deferred，可升级为：

```text
READY_FOR_PHASE2_5_PR
```
