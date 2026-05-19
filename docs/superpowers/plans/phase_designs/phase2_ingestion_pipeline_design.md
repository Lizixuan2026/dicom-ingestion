# Phase 2: 摄入管道 - 详细设计

**目标**: 建立完整的本地/NAS文件夹摄入工作流，包括作业调度、异步处理、报告生成
**交付顺序**: 7D → 7E → 7F
**预计工期**: 3-4 周
**依赖**: Phase 1 (7A, 7B, 7C)

---

## 系统架构概览

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                          Phase 2: Ingestion Pipeline                        │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐    ┌───────────┐ │
│  │ IngestSource │───▶│ IngestJob    │───▶│ ParseWorker  │───▶│ Report    │ │
│  │   (7D)       │    │ Scheduler    │    │ Async (7E)   │    │ Gen (7F)  │ │
│  └──────────────┘    └──────────────┘    └──────────────┘    └───────────┘ │
│         │                   │                   │                   │       │
│         ▼                   ▼                   ▼                   ▼       │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐    ┌───────────┐ │
│  │ Folder       │    │ Task Queue   │    │ State Machine│    │ Conflict  │ │
│  │ Scanner      │    │ (Redis/RMQ)  │    │ (DB + Lock)  │    │ Resolver  │ │
│  └──────────────┘    └──────────────┘    └──────────────┘    └───────────┘ │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 7D: Folder Ingest API + Source 抽象

### 目标
建立统一的摄入源抽象，支持文件夹扫描、文件发现、作业创建

### 数据模型

**IngestSource 抽象**
```python
# models/ingest_source.py
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Iterator, List, Optional, Dict
from datetime import datetime
from enum import Enum

class SourceType(Enum):
    LOCAL_FOLDER = "local_folder"
    ZIP_ARCHIVE = "zip_archive"
    DICOM_DIR = "dicom_dir"
    MANIFEST_FILE = "manifest_file"

@dataclass
class SourceFile:
    """发现的源文件"""
    source_id: str           # 源内唯一标识
    path: str                # 相对/绝对路径
    size: int
    modified_time: datetime
    checksum: Optional[str] = None
    mime_type: Optional[str] = None
    metadata: Dict = field(default_factory=dict)

@dataclass 
class ScanResult:
    """扫描结果"""
    source_id: str
    files: List[SourceFile]
    total_size: int
    file_count: int
    errors: List[str] = field(default_factory=list)
    scan_time_ms: int = 0

class IngestSource(ABC):
    """
    摄入源抽象基类
    支持迭代器模式遍历文件
    """
    
    @property
    @abstractmethod
    def source_type(self) -> SourceType:
        pass
    
    @property
    @abstractmethod
    def source_id(self) -> str:
        """源唯一标识（通常是路径的哈希）"""
        pass
    
    @abstractmethod
    def scan(self) -> ScanResult:
        """
        扫描源，发现所有文件
        
        Returns:
            ScanResult包含所有发现的文件
        """
        pass
    
    @abstractmethod
    def iter_files(self) -> Iterator[SourceFile]:
        """
        惰性迭代文件
        用于大文件夹，避免一次性加载所有文件
        """
        pass
    
    @abstractmethod
    def get_file_stream(self, file_id: str):
        """获取文件流用于读取"""
        pass
    
    @abstractmethod
    def validate(self) -> bool:
        """验证源是否可访问"""
        pass
    
    @abstractmethod
    def close(self):
        """清理资源"""
        pass
```

### 具体实现

**1. 本地文件夹源**
```python
# sources/local_folder_source.py
import hashlib
import os
from pathlib import Path
from typing import Iterator
import mimetypes

class LocalFolderSource(IngestSource):
    """本地文件夹摄入源"""
    
    def __init__(self, folder_path: str, recursive: bool = True, 
                 file_pattern: str = "*.dcm"):
        self.folder_path = Path(folder_path).resolve()
        self.recursive = recursive
        self.file_pattern = file_pattern
        self._validate_path()
        
    @property
    def source_type(self) -> SourceType:
        return SourceType.LOCAL_FOLDER
    
    @property
    def source_id(self) -> str:
        """基于路径的哈希标识"""
        path_hash = hashlib.sha256(str(self.folder_path).encode()).hexdigest()[:16]
        return f"local_{path_hash}"
    
    def scan(self) -> ScanResult:
        """完整扫描文件夹"""
        start_time = datetime.now()
        files = []
        errors = []
        total_size = 0
        
        try:
            glob_pattern = "**/*" if self.recursive else "*"
            full_pattern = f"{glob_pattern}.{self.file_pattern.replace('*.', '')}"
            
            for file_path in self.folder_path.glob(full_pattern):
                if file_path.is_file():
                    try:
                        stat = file_path.stat()
                        source_file = SourceFile(
                            source_id=str(file_path.relative_to(self.folder_path)),
                            path=str(file_path),
                            size=stat.st_size,
                            modified_time=datetime.fromtimestamp(stat.st_mtime),
                            mime_type=mimetypes.guess_type(str(file_path))[0]
                        )
                        files.append(source_file)
                        total_size += stat.st_size
                    except OSError as e:
                        errors.append(f"Cannot access {file_path}: {e}")
        except Exception as e:
            errors.append(f"Scan failed: {e}")
        
        scan_time = (datetime.now() - start_time).total_seconds() * 1000
        
        return ScanResult(
            source_id=self.source_id,
            files=files,
            total_size=total_size,
            file_count=len(files),
            errors=errors,
            scan_time_ms=int(scan_time)
        )
    
    def iter_files(self) -> Iterator[SourceFile]:
        """惰性迭代器"""
        glob_pattern = "**/*" if self.recursive else "*"
        
        for file_path in self.folder_path.glob(glob_pattern):
            if file_path.is_file() and self._is_dicom(file_path):
                stat = file_path.stat()
                yield SourceFile(
                    source_id=str(file_path.relative_to(self.folder_path)),
                    path=str(file_path),
                    size=stat.st_size,
                    modified_time=datetime.fromtimestamp(stat.st_mtime)
                )
    
    def get_file_stream(self, file_id: str):
        """获取文件流"""
        file_path = self.folder_path / file_id
        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")
        return open(file_path, 'rb')
    
    def validate(self) -> bool:
        """验证文件夹可访问"""
        return self.folder_path.exists() and self.folder_path.is_dir()
    
    def close(self):
        """本地文件夹无需清理"""
        pass
    
    def _validate_path(self):
        """安全验证：防止目录遍历"""
        # 解析为绝对路径，检查是否在允许范围内
        resolved = self.folder_path.resolve()
        # 可添加额外的安全检查，如白名单路径
        
    def _is_dicom(self, path: Path) -> bool:
        """检查文件是否为DICOM"""
        # 简单检查：文件扩展名或魔术数字
        if path.suffix.lower() in ['.dcm', '.dicom']:
            return True
        # 读取前128字节检查DICM魔术数字
        try:
            with open(path, 'rb') as f:
                header = f.read(132)
                return len(header) >= 132 and header[128:132] == b'DICM'
        except:
            return False
```

**2. ZIP归档源**
```python
# sources/zip_archive_source.py
import zipfile
import tempfile
from pathlib import Path
from typing import Iterator

class ZipArchiveSource(IngestSource):
    """ZIP归档摄入源"""
    
    def __init__(self, zip_path: str, extract_to: Optional[str] = None):
        self.zip_path = Path(zip_path)
        self._temp_dir = None
        self._extract_path = None
        
        if extract_to:
            self._extract_path = Path(extract_to)
        else:
            # 创建临时目录
            self._temp_dir = tempfile.TemporaryDirectory()
            self._extract_path = Path(self._temp_dir.name)
    
    @property
    def source_type(self) -> SourceType:
        return SourceType.ZIP_ARCHIVE
    
    @property
    def source_id(self) -> str:
        path_hash = hashlib.sha256(str(self.zip_path).encode()).hexdigest()[:16]
        return f"zip_{path_hash}"
    
    def scan(self) -> ScanResult:
        """扫描ZIP内容"""
        # 先解压或列出内容
        with zipfile.ZipFile(self.zip_path, 'r') as zf:
            # 检查ZIP炸弹
            total_size = sum(info.file_size for info in zf.infolist())
            compressed_size = sum(info.compress_size for info in zf.infolist())
            
            # ZIP炸弹检测：解压比过高
            if compressed_size > 0 and total_size / compressed_size > 100:
                raise ValueError("Potential ZIP bomb detected")
            
            # 解压到临时目录
            if not any(self._extract_path.iterdir()):
                zf.extractall(self._extract_path)
        
        # 使用LocalFolderSource扫描解压后的目录
        inner_source = LocalFolderSource(str(self._extract_path))
        result = inner_source.scan()
        result.source_id = self.source_id
        return result
    
    def iter_files(self) -> Iterator[SourceFile]:
        """惰性迭代ZIP内容"""
        inner_source = LocalFolderSource(str(self._extract_path))
        yield from inner_source.iter_files()
    
    def get_file_stream(self, file_id: str):
        """获取文件流"""
        file_path = self._extract_path / file_id
        return open(file_path, 'rb')
    
    def validate(self) -> bool:
        """验证ZIP文件有效"""
        try:
            with zipfile.ZipFile(self.zip_path, 'r') as zf:
                zf.testzip()
            return True
        except zipfile.BadZipFile:
            return False
    
    def close(self):
        """清理临时目录"""
        if self._temp_dir:
            self._temp_dir.cleanup()
```

### IngestJob 调度器

```python
# scheduler/ingest_job_scheduler.py
from dataclasses import dataclass
from typing import List, Optional, Dict
from datetime import datetime
from enum import Enum
import hashlib

class JobStatus(Enum):
    PENDING = "pending"
    SCANNING = "scanning"
    QUEUED = "queued"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

@dataclass
class IngestJob:
    """摄入作业"""
    id: str
    source: IngestSource
    actor_id: str           # 创建者标识
    status: JobStatus
    created_at: datetime
    updated_at: datetime
    total_files: int = 0
    processed_files: int = 0
    failed_files: int = 0
    metadata: Dict = None
    # 决策 Gap-6: 指纹去重
    source_fingerprint: str = ""  # 源哈希，用于防重复创建

class IngestJobScheduler:
    """
    摄入作业调度器
    决策 Gap-6: 作业创建幂等（防双击提交）
    """
    
    def __init__(self, db_session, queue_client, dedup_window_seconds: int = 300):
        self.db = db_session
        self.queue = queue_client
        self.dedup_window = dedup_window_seconds  # 5分钟去重窗口
    
    def create_job(
        self,
        source: IngestSource,
        actor_id: str,
        priority: int = 0
    ) -> IngestJob:
        """
        创建摄入作业
        
        决策 Gap-6: 指纹去重（source_hash + actor_id + 时间窗口）
        """
        # 1. 扫描源获取文件列表
        scan_result = source.scan()
        
        # 2. 计算源指纹
        source_fingerprint = self._calculate_fingerprint(
            source.source_id,
            scan_result.files,
            actor_id
        )
        
        # 3. 幂等性检查：检查近期是否有相同指纹的作业
        existing = self._check_duplicate(source_fingerprint)
        if existing:
            logger.info(f"Duplicate job detected, returning existing: {existing.id}")
            return existing
        
        # 4. 创建作业
        job = IngestJob(
            id=self._generate_job_id(),
            source=source,
            actor_id=actor_id,
            status=JobStatus.PENDING,
            created_at=datetime.now(),
            updated_at=datetime.now(),
            total_files=scan_result.file_count,
            source_fingerprint=source_fingerprint,
            metadata={
                "scan_result": {
                    "total_size": scan_result.total_size,
                    "errors": scan_result.errors
                }
            }
        )
        
        # 5. 持久化
        self._persist_job(job)
        
        # 6. 启动扫描阶段
        self._transition_to_scanning(job)
        
        return job
    
    def _calculate_fingerprint(
        self,
        source_id: str,
        files: List[SourceFile],
        actor_id: str
    ) -> str:
        """
        计算源指纹用于去重
        
        包含：源ID + 关键文件属性 + 操作者
        """
        # 收集关键文件信息（前10个文件的大小和修改时间）
        file_signatures = []
        for f in sorted(files, key=lambda x: x.path)[:10]:
            sig = f"{f.path}:{f.size}:{int(f.modified_time.timestamp())}"
            file_signatures.append(sig)
        
        # 组合指纹
        fingerprint_data = {
            "source_id": source_id,
            "actor_id": actor_id,
            "file_signatures": file_signatures,
            "timestamp_window": int(datetime.now().timestamp() / self.dedup_window)
        }
        
        return hashlib.sha256(
            str(fingerprint_data).encode()
        ).hexdigest()
    
    def _check_duplicate(self, fingerprint: str) -> Optional[IngestJob]:
        """检查是否存在重复作业"""
        # 查询数据库中最近window内的相同指纹作业
        cutoff = datetime.now().timestamp() - self.dedup_window
        
        query = """
        SELECT * FROM ingest_jobs 
        WHERE source_fingerprint = :fingerprint
          AND EXTRACT(EPOCH FROM created_at) > :cutoff
          AND status NOT IN ('failed', 'cancelled')
        ORDER BY created_at DESC
        LIMIT 1
        """
        result = self.db.execute(query, {
            "fingerprint": fingerprint,
            "cutoff": cutoff
        }).fetchone()
        
        if result:
            return self._row_to_job(result)
        return None
    
    def _transition_to_scanning(self, job: IngestJob):
        """转换到扫描阶段"""
        job.status = JobStatus.SCANNING
        self._update_job_status(job)
        
        # 异步启动扫描
        self.queue.enqueue(
            'tasks.scan_job',
            job_id=job.id,
            priority=job.metadata.get('priority', 0)
        )
```

### REST API 设计

```yaml
# API: Folder Ingest

POST /api/v1/ingest/folder
  description: 创建文件夹摄入作业
  request:
    body:
      folder_path: string    # 必填，文件夹绝对路径
      recursive: boolean     # 可选，默认true
      priority: integer        # 可选，0-9，默认0
      dry_run: boolean       # 可选，仅扫描不摄入
      metadata: object       # 可选，附加元数据
  
  response:
    201:
      body:
        job_id: string
        status: string       # pending
        estimated_files: integer
        source_fingerprint: string  # 用于查询重复
    
    409:  # 重复作业
      body:
        error: "duplicate_job"
        existing_job_id: string
        message: "相似作业在5分钟内已创建"
    
    400:  # 无效路径
      body:
        error: "invalid_path"
        message: "路径不存在或不可访问"

GET /api/v1/ingest/jobs/{job_id}
  description: 查询作业状态
  response:
    body:
      id: string
      status: string
      progress:
        total: integer
        processed: integer
        failed: integer
        percentage: number
      stages:
        scanning: { status, started_at, completed_at }
        parsing: { status, started_at, completed_at }
        storing: { status, started_at, completed_at }
      errors: [ { file, error, timestamp } ]

POST /api/v1/ingest/jobs/{job_id}/cancel
  description: 取消作业
  response:
    200:
      body:
        status: "cancelled"
        
    409:
      body:
        error: "cannot_cancel"
        message: "作业已完成或已失败，无法取消"

GET /api/v1/ingest/jobs/{job_id}/report
  description: 获取摄入报告
  response:
    body:
      summary:
        total_files: integer
        processed: integer
        failed: integer
        duplicates_found: integer
        conflicts: integer
      series:
        - series_uid: string
          modality: string
          patient_name: string
          file_count: integer
          status: string
      errors:
        - file: string
          error_type: string
          message: string
```

---

## 7E: Async Parse Worker + State机

### 目标
实现异步解析工作器，带完整状态机、幂等性保障、可取消

### 状态机设计

```
                    ┌─────────────────────────────────────────────────────────┐
                    │                    State Machine                          │
                    └─────────────────────────────────────────────────────────┘

┌─────────┐    scan     ┌──────────┐   queue   ┌──────────┐  pickup  ┌──────────┐
│ PENDING │ ───────────▶│ SCANNING │──────────▶│  QUEUED  │─────────▶│IN_PROGRESS│
└─────────┘             └──────────┘           └──────────┘          └─────┬────┘
                                                                              │
              ┌─────────────────────────────────────────────────────────────────┘
              │
              ▼
    ┌─────────────────┐
    │   CANCELLED     │◀─────────────────────────────────────────┐
    │   (用户取消)     │                                          │
    └─────────────────┘    cancel                                 │
           ▲                                              ┌───────┴────────┐
           │                                              │                │
           │    ┌──────────────┐     retry_exhausted      │                │
           └────│    FAILED    │◀───────────────────────│   IN_PROGRESS  │
                │   (最终失败)  │                        │                │
                └──────────────┘     all_done             │                │
                         ▲                               │                │
                         │                               └───────┬────────┘
                         │                                       │
                         │               retry_scheduled          │
                         └─────────────────────────────────────────┘
                                               │
                                               ▼
                                        ┌──────────────┐
                                        │ RETRY_WAITING│  ◀── retry_ready
                                        │  (等待重试)   │────────┐
                                        └──────────────┘        │
                                                                  │
                                                                  ▼
                                                           ┌──────────┐
                                                           │ COMPLETED│
                                                           │  (完成)  │
                                                           └──────────┘

决策 Gap-2: CANCELLED 状态实现
- PENDING, SCANNING, QUEUED: 可立即取消
- IN_PROGRESS: 发送取消信号，当前任务完成后转CANCELLED
- RETRY_WAITING: 从队列移除，标记CANCELLED
```

### 实现代码

**1. 任务状态管理**
```python
# worker/task_state_manager.py
from enum import Enum
from dataclasses import dataclass
from typing import Optional, Dict
from datetime import datetime
import json

class TaskStatus(Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    RETRY_WAITING = "retry_waiting"

@dataclass
class ParseTask:
    """解析任务"""
    id: str
    job_id: str
    file_path: str
    status: TaskStatus
    created_at: datetime
    updated_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    retry_count: int = 0
    max_retries: int = 3
    error_info: Optional[Dict] = None
    worker_id: Optional[str] = None
    cancellation_requested: bool = False  # 决策 Gap-2

class TaskStateManager:
    """
    任务状态管理器
    使用数据库乐观锁实现幂等性（决策 Gap-1）
    """
    
    def __init__(self, db_session):
        self.db = db_session
    
    def create_task(self, job_id: str, file_path: str) -> ParseTask:
        """创建解析任务"""
        task = ParseTask(
            id=self._generate_task_id(),
            job_id=job_id,
            file_path=file_path,
            status=TaskStatus.PENDING,
            created_at=datetime.now(),
            updated_at=datetime.now()
        )
        
        self._persist_task(task)
        return task
    
    def claim_task(self, task_id: str, worker_id: str) -> Optional[ParseTask]:
        """
        工作器认领任务
        
        决策 Gap-1: 数据库唯一约束 + 乐观锁
        - 使用version字段实现乐观锁
        - 仅当status=PENDING时可以claim
        """
        # 原子性更新，带乐观锁
        update_sql = """
        UPDATE parse_tasks
        SET status = 'in_progress',
            worker_id = :worker_id,
            started_at = NOW(),
            updated_at = NOW(),
            version = version + 1
        WHERE id = :task_id
          AND status = 'pending'
          AND (worker_id IS NULL OR worker_id = :worker_id)
        RETURNING *
        """
        
        result = self.db.execute(update_sql, {
            "task_id": task_id,
            "worker_id": worker_id
        }).fetchone()
        
        if result:
            return self._row_to_task(result)
        return None  # 任务已被其他工作器认领或状态不符
    
    def complete_task(
        self, 
        task_id: str, 
        worker_id: str,
        result: Dict
    ) -> bool:
        """完成任务"""
        sql = """
        UPDATE parse_tasks
        SET status = 'completed',
            completed_at = NOW(),
            updated_at = NOW(),
            result_data = :result,
            version = version + 1
        WHERE id = :task_id
          AND worker_id = :worker_id
          AND status = 'in_progress'
        """
        
        result = self.db.execute(sql, {
            "task_id": task_id,
            "worker_id": worker_id,
            "result": json.dumps(result)
        })
        
        return result.rowcount > 0
    
    def fail_task(
        self,
        task_id: str,
        worker_id: str,
        error: Exception,
        retry_policy: Dict
    ) -> TaskStatus:
        """
        标记任务失败，根据策略决定重试或最终失败
        
        决策 Gap-3: 指数退避 + 最大重试年龄 + 死信队列
        """
        task = self.get_task(task_id)
        
        # 检查是否达到最大重试
        if task.retry_count >= task.max_retries:
            return self._final_fail(task_id, worker_id, error, retry_policy)
        
        # 决策 Gap-3: 检查最大重试年龄
        max_age_hours = retry_policy.get('max_retry_age_hours', 24)
        task_age = (datetime.now() - task.created_at).total_seconds() / 3600
        
        if task_age > max_age_hours:
            logger.warning(f"Task {task_id} exceeded max retry age, sending to DLQ")
            return self._send_to_dlq(task_id, worker_id, error, "max_age_exceeded")
        
        # 计算指数退避延迟
        base_delay = retry_policy.get('base_delay_seconds', 60)
        max_delay = retry_policy.get('max_delay_seconds', 3600)
        backoff_factor = retry_policy.get('backoff_factor', 2)
        
        delay = min(base_delay * (backoff_factor ** task.retry_count), max_delay)
        
        # 更新为等待重试状态
        sql = """
        UPDATE parse_tasks
        SET status = 'retry_waiting',
            retry_count = retry_count + 1,
            retry_after = NOW() + INTERVAL ':delay seconds',
            error_info = :error_info,
            updated_at = NOW(),
            version = version + 1
        WHERE id = :task_id
          AND worker_id = :worker_id
          AND status = 'in_progress'
        """
        
        self.db.execute(sql, {
            "task_id": task_id,
            "worker_id": worker_id,
            "delay": int(delay),
            "error_info": json.dumps({
                "error": str(error),
                "type": type(error).__name__,
                "retry_count": task.retry_count + 1,
                "next_retry": delay
            })
        })
        
        return TaskStatus.RETRY_WAITING
    
    def request_cancellation(self, job_id: str) -> int:
        """
        请求取消作业的所有任务
        决策 Gap-2: CANCELLED 状态策略
        """
        # 1. 标记所有未开始任务为CANCELLED
        sql_cancel_pending = """
        UPDATE parse_tasks
        SET status = 'cancelled',
            cancellation_requested = TRUE,
            updated_at = NOW()
        WHERE job_id = :job_id
          AND status IN ('pending', 'queued', 'retry_waiting')
        """
        cancelled = self.db.execute(sql_cancel_pending, {"job_id": job_id}).rowcount
        
        # 2. 标记进行中任务请求取消（工作器会检查）
        sql_request_cancel = """
        UPDATE parse_tasks
        SET cancellation_requested = TRUE,
            updated_at = NOW()
        WHERE job_id = :job_id
          AND status = 'in_progress'
        """
        requested = self.db.execute(sql_request_cancel, {"job_id": job_id}).rowcount
        
        return cancelled + requested
    
    def check_cancellation(self, task_id: str) -> bool:
        """工作器检查任务是否请求取消"""
        result = self.db.execute(
            "SELECT cancellation_requested FROM parse_tasks WHERE id = :id",
            {"id": task_id}
        ).fetchone()
        
        return result and result[0]
```

**2. 解析工作器**
```python
# worker/parse_worker.py
import signal
import threading
from typing import Optional

class ParseWorker:
    """
    异步DICOM解析工作器
    """
    
    def __init__(
        self,
        worker_id: str,
        state_manager: TaskStateManager,
        parser_factory,
        storage_manager,
        max_concurrent: int = 4
    ):
        self.worker_id = worker_id
        self.state = state_manager
        self.parser_factory = parser_factory
        self.storage = storage_manager
        self.max_concurrent = max_concurrent
        
        self._shutdown_event = threading.Event()
        self._current_tasks: Dict[str, threading.Thread] = {}
        
        # 注册信号处理
        signal.signal(signal.SIGTERM, self._handle_shutdown)
        signal.signal(signal.SIGINT, self._handle_shutdown)
    
    def run(self):
        """主循环"""
        logger.info(f"Worker {self.worker_id} started")
        
        while not self._shutdown_event.is_set():
            try:
                # 获取待处理任务
                task = self._claim_next_task()
                
                if task:
                    self._process_task(task)
                else:
                    # 无任务，短暂休眠
                    self._shutdown_event.wait(timeout=1.0)
                    
            except Exception as e:
                logger.exception("Worker error: %s", e)
    
    def _claim_next_task(self) -> Optional[ParseTask]:
        """从队列获取下一个任务"""
        # 1. 优先获取PENDING任务
        query = """
        SELECT * FROM parse_tasks
        WHERE status = 'pending'
           OR (status = 'retry_waiting' AND retry_after <= NOW())
        ORDER BY 
            CASE status 
                WHEN 'pending' THEN 0 
                WHEN 'retry_waiting' THEN 1 
            END,
            created_at
        LIMIT 1
        FOR UPDATE SKIP LOCKED
        """
        
        result = self.state.db.execute(query).fetchone()
        if not result:
            return None
        
        task = self.state._row_to_task(result)
        
        # 尝试认领
        return self.state.claim_task(task.id, self.worker_id)
    
    def _process_task(self, task: ParseTask):
        """处理单个任务"""
        logger.info(f"Processing task {task.id}: {task.file_path}")
        
        try:
            # 1. 检查取消请求（决策 Gap-2）
            if self.state.check_cancellation(task.id):
                logger.info(f"Task {task.id} cancelled before processing")
                self._handle_cancelled(task)
                return
            
            # 2. 解析DICOM
            parser = self.parser_factory.create_parser()
            parse_result = parser.parse(task.file_path)
            
            # 3. 检查取消（长时间操作后再次检查）
            if self.state.check_cancellation(task.id):
                logger.info(f"Task {task.id} cancelled after parsing")
                self._handle_cancelled(task)
                return
            
            # 4. 双存储（决策 Gap-7: 用户选择双存储）
            storage_results = self.storage.dual_store(
                task.file_path,
                parse_result.tags
            )
            
            # 5. 完成
            self.state.complete_task(
                task.id,
                self.worker_id,
                {
                    "parse_result": {
                        "tags": parse_result.tags,
                        "extractors_used": parse_result.extractors_used
                    },
                    "storage_locations": {
                        k: {
                            "uri": v.uri,
                            "checksum": v.checksum,
                            "mode": v.mode.value
                        }
                        for k, v in storage_results.items()
                    }
                }
            )
            
            logger.info(f"Task {task.id} completed successfully")
            
        except Exception as e:
            logger.exception(f"Task {task.id} failed: {e}")
            
            # 失败处理（决策 Gap-3）
            retry_policy = {
                "base_delay_seconds": 60,
                "max_delay_seconds": 3600,
                "backoff_factor": 2,
                "max_retry_age_hours": 24
            }
            self.state.fail_task(task.id, self.worker_id, e, retry_policy)
    
    def _handle_cancelled(self, task: ParseTask):
        """处理取消"""
        sql = """
        UPDATE parse_tasks
        SET status = 'cancelled',
            completed_at = NOW(),
            updated_at = NOW()
        WHERE id = :task_id
          AND worker_id = :worker_id
        """
        self.state.db.execute(sql, {
            "task_id": task.id,
            "worker_id": self.worker_id
        })
    
    def _handle_shutdown(self, signum, frame):
        """优雅关闭"""
        logger.info(f"Worker {self.worker_id} received shutdown signal")
        self._shutdown_event.set()
```

**3. Saga 事务协调器（决策 Gap-2: 事务回滚）**
```python
# worker/saga_coordinator.py
from typing import List, Callable, Dict, Any
from dataclasses import dataclass
from enum import Enum

class SagaStatus(Enum):
    RUNNING = "running"
    COMPLETED = "completed"
    COMPENSATING = "compensating"
    FAILED = "failed"

@dataclass
class SagaStep:
    """Saga步骤定义"""
    name: str
    action: Callable  # 正向操作
    compensation: Callable  # 补偿操作
    action_args: Dict = None
    compensation_args: Dict = None

class SagaCoordinator:
    """
    Saga模式协调器
    决策 Gap-2: 冲突解析中途失败的事务管理
    """
    
    def __init__(self, event_bus):
        self.event_bus = event_bus
        self._completed_steps: List[str] = []
    
    def execute(self, saga_id: str, steps: List[SagaStep]) -> Dict[str, Any]:
        """
        执行Saga事务
        
        Args:
            saga_id: 事务ID
            steps: 步骤列表
            
        Returns:
            执行结果或异常
            
        Raises:
            SagaFailedException: 事务失败且补偿完成
        """
        results = {}
        
        try:
            for step in steps:
                logger.info(f"Saga {saga_id}: Executing step {step.name}")
                
                # 执行正向操作
                try:
                    result = step.action(**(step.action_args or {}))
                    results[step.name] = result
                    self._completed_steps.append(step.name)
                    
                    # 发布步骤完成事件
                    self.event_bus.publish("saga_step_completed", {
                        "saga_id": saga_id,
                        "step": step.name,
                        "result": result
                    })
                    
                except Exception as e:
                    logger.error(f"Saga {saga_id}: Step {step.name} failed: {e}")
                    
                    # 启动补偿
                    self._compensate(saga_id, steps, results)
                    
                    raise SagaFailedException(
                        f"Step {step.name} failed",
                        completed_steps=self._completed_steps,
                        failed_step=step.name,
                        error=e
                    )
            
            return results
            
        except SagaFailedException:
            raise
        except Exception as e:
            # 意外异常，同样补偿
            self._compensate(saga_id, steps, results)
            raise
    
    def _compensate(self, saga_id: str, steps: List[SagaStep], results: Dict):
        """
        执行补偿（回滚）
        按完成顺序的逆序执行补偿
        """
        logger.info(f"Saga {saga_id}: Starting compensation")
        
        for step_name in reversed(self._completed_steps):
            step = next(s for s in steps if s.name == step_name)
            
            try:
                logger.info(f"Saga {saga_id}: Compensating step {step.name}")
                
                # 使用执行结果作为补偿参数
                comp_args = {
                    **(step.compensation_args or {}),
                    "action_result": results.get(step_name)
                }
                
                step.compensation(**comp_args)
                
                self.event_bus.publish("saga_step_compensated", {
                    "saga_id": saga_id,
                    "step": step.name
                })
                
            except Exception as e:
                # 补偿失败 - 记录，需要人工介入
                logger.error(f"Saga {saga_id}: Compensation failed for {step.name}: {e}")
                
                self.event_bus.publish("saga_compensation_failed", {
                    "saga_id": saga_id,
                    "step": step.name,
                    "error": str(e)
                })
                # 这里可以触发告警通知运维


# 使用示例：冲突解析Saga
def resolve_conflict_with_saga(
    coordinator: SagaCoordinator,
    conflict_info: Dict,
    resolution_strategy: str
):
    """
    使用Saga模式解析冲突
    
    步骤：
    1. 验证新数据
    2. 更新Series绑定（可能需要创建修订版）
    3. 存储文件到对象存储
    4. 存储文件到本地/NAS
    5. 更新冲突状态为已解决
    
    补偿：
    - 删除已存储的文件
    - 恢复原始绑定状态
    """
    
    saga_id = f"conflict_resolve_{conflict_info['id']}"
    
    steps = [
        SagaStep(
            name="validate",
            action=lambda data: validate_new_data(data),
            compensation=lambda **kw: None,  # 验证无需补偿
            action_args={"data": conflict_info["new_data"]}
        ),
        SagaStep(
            name="update_binding",
            action=lambda series_id, data: update_series_binding(series_id, data),
            compensation=lambda action_result, **kw: 
                restore_binding(action_result["original_state"]),
            action_args={
                "series_id": conflict_info["series_id"],
                "data": conflict_info["binding_data"]
            }
        ),
        SagaStep(
            name="store_object",
            action=lambda file_path, tags: 
                storage.store_for_processing(file_path, tags),
            compensation=lambda action_result, **kw:
                storage.delete(action_result["location"]),
            action_args={
                "file_path": conflict_info["file_path"],
                "tags": conflict_info["tags"]
            }
        ),
        SagaStep(
            name="store_local",
            action=lambda file_path, tags:
                storage.store_for_archive(file_path, tags),
            compensation=lambda action_result, **kw:
                storage.delete(action_result["location"]),
            action_args={
                "file_path": conflict_info["file_path"],
                "tags": conflict_info["tags"]
            }
        ),
        SagaStep(
            name="mark_resolved",
            action=lambda conflict_id: mark_conflict_resolved(conflict_id),
            compensation=lambda **kw: mark_conflict_unresolved(kw["conflict_id"]),
            action_args={"conflict_id": conflict_info["id"]}
        )
    ]
    
    return coordinator.execute(saga_id, steps)
```

### 决策实施清单

| 决策 | 实施位置 | 检查点 |
|-----|---------|-------|
| Gap-1: 幂等性 | `TaskStateManager.claim_task()` | version乐观锁 |
| Gap-2: 事务回滚 | `SagaCoordinator._compensate()` | 事件驱动补偿 |
| Gap-2: CANCELLED | `TaskStateManager.request_cancellation()` | 两阶段取消 |
| Gap-3: 重试策略 | `TaskStateManager.fail_task()` | 指数退避+最大年龄 |
| Gap-6: 作业去重 | `IngestJobScheduler.create_job()` | 指纹检查 |

---

## 7F: Ingest Report + 冲突UI

### 目标
生成详细的摄入报告，提供冲突检测和管理界面

### 报告数据模型

```python
# reports/ingest_report.py
from dataclasses import dataclass, field
from typing import List, Dict, Optional
from datetime import datetime
from enum import Enum

class FileStatus(Enum):
    SUCCESS = "success"
    DUPLICATE = "duplicate"
    CONFLICT = "conflict"
    PARSE_ERROR = "parse_error"
    STORE_ERROR = "store_error"
    CANCELLED = "cancelled"

class ConflictType(Enum):
    SERIES_MERGE = "series_merge"           # 同Series不同Study
    PATIENT_MISMATCH = "patient_mismatch"   # Series间Patient信息冲突
    UID_COLLISION = "uid_collision"         # SOP UID已存在
    METADATA_MISMATCH = "metadata_mismatch" # 相同UID不同元数据

@dataclass
class FileReport:
    """单个文件报告"""
    source_path: str
    file_size: int
    status: FileStatus
    duration_ms: int
    
    # 解析结果
    parsed_tags: Optional[Dict] = None
    extractors_used: List[str] = field(default_factory=list)
    
    # 存储结果
    storage_locations: Dict = field(default_factory=dict)
    
    # 错误信息
    error_type: Optional[str] = None
    error_message: Optional[str] = None
    
    # 冲突信息
    conflict_type: Optional[ConflictType] = None
    conflict_details: Optional[Dict] = None

@dataclass
class SeriesSummary:
    """Series汇总"""
    series_uid: str
    modality: str
    patient_name: str
    study_description: Optional[str]
    file_count: int
    status: str  # complete, partial, conflict
    conflicts: List[Dict] = field(default_factory=list)

@dataclass
class IngestReport:
    """完整摄入报告"""
    job_id: str
    created_at: datetime
    completed_at: Optional[datetime]
    
    # 汇总
    summary: Dict = field(default_factory=dict)
    
    # 详细列表
    series: List[SeriesSummary] = field(default_factory=list)
    files: List[FileReport] = field(default_factory=list)
    errors: List[Dict] = field(default_factory=list)
    conflicts: List[Dict] = field(default_factory=list)
    
    # 性能指标
    performance: Dict = field(default_factory=dict)
```

### 报告生成器

```python
# reports/report_generator.py

class IngestReportGenerator:
    """摄入报告生成器"""
    
    def __init__(self, db_session):
        self.db = db_session
    
    def generate(self, job_id: str) -> IngestReport:
        """为作业生成完整报告"""
        
        # 1. 查询所有任务结果
        tasks = self._get_tasks(job_id)
        
        # 2. 按Series分组
        series_map: Dict[str, SeriesSummary] = {}
        file_reports: List[FileReport] = []
        conflicts: List[Dict] = []
        
        for task in tasks:
            file_report = self._task_to_file_report(task)
            file_reports.append(file_report)
            
            # 提取Series信息
            series_uid = file_report.parsed_tags.get('series_uid') if file_report.parsed_tags else None
            if series_uid:
                if series_uid not in series_map:
                    series_map[series_uid] = SeriesSummary(
                        series_uid=series_uid,
                        modality=file_report.parsed_tags.get('modality', 'Unknown'),
                        patient_name=file_report.parsed_tags.get('patient_name', 'Unknown'),
                        study_description=file_report.parsed_tags.get('study_description'),
                        file_count=0,
                        status='complete'
                    )
                
                series_map[series_uid].file_count += 1
                
                # 检查冲突
                if file_report.status == FileStatus.CONFLICT:
                    series_map[series_uid].status = 'conflict'
                    series_map[series_uid].conflicts.append({
                        "file": file_report.source_path,
                        "type": file_report.conflict_type.value,
                        "details": file_report.conflict_details
                    })
                    conflicts.append(file_report.conflict_details)
        
        # 3. 生成汇总
        summary = self._generate_summary(file_reports)
        
        # 4. 组装报告
        return IngestReport(
            job_id=job_id,
            created_at=tasks[0].created_at if tasks else datetime.now(),
            completed_at=tasks[-1].completed_at if tasks and all(t.completed_at for t in tasks) else None,
            summary=summary,
            series=list(series_map.values()),
            files=file_reports,
            errors=[f for f in file_reports if f.error_type],
            conflicts=conflicts,
            performance=self._generate_performance_metrics(tasks)
        )
    
    def _generate_summary(self, file_reports: List[FileReport]) -> Dict:
        """生成汇总统计"""
        total = len(file_reports)
        status_counts = {}
        
        for fr in file_reports:
            status_counts[fr.status.value] = status_counts.get(fr.status.value, 0) + 1
        
        return {
            "total_files": total,
            "successful": status_counts.get('success', 0),
            "duplicates": status_counts.get('duplicate', 0),
            "conflicts": status_counts.get('conflict', 0),
            "failed": status_counts.get('parse_error', 0) + status_counts.get('store_error', 0),
            "cancelled": status_counts.get('cancelled', 0),
            "success_rate": round(status_counts.get('success', 0) / total * 100, 2) if total > 0 else 0
        }
```

### 冲突检测API

```yaml
# API: Conflict Management

GET /api/v1/ingest/jobs/{job_id}/conflicts
  description: 获取作业的所有冲突
  response:
    body:
      total: integer
      unresolved: integer
      resolved: integer
      conflicts:
        - id: string
          type: string           # series_merge, patient_mismatch, uid_collision, metadata_mismatch
          severity: string       # warning, critical
          series_uid: string
          files: [string]
          detected_at: datetime
          status: string         # detected, resolving, resolved
          resolution: object     # 如果已解决
          
POST /api/v1/conflicts/{conflict_id}/resolve
  description: 解决冲突
  request:
    body:
      resolution_strategy: string   # merge, replace, skip, create_revision
      metadata: object              # 额外的解决元数据
      
  response:
    200:
      body:
        status: "resolved"
        action_taken: string
        affected_series: [string]
        
    409:
      body:
        error: "conflict_stale"
        message: "冲突状态已变更，请刷新后重试"
        
    500:
      body:
        error: "resolution_failed"
        message: "解决过程中发生错误，已触发补偿"
        saga_status: string
        compensation_status: string

GET /api/v1/conflicts/{conflict_id}/preview
  description: 预览冲突解决结果
  response:
    body:
      current_state: object
      proposed_changes: object
      will_affect:
        series_count: integer
        file_count: integer
      warnings: [string]
```

### 冲突解决UI设计

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         Conflict Resolution UI                               │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌─────────────────────────────────────────────────────────────────────┐  │
│  │ Conflict: Series Merge Detected                                      │  │
│  │                                                                      │  │
│  │  ⚠️  以下文件属于同一个Series，但关联到不同Study                        │  │
│  │                                                                      │  │
│  │  Series UID: 1.2.276.0.7230010.3.1.3.12345...                         │  │
│  │                                                                      │  │
│  │  ┌──────────────┐  ┌──────────────┐                                  │  │
│  │  │ Existing     │  │ New Files    │                                  │  │
│  │  │              │  │              │                                  │  │
│  │  │ Study: A-001 │  │ Study: B-002 │  ← 冲突点                        │  │
│  │  │ Patient:张三 │  │ Patient:张三 │                                  │  │
│  │  │ Files: 120   │  │ Files: 45    │                                  │  │
│  │  └──────────────┘  └──────────────┘                                  │  │
│  │                                                                      │  │
│  │  Resolution Strategy:                                                │  │
│  │                                                                      │  │
│  │  (•) Merge Studies - 将新文件合并到现有Study                         │  │
│  │  ( ) Replace - 用新Study替换现有Study (保留旧数据为修订版)            │  │
│  │  ( ) Create New Series - 将新文件作为独立Series处理                   │  │
│  │  ( ) Skip - 跳过这些文件                                             │  │
│  │                                                                      │  │
│  │  [ Preview Changes ]    [ Confirm Resolution ]    [ Defer ]          │  │
│  │                                                                      │  │
│  │  Preview:                                                              │  │
│  │  ✓ 165个文件将归属于Study A-001                                      │  │
│  │  ✓ 生成新的Series修订版记录                                           │  │
│  │  ⚠️ 原Study B-002将标记为合并来源                                     │  │
│  │                                                                      │  │
│  └─────────────────────────────────────────────────────────────────────┘  │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 报告CLI命令

```python
# CLI: dicom-ingest report

@click.group()
def report():
    """摄入报告命令"""
    pass

@report.command()
@click.argument('job_id')
@click.option('--format', type=click.Choice(['json', 'html', 'text']), default='text')
@click.option('--output', '-o', type=click.Path(), help='输出文件路径')
def generate(job_id: str, format: str, output: Optional[str]):
    """
    生成摄入报告
    
    决策 Gap-7: CLI 使用服务账户 Token（API 包装器）
    """
    # 获取服务账户token
    token = get_service_account_token()
    
    # 调用API
    client = APIClient(token=token)
    report_data = client.get(f"/api/v1/ingest/jobs/{job_id}/report")
    
    # 格式化输出
    if format == 'json':
        content = json.dumps(report_data, indent=2, ensure_ascii=False)
    elif format == 'html':
        content = render_html_report(report_data)
    else:
        content = render_text_report(report_data)
    
    if output:
        with open(output, 'w', encoding='utf-8') as f:
            f.write(content)
        click.echo(f"报告已保存到: {output}")
    else:
        click.echo(content)

@report.command()
@click.argument('job_id')
def conflicts(job_id: str):
    """显示冲突详情"""
    token = get_service_account_token()
    client = APIClient(token=token)
    
    conflicts = client.get(f"/api/v1/ingest/jobs/{job_id}/conflicts")
    
    click.echo(f"共发现 {conflicts['total']} 个冲突:")
    for c in conflicts['conflicts']:
        click.echo(f"\n[{c['id']}] {c['type']}")
        click.echo(f"  Series: {c['series_uid'][:50]}...")
        click.echo(f"  状态: {c['status']}")
        click.echo(f"  文件数: {len(c['files'])}")
```

---

## Phase 2 集成验证

### 端到端测试场景

```python
def test_end_to_end_folder_ingest():
    """端到端文件夹摄入测试"""
    
    # 1. 创建文件夹源
    source = LocalFolderSource("/test/data/siemens_mr", recursive=True)
    
    # 2. 调度作业（幂等创建）
    scheduler = IngestJobScheduler(db, queue)
    job = scheduler.create_job(source, actor_id="test_user")
    
    # 验证：重复创建应返回相同job
    job2 = scheduler.create_job(source, actor_id="test_user")
    assert job.id == job2.id  # Gap-6
    
    # 3. 启动工作器
    worker = ParseWorker(
        worker_id="test_worker",
        state_manager=TaskStateManager(db),
        parser_factory=DicomParserFactory(),
        storage_manager=StorageManager(obj_backend, local_backend)
    )
    
    # 运行处理
    worker.run_single_job(job.id)
    
    # 4. 验证状态机
    tasks = db.query(ParseTask).filter_by(job_id=job.id).all()
    for task in tasks:
        assert task.status in [TaskStatus.COMPLETED, TaskStatus.CANCELLED]
        # 验证version递增（乐观锁）
        assert task.version >= 1  # Gap-1
    
    # 5. 生成报告
    report_gen = IngestReportGenerator(db)
    report = report_gen.generate(job.id)
    
    # 验证报告
    assert report.summary['total_files'] > 0
    assert report.summary['success_rate'] >= 0
    
    # 6. 检查冲突
    if report.summary['conflicts'] > 0:
        # 手动解决第一个冲突
        conflict = report.conflicts[0]
        resolved = resolve_conflict_with_saga(
            coordinator=SagaCoordinator(event_bus),
            conflict_info=conflict,
            resolution_strategy="merge"
        )
        assert resolved
    
    print("End-to-end test passed!")
```

---

**文档状态**: Phase 2 详细设计 - 完成
**依赖**: Phase 1 组件
**下一步**: Phase 3 设计（产品表面）
