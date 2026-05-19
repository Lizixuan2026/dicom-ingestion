# Batch 7 / Batch 8 评审落地（Phase 1）v0.1

**评审日期**: 2026-05-19  
**评审范围**: Batch 7/8 计划文档 + Batch 7 Phase 1 已提交实现（7A/7B/7C 相关）  
**评审结论**: **方向正确，建议按“先对齐契约、再推进实现”执行**

---

## 一、总体结论

本轮提交在“架构骨架”上是正向推进：

- 三阶段拆分清晰（Foundation → Pipeline → Product Surface）。
- Parser / Path Generator / Storage Backend 的模块边界初步可用。
- 对关键 gap（路径长度、大文件、Schema 演进等）已有显式设计意图。

但当前存在“**文档契约与代码行为不一致**”的风险，若不在 Phase 1 收口，Phase 2/3 联调将产生较高返工概率。

---

## 二、关键问题与影响

### P0-1：Batch 8 编号语义在文档间不一致

**现象**
- 一处文档将 8A 定义为 `Ingest Job API`。
- 另一处将 8A 定义为 `Adapter Layer`。

**影响**
- 排期、任务分配和验收口径会发生错位。
- 后续 cross-team 对齐成本上升。

**建议级别**: P0（需先统一后继续推进）

---

### P0-2：Parser 的 `required` 契约未强制执行

**现象**
- Schema 中存在 `required: true` 标签定义。
- 解析过程当前是“取到就填，取不到就跳过”，未对 required 缺失进行失败控制。

**影响**
- “必填 UID 缺失即拒绝”这一核心质量门未落地。
- 脏数据可能进入后续状态机与报告系统。

**建议级别**: P0（Phase 1 内必须补齐）

---

### P1-1：Local/NAS 路径长度控制策略与目标不匹配

**现象**
- 文档目标强调面向 Windows/NAS 的保守路径策略。
- 存储层当前长度阈值偏向 Linux 极限值，且哈希回退策略在极端场景控制力度不足。

**影响**
- 跨平台部署时可能出现路径失败或命名不一致。
- 路径可读性与稳定性难以同时保证。

**建议级别**: P1（Phase 1 尾声前完成）

---

### P1-2：SchemaManager 的兼容性判断与表结构假设过强

**现象**
- 兼容性判断存在占位实现（对 required 新增变更识别不足）。
- 代码假设的投影字段与实际迁移可能未强绑定。

**影响**
- Schema 演进策略可能“文档存在、运行无效”。
- 真实迁移时风险后置到集成阶段爆发。

**建议级别**: P1（尽快建立最小可验证闭环）

---

## 三、落地任务（可直接转执行）

### Task A（P0）：统一 Batch 8 编号语义

1. 选定唯一权威映射（建议采用“8A=Ingest Job API”版本）。
2. 同步修订：
   - `docs/superpowers/plans/phase_designs/README.md`
   - `docs/superpowers/plans/phase_designs/phase3_product_surface_design.md`
3. 在 `README` 增加“版本对齐说明（2026-05-19）”。
4. 每个 phase 文档头部补齐 `Depends on / Blocked by`。

**验收标准**
- 8A~8F 在所有文档中定义唯一且一致。
- 无同编号多含义描述。

---

### Task B（P0）：强制 required 标签校验

1. 在 `ConfigurableDicomParser.parse()` 中收集 required 缺失项。
2. 若存在缺失 required，抛出结构化 `ParseError`。
3. 区分 `warnings`（可恢复）与 `errors`（不可恢复）。
4. 增加 parser 单测覆盖：
   - required 缺失
   - optional 缺失
   - transform 生效
   - private extractor 异常隔离

**验收标准**
- required 缺失时解析必须失败。
- 失败信息包含缺失字段名，便于上游判定 reject 原因。

---

### Task C（P1）：重构路径长度与冲突命名策略

1. 给 Local/NAS 后端增加可配置长度阈值（默认建议 240~255）。
2. 将长度压缩改为**迭代式**策略（避免递归不稳定）。
3. 统一 PathGenerator 与 Storage 层的长度职责。
4. 冲突命名规则与规划文档一致（版本化命名）。
5. 补充测试矩阵：超长 UID、非法字符、同名不同内容、非 ASCII 厂商。

**验收标准**
- 跨平台路径策略稳定可复现。
- 超长路径场景可确定性回退，不发生无限压缩/不可预测命名。

---

### Task D（P1）：Schema 演进最小闭环

1. 将兼容性判断从占位实现改为真实比对（重点：新增 required）。
2. 引入 schema registry（配置或表）统一当前版本来源。
3. 增加 migration gate：代码依赖字段必须有 DDL 先行。
4. 增加兼容性单测：
   - 主版本变化
   - 次版本新增 required
   - 次版本仅新增 optional

**验收标准**
- 不兼容 schema 能被准确识别并触发 stale/reparse 流程。
- 运行时不会因字段假设不满足而静默失败。

---

## 四、建议执行顺序（Phase 1 收口版）

1. **先做 Task A + Task B（P0）**：先统一语义与数据质量门。
2. 再做 **Task C（P1）**：保证路径策略能跨环境稳定。
3. 最后做 **Task D（P1）**：建立 schema 演进可验证闭环。

> 原则：先修“契约正确性”，再扩“功能覆盖面”。

---

## 五、风险与回归关注点

- 若直接推进 Phase 2，P0 问题会在异步状态机和报告层放大。
- 路径与 schema 策略属于“晚暴露高代价”问题，建议前置验证。
- 任何新增 API/CLI 前，需先锁定 auth/owner 表达模型，避免 Batch 8 重构。

---

## 六、状态定义

- 当前状态：`DONE_WITH_CONCERNS`
- 建议下一状态：`READY_FOR_PHASE2`（前提：Task A/B 完成并通过回归）

