# Batch 4 实现评审（v0.1）

## 评审结论

**结论：当前 batch4 实现尚未满足《Batch 4 Execution Plan》定义的完成标准。**

对照文档 `docs/dicom_ingestion_execution/008_batch_4_execution_plan.md` 的 4 条 merge gates：

1. Duplicate facts + canonical pointer rationale 可执行：**未满足**
2. Reference edges 可查询且重放保持：**未满足**
3. Private tags 的存储/脱敏边界明确并执行：**未满足**
4. Binding policy 可被测试验证：**部分满足（字段层面），语义层未闭环**

---

## 评审范围与方法

本评审基于当前仓库代码静态检查（未引入额外实现变更），重点核对 Batch4 相关语义是否已从“表结构/约定”落地为“服务执行 + 测试验证”。

重点检查目录：

- `backend/src/dicom_ingestion/services/`
- `backend/src/dicom_ingestion/models/`
- `backend/src/dicom_ingestion/repositories/`
- `backend/alembic/versions/`
- `backend/tests/`
- `docs/dicom_ingestion_execution/008_batch_4_execution_plan.md`

---

## Gate-by-Gate 评审

### Gate 1：Duplicate detection 产出确定性事实与 canonical pointer 决策理由

**现状：未满足。**

已具备：

- 数据库层存在 `dicom_duplicate_findings` 表与唯一性约束（迁移 + schema invariants 测试）。

缺失：

- 在 canonical persistence 主流程中，未见 duplicate 分类计算并写入 `dicom_duplicate_findings` 的服务逻辑。
- 未见 identity/content duplicate 的执行层判定。
- 未见 canonical pointer selection 的“策略理由”落库（rationale）。

结论：目前更像“结构已预留”，尚未达到“review semantics are executable”。

---

### Gate 2：Reference edges 可查询且重放保持

**现状：未满足。**

已具备：

- 数据库层存在 `dicom_reference_edges` 及幂等约束相关 invariant 测试。

缺失：

- 未见从 DICOM 数据提取引用关系并入库的服务代码。
- 未见明确的 reference-edge repository 查询接口（供上层查询/回放验证）。
- 未见 replay 场景下“边不重复且可重建”的行为测试。

结论：仅有 schema/invariant，不足以证明“可查询且可重放保持”。

---

### Gate 3：Private tags 存储与 redaction boundary

**现状：未满足。**

已具备：

- Parser 已能提取 private tags（包含 creator/tag/raw value 基础信息）。
- 数据库层存在 `dicom_private_tags` 表与基础约束测试。

缺失：

- canonical persistence 流程未见将 private tags 持久化到 `dicom_private_tags` 的逻辑。
- 未见 redaction/retention policy 的显式策略层与执行点。
- 未见 policy 边界测试（如敏感字段脱敏、creator-aware 存储一致性）。

结论：解析能力存在，但“存储 + 策略”未打通。

---

### Gate 4：Binding policy 可由测试验证

**现状：部分满足（字段存在），但总体未闭环。**

已具备：

- `binding_status` 在 model/report 流程中已有字段与透传。

缺失：

- 未见独立 binding policy 状态机或统一策略执行服务。
- 未见“持久化成功但绑定失败时，ingest truth 保持 accepted”的强行为测试闭环。
- 未见失败分类与 reason code 的结构化策略输出。

结论：当前更多是“状态字段存在”，不是“策略可验证”。

---

## 主要证据（代码观察摘要）

1. `CanonicalPersistenceService.persist()` 主流程覆盖 study/series/instance/observation/canonical 标记，但未包含 duplicate/reference/private-tag 持久化步骤。
2. parser 层有 private tag 抽取函数，但服务层未见后续落库链路。
3. DB invariant 测试覆盖 duplicate/reference/private-tag 的唯一约束/基本约束，但不等价于业务语义已执行。
4. terminal report 有 duplicate/binding 字段，但统计来源与语义策略层之间耦合尚不完整。

---

## 风险评估

若以当前状态进入 Batch5（query/replay），存在以下风险：

1. 上游语义事实不足：duplicate/reference/private-tag 策略事实缺失，影响查询真实性。
2. 回放一致性不可证：无行为测试证明 replay 后事实完整且不重复。
3. 运营可解释性不足：canonical pointer 与 binding 决策理由缺失，排障困难。

---

## 建议整改（按优先级）

### P0（必须）

1. **C1/C1b**：落地 duplicate findings 计算与持久化，并把 canonical pointer policy 的决策理由结构化持久化。
2. **C3**：落地 reference edge 抽取与写入，并补充可查询 repository API。
3. **C2**：落地 private tag 持久化链路，并建立 redaction/retention policy 执行点。
4. **C4**：落地 binding policy 统一状态机与错误分类，并补齐行为测试。

### P1（强烈建议）

1. 对四条 gate 建立“验收测试映射表”：每条 gate 对应测试文件与测试用例 ID。
2. 在 terminal report 补 reason code 字段，确保“失败可解释”。
3. 为 replay 增加幂等性回归测试模板（duplicate/reference/private-tag/binding 全覆盖）。

---

## 最终判定

**Batch4 当前判定：不通过（需要继续实现后复审）。**

建议在完成 P0 项并补齐对应测试后发起 `batch4_review_v0.2` 复审。
