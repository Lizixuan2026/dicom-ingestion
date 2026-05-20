# Batch 7 / Batch 8 评审落地（Phase 1）v0.3

**评审日期**: 2026-05-19  
**复核对象**: `origin/main@ade629f` (`fix(review-v0.2): 清理 .site-packages 并统一 pydicom 依赖策略`)  
**文档目的**: 接在 v0.2 之后，复核最新 main 上 Phase 1 实现状态，并给出下一轮修复入口。

---

## 一、v0.3 复核结论

- **当前状态建议**: `DONE_WITH_CONCERNS`
- **是否可进入 Phase 2**: **暂缓**
- **是否需要推倒重来**: **否**

本轮实现已经实质推进了 Batch 7 Phase 1 foundation：

- configurable parser / schema manager 已落地
- Siemens/UIH private tag extractor 已落地
- Local/NAS path generator 已落地
- object/local storage backend abstraction 已落地
- storage manager 已落地
- `.site-packages` 仓库污染已清理
- `.gitignore` 已补充 `backend/.site-packages/`

但当前仍有 1 个测试失败，以及 2 个 spec 契约偏差。建议先完成 Phase 1 收口，再进入 Phase 2 ingestion pipeline。

---

## 二、复核证据

从 `origin/main` 导出干净快照到 `/private/tmp` 后运行全量 backend 测试：

```text
475 passed, 13 skipped, 1 failed
```

失败用例：

```text
backend/tests/storage/test_local_nas_path_control.py::TestIntegrationPathControl::test_component_and_full_path_coordination
```

失败原因摘要：

```text
max_path_length=100
actual full path length=134
```

当前 fallback 路径形如：

```text
.../OVERFLOW/176_a64f60c0339301c09f724812
```

这说明 Local/NAS storage 的完整路径长度控制仍不成立。尤其当 `base_path` 自身已经很长时，仅缩短相对路径不足以保证完整路径满足 `max_path_length`。

---

## 三、阻断问题

### P1-1：Local/NAS full path budget 未真正闭环

**现象**

`LocalNASStorageBackend._ensure_path_length()` 会将长路径压缩到 `OVERFLOW/{original_len}_{hash}`，但没有把 `base_path` 长度纳入剩余 budget 计算。

当 storage root 较长时，即使相对路径已经 fallback，完整路径仍可能超过 `max_path_length`。

**影响**

- Windows/NAS/受限文件系统环境下仍可能写入失败。
- 当前测试已经证明路径长度控制不是完全可靠。
- Phase 2 如果接入 folder ingest，会把这个问题放大到大量文件场景。

**建议修复**

1. 在 `LocalNASStorageBackend` 中显式计算：

```text
available_relative_budget = max_path_length - len(str(base_path)) - path_separator_margin
```

2. 若 budget 足够，生成能 fit 的短 hash fallback。
3. 若 budget 不足以容纳最小合法文件名，直接 fail fast，抛明确 `StorageError`。
4. 更新测试，覆盖：
   - normal long relative path can be shortened
   - very long base path fails fast
   - generated fallback path still preserves deterministic hash

**验收标准**

- `test_component_and_full_path_coordination` 通过。
- 对任意可满足 budget 的路径，最终完整路径长度 `<= max_path_length`。
- 对不可满足 budget 的 storage root，错误明确、可诊断、不静默写入。

---

### P1-2：Local/NAS platform-facing URI 仍使用 `file://absolute/path`

**现象**

当前 `LocalNASStorageBackend.store()` 返回：

```python
uri = f"file://{full_path.absolute()}"
```

但 Batch 7/8 spec 已锁定：

```text
local-nas://storage-root-id/path/to/file.dcm
```

absolute filesystem path 只能留在 backend/admin internal context。

**影响**

- Batch 8 binding envelope 会泄露本地绝对路径。
- API / report / downstream workflow 会依赖不可迁移的 machine-local path。
- 不符合“平台-facing refs 用 opaque URI”的安全边界。

**建议修复**

1. 给 Local/NAS backend 增加 `storage_root_id` 配置。
2. `StorageLocation.uri` 返回：

```text
local-nas://{storage_root_id}/{relative_path}
```

3. `StorageLocation.path` 保留相对路径。
4. 如需 admin/internal absolute path，放入 internal-only metadata 字段，避免 API 默认暴露。
5. 更新测试断言不再接受 `file://absolute/path` 作为平台-facing URI。

**验收标准**

- Local/NAS URI 使用 `local-nas://...`
- API/report/product envelope 不暴露 absolute path。
- retrieve/delete/exists 仍通过 backend internal path 正确工作。

---

### P2-1：默认 parser schema 将 `patient_name` 设为 required，可能过严

**现象**

当前默认 schema 中：

```python
{"tag": "(0010,0010)", "alias": "patient_name", "required": True}
```

这会让缺少 PatientName 的 DICOM 解析失败。

但 Batch 7 spec 的核心质量门是 DICOM identity 必填，重点应是：

- StudyInstanceUID
- SeriesInstanceUID
- SOPInstanceUID
- Modality

PatientName 在匿名化、脱敏、科研 intake 场景中不应默认成为阻断项。

**影响**

- 匿名/脱敏 DICOM 可能被误拒。
- 医疗数据 intake 对 PHI 字段的依赖过强。
- 与“数据管理平台 intake layer”定位不完全一致。

**建议修复**

1. 将默认 schema 中 `patient_name` 改为 optional。
2. 如某些部署需要 PatientName，可通过 external schema 配置启用 required。
3. 增加测试：
   - missing PatientName does not fail by default
   - custom schema can require PatientName
   - missing Study/Series/SOP UID still fails

**验收标准**

- 默认 intake 不因 PatientName 缺失失败。
- DICOM identity UID 缺失仍失败。
- required 行为由 external schema 控制。

---

## 四、建议执行顺序

1. **先修 P1-1 path budget**
   - 这是当前唯一红测试。
   - 修完后全量 backend tests 应恢复全绿。

2. **再修 P1-2 Local/NAS URI 契约**
   - 这是 spec/security/API 边界问题。
   - 越早修，越少污染 Phase 2/3。

3. **最后修 P2-1 default required schema**
   - 小改动，但会影响 intake 行为。
   - 建议与 parser tests 一起补齐。

4. **重跑测试**

```bash
cd backend
python -m pytest -q
python -m pytest tests/parser/test_schema_compatibility.py tests/parser/test_configurable_parser.py tests/storage/test_local_nas_path_control.py -q
```

---

## 五、状态建议

- `READY_FOR_PHASE2`: **暂缓**
- `PHASE1_FIXUP_REQUIRED`: **建议采用**
- `DONE_WITH_CONCERNS`: **当前准确状态**

Phase 1 不需要重做。当前问题集中在 contract closure，不是架构方向错误。

---

## 六、Phase 2 进入条件

进入 Phase 2 前，至少满足：

1. 全量 backend tests 通过。
2. `backend/tests/storage/test_local_nas_path_control.py` 全绿。
3. Local/NAS platform-facing URI 改为 `local-nas://...`。
4. 默认 parser schema 不把 PatientName 作为 intake 阻断项。
5. Phase 1 review 状态更新为 `READY_FOR_PHASE2`。

