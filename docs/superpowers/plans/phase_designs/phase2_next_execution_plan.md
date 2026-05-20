# Phase 2 Next Execution Plan: Pipeline Core 收口与后续切分

**日期**: 2026-05-19  
**适用范围**: Batch 7 Phase 2 ingestion pipeline  
**输入依据**:

- `phase2_ingestion_pipeline_design.md`
- `phase2_manifest_annotation_scope_correction.md`
- `batch7_phase2_pipeline_core_review_v0.1.md`
- `batch7_phase2_pipeline_core_review_v0.2.md`
- `batch7_phase2_pipeline_core_review_v0.3.md`

---

## 1. CEO-level 结论

下一步不要扩。先把 Phase 2 core 正式收口。

当前最优路线：

```text
Phase 2A: Pipeline Core Closeout
  把现有 source → scheduler → parse/storage → report 骨架变成可合入核心能力

Phase 2B: Core Hardening
  补少量生产化边界，但仍保持 in-process，不引入 Redis/RMQ/API/UI

Phase 2.5: Curated Upload Manifest Adapter
  以后再处理 data_manifest.json，把 data 与 annotation refs 关联起来

Batch 8+: Product Surface / Dataset / API / UI
  到这里再引入 Dataset 概念和用户可见工作流
```

核心判断：

- `data_manifest.json` 是用户侧组织说明，不是当前系统内部 Dataset 模型。
- `task_type` 当前只是 tag，不是行为语义。
- annotation 当前最多作为 reference，不解析内容。
- 原设计里的 Redis/RMQ/Celery/外部队列继续后置。
- 当前 Phase 2 的价值是让 ingestion pipeline core 站稳，而不是把产品面铺开。

---

## 2. 当前状态

代码层面，Phase 2 pipeline core 已经过了主要 P1 review：

```text
Focused Phase 2 tests: 13 passed
Full backend tests: 494 passed, 13 skipped, 1 warning
```

已修复：

- report 不再默认输出完整 `parsed_tags`，改为 `dicom_identity` 安全投影。
- rejected items 不再留下误导性 pending downstream axes。
- bytes-only source materialization 会清理临时文件。

仍需收口：

- `ManifestSource` 命名仍容易误导。
- Phase 2 主设计文档中旧的 Redis/RMQ/Async worker 表述需要标记为后置。
- 当前 report/pipeline 缺少少量 production hardening，但不阻断 core 合入。

---

## 3. 下一步推荐顺序

### Step 1: Phase 2A Closeout，小修后合入

目标：把当前 Phase 2 core 从 `READY_WITH_MINOR_CONCERNS` 升级到 `READY_FOR_PHASE2_CORE_PR`。

必须做：

1. `ManifestSource` 改名

   推荐：

   ```text
   ManifestSource → FileListManifestSource
   manifest.py → file_list_manifest.py
   SourceKind.MANIFEST → SourceKind.FILE_LIST_MANIFEST 或保留 value 但文档解释清楚
   ```

   目的不是功能变化，而是防止后续把它误解成用户侧 `data_manifest.json`。

2. 同步测试命名

   ```text
   test_manifest_source_rejects_paths_outside_allowed_root
   → test_file_list_manifest_source_rejects_paths_outside_allowed_root
   ```

3. 同步 docs/spec 中 7D 的 source list

   旧：

   ```text
   ManifestSource(entries[])
   ```

   新：

   ```text
   FileListManifestSource(entries[])
   Curated data_manifest.json deferred to Phase 2.5
   ```

验收：

```bash
cd backend
./venv/bin/python -m pytest tests/sources/test_ingest_sources.py tests/pipeline/test_batch7_pipeline.py -q
./venv/bin/python -m pytest -q
```

如果通过，Phase 2A 可以合入。

---

### Step 2: 文档收敛，防止旧设计误导实现

目标：让后续 AI 不会沿旧 Phase 2 图去加 Redis/RMQ 或 Dataset。

必须做：

1. 在 `phase2_ingestion_pipeline_design.md` 顶部明确：

   ```text
   Current Phase 2 implementation target is in-process pipeline core.
   Redis/RMQ/Celery and DB-backed async worker are deferred.
   ```

2. 把旧架构图中的：

   ```text
   Task Queue (Redis/RMQ)
   ParseWorker Async
   State Machine (DB + Lock)
   ```

   标记为 future hardening，而非当前交付。

3. 保留 `phase2_manifest_annotation_scope_correction.md` 作为权威 correction。

验收：

- 文档读者能明确知道当前 Phase 2 不做外部队列。
- 文档读者能明确知道 `data_manifest.json` 不进入 Phase 2 core。

---

### Step 3: Phase 2B Core Hardening，不扩产品面

目标：让 core pipeline 更稳，但仍不进入 API/UI/外部队列。

建议做，但不要混进 Step 1：

1. Temp cleanup best-effort

   当前 `MaterializedSource.__exit__()` 的 `unlink()` 如果失败可能冒泡。建议改成 best-effort cleanup，并记录 warning metadata/log。

2. 明确 job-level exception 分类

   当前 scheduler 顶层 `except Exception` 可接受，但后续最好分出：

   ```text
   SourceEnumerationFatalError
   ParserInfrastructureError
   StorageConfigurationError
   ReportGenerationError
   ```

   目标是让 report/operator message 更清楚。

3. ZIP adapter contract 注释/测试

   明确当前 ZIP adapter 支持 current `ScanService` 的 bytes payload。如果 scanner 未来返回 URI，需要新适配。

4. no-preamble DICOM 作为 deferred TODO

   当前 magic check 与 scanner 一致，先不改。真实数据遇到后再加 pydicom fallback probe。

验收：

- 不改变 Phase 2 core 的对外行为。
- 不引入 Redis/RMQ/API/UI。
- 测试继续全绿。

---

### Step 4: Phase 2.5 单独设计 Curated Upload Manifest Adapter

这个不进入当前 Phase 2 core，但应该作为后续明确方向。

目标：支持用户上传前已经整理好的数据组织说明。

输入：

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

Phase 2.5 只做：

- validate data path under allowed roots
- validate annotation paths under allowed roots
- enumerate data files/folders
- attach annotation refs to data items
- report annotation coverage

Phase 2.5 不做：

- Dataset model
- annotation parser
- task_type semantic behavior
- annotation versioning
- UI/API

推荐内部输出：

```text
IngestSourceItem
  ├── original_relative_path
  ├── open_bytes()
  └── annotations: list[AnnotationRef]

AnnotationRef
  ├── source_relative_path
  ├── task_type
  ├── label_name
  └── metadata
```

---

## 4. 推荐执行节奏

```text
现在
  │
  ├─ 1. 做 ManifestSource 命名修正
  │     └─ 小 diff，低风险，直接让当前 core 变清楚
  │
  ├─ 2. 更新 Phase 2 设计文档中过时的 async/queue 表述
  │     └─ 防止后续实现跑偏
  │
  ├─ 3. 跑 focused + full backend tests
  │     └─ 通过后 Phase 2A 可合入
  │
  ├─ 4. 再决定是否做 Phase 2B hardening
  │     └─ cleanup best-effort / exception taxonomy / ZIP contract
  │
  └─ 5. 单独开 Phase 2.5 curated manifest adapter 设计
        └─ 只做 data ↔ annotation refs，不做 Dataset
```

---

## 5. NOT in scope

当前下一步明确不做：

- REST API / FastAPI / HTTP endpoints
- UI / conflict UI
- Redis/RMQ/Celery 外部队列
- PACS compatibility
- hospital system integration
- generic DICOMweb
-完整 Dataset 系统类型
- Dataset builder / versioning / lifecycle
- Annotation 内容解析
- segmentation / localization / detection 语义实现
- OHIF viewer/annotation workflow，除非未来出现具体最小桥接需求

---

## 6. 给实现 AI 的最短指令

如果把下一步交给另一个 AI，建议直接给这段：

```text
请只做 Phase 2A closeout，不要扩 scope。

任务：
1. 将当前低层 ManifestSource(entries[]) 改名为 FileListManifestSource 或 ExplicitFileSource。
2. 同步 sources/__init__.py、tests、docs/specs 中的命名。
3. 明确它不是用户侧 data_manifest.json。
4. 不实现 Dataset，不实现 annotation parser，不实现 task_type 语义。
5. 不引入 REST API/UI/Redis/RMQ/Celery。
6. 跑：
   cd backend
   ./venv/bin/python -m pytest tests/sources/test_ingest_sources.py tests/pipeline/test_batch7_pipeline.py -q
   ./venv/bin/python -m pytest -q
```

---

## 7. 决策建议

建议现在选择：**HOLD SCOPE + closeout**。

原因：

- Core pipeline 已经能跑通，P1 已修，应该趁现在把边界钉死。
- `data_manifest.json` 是重要方向，但会自然引出 Dataset/annotation 系统，不能拖进当前 Phase 2。
- Redis/RMQ/DB-backed worker 是未来生产化，不是当前 core 的必要条件。
- 当前最大风险不是功能不够，而是命名和文档让后续实现跑偏。

下一步一句话：

```text
先完成 ManifestSource 命名与文档收口，然后把 Phase 2A pipeline core 合入；curated manifest 作为 Phase 2.5 单独开设计。
```
