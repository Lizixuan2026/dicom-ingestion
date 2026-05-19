# Batch 7 Phase 2 Pipeline Core Review v0.4

**评审日期**: 2026-05-19  
**评审对象**: Phase 2A closeout 修改，重点为 `ManifestSource` → `FileListManifestSource` 命名收口  
**继承自**: `batch7_phase2_pipeline_core_review_v0.3.md`  
**角色定位**: reviewer only

---

## 一、结论

**状态建议**: `READY_FOR_PHASE2_CORE_PR`  
**是否按计划执行 Phase 2A closeout**: 是  
**是否出现 scope creep**: 否  
**是否建议继续合入前清理**: 无（P3 spec 措辞已同步）

这轮修改完成了 v0.3 里剩余的核心命名/scope 问题：

```text
ManifestSource → FileListManifestSource
SourceKind.MANIFEST → SourceKind.FILE_LIST_MANIFEST
manifest.py → file_list_manifest.py
```

并在文档中明确：

- curated `data_manifest.json` defer 到 Phase 2.5。
- 当前 Phase 2 implementation target 是 in-process pipeline core。
- Redis/RMQ/Celery 与 DB-backed async workers 不属于当前 Phase 2A/2B delivery。

测试结果：

```text
Focused Phase 2 tests: 13 passed
Full backend tests: 494 passed, 13 skipped, 1 warning
Diff whitespace check: clean
```

因此，Phase 2 pipeline core 可以从 `READY_WITH_MINOR_CONCERNS` 升级为：

```text
READY_FOR_PHASE2_CORE_PR
```

---

## 二、复核结果

### 1. 命名修正

**状态**: Fixed

改动：

- `backend/src/dicom_ingestion/sources/file_list_manifest.py`
- `backend/src/dicom_ingestion/sources/__init__.py`
- `backend/src/dicom_ingestion/sources/base.py`
- `backend/tests/sources/test_ingest_sources.py`

新的 class 名：

```python
class FileListManifestSource:
    """Enumerate explicitly listed local files under configured roots.

    This is a low-level file path list for pipeline core — not the user-facing
    curated ``data_manifest.json`` adapter (deferred to Phase 2.5).
    """
```

这个注释非常关键，正好封住了后续误解。

评估：

- 行为没有不必要变化。
- source kind 变为 `file_list_manifest`，语义更清楚。
- tests 同步到新命名。
- 内部没有残留对旧 `ManifestSource` 的有效引用。

---

### 2. 文档收口

**状态**: Mostly fixed

`docs/specs/dicom_ingestion_batch7_batch8_spec.md` 已改为：

```text
FileListManifestSource(entries[])
Curated data_manifest.json deferred to Phase 2.5
```

`docs/superpowers/plans/phase_designs/phase2_ingestion_pipeline_design.md` 顶部新增：

```text
Current implementation target (2026-05-19): In-process pipeline core only.
Redis/RMQ/Celery and DB-backed async workers are deferred.
```

并在旧架构图前增加 note，说明 Task Queue / async ParseWorker / DB state machine 是 future hardening。

评估：

- 文档现在不会再误导实现者立刻上 Redis/RMQ。
- `data_manifest.json` 被正确放到 Phase 2.5。
- Dataset 没有进入当前 Phase 2 core。

P3 文档措辞已在 spec acceptance criteria 中同步为 `Explicit file-list manifest input...`。

---

### 3. Scope 检查

**状态**: Clean

本轮没有引入：

- REST API / FastAPI / HTTP endpoint
- UI / conflict UI
- Redis/RMQ/Celery
- PACS compatibility
- hospital system integration
- generic DICOMweb
- Dataset model
- annotation parser
- task_type semantic behavior

这点非常好。它是一次真正的 closeout，不是借修命名扩功能。

---

## 三、测试与验证

已运行：

```bash
cd backend
./venv/bin/python -m pytest tests/sources/test_ingest_sources.py tests/pipeline/test_batch7_pipeline.py -q
./venv/bin/python -m pytest -q
git diff --check
```

结果：

```text
13 passed
494 passed, 13 skipped, 1 warning
Diff whitespace check: clean
```

唯一 warning 仍是既有问题：

```text
PytestCollectionWarning: cannot collect test class 'TestStatus' because it has a __init__ constructor
```

与本轮修改无关。

---

## 四、最终判断

这轮修改达到了 Phase 2A closeout 目标。

建议：

1. 可以把 Phase 2A pipeline core 合入。
2. 下一步如继续开发，进入 Phase 2B hardening，而不是 Phase 2.5 curated manifest。

状态：

```text
READY_FOR_PHASE2_CORE_PR
```
