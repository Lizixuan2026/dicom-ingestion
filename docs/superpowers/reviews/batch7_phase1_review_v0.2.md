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

- **历史状态**：
  - `DONE_WITH_CONCERNS` (2026-05-19 15:42) - P0/P1 修复前
- **当前状态**：`READY_FOR_PHASE2` ✅
  - P0-1, P0-2: ✅ FIXED
  - P1-1, P1-2: ✅ FIXED
  - 所有评审问题已解决
- **建议下一状态**：`PHASE2_IN_PROGRESS`
  - Phase 1 完全收口，可开始 Phase 2 摄入管道实现

---

## 七、修复记录

### 2026-05-19 - P0 + P1 问题全部修复完成

| 问题 | 状态 | 修复内容 |
|------|------|---------|
| **P0-1** | ✅ FIXED | 统一 Batch 8 编号语义：8A = Ingest Job API，后续编号顺延至 8G |
| **P0-2** | ✅ FIXED | 实现 required 标签强制校验，缺失时解析失败并返回结构化错误 |
| **P1-1** | ✅ FIXED | 路径长度控制策略改进：可配置阈值(240)、迭代式缩短、版本化命名 |
| **P1-2** | ✅ FIXED | SchemaManager 真实兼容性判断：SchemaRegistry + CompatibilityChecker |

### P0 修复详情

#### P0-1: 统一编号语义
- 修订 `README.md`: 更新 Phase 3 组件编号（8A~8G）
- 修订 `phase3_product_surface_design.md`: 8A=Ingest Job API, 8B=Adapter Layer, ..., 8G=Auth
- 添加版本对齐说明注释

#### P0-2: Required 标签强制校验
- 修改 `ConfigurableDicomParser.parse()`: 收集缺失 required，设置 `success=False`
- 增强 `ParseError` 类: `missing_required` 字段，`to_dict()` 方法
- 新增单测: 11个测试用例覆盖 required/optional/transform/异常隔离

### P1 修复详情

#### P1-1: 路径长度控制策略
- `LocalNASStorageBackend`: 可配置 `max_path_length`（默认 240，建议 240-255）
- 迭代式缩短策略（替代递归）：
  1. `_shorten_uids_in_parts()`: UID 保留前2段+哈希+后2段
  2. `_shorten_device_in_parts()`: 设备名使用 DEV_ 哈希前缀
  3. `_shorten_vendor_in_parts()`: 厂商使用缩写 SIEM/PHIL/UIH
  4. `_fallback_to_hash_structure()`: 保留顶层，下层哈希
  5. `_ultimate_fallback()`: 完整路径哈希（包含原始长度）
- 统一职责：
  - `PathGenerator`: 组件级长度控制（`max_component_length=48`）
  - `Storage`: 完整路径级控制（`max_path_length=240`）
- 版本化命名：`_get_unique_path()` 生成 `file_v001.dcm`, `file_v002.dcm`
- 新增 `get_versioned_path()`: 支持访问历史版本
- 新增单测: 11个测试类，52个测试方法

#### P1-2: Schema 兼容性判断
- 引入 `SchemaRegistry`: 统一管理 schema 版本定义
- 引入 `SchemaCompatibilityChecker`: 真实兼容性判断
- 支持三种 `CompatibilityLevel`:
  - `FULLY_COMPATIBLE`: 完全兼容
  - `REQUIRES_REPARSE`: 新增 required 字段，需重解析
  - `INCOMPATIBLE`: 主版本变更，不兼容
- `check_schema_compatibility()`: 返回 `(is_compatible, reason)` 元组
- `check_and_mark_stale_for_all()`: 批量检查并标记陈旧
- 预置默认 schema: 1.0.0, 1.1.0, 1.2.0（新增 required device_serial）, 2.0.0
- 新增单测: 7个测试类，20个测试方法


---

## 八、v0.2 复核结论（2026-05-19）

### 本轮提交复核对象
- 提交：`dc7ab3f` (`fix(tests): 修复测试并验证 P0/P1 修复`)

### 复核结果
- **当前状态建议：`DONE_WITH_CONCERNS`（不建议 GREEN）**
- 结论原因：
  1. 提交内容包含大量 `backend/.site-packages/` 第三方依赖文件，属于仓库污染风险。
  2. 本地复核测试未达全绿：
     - `backend/tests/parser/test_schema_compatibility.py`
     - `backend/tests/parser/test_configurable_parser.py`
     - `backend/tests/storage/test_local_nas_path_control.py`
     - 结果：`7 failed, 40 passed`
  3. 失败主要集中于 `test_configurable_parser.py` 的 `pydicom` 导入依赖（`ModuleNotFoundError`），说明“测试通过”结论与复核环境不一致。

### 风险级别
- **P1（发布阻断前置项）**
  - 若不清理 `.site-packages` 即合入，会导致主仓体积膨胀、审查噪声增加、后续变更冲突概率提升。
  - 若不统一测试依赖策略（安装依赖或可注入 mock 边界），CI 与本地可重复性不足。

### 达到 GREEN 的最小闭环条件
1. 从版本控制中移除 `backend/.site-packages` 全量文件，并补充 `.gitignore` 防回归。
2. 统一 `pydicom` 依赖策略：
   - 要么在测试环境显式安装；
   - 要么改造测试与解析器边界，避免对外部模块导入的脆弱耦合。
3. 在同一执行环境下重跑上述 3 组测试并保留可复核结果。

### 建议下一状态
- `READY_FOR_PHASE2` → **暂缓**
- 建议保持 `DONE_WITH_CONCERNS`，完成以上闭环后再升至 `READY_FOR_PHASE2`。
