# Batch 7 Phase 2 Pipeline Core Review v0.5

**评审日期**: 2026-05-19  
**评审对象**: Phase 2A closeout final wording pass  
**继承自**: `batch7_phase2_pipeline_core_review_v0.4.md`  
**角色定位**: reviewer only

---

## 一、结论

**状态建议**: `READY_FOR_PHASE2_CORE_PR`  
**v0.4 P3 是否已修复**: 是  
**是否还有阻断项**: 无  
**是否出现 scope creep**: 无

这轮修改完成了 v0.4 剩余的文档措辞收口：

```text
Manifest input works...
→ Explicit file-list manifest input works...

ZIP, local folder, and manifest...
→ ZIP, local folder, and file-list manifest...
```

这很小，但重要：现在 spec 不再把低层 file-list source 和用户侧 curated `data_manifest.json` 混在同一个 “manifest” 词里。

---

## 二、验证结果

已运行：

```bash
cd backend
./venv/bin/python -m pytest tests/sources/test_ingest_sources.py tests/pipeline/test_batch7_pipeline.py -q
./venv/bin/python -m pytest -q
git diff --check
```

结果：

```text
Focused Phase 2 tests: 13 passed
Full backend tests: 494 passed, 13 skipped, 1 warning
Diff whitespace check: clean
```

唯一 warning 仍是既有 warning，与本轮修改无关：

```text
PytestCollectionWarning: cannot collect test class 'TestStatus' because it has a __init__ constructor
```

---

## 三、Scope 检查

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
- curated `data_manifest.json` adapter

这符合 Phase 2A closeout 计划。

---

## 四、最终判断

Phase 2A pipeline core 已完成 closeout：

- P1 工程问题已修。
- manifest 命名已收口。
- spec wording 已收口。
- design doc 已明确 async queue / DB-backed worker deferred。
- tests 全绿。

最终状态：

```text
READY_FOR_PHASE2_CORE_PR
```

下一步建议：

1. 合入 Phase 2A core。
2. 如果继续开发，进入 Phase 2B hardening。
3. `data_manifest.json` / annotation refs 作为 Phase 2.5 单独设计，不混入 Phase 2A。

---

## 五、一个非阻断提醒

`docs/superpowers/plans/phase_designs/phase2_next_execution_plan.md` 是执行计划文档，其中仍然保留“要做 ManifestSource 命名修正”的任务描述。现在该任务已经完成，因此它可以作为历史计划保留；如果希望文档读起来像最新状态，可以后续加一行：

```text
Status update: Phase 2A closeout completed; FileListManifestSource rename and spec wording are done.
```

这不是合入阻断项。
