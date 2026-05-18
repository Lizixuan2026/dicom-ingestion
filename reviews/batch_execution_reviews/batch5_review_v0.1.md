# Batch 5 实现评审（v0.1）

## 评审结论

**结论：当前不建议直接给 GREEN，建议判定为 YELLOW（可修后转绿）。**

本次 Batch5 已完成 C5/C6/D1/D3 的主体代码与测试框架搭建，方向正确，模块边界清晰；
但在“D3 可执行性”与“文档验收口径”上仍有关键缺口，需要先修补后再给最终 GREEN。

---

## 与 Batch5 计划文档的对照

对照文档：`docs/dicom_ingestion_execution/009_batch_5_execution_plan.md`

### Gate 1：Read models/projected views 可从 source-of-truth rebuild

**状态：基本满足。**

- 已提供 `ProjectionService`，支持单实例 build、批量 rebuild、query、stats。
- C5 的“可重建投影”能力在服务接口与测试层均有体现。

### Gate 2：Retry/replay 不依赖用户重新上传

**状态：基本满足。**

- 已提供 `ReplayService` 与 retry/replay 请求与结果模型。
- 设计上明确“从存储读取原始字节，不要求 re-upload”。

### Gate 3：Query 接口语义一致

**状态：基本满足。**

- 已提供 `ReviewQueryService`，并包含 Batch4 语义事实聚合（duplicate/private-tags/references/binding）。

### Gate 4：Reindex/rebuild 可按文档化 operator steps 执行

**状态：部分满足（当前是主要阻断项）。**

- 已有 `ReindexWorkflow` 代码实现 create/plan/execute/pause/resume/cancel。
- 但存在可执行性缺陷（见下方 P1）与操作文档交付缺口（见 P2）。

---

## 关键问题清单

### P1-1：`ReindexWorkflow.plan()` 在 `scope=all` 下存在 SQL 别名不一致风险

现象：部分 scope query 的 `additional_where` 使用 `i.current_canonical_observation_id`，
但 `base_query` 为 `FROM dicom_instances`（无 `i` 别名），导致 SQL 语句可能失败并进入异常路径。

影响：D3 的 “plan 可执行” 与稳定性受影响。

建议：统一 scope query 的 `FROM dicom_instances i` 写法，并补 `scope=all` 路径单测。

### P1-2：`_get_job()` 对 JSON 字段 `json.loads` 存在类型兼容风险

现象：`scope_params`/`steps` 字段可能由驱动直接返回 `dict/list`，重复 `json.loads` 会抛错。

影响：`plan/execute/status` 链路可被运行时类型问题击穿。

建议：改为类型自适配解析（str 才 loads，dict/list 直接使用），并补双形态单测。

### P2：D3 要求的 operator steps 文档交付不充分

现状：代码已实现 workflow，但尚缺面向运维/值班的执行手册（runbook/SOP）作为验收证据。

影响：与 Batch5 文档 gate 4（documented operator steps）不完全对应。

建议：补一份 reindex/rebuild runbook，至少覆盖：参数说明、执行顺序、dry-run 与正式差异、失败恢复、常见告警排查。

---

## 建议整改任务（可直接纳入下一次提交）

### P1（转绿前必须完成）

1. 修复 `ReindexWorkflow` scope SQL 别名一致性问题。
2. 修复 `_get_job()` JSON 字段反序列化兼容性问题。
3. 为上述两项补齐单测（特别是 `scope=all` 和 JSON 双返回形态）。

### P2（强烈建议）

1. 新增 Batch5 Reindex/Replay 运维手册（runbook）。
2. 在评审材料中增加“Gate -> 代码/测试/文档证据映射表”。

---

## 最终判定（v0.1）

**Batch5（v0.1）判定：YELLOW（暂不 GREEN）。**

当 P1 两项修复完成并补齐 D3 操作文档后，建议发起 v0.2 复审；
若修复项均通过，可升级为 **GREEN**。
