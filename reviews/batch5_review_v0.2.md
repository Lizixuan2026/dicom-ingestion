# Batch 5 实现评审（v0.2）

## 评审结论

**结论：当前仍不建议直接给 GREEN，建议判定为 YELLOW（补齐剩余 P1 后可转绿）。**

基于最新提交（`0b056bb`）与 v0.1 问题清单复核：

- v0.1 的两个 P1 方向中，`plan()` 的 SQL alias 一致性与 `_get_job()` JSON 兼容性已得到实质修复；
- 但 `ReindexWorkflow._step_analyze()` 在非 `scope=all` 场景仍存在 alias 不一致风险，会影响 D3 执行链路稳定性。

因此本轮评审建议仍为 **YELLOW**。

---

## 与 v0.1 关键问题对照

对照文档：`batch5_review_v0.1.md`

### P1-1（plan alias）

**状态：已修复。**

- `plan()` 中 scope query 使用 `FROM dicom_instances i`，并配套 `i.current_canonical_observation_id IS NOT NULL`；
- 同时新增了 `scope=all` 路径测试，验证 alias 使用一致。

### P1-2（_get_job JSON 兼容）

**状态：已修复。**

- `_get_job()` 对 `scope_params` / `steps` 的解析改为类型自适配：
  - `str`：`json.loads`；
  - `dict/list`：直接使用；
  - `None/空字符串`：回落默认值；
- 新增 string / parsed / null / empty-string 四类单测覆盖。

---

## 新增阻断问题（本轮）

### P1-3：`_step_analyze()` 在 `study/series/date_range` scope 下 alias 仍不一致

现象：

- `_step_analyze()` 的 base query 仍是：`SELECT COUNT(*) FROM dicom_instances`（无 `i` 别名）；
- 但 `_build_scope_query()` 在非 all scope 会拼接：
  - `JOIN dicom_studies st ON st.id = i.study_id`
  - `JOIN dicom_series s ON s.id = i.series_id`
  - `JOIN dicom_instance_observations o ON o.id = i.current_canonical_observation_id`
- 这些 join 条件依赖 `i` 别名，导致非 all scope 时仍可能 SQL 失败。

影响：

- D3 的 analyze 步骤在特定 scope 下可执行性不稳定；
- 可能出现 dry-run 或正式执行中 analyze step 异常，影响 operator workflow 可信度。

建议：

1. 将 `_step_analyze()` 的 base query 改为 `SELECT COUNT(*) FROM dicom_instances i`；
2. 将 additional_where 同步改为 `i.current_canonical_observation_id IS NOT NULL`；
3. 增补 `scope=study`（建议再补 `series/date_range`）的 analyze 路径单测，明确校验 SQL alias 与 join 可执行。

---

## Gate 结论更新（v0.2）

对照 `docs/dicom_ingestion_execution/009_batch_5_execution_plan.md`：

1. **Read models/projected views 可重建**：基本满足；
2. **Retry/replay 不依赖 re-upload**：基本满足；
3. **Query 接口语义一致**：基本满足；
4. **Reindex/rebuild 可按 documented operator steps 执行**：**部分满足**（受 P1-3 影响，仍未达到可直接 GREEN 的稳定程度）。

---

## 建议整改任务（转绿前）

### P1（必须）

1. 修复 `_step_analyze()` 的 alias 一致性；
2. 增补非 all scope 的 analyze 回归测试（至少 study，一并覆盖 series/date_range 更稳妥）。

### P2（建议）

1. 补充面向运维/值班的 reindex/rebuild runbook（参数、执行顺序、dry-run vs 正式、失败恢复、告警排查）；
2. 在评审材料中维护 Gate → 代码/测试/文档证据映射，降低后续复审成本。

---

## 最终判定（v0.2）

**Batch5（v0.2）判定：YELLOW（暂不 GREEN）。**

当 P1-3 完成并通过相应回归测试后，建议发起下一轮复审；
若修复项通过，可升级为 **GREEN**。
