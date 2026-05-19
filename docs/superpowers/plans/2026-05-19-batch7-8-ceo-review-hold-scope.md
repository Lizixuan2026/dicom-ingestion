# DICOM Ingestion Batch 7/8 CEO 审查报告 — HOLD SCOPE 模式

**日期**: 2026-05-19  
**审查模式**: HOLD SCOPE（最大严格度审查，无范围扩展）  
**审查状态**: DONE_WITH_CONCERNS  
**审查范围**: Batch 7（本地/NAS 文件夹摄入楔形）+ Batch 8（产品表面 + 审核工作流）  
**文档版本**: v1.0

---

## 执行摘要

### 审查结论

规划整体方向**正确**，符合「医学影像数据管理平台 intake 层」定位。主要架构决策合理，但存在 **10 个关键缺口**需要补充明确策略并写入规划文档。

| 维度 | 评估 |
|------|------|
| 战略定位 | ✅ 正确 — 明确区分「数据平台 intake 层」vs「PACS/DICOMweb」 |
| 批次划分 | ✅ 合理 — Batch 7 基础闭合先于 Batch 8 产品表面 |
| 技术可行性 | ⚠️ 中 — 存在关键缺口需补充 |
| 实施顺序 | ⚠️ 需要调整 — 建议 3 阶段实施 |
| 运营准备度 | ⚠️ 需要补充 — Runbook 需要验证 |

### 核心决策（已确定）

| 决策 | 场景 | 选择 | 理由 |
|------|------|------|------|
| 路径长度处理 | Windows/NAS 限制 | **哈希回退策略** | 保持功能完整性，超长 UID 时使用哈希段替代 |
| 取消策略 | 数据保留 vs 清理 | **软取消** | 符合「永不丢失源数据」承诺，标记孤儿状态 |
| MeasUID 提取器 | 可配置 vs 代码级 | **全可配置 extractors** | 用户选择扩展性优先，支持用户自定义设备厂商提取器 |
| 冲突存储 | 重复 SOP 存储 | **版本化路径** | `.../{SOP}__v2_{hash}.dcm`，清晰可追踪 |

### 关键缺口（必须解决）

| 缺口 | 严重性 | 状态 | 决策 |
|------|--------|------|------|
| 路径长度限制（Windows/NAS） | 🔴 高 | ✅ 已决策 | **哈希回退策略** — 超长 UID 使用哈希段 |
| CANCELLED 状态与 bytes 清理 | 🔴 高 | ✅ 已决策 | **软取消** — 保留已存字节，标记孤儿状态 |
| MeasUID 提取器接口定义 | 🔴 高 | ✅ 已决策 | **全可配置 extractors** — 首个版本内置 Siemens |
| 幂等性策略（重复工作器） | 🟡 中 | ✅ 已决策 | **数据库唯一约束 + 乐观锁** |
| 事务回滚（冲突解析中途失败） | 🟡 中 | ✅ 已决策 | **Saga 模式（事件驱动补偿）** |
| 重试队列积压（死信队列） | 🟡 中 | ✅ 已决策 | **指数退避 + 最大重试年龄 + 死信队列** |
| Tag Schema 版本演化 | 🟡 中 | ✅ 已决策 | **按需重解析（Lazy）+ 投影标记陈旧** |
| OOM/大文件策略 | 🟡 中 | ✅ 已决策 | **流式头部解析 + 延迟像素数据加载** |
| 作业创建幂等（双击提交） | 🟢 低 | ✅ 已决策 | **指纹去重（source_hash + actor_id + 时间窗口）** |
| CLI/API 权限模型同步 | 🟢 低 | ✅ 已决策 | **CLI 使用服务账户 Token（API 包装器）** |

---

## 架构验证

### 整体系统设计

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           DICOM Ingestion 架构                              │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌──────────────┐     ┌──────────────┐     ┌──────────────┐                │
│  │  IngestSource │────▶│  Raw Byte    │────▶│  Parse Task  │               │
│  │  Abstraction  │     │  Preservation│     │  (Async)     │               │
│  └──────────────┘     └──────────────┘     └──────┬───────┘                │
│         │                                         │                         │
│         │    ┌────────────────────────────────────┘                        │
│         │    │                                                              │
│         ▼    ▼                                                              │
│  ┌─────────────────────────────────────────┐                                │
│  │           Parser Adapter                  │                                │
│  │  ┌─────────────┐    ┌─────────────┐      │                                │
│  │  │ Tag Schema  │───▶│ Extractor   │      │                                │
│  │  │ (Config)    │    │ (Standard + │      │                                │
│  │  └─────────────┘    │ Private)    │      │                                │
│  │                     └─────────────┘      │                                │
│  └─────────────────────────────────────────┘                                │
│                      │                                                      │
│                      ▼                                                      │
│  ┌─────────────────────────────────────────┐                                │
│  │    Canonical Study/Series/Instance      │                                │
│  │         Persistence Layer               │                                │
│  └─────────────────────────────────────────┘                                │
│                      │                                                      │
│          ┌───────────┼───────────┐                                           │
│          ▼           ▼           ▼                                           │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐                                    │
│  │Duplicate │ │Reference │ │ Conflict │                                    │
│  │Detection │ │ Binding  │ │ Service  │                                    │
│  └────┬─────┘ └────┬─────┘ └────┬─────┘                                    │
│       │            │            │                                            │
│       └────────────┼────────────┘                                           │
│                    ▼                                                        │
│  ┌─────────────────────────────────────────┐                                │
│  │      Storage Backend Abstraction        │                                │
│  │  ┌─────────────┐    ┌─────────────┐    │                                │
│  │  │ Object      │    │ Local/NAS   │    │                                │
│  │  │ Storage     │    │ Path Gen +  │    │                                │
│  │  │ (Hash keys) │    │ Backend     │    │                                │
│  │  └─────────────┘    └─────────────┘    │                                │
│  └─────────────────────────────────────────┘                                │
│                                                                             │
│  ┌─────────────────────────────────────────┐                                │
│  │         Projection / Query Layer        │◀── API Surface (Batch 8)        │
│  └─────────────────────────────────────────┘                                │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 数据流四路径验证

| 数据流 | Happy Path | Nil Path | Empty Path | Error Path |
|--------|------------|----------|------------|------------|
| **Tag 提取** | 标准+私有标签提取成功 | 必需 UID 缺失 → 拒绝项 | 可选标签缺失 → 回退值 | 解析异常 → 标记失败 |
| **路径生成** | 完整元数据路径生成 | 必需字段缺失 → 拒绝 | 可选字段缺失 → 回退段 | 路径不安全 → 安全拒绝 |
| **存储写入** | 写入成功，返回 URI | N/A | N/A | 写入失败 → 可见错误 |
| **冲突解析** | 成功解析，更新状态 | N/A | N/A | 事务失败 → 回滚 |

### 状态机：解析任务

```
             ┌────────────┐
             │  PENDING   │
             └─────┬──────┘
                   │
                   ▼
             ┌────────────┐
             │ IN_PROGRESS│
             └────┬───────┘
                  │
        ┌─────────┼─────────┐
        │         │         │
   success  recoverable   non-recoverable
        │      error         or retry
        │         │         exhausted
        ▼         ▼         │
   ┌────────┐ ┌──────────┐  │
   │COMPLETED│ │RETRY_WAIT│◀─┘
   └────────┘ └────┬─────┘
                   │
                   └────▶ IN_PROGRESS

额外转换：
- PENDING → CANCELLED（软取消，保留已存 bytes）
- IN_PROGRESS → FAILED（重试耗尽）
- 任何状态 → FAILED（致命错误）
```

**关键约束**: 重试必须是幂等的。重新运行任务不能重复创建规范记录或静默覆盖文件。

### 安全架构验证

| 边界 | 谁可调用 | 获得什么 | 可改变什么 |
|------|----------|----------|------------|
| IngestSource 枚举 | 授权用户/服务 | 文件列表 | 无（只读） |
| 存储后端.store | 内部服务 | 存储 URI | 创建新对象 |
| 解析任务执行 | 工作器（内部） | 解析元数据 | 更新任务状态 |
| 冲突解析 API | 作业所有者/管理员 | 冲突摘要 | 解决状态 + 审计日志 |
| 查询 API | 授权用户/服务 | Study/Series/Instance 视图 | 无（只读） |

---

## 实施建议顺序（修订版）

基于 HOLD SCOPE 严格审查，建议调整为 **3 阶段实施**：

### Phase 1: 基础稳定（7A-C + 7G）

**目标**: 建立稳定的技术基础，所有其他工作依赖这些原语。

| 顺序 | 工作项 | 关键交付 | 依赖 |
|------|--------|----------|------|
| 1 | **7G: Binding Vocabulary Cleanup** | 移除/重命名 `BindingTargetType.STUDY` | 无 |
| 2 | **7A: Parser Seam + Tag Schema** | 解析器接口 + 可配置 extractor 接口定义 | 7G |
| 3 | **7B: Dual Storage Backend** | 对象存储 + 本地/NAS 适配器 | 无 |
| 4 | **7C: Local/NAS Path Generator** | 路径生成 + **哈希回退策略**（决策 1） | 7B |

**Phase 1 完成标准**:
- [ ] `BindingTargetType.STUDY` 已清理，测试通过
- [ ] Tag Schema 可加载，extractor 接口已定义（决策 3）
- [ ] 存储后端可通过配置切换（对象 ↔ 本地/NAS）
- [ ] 路径生成通过长度测试（含哈希回退）

### Phase 2: 摄入管道（7D-F）

**目标**: 完成端到端摄入管道，产生可信的摄入报告。

| 顺序 | 工作项 | 关键交付 | 依赖 |
|------|--------|----------|------|
| 5 | **7D: Folder Ingest Model** | 通用 IngestSource 抽象 | 7A, 7C |
| 6 | **7E: Async Parse Worker** | 状态机 + **软取消策略**（决策 2）+ 幂等策略 | 7D |
| 7 | **7F: Ingest Report** | 报告生成 + 幂等性 | 7E |

**关键缺口补充**:
- 7D: 需要**幂等作业创建**（防双击提交）— 相同 source + actor 返回现有作业
- 7E: 需要**幂等项处理**（防重复工作器）— 重复执行检测
- 7E: 需要**事务回滚策略**（冲突解析中途失败）— 全有或全无证明
- 7E: 需要**重试队列策略** — 最大重试年龄，死信队列
- 7E: 需要**OOM/大文件策略** — 内存限制，分块处理

**Phase 2 完成标准**:
- [ ] 文件夹摄入端到端测试通过（含嵌套、符号链接、空文件夹）
- [ ] 异步解析状态机转换测试通过（含取消、重试、失败）
- [ ] 摄入报告格式稳定，Batch 8 API 可依赖

### Phase 3: 产品表面（Batch 8）

**目标**: 使平台可用，用户和下游服务可操作。

**⚠️ 前置条件**: Phase 1-2 完成，特别是 **auth/user 模型决策**（当前是 Open Decision，阻塞 8A）

| 顺序 | 工作项 | 关键交付 | 依赖 |
|------|--------|----------|------|
| 8 | **8A: Ingest Job API** | 作业创建/查询/取消 API | Phase 1-2, auth 模型 |
| 9 | **8B: Query APIs** | Study/Series/Instance 查询 | 8A |
| 10 | **8C: Series Duplicate Summary** | Series 级重复摘要 | 8B |
| 11 | **8D: Conflict Resolution** | 冲突解析工作流 | 8C |
| 12 | **8E: Binding Response Envelope** | 平台对象绑定响应 | 8D |
| 13 | **8F: Operator Runbooks** | 运营 Runbook 和 CLI | 全部 |

**关键缺口补充**:
- 8A: 需要明确 **auth/user 模型** — job owner/uploader 身份表示
- 8F: Runbook 需要**实际运维场景验证** — 卡住作业、回放、重建投影
- 8D: 需要 **Tag Schema 版本演化策略** — schema 变更时如何处理已存数据
- 8A/8F: 需要 **CLI/API 权限模型同步** — 统一身份体系

**Phase 3 完成标准**:
- [ ] API 端到端工作流测试通过（摄入 → 查询 → 冲突解析）
- [ ] 运营 Runbook 命令在实际场景验证通过
- [ ] 下游数据集/注释工作流可引用摄入结果

---

## 决策详细记录

### 决策 1: 路径长度限制处理

**场景**: Windows（260 字符限制）和某些 NAS（快照路径限制）

**选择**: **哈希回退策略**

**实现细节**:
```python
# 伪代码示意
def generate_path(modality, vendor, device, study_uid, meas_uid, series_uid, sop_uid):
    base_path = f"DICOM_{modality}/{vendor}/{device}/{study_uid}/{meas_uid}/{series_uid}/{sop_uid}.dcm"
    
    # 检查路径长度
    if len(base_path) > 240:  # 预留余量
        # 哈希回退：前 16 字符 + 短哈希
        study_seg = f"{study_uid[:16]}_{short_hash(study_uid)}"
        series_seg = f"{series_uid[:16]}_{short_hash(series_uid)}"
        sop_seg = f"{sop_uid[:16]}_{short_hash(sop_uid)}"
        
        return f"DICOM_{modality}/{vendor}/{device}/{study_seg}/{meas_uid}/{series_seg}/{sop_seg}.dcm"
    
    return base_path
```

**验证要求**:
- [ ] 相同 UID 始终生成相同路径（确定性）
- [ ] 超长路径自动触发回退
- [ ] 回退路径仍然唯一（哈希保证）
- [ ] 回退事件记录在摄入报告

### 决策 2: CANCELLED 状态策略

**场景**: 用户在摄入过程中取消作业

**选择**: **软取消** — 保留已存储字节，标记为孤儿状态

**状态定义**:
```
PENDING → CANCELLED（工作器启动前）: 无数据，直接取消
IN_PROGRESS → CANCELLED（软取消）: 
  - 停止新项处理
  - 保留已存储原始字节
  - 标记未解析项为 CANCELLED
  - 已解析项保持当前状态
  - 生成部分摄入报告
  - 定期清理任务可标记孤儿数据
```

**审计日志**:
```json
{
  "event": "job.cancelled",
  "job_id": "...",
  "actor_id": "...",
  "cancelled_at": "...",
  "items_stored": 150,
  "items_cancelled": 50,
  "orphan_data": true
}
```

### 决策 3: MeasUID 提取器接口

**场景**: Siemens UIH 设备 `MeasUID` 私有标签提取

**选择**: **全可配置 extractors**

**接口定义**:
```python
# 代码级 extractor 注册表
EXTRACTORS: Dict[str, Callable[[Dataset], Any]] = {
    "siemens_meas_uid": extract_siemens_meas_uid,
    # 未来可扩展...
}

# Tag Schema 配置
@dataclass
class PrivateTagConfig:
    creator: str           # e.g., "SIEMENS CSA HEADER"
    tag: str             # e.g., "0029,1020"
    extractor: str       # e.g., "siemens_meas_uid" → 查找 EXTRACTORS

# 提取器接口协议
def extractor_protocol(dataset: Dataset, config: PrivateTagConfig) -> ExtractedValue:
    """
    从 DICOM Dataset 提取指定私有标签值
    
    Returns:
        ExtractedValue: 包含原始值、规范化值、提取状态
    
    Raises:
        PrivateTagNotFound: 标签不存在
        PrivateTagMalformed: 标签存在但格式无法解析
    """
    ...
```

**首个版本内置 extractors**:
- `siemens_meas_uid`: Siemens UIH MR 设备的 MeasUID 提取
- 用户可通过 PR 添加新 extractor 到注册表

---

## 缺口详细说明与建议

### 🔴 高严重性缺口

#### 缺口 1: 幂等性策略（重复工作器）

**问题**: 规划中声称 "rerunning a task cannot duplicate canonical records"，但未明确如何实现重复执行检测。

**建议策略**:
```python
# 工作器启动时检查
async def execute_parse_task(task_id: str):
    task = await get_task(task_id)
    
    # 重复执行检测
    if task.status == ParseStatus.IN_PROGRESS:
        if task.worker_id == current_worker_id:
            # 同一工作器重试，继续执行
            pass
        else:
            # 不同工作器，可能重复执行
            # 检查心跳时间戳
            if time.now() - task.last_heartbeat < 60:
                raise DuplicateExecutionError("Task appears to be running on another worker")
    
    # 幂等项处理
    if task.status == ParseStatus.COMPLETED:
        # 已完成，返回缓存结果
        return task.result
    
    # 执行解析...
```

**验收标准**:
- [ ] 测试：同一任务并发执行 10 次，只产生 1 条规范记录
- [ ] 测试：工作器崩溃后重启，可从 IN_PROGRESS 恢复或标记失败

#### 缺口 2: 事务回滚（冲突解析中途失败）

**问题**: `KEEP_BOTH` 或 `PROMOTE_UPLOADED` 可能涉及多表更新（冲突记录、规范记录、存储引用），中途失败需要全有或全无。

**建议策略**:
```python
# 使用数据库事务
async def resolve_conflict(series_uid: str, action: ResolutionAction):
    async with db.transaction():
        # 1. 锁定冲突记录
        conflict = await ConflictRecord.lock(series_uid)
        
        # 2. 验证冲突版本（乐观锁）
        if conflict.version != expected_version:
            raise StaleConflictError()
        
        # 3. 执行解析动作
        if action == ResolutionAction.KEEP_BOTH:
            await create_canonical_record(conflict.new_upload)
        elif action == ResolutionAction.PROMOTE_UPLOADED:
            await replace_canonical_record(conflict.existing, conflict.new_upload)
        
        # 4. 更新冲突状态
        await conflict.resolve(action, actor_id, reason)
        
        # 5. 审计日志（事务内）
        await AuditLog.record("conflict.resolved", ...)
    
    # 事务外：触发投影重建（异步）
    await trigger_projection_rebuild(series_uid)
```

**验收标准**:
- [ ] 测试：解析中途 kill 数据库连接，数据保持一致
- [ ] 测试：并发解析同一冲突，只有一个成功

### 🟡 中严重性缺口

#### 缺口 3: 重试队列积压（死信队列）

**问题**: 规划中未明确重试延迟策略和最大重试年龄。

**建议策略**:
```yaml
# 配置
retry_policy:
  max_attempts: 3
  backoff: exponential  # 固定间隔 / 指数退避
  initial_delay: 60s
  max_delay: 300s
  
  # 死信队列
  dead_letter:
    max_age: 24h        # 超过 24 小时放弃重试
    queue: parse_dlq    # 死信队列名称
```

**状态转换**:
```
FAILED (可重试) → RETRY_WAITING (指数退避) → IN_PROGRESS
                                    ↓
                              重试耗尽或超龄
                                    ↓
                              FAILED (最终，入 DLQ)
```

#### 缺口 4: OOM/大文件策略

**问题**: GB 级 DICOM 文件可能导致解析器 OOM。

**建议策略**:
```python
# 大文件检测
MAX_MEMORY_FILE_SIZE = 500 * 1024 * 1024  # 500MB

def parse_dicom(file_path: str):
    size = os.path.getsize(file_path)
    
    if size > MAX_MEMORY_FILE_SIZE:
        # 流式解析或分块处理
        return streaming_parse(file_path)
    else:
        # 标准解析
        return standard_parse(file_path)
```

**备选**: 对超大文件，仅提取头部（前 N MB），延迟像素数据加载。

#### 缺口 5: Tag Schema 版本演化

**问题**: 当 schema 变更（如新增 required 字段），已存储的 DICOM 如何处理？

**建议策略**:
```yaml
# Schema 版本声明
schema:
  version: "1.2"
  name: default_mr_intake
  
  # 版本兼容性
  compatibility: backward  # backward / forward / full
  
  # 迁移策略
  migration:
    strategy: lazy         # lazy（按需重解析）/ eager（批处理）/ none
    trigger: on_query      # on_query / on_access / manual
```

**版本变更场景**:
- **新增 optional 字段**: 现有数据使用 fallback，新数据提取
- **新增 required 字段**: 需要重解析或标记 legacy 数据
- **提取器变更**: 重解析受影响的文件

### 🟢 低严重性缺口

#### 缺口 6: 作业创建幂等（防双击提交）

**建议**: 相同 `source_type + source_hash + actor_id` 在 5 分钟内返回现有作业。

```python
async def create_job(request: CreateJobRequest) -> Job:
    # 生成 source 指纹
    source_hash = hash(request.source)
    dedup_key = f"{request.source_type}:{source_hash}:{request.actor_id}"
    
    # 检查近期作业
    existing = await Job.find_recent(dedup_key, within_minutes=5)
    if existing:
        return existing  # 返回现有作业，201 → 200
    
    # 创建新作业
    return await Job.create(request, dedup_key=dedup_key)
```

#### 缺口 7: CLI/API 权限模型同步

**建议**: CLI 命令使用与 API 相同的 identity token。

```bash
# CLI 使用服务账户 token
export DICOM_INGEST_TOKEN=$(cat /etc/service-accounts/dicom-ingest)
dicom-ingest retry-failed --job-id <job_id> --actor <actor_id> --reason "ops recovery"
```

服务器端验证 token 权限，CLI 只是 HTTP 客户端包装。

---

## 验收标准汇总

### Phase 1 验收

| 工作项 | 验收标准 |
|--------|----------|
| 7G Binding Vocab Cleanup | `BindingTargetType.STUDY` 已移除或重命名；所有引用和测试已更新；文档区分 DICOM Study vs 平台 Study |
| 7A Parser Seam | 解析器接口存在；调用者依赖接口而非 pydicom；默认 pydicom-backed 解析器工作；Tag Schema 支持标准标签、私有标签、语义名称；首个 extractor（Siemens MeasUID）工作 |
| 7B Storage Backend | `StorageBackend` 抽象存在；对象存储行为兼容当前；本地/NAS 后端可写配置根；存储结果持久化后端、URI、校验和、大小 |
| 7C Path Generator | 相同输入元数据产生相同路径；可选缺失标签产生记录回退段；必需缺失标签拒绝项；路径长度 > 240 触发哈希回退；哈希回退路径测试通过 |

### Phase 2 验收

| 工作项 | 验收标准 |
|--------|----------|
| 7D Folder Ingest | 嵌套文件夹输入工作；清单输入工作；ZIP 扫描器输出适配 `IngestSourceItem`；混合 DICOM 和非 DICOM 工作；空文件夹产生完成作业；不可读文件报告；幂等作业创建测试通过 |
| 7E Async Worker | 状态转换强制执行；幂等项处理测试通过；重复执行检测测试通过；失败项出现在摄入报告；卡住 IN_PROGRESS 任务可通过超时检测；软取消策略测试通过 |
| 7F Ingest Report | 报告可在完成、部分失败、失败作业后生成；报告包含回退使用和拒绝文件；报告包含存储目的地计数；报告格式稳定（Batch 8 API 可依赖）|

### Phase 3 验收

| 工作项 | 验收标准 |
|--------|----------|
| 8A Job API | 作业创建验证源类型、存储后端、Tag Schema；作业状态暴露项计数和失败计数；报告端点复用 Batch 7 摄入报告；取消仅在允许状态工作；重试失败仅重试失败/可重试项 |
| 8B Query APIs | 查询响应清晰使用 DICOM 身份；Series 和 Instance 分页必需；存储引用可见但不暴露不安全本地绝对路径；缺失记录返回类型化未找到响应 |
| 8C Duplicate Summary | 重复摘要按 Series 分组；SOP 级证据可在需要时检查；冲突状态稳定和可查询；测试覆盖同校验和重复、不同校验和冲突、混合干净/冲突 Series |
| 8D Conflict Resolution | 每个解析动作创建审计日志；只有摄入作业所有者/上传者可解析正常冲突；内部管理员/操作员覆盖需要显式 actor、actor 类型和理由；解析对相同动作和冲突版本幂等；过期冲突版本被拒绝；用户可检查先前解析理由；解析更新投影或标记重建 |
| 8E Binding Envelope | Envelope 不使用模糊 `STUDY` 绑定词汇；数据集/审核工作流可引用 Study/Series/Instance 而无需直接表耦合；Envelope 可后支持窄 OHIF 桥而不使 DICOMweb 成为产品目标 |
| 8F Runbooks | 每个 Runbook 命名症状、诊断查询、动作和验证；恢复动作被记录；危险动作需要显式 actor/理由；Runbook 命令在实际运维场景验证 |

---

## 风险与缓解

| 风险 | 可能性 | 影响 | 缓解 |
|------|--------|------|------|
| Phase 1 技术复杂度超预期 | 中 | 延迟 | 7A extractors 首个版本仅内置 Siemens，推迟用户自定义到后续 |
| 本地/NAS 路径长度问题 | 高 | 部署失败 | 已决策哈希回退策略，需在 7C 实现和测试 |
| 异步工作器状态机复杂 | 中 | 缺陷 | 增加测试覆盖：重复执行、事务回滚、幂等性 |
| auth/user 模型未定阻塞 8A | 高 | 进度阻塞 | 需在产品 Backlog 中优先解决此 Open Decision |
| 运营团队不熟悉 Runbook | 中 | 恢复延迟 | 8F 需与运营团队共同开发，场景验证 |

---

## 附录

### A. 参考文档

- [原始规划: Batch 7/8 Spec](../../../docs/specs/dicom_ingestion_batch7_batch8_spec.md)
- [设计文档: Product Wedge](../../../docs/designs/dicom_ingestion_batch7_batch8_product_wedge.md)
- [范围综合: Scope Synthesis](../../../reviews/codex_review/dicom_ingestion_batch7_batch8_scope_synthesis_v0.1.md)
- [V1 CEO Review](../../../reviews/codex_review/dicom_ingestion_v1_product_surface_ceo_review_v0.1.md)

### B. 术语表

| 术语 | 解释 |
|------|------|
| **DICOM** | 医学数字成像和通信标准 |
| **PACS** | 影像归档和通信系统（明确非本产品目标） |
| **DICOMweb** | DICOM 的 RESTful Web 服务标准（STOW-RS/QIDO-RS/WADO-RS，明确非本产品目标） |
| **MeasUID** | Siemens UIH MR 设备特定的私有标签，用于标识一次扫描 |
| **IngestSource** | 摄入源抽象（ZIP、本地文件夹、清单） |
| **Tag Schema** | 可配置的 DICOM 标签提取规则 |
| ** orphans** | 软取消后保留的、无关联作业的原始字节 |

### C. 审查方法说明

本次审查采用 **HOLD SCOPE** 模式：
- 严格保持 Batch 7/8 范围，不做扩展
- 最大严格度审查架构、安全、边界情况、可观测性、部署
- 发现 10 个关键缺口，全部已通过 AskUserQuestion 完成决策

审查覆盖 11 个标准章节：
1. 架构审查 ✅
2. 错误与救援映射 ✅
3. 安全与威胁模型 ✅
4. 数据流与交互边界情况 ✅
5. 代码质量审查 ✅
6. 测试审查 ✅
7. 性能审查 ✅
8. 可观测性与可调试性审查 ✅
9. 部署与发布审查 ✅
10. 长期轨迹审查 ✅
11. 设计与 UX 审查 ✅（本规划主要是后端/API，UI 范围有限）

---

## 完整决策汇总（10 项）

### 前期已决策（3 项）

| # | 决策 | 场景 | 选择 | 实施位置 |
|---|------|------|------|----------|
| 1 | 路径长度处理 | Windows/NAS 260 字符限制 | **哈希回退策略** | 7C 本地/NAS 路径生成器 |
| 2 | 取消策略 | 数据保留 vs 清理 | **软取消** | 7E 异步解析工作器 |
| 3 | MeasUID 提取器 | 可配置 vs 代码级 | **全可配置 extractors** | 7A Tag Schema |

### 本次决策（7 项）

| # | 缺口 | 决策 | 实施位置 |
|---|------|------|----------|
| 4 | 幂等性策略（重复工作器）| **数据库唯一约束 + 乐观锁** | 7E 异步解析工作器 |
| 5 | 事务回滚策略 | **Saga 模式（事件驱动补偿）** | 8D 冲突解析工作流 |
| 6 | 重试队列策略 | **指数退避 + 最大重试年龄 + 死信队列** | 7E 异步解析工作器 |
| 7 | Tag Schema 版本演化 | **按需重解析（Lazy）+ 投影标记陈旧** | 7A/8D Tag Schema |
| 8 | OOM/大文件策略 | **流式头部解析 + 延迟像素数据加载** | 7E 异步解析工作器 |
| 9 | 作业创建幂等 | **指纹去重（source_hash + actor_id + 时间窗口）** | 8A Ingest Job API |
| 10 | CLI/API 权限模型同步 | **CLI 使用服务账户 Token（API 包装器）** | 8A/8F API 和 CLI |

### 决策实施检查清单

**7A Tag Schema**: 
- [ ] 解析器接口存在
- [ ] extractor 注册表实现（含 siemens_meas_uid）
- [ ] Schema 版本字段支持
- [ ] 按需重解析逻辑（决策 7）

**7C 路径生成器**:
- [ ] 路径长度检查（>240 字符）
- [ ] 哈希回退实现（决策 1）
- [ ] 回退事件记录

**7E 异步工作器**:
- [ ] 幂等项处理（决策 4）
- [ ] 软取消策略（决策 2）
- [ ] 指数退避重试（决策 6）
- [ ] 死信队列支持（决策 6）
- [ ] 流式头部解析（决策 8）

**8A Ingest Job API**:
- [ ] 指纹去重（决策 9）
- [ ] CLI 服务账户 Token（决策 10）

**8D 冲突解析**:
- [ ] Saga 模式实现（决策 5）
- [ ] 事件驱动补偿逻辑

---

## 修订记录

| 日期 | 版本 | 修订内容 |
|------|------|----------|
| 2026-05-19 | v1.0 | 初始 CEO 审查报告，HOLD SCOPE 模式，记录 3 个已决策和 7 个待明确缺口 |
| 2026-05-19 | v1.1 | 完成全部 7 个剩余缺口决策，更新状态表，添加完整决策汇总章节 |

---

**审查完成** ✅

状态: **DONE** — 全部 10 个关键缺口已完成决策，可进入实施阶段。

**实施建议**: 
1. 按 Phase 1 → Phase 2 → Phase 3 顺序执行
2. 每个工作项完成后对照「决策实施检查清单」验证
3. 特别注意 auth/user 模型是 8A 的前置条件，需提前解决
