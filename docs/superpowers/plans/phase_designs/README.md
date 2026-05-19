# Batch 7 + 8 三阶段详细设计

**文档版本**: v1.0
**创建日期**: 2026-05-19
**范围**: DICOM Ingestion Batch 7 + 8 (Local/NAS Folder Ingestion + Product Surface)

---

## 设计文档清单

| Phase | 文档 | 内容 | 依赖 |
|-------|-----|------|-----|
| Phase 1 | [phase1_foundation_design.md](./phase1_foundation_design.md) | 基础稳定：7G+7A+7B+7C | 无 |
| Phase 2 | [phase2_ingestion_pipeline_design.md](./phase2_ingestion_pipeline_design.md) | 摄入管道：7D+7E+7F | Phase 1 |
| Phase 3 | [phase3_product_surface_design.md](./phase3_product_surface_design.md) | 产品表面：8A-8F | Phase 2 |

---

## 快速导航

### Phase 1: 基础稳定
- **7G**: Binding Vocabulary Cleanup - 术语统一与清理
- **7A**: Parser Seam + Tag Schema - 可扩展解析框架
- **7B**: Dual Storage Backend - 双存储模式实现
- **7C**: Local/NAS Path Generator - 层级路径生成

### Phase 2: 摄入管道
- **7D**: Folder Ingest API + Source Abstraction - 摄入源抽象
- **7E**: Async Parse Worker + State Machine - 异步工作器与状态机
- **7F**: Ingest Report + Conflict UI - 报告生成与冲突管理

### Phase 3: 产品表面
- **8A**: Ingest Job API - 摄入作业管理接口
- **8B**: Adapter Layer - IngestSource + Storage 适配器契约
- **8C**: Workflow API - 多源输入支持
- **8D**: Review Workflow - 审查工作流集成
- **8E**: Platform Binding - Series/Study/Patient 绑定
- **8F**: CLI Admin Tools - 管理命令行工具
- **8G**: Auth/Perms - 认证与权限

> **版本对齐说明 (2026-05-19)**: 8A 统一为 Ingest Job API，与评审文档保持一致

---

## 决策实施速查表

所有CEO审查决策在设计中的实施位置：

| 决策 | 描述 | 实施文档 | 代码位置 |
|-----|------|---------|---------|
| **Gap-1** | 路径长度限制 | Phase 1 | `LocalNASStorageBackend._ensure_path_length()` |
| **Gap-1** | 幂等性策略 | Phase 2 | `TaskStateManager.claim_task()` - version乐观锁 |
| **Gap-2** | Saga模式事务 | Phase 2 | `SagaCoordinator` 类 |
| **Gap-2** | CANCELLED状态 | Phase 2 | `TaskStateManager.request_cancellation()` |
| **Gap-3** | 指数退避+最大年龄 | Phase 2 | `TaskStateManager.fail_task()` |
| **Gap-4** | Schema版本管理 | Phase 1 | `SchemaManager.mark_stale_projections()` |
| **Gap-5** | OOM流式处理 | Phase 1 | `ConfigurableDicomParser.parse()` - `stop_before_pixels=True` |
| **Gap-6** | 指纹去重 | Phase 2 | `IngestJobScheduler.create_job()` - source_fingerprint |
| **Gap-7** | CLI服务账户Token | Phase 3 | `get_authenticated_client()` |
| **Gap-8** | MeasUID提取器 | Phase 1 | `SiemensMeasUIDExtractor` + `UIHMeasUIDExtractor` |

---

## 实施建议顺序

### 第1周：Phase 1 基础设施
1. 7G: 术语清理（1天）
2. 7A: Tag Schema + Parser Seam（3天）
3. 7B: 对象存储后端（2天）

### 第2周：Phase 1 完成
4. 7C: 路径生成器（2天）
5. 7B: 本地/NAS后端（2天）
6. 集成测试（1天）

### 第3周：Phase 2 摄入管道
7. 7D: Source抽象 + API（3天）
8. 7E: 状态机 + 任务管理（2天）

### 第4周：Phase 2 完成
9. 7E: 解析工作器实现（3天）
10. 7F: 报告生成（1天）
11. 冲突管理UI（1天）

### 第5周：Phase 3 适配器
12. 8A: 适配器层（3天）
13. 8B: Workflow API（2天）

### 第6周：Phase 3 完成
14. 8C: 审查工作流（2天）
15. 8D: 平台绑定（1天）
16. 8E: CLI工具（2天）
17. 8F: 认证权限（1天）

### 第7-8周：集成测试与优化
- 端到端测试
- 性能优化
- 文档完善

---

## 关键API端点汇总

### 摄入API
```
POST /api/v1/ingest/folder      # 文件夹摄入
POST /api/v1/ingest/zip         # ZIP摄入
POST /api/v1/ingest/manifest    # 清单摄入
GET  /api/v1/ingest/jobs/{id}   # 作业状态
POST /api/v1/ingest/jobs/{id}/cancel  # 取消作业
```

### 查询API
```
GET /api/v1/series          # Series列表
GET /api/v1/studies         # Study列表
GET /api/v1/patients        # Patient列表
GET /api/v1/series/{uid}/files  # 文件列表
```

### 冲突API
```
GET  /api/v1/conflicts              # 冲突列表
GET  /api/v1/conflicts/{id}           # 冲突详情
POST /api/v1/conflicts/{id}/resolve  # 解决冲突
GET  /api/v1/conflicts/{id}/preview  # 预览解决
```

---

## CLI命令汇总

```bash
# 作业管理
dicom-ingest job list --status=completed --limit=20
dicom-ingest job show <job_id>
dicom-ingest job retry <job_id>
dicom-ingest job cancel <job_id>

# 冲突管理
dicom-ingest conflict list --status=detected
dicom-ingest conflict show <conflict_id>
dicom-ingest conflict resolve <conflict_id> --strategy=merge

# 存储查询
dicom-ingest storage locate <series_uid>
```

---

## 架构约束

1. **存储路径限制** (Gap-1): 路径长度超过4096字符时自动使用哈希缩短
2. **Schema兼容性** (Gap-4): 主版本变更时标记所有投影为陈旧
3. **大文件处理** (Gap-5): 大于512MB文件使用流式解析，内存占用<200MB
4. **作业去重** (Gap-6): 5分钟内相同源+actor的作业自动去重
5. **事务一致性** (Gap-2): 冲突解决使用Saga模式，失败时自动补偿

---

**状态**: 设计完成，等待实施开始
