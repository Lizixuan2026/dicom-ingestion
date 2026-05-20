# Batch 7 Phase 2 Pipeline Core Review v0.3

**评审日期**: 2026-05-19  
**评审对象**: commit `9cb2a4f fix(batch7): close phase2 pipeline core contract gaps`  
**继承自**: `batch7_phase2_pipeline_core_review_v0.1.md`, `batch7_phase2_pipeline_core_review_v0.2.md`  
**范围**: Phase 2 pipeline/source/report implementation and tests  
**角色定位**: reviewer only

---

## 一、结论

**状态建议**: `READY_WITH_MINOR_CONCERNS`  
**v0.1 P1 是否已修复**: 是  
**是否建议继续 Phase 2 后续工作**: 可以  
**是否建议直接忽略 v0.2 scope correction**: 不建议

本次修改针对 v0.1 的三个 P1 做了有效收口：

1. report 不再默认输出完整 `parsed_tags`，改为 `dicom_identity` 安全投影。
2. rejected items 会关闭 pending downstream axes，避免 operator/retry 视图误判。
3. bytes-only source materialization 改为 context manager，临时文件会清理。

测试结果：

```text
Focused Phase 2 tests: 13 passed
Full backend tests: 494 passed, 13 skipped, 1 warning
```

整体上，这版已经从 `DONE_WITH_CONCERNS` 升级为 `READY_WITH_MINOR_CONCERNS`。剩下主要是命名/scope 边界和一些 P2 生产化问题，不再是 pipeline core 的阻断项。

---

## 二、v0.1 P1 复核

### P1-1: Report 暴露 parsed DICOM tags / PHI 风险

**状态**: Fixed

当前 `backend/src/dicom_ingestion/pipeline/report.py` 中 report item 使用：

```python
dicom_identity = {
    "study_uid": full_tags.get("study_uid", ""),
    "series_uid": full_tags.get("series_uid", ""),
    "sop_instance_uid": full_tags.get("sop_instance_uid", ""),
    "modality": full_tags.get("modality", ""),
}
```

并且 report item 不再输出完整 `parsed_tags`。

新增测试：

```text
test_report_does_not_expose_phi_fields
```

评估：

- 默认 report shape 更安全。
- `patient_name` / `patient_id` 不再进入 report。
- DICOM identity 仍然保留，足够支撑 Batch 8 API/product surface 的基础查询。

剩余注意：

- `item.metadata["parsed_tags"]` 内部仍保留完整 parsed tags，这是可以接受的内部事实，但后续任何 API/report/export 都必须继续走 safe projection。

---

### P1-2: Non-DICOM / unreadable / missing required rejected item 留下 pending axes

**状态**: Fixed

当前新增：

```python
item.close_pending_axes()
```

并在 `IngestionItem` 中实现：

```python
def close_pending_axes(self, status: str = ItemStatusValue.REJECTED.value) -> None:
    ...
```

新增测试：

```text
test_rejected_items_do_not_leave_pending_axes
```

评估：

- non-DICOM item 不再显示 parse/storage/metadata/binding/index 仍 pending。
- missing required tag item 的 parse axis 保留 failed，后续 pending axes 被关闭为 rejected。
- 这比把所有 axis 都粗暴设成 failed 更好，因为 rejected 与 retryable failed 可以区分。

剩余注意：

- storage failure 后 metadata/binding/index 仍 pending。目前这是可接受的，因为该 item 是 retryable failed，不是 terminal rejected。后续如果 operator UI 需要更清晰，可以引入 `blocked` / `not_applicable` 状态，但不建议现在扩 enum。

---

### P1-3: bytes-only source materialization 遗留 temp files

**状态**: Fixed

当前新增：

```python
class MaterializedSource:
    ...
    def __exit__(...):
        if self._is_temp and self.path is not None and self.path.exists():
            self.path.unlink()
```

`_process_item()` 使用：

```python
with MaterializedSource(source_item, data) as source_path:
    ...
```

新增测试：

```text
test_bytes_only_source_cleans_temp_files
```

评估：

- bytes-only ZIP/source item 不再固定泄漏 `/tmp/dicom-ingest-*`。
- local file source 不会被误删。
- parse/storage 成功路径已覆盖。

剩余注意：

- `unlink()` 如果失败会向外抛出，理论上可能把一次成功处理变成 job-level fatal。概率低，但生产化时更稳的做法是 best-effort cleanup + warning log。当前不阻断 Phase 2 core。

---

## 三、v0.2 scope correction 复核

### Manifest 命名仍需校正

**状态**: Still open, but not a pipeline correctness blocker

当前代码仍然是：

```text
backend/src/dicom_ingestion/sources/manifest.py
class ManifestSource
```

它的行为是 explicit file list：给一组文件路径，验证是否在 allowed roots 下，然后枚举为 source items。

这不是用户侧 curated `data_manifest.json`。

建议在进入 PR/交给下一个实现者前做一个小修：

```text
ManifestSource → FileListManifestSource 或 ExplicitFileSource
```

并在 `sources/__init__.py` 和测试里同步命名。

为什么这件事重要：

- 技术上不影响当前测试。
- 但产品/架构语义上容易误导后续 AI 或工程师，把 manifest 当成 Dataset/annotation 上传协议继续扩。
- v0.2 已经明确：`data_manifest.json` 是用户侧组织说明，完整 Dataset 支持后置。

建议优先级：P1-doc/naming，低风险小改。

---

## 四、剩余 P2 问题

### P2-1: no-preamble DICOM 仍会被拒绝

当前：

```python
return len(data) >= 132 and data[128:132] == b"DICM"
```

这与当前 scanner 行为一致，可以接受。真实样本如果出现 no-preamble DICOM，再加 pydicom fallback probe。

### P2-2: in-memory job/item ids

当前 scheduler 使用 `_next_job_id` / `_next_item_id`。这符合 Phase 2 core 的 in-process 目标，不应现在扩成 DB-backed repository。

### P2-3: ZIP adapter URI payload 未支持

如果 `ScanService` 未来返回 URI/string payload，adapter 仍需扩展。当前 scanner byte payload 路径可用。

### P2-4: top-level `except Exception` 把所有 job-level error 合并为 fatal

当前对 core pipeline 可接受。后续进入 product surface 时，需要把 source validation error、storage config error、parser infra error 分成明确 exception class 和 operator message。

---

## 五、测试评价

本轮新增/验证的关键测试是对的：

- `test_report_does_not_expose_phi_fields`
- `test_rejected_items_do_not_leave_pending_axes`
- `test_bytes_only_source_cleans_temp_files`
- focused Phase 2 source/pipeline tests 全绿
- full backend tests 全绿

建议后续可补但不阻断：

1. `MaterializedSource.__exit__` cleanup failure 不应导致 successful item 变 fatal。
2. `ManifestSource` rename 后保留 outside root rejection 测试。
3. curated `data_manifest.json` 不在 Phase 2 core acceptance gate 中，避免测试误导。

---

## 六、NOT in scope 检查

当前实现仍未引入：

- REST API / FastAPI / HTTP endpoint
- UI / conflict UI
- Redis/RMQ/Celery
- PACS compatibility
- hospital system integration
- generic DICOMweb
-完整 Dataset 系统类型
- Annotation 内容解析
- OHIF viewer/annotation workflow

这点仍然正确。

---

## 七、Recommended next actions

建议按这个顺序继续：

1. **小命名修正**
   - `ManifestSource` 改为 `FileListManifestSource` / `ExplicitFileSource`。
   - 文档说明它不是用户侧 `data_manifest.json`。

2. **保留当前 pipeline core，不继续扩 scope**
   - 不做 Dataset。
   - 不做 annotation parser。
   - 不做 `task_type` 语义。

3. **可以进入下一阶段实现/评审**
   - 当前 P1 工程问题已收口。
   - 如果要合入，建议先完成 manifest 命名修正，避免后续方向误读。

---

## 八、最终状态

当前 Phase 2 pipeline core patch：`READY_WITH_MINOR_CONCERNS`

如果完成 `ManifestSource` 命名/scope 小修，可升级为：

```text
READY_FOR_PHASE2_CORE_PR
```
