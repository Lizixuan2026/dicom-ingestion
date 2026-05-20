# Batch 7 Phase 2 Pipeline Core Review v0.1

**评审日期**: 2026-05-19  
**评审对象**: 当前 `main` 工作区未提交 Phase 2 candidate patch  
**范围**: `backend/src/dicom_ingestion/sources/`, `backend/src/dicom_ingestion/pipeline/`, `backend/tests/sources/`, `backend/tests/pipeline/`  
**角色定位**: reviewer only, 不继续扩展实现

---

## 一、结论

**状态建议**: `DONE_WITH_CONCERNS`  
**是否建议保留方向**: 是  
**是否建议直接合入**: 否，先修 P1  
**是否越过 scope**: 基本没有

这版实现遵守了 Phase 2 Pipeline Core 的主边界：没有引入 REST API、UI、Redis/RMQ/Celery，也没有碰 PACS / hospital integration / generic DICOMweb。新增的 source abstraction、in-process scheduler、report builder 方向正确，适合作为 Phase 2 core 的第一版骨架。

测试结果已验证：

```text
Focused Phase 1 + Phase 2 tests: 62 passed
Full backend tests: 491 passed, 13 skipped, 1 warning
```

但当前 patch 仍有几个工程问题：主要不是测试红，而是契约和生产化边界还没收口。建议保留实现方向，先做小修再进入下一步。

---

## 二、What already exists / reuse 判断

当前实现复用了这些已有能力：

- `ConfigurableDicomParser`：用于 DICOM header parse 和 required tag validation。
- `StorageManager` + `LocalNASStorageBackend`：用于 Local/NAS archive storage。
- `IngestionJob` / `JobStateMachine`：用于 job 状态推进。
- `IngestionItem` status axes：用于 scan / parse / storage / metadata / validation / binding / index 状态。
- `ScanService`：ZIP adapter 没有重写 ZIP safety，而是适配已有 scanner 输出。

没有明显重复造轮子的地方。source abstraction 是缺口，新增合理。

---

## 三、P1 问题

### P1-1: Report 暴露 parsed DICOM tags，存在 PHI 泄露风险

**位置**: `backend/src/dicom_ingestion/pipeline/report.py`

当前 report item 中包含：

```python
"parsed_tags": parsed_tags
```

`parsed_tags` 可能包含 `patient_name`、`patient_id`、以及未来 external schema 配置出来的其他 PHI 字段。虽然当前实现过滤了 `absolute_path` / `local_path`，但没有做 PHI-safe projection。

**影响**

- Batch 7 report 未来会被 Batch 8 API / product surface 复用。
- 如果 report 默认携带 PatientName/PatientID，会把内部 parse 事实变成用户/API 输出事实。
- 这和 intake layer 的安全边界不一致。

**建议修复**

1. 不在默认 report item 输出完整 `parsed_tags`。
2. 改成 report-safe identity projection，例如：

```json
{
  "dicom_identity": {
    "study_uid": "...",
    "series_uid": "...",
    "sop_instance_uid": "...",
    "modality": "..."
  }
}
```

3. 如果需要调试完整 tags，放到 explicit debug/internal report，不作为默认 Batch 7 report shape。
4. 增加测试：report 中不包含 `patient_name`、`patient_id`，但包含 Study/Series/SOP/Modality。

**验收标准**

- `str(report)` 不包含 patient name/id 测试值。
- report 仍包含必要 DICOM identity。
- storage URI 仍为 `local-nas://...`。

---

### P1-2: Non-DICOM / unreadable source item 的状态轴不完整

**位置**: `backend/src/dicom_ingestion/pipeline/scheduler.py`

当前 `SourceFileUnreadable` 分支：

```python
item.mark_scanned(False, "SourceFileUnreadable")
item.error_detail = str(exc)
return
```

`mark_scanned(False)` 会将 item 设为 `terminal_outcome=rejected`，但 parse/storage 等轴仍是 `pending`。Non-DICOM 分支也类似。

**影响**

- report 能看出 rejected，但状态轴显示后续步骤 pending，容易让 operator 误以为还有未处理任务。
- Batch 8 若按 status axes 计算 pending/retryable，可能产生误导。

**建议修复**

为 terminal rejected items 明确关闭不适用的后续轴。最小做法：

- 对 non-DICOM / source unreadable / required tag missing：
  - `terminal_outcome = rejected`
  - parse/storage/metadata/validation/binding/index 不再保持 ambiguous pending
- 如果现有 enum 没有 `not_applicable`，建议先用已有 `rejected` 或新增明确常量，但要全测试覆盖。

**验收标准**

- Non-DICOM item 不显示为后续 pipeline pending。
- Required tag missing item 的 parse status 是 failed/rejected，storage 不表现为等待写入。
- report 能区分 rejected vs failed retryable。

---

### P1-3: Non-local source materialization 会遗留临时文件

**位置**: `backend/src/dicom_ingestion/pipeline/scheduler.py`

当前 `_materialize_if_needed()` 对 ZIP item 等 bytes-only source 使用：

```python
tempfile.NamedTemporaryFile(..., delete=False)
```

但没有清理路径。每个 ZIP item parse/storage 都可能留下临时文件。

**影响**

- 大批量 ZIP ingest 会污染 `/tmp`。
- 长时间运行会造成磁盘泄漏。
- 失败路径也不会清理。

**建议修复**

1. 将 materialization 生命周期放进 `_process_item()`，用 `try/finally` 清理。
2. 或创建 `MaterializedSource` context manager：

```python
with materialize_source_item(source_item, data) as source_path:
    parse(...)
    store(...)
```

3. 对 local file source 不删除原始文件；只清理 pipeline 自己创建的 temp file。
4. 增加 ZIP adapter pipeline 测试，断言 temp file 被清理或使用 monkeypatch 记录 cleanup。

**验收标准**

- bytes-only source 不遗留 temp file。
- local folder source 不删除原始文件。
- parse failure/storage failure 路径也清理 temp file。

---

## 四、P2 问题

### P2-1: DICOM 判定只接受 128-byte preamble + `DICM`

**位置**: `Batch7PipelineScheduler._looks_like_dicom()`

当前逻辑：

```python
return len(data) >= 132 and data[128:132] == b"DICM"
```

这会拒绝某些 pydicom `force=True` 可读但没有 preamble 的 DICOM-like files。

**建议**

短期可以接受，因为现有 scanner 也是 magic-number 风格；但应在 TODO 或后续 review 中明确：如果真实样本有 no-preamble DICOM，需要改成“fast magic check + pydicom fallback probe”。

---

### P2-2: Scheduler 只使用内存 job/item id

当前 `_next_job_id` / `_next_item_id` 是内存自增。这符合 Phase 2 core first，但不是 production persistence。

**建议**

文档和 review 中明确这是 core orchestrator，不是 DB-backed job repository。下一阶段若进入 product surface 或 operator workflow，需要接 repository/migration，而不是继续扩大内存实现。

---

### P2-3: `ZipArchiveSourceAdapter` 对 scanner URI item 不处理

当前 ZIP adapter 如果 `ScanItem.item_bytes_or_uri` 是 `str`，payload 会变成 `b""`：

```python
payload = item.item_bytes_or_uri if isinstance(item.item_bytes_or_uri, bytes) else b""
```

当前 existing scanner 对 ZIP entries 返回 bytes，所以测试通过。但 adapter 契约本身没有处理 URI source。

**建议**

先不扩。加注释或测试锁定：ZIP adapter v1 only supports byte payloads produced by current `ScanService`; URI item support deferred.

---

## 五、NOT in scope 仍然正确

本 patch 没有引入：

- REST API / FastAPI / HTTP endpoint
- UI / conflict UI
- Redis/RMQ/Celery
- PACS compatibility
- hospital system integration
- generic DICOMweb

这点是好的。继续保持。

---

## 六、测试评价

已有测试覆盖：

- nested folder enumeration
- empty folder
- unreadable file report
- manifest outside allowed root rejection
- ZIP adapter reuses scanner output
- mixed folder pipeline
- accepted item axes
- required tag rejection
- storage failure
- deterministic rerun with same bytes
- report excludes `absolute_path`

缺失测试建议：

1. report does not expose PHI fields.
2. bytes-only ZIP item pipeline cleans temp files.
3. rejected items do not leave misleading pending axes.
4. no-preamble DICOM behavior documented or tested as rejected.

---

## 七、Recommended next actions

建议按这个顺序修：

1. **P1-1 report-safe projection**
   - 不输出完整 `parsed_tags`。
   - 输出 DICOM identity subset。
   - 加 PHI 不泄露测试。

2. **P1-2 terminal rejected status axes cleanup**
   - 明确 non-DICOM / missing required / unreadable 的后续轴状态。
   - 加 pending 不误导测试。

3. **P1-3 temp file cleanup**
   - 对 bytes-only source 加 context-managed materialization。
   - 加 ZIP/bytes source cleanup 测试。

完成后再跑：

```bash
cd backend
./venv/bin/python -m pytest tests/sources/test_ingest_sources.py tests/pipeline/test_batch7_pipeline.py -q
./venv/bin/python -m pytest -q
```

---

## 八、状态建议

当前 candidate patch：`DONE_WITH_CONCERNS`

修完 P1 后可升级为：`READY_FOR_PHASE2_CORE_PR`

不建议继续扩 Phase 2 scope。下一步应该是把这个 core patch 打磨干净，而不是加 API/CLI/UI。
