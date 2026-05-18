# Batch 4 实现评审（v0.2）

## 评审结论

**结论：Batch4 可判定为“有条件通过（GREEN with follow-ups）”，允许启动 Batch5。**

与 `reviews/batch4_review_v0.1.md` 相比，当前实现已从“主要停留在 schema/invariant 层”推进到“canonical persistence 主流程执行层已接入 C1/C2/C3/C4”。

但仍存在两个会影响 Batch5 查询/回放可信度的高优先级修补项，建议在 Batch5 初期优先闭环。

---

## 与 v0.1 对比变化（关键进展）

### Gate 1：Duplicate facts + canonical pointer rationale

**状态：从“未满足”提升为“基本满足（执行链路已落地）”。**

已实现：

- `CanonicalPersistenceService.persist()` 已接入 C1 步骤，调用 duplicate detection service。
- duplicate 检测结果可写入 `PersistenceResult.duplicate_check_result`。
- canonical pointer rationale 已在主流程中显式记录：
  - `first_observation_becomes_canonical`
  - `canonical_already_exists`

仍需补强：

- `pixel_digest` 目前未透传（当前为 `None`），内容重复识别覆盖不完整。

---

### Gate 2：Reference edges 可查询且重放保持

**状态：从“未满足”提升为“基本满足（执行 + 查询接口已具备）”。**

已实现：

- `persist()` 已接入 C3，执行 reference extraction 并持久化。
- reference service 提供边写入与查询能力（含 unresolved 查询与解析逻辑）。
- 实现中已体现 upsert/幂等语义，方向与 replay 保持一致。

仍需补强：

- 建议在回放场景增加端到端验证用例（重放前后边数量/内容一致且不重复）。

---

### Gate 3：Private tags 存储与 redaction boundary

**状态：从“未满足”提升为“基本满足（解析→持久化链路已打通）”。**

已实现：

- `persist()` 已接入 C2，调用 private tag persistence service。
- 已有 redaction 状态模型与 redaction 相关服务能力。
- 持久化结果可回写到 `PersistenceResult.private_tag_result`。

仍需补强：

- 建议补充 creator-aware 与策略边界测试矩阵（保留/脱敏/截断的明确断言）。

---

### Gate 4：Binding policy 可由测试验证

**状态：从“部分满足”提升为“基本满足（服务与模型层已建立）”。**

已实现：

- `persist()` 已接入 C4，创建 binding policy record。
- binding policy service/model 与测试已存在，具备状态管理与失败信息保存语义。

仍需补强（高优先级）：

- 当前 `BindingContext(project_id="", user_id="")` 为空占位，导致策略上下文不完整，影响审计与可解释性。

---

## 主要证据（代码观察摘要）

1. `backend/src/dicom_ingestion/services/canonical/canonical_persistence.py`
   - `persist()` 管线包含步骤 7~10（C1~C4）。
   - 分别调用 `_execute_duplicate_detection/_execute_private_tag_persistence/_execute_reference_extraction/_execute_binding_policy`。
2. duplicate/reference/private-tag/binding 对应服务均已存在，并非仅 schema 预留。
3. `backend/tests/` 下已存在对应模块测试（integration/service/model 维度），证明不是纯字段占位。

---

## 风险评估（进入 Batch5 前）

允许进入 Batch5，但需明确“带修补项前进”：

1. **Binding 上下文为空**：可能导致跨系统绑定记录缺失关键归因信息。
2. **缺少 pixel_digest 路径**：内容重复识别对“同像素异封装”场景覆盖不足。

上述两项不阻断 Batch5 启动，但应列为 Batch5 Sprint 的前置修复任务（优先级 P0）。

---

## 建议整改（v0.2）

### P0（Batch5 初期必须完成）

1. **绑定上下文闭环（C4 修补）**
   - 去除 `BindingContext(project_id="", user_id="")` 的空值占位。
   - 从调用链透传真实上下文；若缺失，给出明确策略（拒绝/系统默认身份 + reason code）。
   - 增加对应行为测试（上下文存在/缺失两分支）。

2. **pixel_digest 闭环（C1 修补）**
   - 在解析或预处理阶段产出 pixel digest。
   - 透传至 `DuplicateDetectionContext.pixel_digest`。
   - 增补“同像素不同文件哈希”命中 content duplicate 的测试与统计验证。

### P1（强烈建议）

1. 增加 replay 端到端回归模板（duplicate/reference/private-tag/binding 四维度）。
2. terminal/reporting 统一 reason code 输出，增强失败可解释性。
3. 建立 gate → 用例映射表（便于后续批次复审与回归）。

---

## 最终判定

**Batch4（v0.2）判定：GREEN（有条件通过）。**

可启动 Batch5；但需将上述 P0 两项作为 Batch5 初期的必做修补任务，并在完成后补一次轻量复核。
