# DICOM 摄取服务问题记录

记录人：用户  
记录时间：2026-05-18  
项目：dicom-ingestion  

---

## 说明

本文档用于统一记录在 review DICOM 摄取服务过程中提出的问题。每个问题将按顺序记录，包含：
- 问题编号
- 问题内容
- 涉及的模块/文件
- 提问时间
- 答案/解答
- 状态（待回答 / 已解答 / 需跟进）

---

## 问题列表

| 编号 | 问题内容 | 涉及模块 | 提问时间 | 答案/解答 | 状态 |
|------|---------|---------|---------|-----------|------|
| Q1 | 请给我一步一步的解释下当前实现的功能，我是小白 | 整体架构 | 2026-05-18 18:01 | 已提供完整解释：1) 上传服务 2) 扫描服务 3) DICOM解析 4) 摄取作业跟踪 5) 重复检测 6) 绑定策略 7) 对象存储 | ✅ 已解答 |
| Q2 | 用户上传不支持文件夹吗？ | upload_service.py, scan_service.py | 2026-05-18 18:08 | 不支持直接上传文件夹。当前只支持：1) 单个文件 2) ZIP压缩包。scan()方法中只有is_zip判断，没有处理目录的逻辑。用户提出需求：希望支持文件夹上传 | 📝 需求待实现 |
| Q3 | 关于DICOM tag解析的需求总结是否准确？（配置化标签、可替换解析器、异步解析） | dicom_parser.py | 2026-05-18 18:26 | **确认准确**。当前代码验证：1) 私有标签确实盲存（PrivateTag只有raw_value） 2) pydicom硬编码（直接import和调用） 3) 同步解析（无async）。用户提出的三个核心需求合理且需要实现 | ✅ 已确认/📝 需架构升级 |
| Q4 | 引入Celery异步服务架构（保持组件分离、Worker状态管理、幂等性、重试机制） | dicom_parser.py, ingestion_item.py, 新增 celery_tasks 模块 | 2026-05-18 18:41 | **确认可行**。现状：IN_PROGRESS状态已定义但未使用，解析是同步的。需求合理：1) DicomParser保持纯工具 2) Celery Worker管理状态流转 3) 需要幂等检查 4) max_retries自动重试 | ✅ 已确认/📝 需架构升级 |
| Q5 | 重复检测报告应按Series维度聚合，而非逐个列出SOP（批量重复时用户体验优化） | duplicate_detection.py, duplicate_finding.py, terminal_report.py | 2026-05-18 19:07 | **确认需求**。现状：1) 检测逐个检查observation 2) DuplicateFindingSummary只有by_sop_instance_uid 3) 报告层只有duplicate_findings计数。需要：按SeriesInstanceUID聚合的重复检测摘要/告警 | ✅ 已确认/📝 需UX优化 |
| Q6 | 绑定目标类型中"STUDY"概念容易与dicom_studies表混淆，建议去掉 | binding_policy.py | 2026-05-18 19:23 | **确认变更**。Q6解释了STUDY绑定目标是指"平台的Study对象（业务概念）"，但用户认为这个概念容易与dicom_studies表（DICOM元数据）混淆。同意去掉STUDY作为BindingTargetType，后续如果需要平台业务层的Study绑定，可以用其他命名（如RESEARCH_STUDY/PROJECT_STUDY） | 📝 变更待执行 |
| Q7 | 支持双模式存储架构（对象存储+本地/公盘存储），本地存储需按DICOM Tag层级组织目录结构 | raw_object_store.py, dicom_parser.py, storage/ | 2026-05-18 19:36 | **需求已理解**。用户提供了完整的存储结构设计文档（016_data_storage_structure_design.md），包含：1) 双模式存储（对象存储扁平化 vs 本地存储层级化） 2) 本地存储路径依赖DICOM Tag（厂商/设备/StudyUID/MeasUID/SeriesUID） 3) 多模态数据支持 4) Annotation存储结构。与REQ-002强相关（需要提取Private tag如MeasUID） | ✅ 已理解/📝 需架构设计 |
| Q8 | 当前上传是否支持分块上传？对于大DICOM文件需要分块上传能力 | upload_service.py, scan_service.py, 前端upload组件 | 2026-05-18 19:44 | **确认现状**：当前使用multipart/form-data一次性完整上传，不支持分块上传。**用户核心诉求**：支持分块上传功能，DICOM文件通常100MB-1GB，需要：1) 前端分块切片 2) 并发上传 3) 进度可见 4) 断点续传 5) 后端组装。**推荐方案**：前端分块（File.slice）+ 后端组装（临时存储+校验+合并） | ✅ 已理解/📝 需求待实现 |

---

## 按模块分类

### 1. 上传与接收 (upload/)
- Q2: 不支持文件夹上传（只支持单文件或ZIP）
- Q8: 不支持分块上传（需要支持大文件分块、断点续传）
- REQ-006: 分块上传功能（前端分块+后端组装）

### 2. 扫描与安全 (scanner/)
- Q2: 扫描服务只处理ZIP或单文件，无目录处理逻辑

### 3. 解析与处理 (parser/)
- Q3: DICOM解析器架构升级需求（配置化标签、可替换解析器、异步解析）
- Q4: Celery异步解析服务需求（Worker状态管理、幂等性、重试机制）
- REQ-002: 解析器架构升级（标签配置、异步解析、插件化）
- REQ-003: Celery异步解析服务（Worker、幂等、重试、IN_PROGRESS监控）

### 4. 重复检测 (detection/)
- Q5: 重复检测报告应按Series维度聚合（批量重复用户体验优化）
- REQ-004: Series维度重复检测聚合报告

### 5. 绑定策略 (binding/)
- Q6: 去掉STUDY作为BindingTargetType（避免与dicom_studies表概念混淆）
- CHANGE-001: 从BindingTargetType枚举中移除STUDY

### 6. 存储 (storage/)
- Q7: 双模式存储架构设计（对象存储+本地/公盘存储）
- REQ-005: 双模式存储 + 层级化路径（依赖DICOM Tag提取）

### 7. 整体架构/流程
- Q1: 整体功能解释

---

## 需求/待办清单

| 编号 | 需求描述 | 涉及模块 | 优先级 | 预计改动点 | 状态 |
|------|---------|---------|--------|-----------|------|
| REQ-001 | 支持文件夹直接上传 | scan_service.py, upload_service.py | 待评估 | 1) UploadService增加目录处理逻辑 2) ScanService增加_is_directory判断和_scan_directory方法 3) 需要处理递归遍历、路径安全、大文件列表内存占用等问题 | 📝 已记录 |
| REQ-002 | DICOM解析器架构升级（配置化标签定义、可替换解析器、异步解析） | dicom_parser.py, 新增 tag_schema, parser_interface, async_parser 模块 | 高 | 1) 抽象解析器接口（ParserInterface）支持多后端 2) 标签配置系统（TagSchema：tag→含义→处理器） 3) 异步解析任务队列 4) 标签处理器注册机制（支持解密、自定义逻辑） 5) 私有标签语义化 | 📝 已记录 |
| REQ-003 | Celery异步解析服务（Worker状态管理、幂等性、自动重试、IN_PROGRESS监控） | dicom_parser.py, ingestion_item.py, 新增 celery_tasks, parse_worker 模块 | 高 | 1) IngestionItem增加mark_parsing_in_progress()方法 2) 创建Celery任务ParseDicomTask（幂等检查、状态流转、异常处理） 3) DicomParser保持纯工具性质 4) 监控接口：查询in_progress任务数量 5) 与REQ-002配合：异步执行解析器接口 | 📝 已记录 |
| REQ-004 | Series维度重复检测聚合报告（批量重复用户体验优化） | duplicate_detection.py, duplicate_finding.py, terminal_report.py, 新增 duplicate_alert_service | 中 | 1) DuplicateFindingSummary增加by_series_instance_uid聚合 2) 新增SeriesDuplicateSummary（Series级别重复摘要） 3) 批量重复检测时生成聚合告警而非单个SOP告警 4) 终端报告增加Series重复维度统计 5) 支持配置阈值（如Series内超过N个重复才聚合告警） | 📝 已记录 |
| CHANGE-001 | 从BindingTargetType中移除STUDY枚举值 | binding_policy.py:24-30 | 低 | 1) 从BindingTargetType枚举中删除STUDY = "study" 2) 检查并更新任何引用STUDY类型的代码 3) 如果未来需要平台业务层Study绑定，使用更清晰的命名如RESEARCH_STUDY或PROJECT_STUDY | 📝 变更待执行 |
| REQ-005 | 双模式存储架构 + 层级化本地存储路径（支持对象存储和本地/公盘存储，本地存储按DICOM Tag层级组织） | raw_object_store.py, 新增 storage_backend/, path_generator/, multimodal/ 模块 | 高 | 1) 抽象存储后端接口（StorageBackend）支持对象存储和本地存储 2) 路径生成策略（PathGenerator）：对象存储用content_hash扁平化，本地存储用DICOM Tag层级化 3) DICOM Tag提取增强：需要提取厂商、设备名、MeasUID（Private tag） 4) 多模态数据分流：DICOM/RawData/IMAGE/TEXT/DOCUMENT/AUDIO/VIDEO/STRUCTURED 5) Annotation存储结构 6) 与REQ-002强相关：需要Private tag解析能力 | 📝 已记录 |
| REQ-006 | 分块上传功能（支持大DICOM文件上传、进度可见、断点续传） | upload_service.py, 新增 chunk_upload/, frontend_upload组件, assembly_service | 高 | 1) 前端分块：File.slice()切分文件（建议5MB/块），并发上传 2) 后端分块接收：/upload/chunk接口，临时存储分块（Redis/文件系统） 3) 分块校验：每块校验MD5/SHA256 4) 分块组装：所有分块到齐后组装完整文件 5) 断点续传：记录上传进度，失败只重传失败分块 6) 与REQ-001配合：文件夹上传大文件需要分块 | 📝 已记录 |

### REQ-001 实现建议

如果要支持文件夹上传，需要修改以下代码：

**1. UploadService.accept() 方法**
- 增加对本地目录路径的支持
- 将目录打包成临时ZIP或逐个处理文件

**2. ScanService.scan() 方法**
- 在 `is_zip` 判断前增加 `is_directory` 判断
- 新增 `_scan_directory()` 方法递归遍历目录
- 复用现有的文件分类逻辑

**3. 需要注意的问题**
- 路径安全：防止路径遍历攻击
- 符号链接处理：防止循环链接
- 大目录性能：大量文件时的内存和性能问题
- 跨平台兼容：Windows/Unix路径差异

### REQ-002 实现建议（DICOM解析器架构升级）

**1. 抽象解析器接口**
```python
class ParserInterface(ABC):
    @abstractmethod
    async def parse_header(self, item_bytes: bytes, context: ParseContext) -> ParsedDicomHeader:
        pass
```

**2. 标签配置系统（TagSchema）**
```python
@dataclass
class TagDefinition:
    tag_address: str           # "0010,0010"
    name: str                  # "PatientName"
    meaning: str               # 语义描述
    value_processor: Optional[Callable]  # 解密/转换函数
    is_private: bool = False
```

**3. 异步解析流程**
```python
# 当前：同步调用
header = parser.parse_header(bytes)

# 目标：异步任务
parse_task = await parse_queue.submit(bytes, tag_schema)
header = await parse_task.result()
```

**4. 标签处理器注册**
```python
# 支持自定义处理器（解密、自定义逻辑）
tag_registry.register_processor("0019,xx01", my_decrypt_func)
```

**5. 向后兼容**
- 保留现有 DicomParser 作为默认实现
- 通过配置开关启用新架构

### REQ-003 实现建议（Celery异步解析服务）

**1. IngestionItem 状态方法扩展**
```python
# ingestion_item.py 新增方法
def mark_parsing_in_progress(self) -> None:
    """标记解析进行中（Celery任务开始时调用）"""
    self.status_axes.parse_status = ItemStatusValue.IN_PROGRESS.value
    self.updated_at = datetime.utcnow()

# 现有方法 mark_parsed 保持不变（Celery任务结束时调用）
```

**2. Celery任务实现**
```python
# celery_tasks/parse_dicom_task.py
from celery import Task

class ParseDicomTask(Task):
    """
    Celery任务：异步解析DICOM文件
    
    职责：
    - 幂等性检查（已完成则跳过）
    - 状态流转：pending → in_progress → completed/failed
    - 异常处理和自动重试
    """
    max_retries = 3
    default_retry_delay = 60  # 1分钟后重试
    
    def run(self, item_id: int, raw_bytes_uri: str):
        # 1. 幂等性检查
        item = item_repository.get(item_id)
        if item.status_axes.parse_status == ItemStatusValue.COMPLETED.value:
            logger.info(f"Item {item_id} already parsed, skipping")
            return {"status": "skipped", "reason": "already_completed"}
        
        # 2. 状态→IN_PROGRESS
        item.mark_parsing_in_progress()
        item_repository.save(item)
        
        try:
            # 3. 调用纯工具DicomParser（无副作用）
            raw_bytes = object_store.get(raw_bytes_uri)
            header = dicom_parser.parse_header(raw_bytes)
            
            # 4. 状态→COMPLETED
            item.mark_parsed(success=True)
            item_repository.save(item)
            
            return {"status": "success", "header": header.to_dict()}
            
        except Exception as exc:
            # 5. 状态→FAILED，触发重试
            item.mark_parsed(success=False, error_code="ParseFailed", error_detail=str(exc))
            item_repository.save(item)
            
            # Celery自动重试
            raise self.retry(exc=exc, countdown=60 * (self.request.retries + 1))
```

**3. 监控接口**
```python
# monitoring/parse_monitor.py
class ParseMonitor:
    """监控解析任务状态"""
    
    def get_in_progress_count(self) -> int:
        """获取正在解析的任务数量"""
        return item_repository.count_by_status(
            parse_status=ItemStatusValue.IN_PROGRESS.value
        )
    
    def get_parse_queue_stats(self) -> dict:
        """获取解析队列统计"""
        return {
            "pending": item_repository.count_by_status("pending"),
            "in_progress": item_repository.count_by_status("in_progress"),
            "completed": item_repository.count_by_status("completed"),
            "failed": item_repository.count_by_status("failed"),
        }
```

**4. 架构关系**
```
┌─────────────────────────────────────────────────────────────┐
│                     Celery异步解析架构                         │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  ┌─────────────────┐     ┌──────────────────┐     ┌────────┐ │
│  │ IngestionItem   │────▶│ ParseDicomTask   │────▶│ Dicom  │ │
│  │ (状态管理)       │     │ (Celery Worker)  │     │ Parser │ │
│  │                 │◀────│                  │◀────│ (纯工具)│ │
│  │ - mark_in_      │     │ - 幂等检查       │     │        │ │
│  │   progress()    │     │ - 状态流转       │     │        │ │
│  │ - mark_parsed() │     │ - 重试机制       │     │        │ │
│  └─────────────────┘     └──────────────────┘     └────────┘ │
│           ▲                                               │
│           └───────────────────────────────────────────────┘
│                                                              │
│  与REQ-002的关系：                                             │
│  - REQ-002提供「解析器抽象接口」                               │
│  - REQ-003提供「异步执行框架」                                 │
│  - Celery任务可以调用任何实现了ParserInterface的解析器          │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

**5. 部署考虑**
- 需要Redis作为Celery broker
- Worker独立部署，可水平扩展
- 与主应用通过消息队列解耦

### REQ-004 实现建议（Series维度重复检测聚合报告）

**1. 现状问题**
```python
# duplicate_finding.py:175
by_sop_instance_uid: Dict[str, list]  # ← 只有SOP维度，没有Series维度

# terminal_report.py:116
duplicate_findings: int  # ← 只有总数，没有分组
```

**2. 新增Series维度聚合**
```python
# duplicate_finding.py 新增
@dataclass
class SeriesDuplicateSummary:
    """Series级别的重复检测摘要"""
    series_instance_uid: str
    study_instance_uid: str  # 关联的Study
    total_instances: int           # Series总instance数
    duplicate_count: int           # 重复instance数
    duplicate_rate: float          # 重复率（0-1）
    duplicate_sop_list: List[str]  # 重复的SOP列表
    first_upload_time: datetime    # 首次上传时间
    latest_upload_time: datetime   # 最新重复时间
    
    def is_significant(self, threshold: int = 5) -> bool:
        """是否达到聚合告警阈值（如超过5个重复）"""
        return self.duplicate_count >= threshold

# DuplicateFindingSummary 扩展
@dataclass
class DuplicateFindingSummary:
    # ... 原有字段
    by_sop_instance_uid: Dict[str, list]
    by_series_instance_uid: Dict[str, SeriesDuplicateSummary]  # ← 新增
```

**3. Series聚合服务**
```python
# services/detection/series_duplicate_aggregator.py
class SeriesDuplicateAggregator:
    """
    Series维度重复检测聚合器
    
    职责：
    - 收集单个observation的重复检测结果
    - 按SeriesInstanceUID聚合
    - 生成聚合告警/报告
    """
    
    def aggregate_by_series(
        self,
        job_id: int,
        findings: List[DicomDuplicateFinding]
    ) -> Dict[str, SeriesDuplicateSummary]:
        """
        将重复检测结果按Series聚合
        
        Args:
            job_id: 摄取作业ID
            findings: 所有重复检测结果
            
        Returns:
            Dict[SeriesInstanceUID, SeriesDuplicateSummary]
        """
        series_groups: Dict[str, List[DicomDuplicateFinding]] = defaultdict(list)
        
        # 按Series分组
        for finding in findings:
            series_uid = self._get_series_uid(finding)
            series_groups[series_uid].append(finding)
        
        # 生成Series摘要
        summaries = {}
        for series_uid, series_findings in series_groups.items():
            summary = self._create_series_summary(series_uid, series_findings)
            summaries[series_uid] = summary
            
        return summaries
    
    def generate_aggregated_alert(
        self,
        threshold: int = 5
    ) -> List[Dict]:
        """
        生成聚合告警（超过阈值的Series）
        
        Returns:
            聚合告警列表
            例如：[{"series_uid": "1.2.3...", "duplicate_count": 100, "message": "Series X 有100个instance重复"}]
        """
        alerts = []
        for series_uid, summary in self.summaries.items():
            if summary.is_significant(threshold):
                alerts.append({
                    "series_uid": series_uid,
                    "study_uid": summary.study_instance_uid,
                    "duplicate_count": summary.duplicate_count,
                    "duplicate_rate": f"{summary.duplicate_rate:.1%}",
                    "message": (
                        f"Series {series_uid[:20]}... "
                        f"有 {summary.duplicate_count} 个 instance 身份重复，"
                        f"建议检查此 Series 的上传"
                    ),
                    "severity": "warning" if summary.duplicate_rate < 0.5 else "critical"
                })
        return alerts
```

**4. 报告层集成**
```python
# terminal_report.py 扩展
@dataclass
class JobTerminalSummary:
    # ... 原有字段
    duplicate_findings: int
    series_with_duplicates: int  # ← 新增：有重复的Series数
    series_duplicate_breakdown: List[Dict]  # ← 新增：Series重复详情

class TerminalReportService:
    async def generate_job_report(self, job_id, items, duplicate_count, ...):
        # ... 原有逻辑
        
        # 新增：获取Series聚合信息
        series_summaries = series_aggregator.aggregate_by_series(job_id, findings)
        aggregated_alerts = series_aggregator.generate_aggregated_alert(threshold=5)
        
        summary = JobTerminalSummary(
            # ... 原有字段
            series_with_duplicates=len(series_summaries),
            series_duplicate_breakdown=[s.to_dict() for s in series_summaries.values()]
        )
        
        # 报告metadata增加聚合告警
        report.metadata["aggregated_alerts"] = aggregated_alerts
```

**5. 用户体验对比**

| 场景 | 当前体验 | 优化后体验 |
|-----|---------|-----------|
| 100个SOP重复 | 100条单独告警，淹没在列表中 | 1条聚合告警："Series X有100个instance重复，建议检查此Series的上传" |
| 定位问题 | 逐个查看SOP，不知道属于哪批数据 | 直接知道是某个Series的问题，按Series维度定位原始数据 |
| 批量处理 | 无法批量处理 | 可以按Series批量处理或批量忽略 |

### CHANGE-001 执行方案（移除STUDY绑定目标）

**1. 当前代码**
```python
# binding_policy.py:24-30
class BindingTargetType(str, Enum):
    ASSET = "asset"
    DATASET_SAMPLE = "dataset_sample"
    ANNOTATION = "annotation"
    PROJECT = "project"
    STUDY = "study"  # ← 需要移除
```

**2. 变更内容**
```python
# 变更后
class BindingTargetType(str, Enum):
    ASSET = "asset"               # 单个DICOM文件资源
    DATASET_SAMPLE = "dataset_sample"  # 数据集样本
    ANNOTATION = "annotation"     # 标注对象
    PROJECT = "project"           # 项目
    # STUDY 已移除：避免与dicom_studies表概念混淆
    # 如未来需要平台业务层Study概念，建议使用：
    # RESEARCH_STUDY = "research_study"  # 研究项目
    # PROJECT_GROUP = "project_group"    # 项目组
```

**3. 影响检查**
- [ ] 检查所有引用 `BindingTargetType.STUDY` 的代码
- [ ] 检查数据库中是否存在 `target_type = 'study'` 的记录
- [ ] 更新相关文档和注释

**4. 变更原因**
- STUDY 容易与 DICOM 标准中的 Study（存储在 dicom_studies 表）混淆
- 用户的业务场景中，DICOM Study 元数据已经足够，不需要额外的"平台 Study"绑定概念
- 如果未来确实需要业务层的 Study 概念，应该使用更清晰的命名

### REQ-005 实现建议（双模式存储架构 + 层级化本地存储）

**背景**：用户提供了完整的存储结构设计文档（`016_data_storage_structure_design.md`），需要同时支持对象存储（MinIO/S3，扁平化）和本地/公盘存储（层级化，便于人工浏览）。

**1. 存储后端抽象**
```python
# storage/backend_interface.py
from abc import ABC, abstractmethod
from enum import Enum

class StorageMode(str, Enum):
    OBJECT_STORAGE = "object_storage"  # MinIO/S3，扁平化
    LOCAL_STORAGE = "local_storage"    # 本地/公盘，层级化

class StorageBackend(ABC):
    """存储后端抽象接口"""
    
    @abstractmethod
    def put(self, data: bytes, path: str, metadata: dict = None) -> dict:
        """存储数据，返回存储位置信息"""
        pass
    
    @abstractmethod
    def get(self, path: str) -> bytes:
        """获取数据"""
        pass
    
    @abstractmethod
    def exists(self, path: str) -> bool:
        """检查路径是否存在"""
        pass

# 对象存储实现（现有RawObjectStore的升级）
class ObjectStorageBackend(StorageBackend):
    """对象存储后端（MinIO/S3）- 扁平化存储"""
    def __init__(self, endpoint: str, bucket: str):
        self.endpoint = endpoint
        self.bucket = bucket
    
    def put(self, data: bytes, content_hash: str, metadata: dict = None) -> dict:
        # 扁平化路径：s3://bucket/{content_hash}
        path = f"s3://{self.bucket}/{content_hash}"
        # ... 存储逻辑
        return {"uri": path, "mode": StorageMode.OBJECT_STORAGE}

# 本地存储实现
class LocalStorageBackend(StorageBackend):
    """本地存储后端 - 层级化目录结构"""
    def __init__(self, base_dir: str, path_generator: "PathGenerator"):
        self.base_dir = base_dir
        self.path_generator = path_generator
    
    def put(self, data: bytes, dicom_tags: dict, metadata: dict = None) -> dict:
        # 层级化路径生成
        path = self.path_generator.generate_path(dicom_tags)
        full_path = os.path.join(self.base_dir, path)
        # ... 存储逻辑
        return {"uri": full_path, "mode": StorageMode.LOCAL_STORAGE}
```

**2. 路径生成策略**
```python
# storage/path_generator.py
from typing import Dict, Any

class PathGenerator:
    """本地存储路径生成器 - 根据DICOM Tag生成层级化路径"""
    
    def __init__(self, template: str = None):
        # 默认路径模板
        self.template = template or (
            "DICOM_{Modality}/{Manufacturer}/{StationName}/"
            "{StudyInstanceUID}/{MeasUID}/{SeriesInstanceUID}/"
            "{SOPInstanceUID}.dcm"
        )
    
    def generate_path(self, tags: Dict[str, Any]) -> str:
        """
        根据DICOM Tag生成存储路径
        
        需要的Tag：
        - Modality: CT/MR 等
        - Manufacturer: 厂商（UIH/友商）
        - StationName: 设备名
        - StudyInstanceUID: Study UID
        - MeasUID: Private tag，一次扫描标识
        - SeriesInstanceUID: Series UID
        - SOPInstanceUID: SOP Instance UID
        """
        # 厂商映射（可选）
        manufacturer_map = {
            "United Imaging": "UIH",
            "GE": "GE",
            "Siemens": "Siemens",
            # ...
        }
        
        manufacturer = manufacturer_map.get(tags.get("Manufacturer"), "Other")
        
        # 构建路径
        path = self.template.format(
            Modality=tags.get("Modality", "UNKNOWN"),
            Manufacturer=manufacturer,
            StationName=tags.get("StationName", "unknown"),
            StudyInstanceUID=tags.get("StudyInstanceUID"),
            MeasUID=tags.get("MeasUID"),  # ← Private tag，需要REQ-002支持
            SeriesInstanceUID=tags.get("SeriesInstanceUID"),
            SOPInstanceUID=tags.get("SOPInstanceUID"),
        )
        
        return path
```

**3. 与REQ-002的关系（关键依赖）**
```
REQ-002: DICOM解析器架构升级
    ↓ 提供
Private Tag提取能力（MeasUID）
    ↓ 用于
REQ-005: 层级化路径生成
    ↓ 生成
本地存储目录结构
```

**MeasUID提取示例**：
```python
# 需要在TagSchema中定义MeasUID（Private tag）
TagDefinition(
    tag_address="0019,1002",  # 假设MeasUID的tag地址
    name="MeasUID",
    meaning="Measurement UID - identifies a scan session",
    is_private=True,
    # 可能需要value_processor来解析Private tag结构
)
```

**4. 多模态数据存储**
```python
# storage/multimodal_storage.py
class MultimodalStorage:
    """多模态数据存储管理器"""
    
    def __init__(self, storage_backend: StorageBackend):
        self.backend = storage_backend
        self.upload_id_generator = UUIDGenerator()
    
    def store_dicom(self, dicom_bytes: bytes, tags: dict) -> str:
        """存储DICOM文件"""
        # DICOM_CT/ 或 DICOM_MR/
        modality = f"DICOM_{tags.get('Modality', 'UNKNOWN')}"
        
        if isinstance(self.backend, LocalStorageBackend):
            # 本地存储：层级化路径
            path = self.backend.path_generator.generate_path(tags)
        else:
            # 对象存储：扁平化
            path = hashlib.sha256(dicom_bytes).hexdigest()
        
        return self.backend.put(dicom_bytes, path)
    
    def store_rawdata(self, rawdata_bytes: bytes, metadata: dict) -> str:
        """存储RawData"""
        # RAWDATA_CT/ 或 RAWDATA_MR/
        # 路径：/{二级协议}/{MeasUID}/{Version}/Rawdata/
        pass
    
    def store_document(self, upload_id: str, doc_bytes: bytes, 
                       sample_id: str = "data_sample_0") -> str:
        """存储文档"""
        # DOCUMENT/{upload_id}/{sample_id}/
        path = f"DOCUMENT/{upload_id}/{sample_id}/document.pdf"
        return self.backend.put(doc_bytes, path)
    
    def store_audio(self, upload_id: str, audio_bytes: bytes,
                    sample_id: str = "data_sample_0") -> str:
        """存储音频"""
        # AUDIO/{upload_id}/{sample_id}/
        path = f"AUDIO/{upload_id}/{sample_id}/audio.wav"
        return self.backend.put(audio_bytes, path)
    
    def store_multimodal_upload(self, upload_files: List[Dict]) -> Dict:
        """
        处理多模态upload
        
        多模态数据不单独建立文件夹，内容分流到不同单模态目录
        """
        upload_id = str(self.upload_id_generator.generate())
        results = {}
        
        for file in upload_files:
            file_type = self._detect_file_type(file)
            
            if file_type == "DICOM":
                # 解析DICOM，提取tags，存入DICOM_MR/CT/
                tags = dicom_parser.parse_header(file["bytes"])
                results[file["name"]] = self.store_dicom(file["bytes"], tags)
                
            elif file_type == "DOCUMENT":
                # 回流到DOCUMENT/
                results[file["name"]] = self.store_document(
                    upload_id, file["bytes"], file.get("sample_id")
                )
                
            elif file_type == "AUDIO":
                # 回流到AUDIO/
                results[file["name"]] = self.store_audio(
                    upload_id, file["bytes"], file.get("sample_id")
                )
                
            # ... 其他类型
        
        return {"upload_id": upload_id, "files": results}
```

**5. Annotation存储结构**
```python
# storage/annotation_storage.py
class AnnotationStorage:
    """标注数据存储"""
    
    def __init__(self, storage_backend: StorageBackend):
        self.backend = storage_backend
    
    def store_dicom_annotation(
        self, 
        dicom_tags: dict,
        annotation_id: str,
        label_name: str,
        annotation_data: bytes
    ) -> str:
        """
        存储DICOM标注
        
        路径：Annotation/DICOM_{Modality}/{Manufacturer}/{StationName}/
              {StudyUID}/{MeasUID}/{SeriesUID}/{annotation_id}/{label_name}/
        """
        modality = dicom_tags.get("Modality", "UNKNOWN")
        manufacturer = dicom_tags.get("Manufacturer", "Other")
        
        path = (
            f"Annotation/DICOM_{modality}/{manufacturer}/"
            f"{dicom_tags.get('StationName', 'unknown')}/"
            f"{dicom_tags.get('StudyInstanceUID')}/"
            f"{dicom_tags.get('MeasUID')}/"
            f"{dicom_tags.get('SeriesInstanceUID')}/"
            f"{annotation_id}/{label_name}/"
        )
        
        return self.backend.put(annotation_data, path)
    
    def store_document_annotation(
        self,
        upload_id: str,
        sample_id: str,
        annotation_id: str,
        label_name: str,
        annotation_data: bytes
    ) -> str:
        """存储文档标注"""
        path = f"Annotation/DOCUMENT/{upload_id}/{sample_id}/{annotation_id}/{label_name}/"
        return self.backend.put(annotation_data, path)
```

**6. 配置示例**
```yaml
# storage_config.yaml
storage:
  mode: "local_storage"  # 或 "object_storage"
  
  local_storage:
    base_dir: "/data/medical_storage"
    path_template: "DICOM_{Modality}/{Manufacturer}/{StationName}/{StudyInstanceUID}/{MeasUID}/{SeriesInstanceUID}/{SOPInstanceUID}.dcm"
    
  object_storage:
    endpoint: "http://minio:9000"
    bucket: "dicom-data"
    access_key: "xxx"
    secret_key: "yyy"
```

**7. 与现有需求的关系**

| 需求 | 关系 | 说明 |
|------|------|------|
| REQ-001 | 配合 | 文件夹上传需要存储到正确路径 |
| REQ-002 | 强依赖 | 需要Private tag（MeasUID）提取能力 |
| REQ-003 | 独立 | Celery异步与存储后端解耦 |
| REQ-004 | 独立 | Series重复检测与存储无关 |
| CHANGE-001 | 独立 | 绑定类型与存储无关 |

### REQ-006 实现建议（分块上传功能）

**背景**：DICOM文件通常100MB-1GB，当前一次性上传在大文件/不稳定网络环境下体验差。需要支持分块上传、进度可见、断点续传。

**核心诉求**：
1. **前端分块切片**：大文件切分为小块（如5MB），并发上传
2. **进度可见**：上传进度条让用户知道状态
3. **断点续传**：失败后只重传失败分块，不用从头开始
4. **后端组装**：接收分块、校验、合并成完整文件

**1. 前端分块上传实现**
```javascript
// frontend/upload/chunked_uploader.js
class ChunkedUploader {
    constructor(options = {}) {
        this.chunkSize = options.chunkSize || 5 * 1024 * 1024; // 默认5MB
        this.concurrency = options.concurrency || 3; // 并发数
        this.retryCount = options.retryCount || 3; // 重试次数
    }
    
    async uploadFile(file, metadata = {}) {
        // 1. 计算文件指纹（用于断点续传识别）
        const fileHash = await this.calculateFileHash(file);
        
        // 2. 初始化上传任务（获取upload_id）
        const initResponse = await this.initUpload({
            filename: file.name,
            size: file.size,
            hash: fileHash,
            metadata: metadata
        });
        const uploadId = initResponse.upload_id;
        
        // 3. 分块
        const chunks = this.createChunks(file);
        const totalChunks = chunks.length;
        
        // 4. 检查已上传的分块（断点续传）
        const uploadedChunks = await this.getUploadedChunks(uploadId);
        
        // 5. 并发上传未上传的分块
        const uploadTasks = chunks
            .filter(chunk => !uploadedChunks.includes(chunk.index))
            .map(chunk => this.uploadChunk(uploadId, chunk, fileHash));
        
        // 控制并发数
        await this.runWithConcurrency(uploadTasks, this.concurrency, (progress) => {
            this.onProgress(progress);
        });
        
        // 6. 通知后端组装
        const result = await this.finalizeUpload(uploadId);
        return result;
    }
    
    createChunks(file) {
        const chunks = [];
        let start = 0;
        let index = 0;
        
        while (start < file.size) {
            const end = Math.min(start + this.chunkSize, file.size);
            chunks.push({
                index: index,
                blob: file.slice(start, end),
                start: start,
                end: end,
                size: end - start
            });
            start = end;
            index++;
        }
        
        return chunks;
    }
    
    async uploadChunk(uploadId, chunk, fileHash) {
        const formData = new FormData();
        formData.append('upload_id', uploadId);
        formData.append('chunk_index', chunk.index);
        formData.append('chunk_hash', await this.calculateChunkHash(chunk.blob));
        formData.append('file_hash', fileHash);
        formData.append('chunk', chunk.blob);
        
        let retries = 0;
        while (retries < this.retryCount) {
            try {
                const response = await fetch('/api/upload/chunk', {
                    method: 'POST',
                    body: formData
                });
                
                if (response.ok) {
                    return await response.json();
                }
                throw new Error(`Chunk ${chunk.index} upload failed`);
            } catch (error) {
                retries++;
                if (retries >= this.retryCount) {
                    throw error;
                }
                await this.delay(1000 * retries); // 指数退避
            }
        }
    }
    
    calculateFileHash(file) {
        // 使用spark-md5或类似库计算文件hash
        // 大文件可以只计算开头/结尾/中间部分
        return sparkMd5.hash(file.slice(0, 1024 * 1024)); // 前1MB
    }
}
```

**2. 后端分块接收与组装**
```python
# services/upload/chunk_upload_service.py
import os
import hashlib
import tempfile
from typing import Dict, List, Optional
from dataclasses import dataclass
from redis import Redis

@dataclass
class ChunkInfo:
    """分块信息"""
    index: int
    size: int
    hash: str
    received: bool = False
    stored_path: str = ""

class ChunkUploadService:
    """分块上传服务"""
    
    def __init__(self, 
                 temp_storage_path: str = "/tmp/chunks",
                 redis_client: Optional[Redis] = None):
        self.temp_path = temp_storage_path
        self.redis = redis_client
        os.makedirs(temp_storage_path, exist_ok=True)
    
    def init_upload(self, 
                    filename: str, 
                    file_size: int, 
                    file_hash: str,
                    total_chunks: int,
                    metadata: dict = None) -> dict:
        """
        初始化上传任务
        
        Returns:
            upload_id: 上传任务ID
            uploaded_chunks: 已上传的分块索引列表（断点续传）
        """
        import uuid
        upload_id = str(uuid.uuid4())
        
        # 保存上传任务元数据
        upload_info = {
            "upload_id": upload_id,
            "filename": filename,
            "file_size": file_size,
            "file_hash": file_hash,
            "total_chunks": total_chunks,
            "metadata": metadata or {},
            "status": "uploading",
            "created_at": datetime.utcnow().isoformat()
        }
        
        # 存储到Redis或数据库
        self._save_upload_info(upload_id, upload_info)
        
        # 检查是否有已上传的分块（断点续传）
        uploaded_chunks = self._get_uploaded_chunks(upload_id)
        
        return {
            "upload_id": upload_id,
            "uploaded_chunks": uploaded_chunks
        }
    
    def receive_chunk(self,
                      upload_id: str,
                      chunk_index: int,
                      chunk_hash: str,
                      chunk_data: bytes) -> dict:
        """
        接收单个分块
        
        Args:
            upload_id: 上传任务ID
            chunk_index: 分块索引
            chunk_hash: 分块哈希（前端计算）
            chunk_data: 分块数据
            
        Returns:
            接收结果
        """
        # 1. 校验分块哈希
        actual_hash = hashlib.md5(chunk_data).hexdigest()
        if actual_hash != chunk_hash:
            return {
                "success": False,
                "error": "Chunk hash mismatch",
                "chunk_index": chunk_index
            }
        
        # 2. 保存分块到临时存储
        chunk_path = os.path.join(
            self.temp_path, 
            upload_id, 
            f"chunk_{chunk_index:04d}"
        )
        os.makedirs(os.path.dirname(chunk_path), exist_ok=True)
        
        with open(chunk_path, 'wb') as f:
            f.write(chunk_data)
        
        # 3. 记录分块已接收
        self._mark_chunk_received(upload_id, chunk_index, chunk_path)
        
        # 4. 检查是否所有分块都已上传
        upload_info = self._get_upload_info(upload_id)
        received_chunks = self._get_uploaded_chunks(upload_id)
        
        is_complete = len(received_chunks) >= upload_info["total_chunks"]
        
        return {
            "success": True,
            "chunk_index": chunk_index,
            "received_chunks": len(received_chunks),
            "total_chunks": upload_info["total_chunks"],
            "is_complete": is_complete
        }
    
    def assemble_file(self, upload_id: str) -> dict:
        """
        组装所有分块为完整文件
        
        Returns:
            组装结果，包含完整文件路径
        """
        upload_info = self._get_upload_info(upload_id)
        uploaded_chunks = self._get_uploaded_chunks(upload_id)
        
        # 1. 检查所有分块是否到齐
        if len(uploaded_chunks) < upload_info["total_chunks"]:
            missing = set(range(upload_info["total_chunks"])) - set(uploaded_chunks)
            return {
                "success": False,
                "error": f"Missing chunks: {missing}"
            }
        
        # 2. 按顺序组装文件
        assembled_path = os.path.join(
            self.temp_path,
            upload_id,
            "assembled",
            upload_info["filename"]
        )
        os.makedirs(os.path.dirname(assembled_path), exist_ok=True)
        
        with open(assembled_path, 'wb') as outfile:
            for i in range(upload_info["total_chunks"]):
                chunk_path = os.path.join(
                    self.temp_path,
                    upload_id,
                    f"chunk_{i:04d}"
                )
                with open(chunk_path, 'rb') as infile:
                    outfile.write(infile.read())
        
        # 3. 校验完整文件哈希
        if not self._verify_assembled_file(assembled_path, upload_info["file_hash"]):
            return {
                "success": False,
                "error": "Assembled file hash mismatch"
            }
        
        # 4. 更新状态
        upload_info["status"] = "assembled"
        upload_info["assembled_path"] = assembled_path
        self._save_upload_info(upload_id, upload_info)
        
        return {
            "success": True,
            "upload_id": upload_id,
            "assembled_path": assembled_path,
            "file_size": os.path.getsize(assembled_path)
        }
    
    def finalize_upload(self, upload_id: str) -> dict:
        """
        完成上传，将组装好的文件送入原有处理流程
        
        调用UploadService继续处理：扫描 → 解析 → 存储
        """
        assemble_result = self.assemble_file(upload_id)
        
        if not assemble_result["success"]:
            return assemble_result
        
        # 调用原有UploadService处理
        from dicom_ingestion.services.upload.upload_service import UploadService
        
        upload_service = UploadService(object_store)
        
        with open(assemble_result["assembled_path"], 'rb') as f:
            package = upload_service.accept(
                input_data=f,
                filename=upload_info["filename"]
            )
        
        # 清理临时分块文件
        self._cleanup_chunks(upload_id)
        
        return {
            "success": True,
            "upload_id": upload_id,
            "package_uri": package.uri,
            "status": "uploaded"
        }
    
    def _cleanup_chunks(self, upload_id: str):
        """清理临时分块文件"""
        import shutil
        chunk_dir = os.path.join(self.temp_path, upload_id)
        if os.path.exists(chunk_dir):
            shutil.rmtree(chunk_dir)
```

**3. API接口设计**
```python
# api/upload_api.py
from fastapi import APIRouter, UploadFile, File, Form, HTTPException

router = APIRouter(prefix="/api/upload")

@router.post("/init")
async def init_upload(
    filename: str = Form(...),
    file_size: int = Form(...),
    file_hash: str = Form(...),
    total_chunks: int = Form(...),
    metadata: str = Form("{}")
):
    """初始化分块上传任务"""
    service = ChunkUploadService()
    result = service.init_upload(
        filename=filename,
        file_size=file_size,
        file_hash=file_hash,
        total_chunks=total_chunks,
        metadata=json.loads(metadata)
    )
    return result

@router.post("/chunk")
async def upload_chunk(
    upload_id: str = Form(...),
    chunk_index: int = Form(...),
    chunk_hash: str = Form(...),
    file_hash: str = Form(...),
    chunk: UploadFile = File(...)
):
    """上传单个分块"""
    service = ChunkUploadService()
    chunk_data = await chunk.read()
    
    result = service.receive_chunk(
        upload_id=upload_id,
        chunk_index=chunk_index,
        chunk_hash=chunk_hash,
        chunk_data=chunk_data
    )
    
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["error"])
    
    return result

@router.post("/finalize")
async def finalize_upload(upload_id: str = Form(...)):
    """完成上传，组装分块并处理"""
    service = ChunkUploadService()
    result = service.finalize_upload(upload_id)
    
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result.get("error"))
    
    return result

@router.get("/progress/{upload_id}")
async def get_upload_progress(upload_id: str):
    """获取上传进度（用于进度条）"""
    service = ChunkUploadService()
    info = service._get_upload_info(upload_id)
    uploaded = service._get_uploaded_chunks(upload_id)
    
    return {
        "upload_id": upload_id,
        "total_chunks": info["total_chunks"],
        "uploaded_chunks": len(uploaded),
        "progress": len(uploaded) / info["total_chunks"],
        "status": info["status"]
    }
```

**4. 与现有需求的关系**

| 需求 | 关系 | 说明 |
|------|------|------|
| REQ-001 | 强配合 | 文件夹上传大文件需要分块上传支持 |
| REQ-006 | 主体 | 分块上传功能 |
| 其他 | 独立 | 分块上传是前置步骤，与解析、存储等解耦 |

**5. 实施建议**

- **阶段1**：实现基础分块上传（前端切片 + 后端接收 + 组装）
- **阶段2**：添加断点续传（记录已上传分块）
- **阶段3**：优化并发和重试机制
- **阶段4**：与 REQ-001 配合支持文件夹大文件上传

---

## 统计

- 总问题数：8
- 已解答：5
  - Q1: 整体功能解释
  - Q3: DICOM解析需求确认
  - Q6: STUDY绑定概念解释
  - Q7: 双模式存储架构需求理解
  - Q8: 分块上传需求理解
- 需求待实现：6
  - REQ-001: 文件夹上传
  - REQ-002: DICOM解析器架构升级（REQ-005强依赖）
  - REQ-003: Celery异步解析服务
  - REQ-004: Series维度重复检测聚合报告
  - REQ-005: 双模式存储 + 层级化本地存储路径
  - REQ-006: 分块上传功能（前端分块+后端组装+断点续传）
- 变更待执行：1
  - CHANGE-001: 从BindingTargetType移除STUDY
- 需求依赖关系：
  - REQ-005（存储路径）→ 依赖 → REQ-002（Private tag提取）
  - REQ-001（文件夹上传）→ 配合 → REQ-006（分块上传大文件）
- 待回答：0
- 需跟进：0

---

*最后更新：2026-05-18 19:44*
