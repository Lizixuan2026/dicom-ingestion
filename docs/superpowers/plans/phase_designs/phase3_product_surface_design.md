# Phase 3: 产品表面 - 详细设计

**目标**: 实现面向用户的产品功能：工作流API、查询端点、适配器层
**交付顺序**: 8A → 8B → 8C → 8D → 8E → 8F
**预计工期**: 3-4 周
**依赖**: Phase 2 (7D, 7E, 7F)

---

## 系统架构概览

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        Phase 3: Product Surface                             │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                        Adapter Layer (8A)                            │   │
│  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐              │   │
│  │  │ IngestSource │  │  Storage     │  │  Query       │              │   │
│  │  │ Adapter      │  │  Adapter     │  │  Adapter     │              │   │
│  │  └──────────────┘  └──────────────┘  └──────────────┘              │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                    │                                       │
│                                    ▼                                       │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                    Workflow API (8B)                                 │   │
│  │  POST /api/v1/ingest/folder        GET /api/v1/series                │   │
│  │  POST /api/v1/ingest/zip           GET /api/v1/studies               │   │
│  │  POST /api/v1/ingest/manifest      GET /api/v1/patients              │   │
│  │  GET  /api/v1/jobs/{id}            POST /api/v1/query                │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                    │                                       │
│                                    ▼                                       │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                    Review Workflow (8C)                              │   │
│  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐              │   │
│  │  │ Conflict     │  │  QA Review   │  │  Approval    │              │   │
│  │  │ Detection    │  │  Workflow    │  │  Chain       │              │   │
│  │  └──────────────┘  └──────────────┘  └──────────────┘              │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                    │                                       │
│                                    ▼                                       │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                    Platform Binding (8D)                             │   │
│  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐              │   │
│  │  │ Series       │  │  Study       │  │  Patient     │              │   │
│  │  │ Binding      │  │  Binding     │  │  Binding     │              │   │
│  │  └──────────────┘  └──────────────┘  └──────────────┘              │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                    │                                       │
│                                    ▼                                       │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                    CLI Admin Tools (8E)                            │   │
│  │  dicom-ingest job list    dicom-ingest job retry                   │   │
│  │  dicom-ingest conflict ls dicom-ingest conflict resolve            │   │
│  │  dicom-ingest storage sync dicom-ingest report generate            │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                    │                                       │
│                                    ▼                                       │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                    Auth/Perms (8F)                                 │   │
│  │  Token-based Auth  │  RBAC  │  Audit Logging  │  Service Accounts    │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 8A: Adapter Layer - IngestSource + Storage Adapter Contracts

### 目标
建立清晰的适配器接口，支持未来扩展（如OHIF、第三方PACS）

### 适配器模式设计

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           Adapter Architecture                               │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                      Application Core                                │   │
│  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐              │   │
│  │  │ IngestJob    │  │  ParseTask   │  │  Series      │              │   │
│  │  │ Service      │  │  Service     │  │  Service     │              │   │
│  │  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘              │   │
│  │         │                 │                 │                      │   │
│  │         ▼                 ▼                 ▼                      │   │
│  │  ┌─────────────────────────────────────────────────────────────┐  │   │
│  │  │              Adapter Interface (Abstract)                    │  │   │
│  │  └─────────────────────────────────────────────────────────────┘  │   │
│  │                              │                                     │   │
│  └──────────────────────────────┼─────────────────────────────────────┘   │
│                                 │                                         │
│         ┌───────────────────────┼───────────────────────┐                  │
│         │                       │                       │                  │
│         ▼                       ▼                       ▼                  │
│  ┌──────────────┐      ┌──────────────┐      ┌──────────────┐             │
│  │  Local       │      │  Future:     │      │  Future:     │             │
│  │  Folder      │      │  OHIF        │      │  PACS        │             │
│  │  Adapter     │      │  Adapter     │      │  Adapter     │             │
│  └──────────────┘      └──────────────┘      └──────────────┘             │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 适配器接口定义

**1. IngestSource Adapter**
```python
# adapters/ingest_source_adapter.py
from abc import ABC, abstractmethod
from typing import Iterator, Dict, Optional
from dataclasses import dataclass

@dataclass
class SourceCapability:
    """源能力声明"""
    supports_streaming: bool
    supports_resume: bool
    supports_metadata_extraction: bool
    max_file_size: Optional[int]  # bytes, None = unlimited
    allowed_extensions: list

class IngestSourceAdapter(ABC):
    """
    摄入源适配器接口
    统一不同来源的数据摄入
    """
    
    @property
    @abstractmethod
    def name(self) -> str:
        """适配器唯一名称"""
        pass
    
    @property
    @abstractmethod
    def version(self) -> str:
        """适配器版本（语义化版本）"""
        pass
    
    @property
    @abstractmethod
    def capabilities(self) -> SourceCapability:
        """声明能力"""
        pass
    
    @abstractmethod
    def create_source(self, config: Dict) -> IngestSource:
        """
        根据配置创建源
        
        Args:
            config: 源配置，至少包含source_type和location
            
        Returns:
            IngestSource实例
        """
        pass
    
    @abstractmethod
    def validate_config(self, config: Dict) -> tuple[bool, Optional[str]]:
        """
        验证配置有效性
        
        Returns:
            (是否有效, 错误信息)
        """
        pass
    
    @abstractmethod
    def get_health_status(self) -> Dict:
        """获取适配器健康状态"""
        pass


# 本地文件夹适配器实现
class LocalFolderAdapter(IngestSourceAdapter):
    """本地文件夹摄入源适配器"""
    
    name = "local_folder"
    version = "1.0.0"
    
    @property
    def capabilities(self) -> SourceCapability:
        return SourceCapability(
            supports_streaming=True,
            supports_resume=True,
            supports_metadata_extraction=True,
            max_file_size=None,
            allowed_extensions=['.dcm', '.dicom', '.zip']
        )
    
    def create_source(self, config: Dict) -> IngestSource:
        source_type = config.get('source_type')
        
        if source_type == 'local_folder':
            return LocalFolderSource(
                folder_path=config['folder_path'],
                recursive=config.get('recursive', True),
                file_pattern=config.get('file_pattern', '*.dcm')
            )
        elif source_type == 'zip_archive':
            return ZipArchiveSource(
                zip_path=config['zip_path'],
                extract_to=config.get('extract_to')
            )
        else:
            raise ValueError(f"Unknown source type: {source_type}")
    
    def validate_config(self, config: Dict) -> tuple[bool, Optional[str]]:
        source_type = config.get('source_type')
        
        if source_type == 'local_folder':
            folder_path = config.get('folder_path')
            if not folder_path:
                return False, "folder_path is required"
            if not Path(folder_path).exists():
                return False, f"Path does not exist: {folder_path}"
            return True, None
            
        elif source_type == 'zip_archive':
            zip_path = config.get('zip_path')
            if not zip_path:
                return False, "zip_path is required"
            if not Path(zip_path).exists():
                return False, f"ZIP file does not exist: {zip_path}"
            return True, None
        
        return False, f"Unsupported source type: {source_type}"
    
    def get_health_status(self) -> Dict:
        return {
            "status": "healthy",
            "timestamp": datetime.now().isoformat(),
            "active_sources": 0  # 可从监控获取
        }


# 适配器注册表
class AdapterRegistry:
    """适配器注册与管理"""
    
    _adapters: Dict[str, IngestSourceAdapter] = {}
    
    @classmethod
    def register(cls, adapter: IngestSourceAdapter):
        """注册适配器"""
        cls._adapters[adapter.name] = adapter
        logger.info(f"Registered adapter: {adapter.name} v{adapter.version}")
    
    @classmethod
    def get(cls, name: str) -> Optional[IngestSourceAdapter]:
        """获取适配器"""
        return cls._adapters.get(name)
    
    @classmethod
    def list_adapters(cls) -> Dict[str, Dict]:
        """列出所有适配器"""
        return {
            name: {
                "version": adapter.version,
                "capabilities": adapter.capabilities
            }
            for name, adapter in cls._adapters.items()
        }


# 自动注册
AdapterRegistry.register(LocalFolderAdapter())
```

**2. Storage Adapter**
```python
# adapters/storage_adapter.py
from abc import ABC, abstractmethod
from typing import BinaryIO, Dict, Optional

class StorageAdapter(ABC):
    """
    存储适配器接口
    统一不同存储后端的操作
    """
    
    @property
    @abstractmethod
    def storage_type(self) -> str:
        """存储类型标识"""
        pass
    
    @abstractmethod
    def store(self, source_path: str, destination: str, 
              metadata: Dict) -> StorageLocation:
        """存储文件"""
        pass
    
    @abstractmethod
    def retrieve(self, location: StorageLocation) -> BinaryIO:
        """检索文件"""
        pass
    
    @abstractmethod
    def delete(self, location: StorageLocation) -> bool:
        """删除文件"""
        pass
    
    @abstractmethod
    def exists(self, location: StorageLocation) -> bool:
        """检查文件是否存在"""
        pass
    
    @abstractmethod
    def copy_to(self, location: StorageLocation, 
                destination_adapter: 'StorageAdapter',
                destination_path: str) -> StorageLocation:
        """
        跨存储复制
        用于从对象存储复制到本地/NAS
        """
        pass


# MinIO对象存储适配器
class MinIOStorageAdapter(StorageAdapter):
    """MinIO对象存储适配器"""
    
    storage_type = "minio"
    
    def __init__(self, client, bucket: str, prefix: str = ""):
        self.client = client
        self.bucket = bucket
        self.prefix = prefix
    
    def store(self, source_path: str, destination: str,
              metadata: Dict) -> StorageLocation:
        """存储到MinIO"""
        object_key = f"{self.prefix}/{destination}".strip('/')
        
        # 上传
        self.client.fput_object(
            self.bucket, object_key, source_path,
            metadata={k: str(v) for k, v in metadata.items()}
        )
        
        # 计算校验和
        checksum = self._calculate_checksum(source_path)
        
        return StorageLocation(
            mode=StorageMode.OBJECT,
            uri=f"s3://{self.bucket}/{object_key}",
            path=object_key,
            bucket=self.bucket,
            metadata=metadata,
            checksum=checksum
        )
    
    def retrieve(self, location: StorageLocation) -> BinaryIO:
        """从MinIO检索"""
        response = self.client.get_object(
            location.bucket or self.bucket,
            location.path
        )
        return io.BytesIO(response.read())
    
    def copy_to(self, location: StorageLocation,
                destination_adapter: StorageAdapter,
                destination_path: str) -> StorageLocation:
        """从MinIO复制到其他存储"""
        # 流式复制避免占用大量内存
        stream = self.retrieve(location)
        
        # 创建临时文件
        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            shutil.copyfileobj(stream, tmp)
            tmp_path = tmp.name
        
        try:
            # 存储到目标适配器
            result = destination_adapter.store(
                tmp_path, destination_path, location.metadata
            )
            return result
        finally:
            os.unlink(tmp_path)
    
    def _calculate_checksum(self, file_path: str) -> str:
        sha256 = hashlib.sha256()
        with open(file_path, 'rb') as f:
            for chunk in iter(lambda: f.read(8192), b""):
                sha256.update(chunk)
        return sha256.hexdigest()
```

**3. Query Adapter**
```python
# adapters/query_adapter.py
from abc import ABC, abstractmethod
from typing import List, Dict, Optional

class QueryAdapter(ABC):
    """
    查询适配器接口
    统一不同数据源的数据查询
    """
    
    @abstractmethod
    def query_series(self, filters: Dict) -> List[Dict]:
        """查询Series"""
        pass
    
    @abstractmethod
    def query_studies(self, filters: Dict) -> List[Dict]:
        """查询Studies"""
        pass
    
    @abstractmethod
    def query_patients(self, filters: Dict) -> List[Dict]:
        """查询Patients"""
        pass
    
    @abstractmethod
    def get_series_files(self, series_uid: str) -> List[Dict]:
        """获取Series下的所有文件"""
        pass


# 内部数据库查询适配器
class InternalQueryAdapter(QueryAdapter):
    """查询内部数据库"""
    
    def __init__(self, db_session):
        self.db = db_session
    
    def query_series(self, filters: Dict) -> List[Dict]:
        """查询Series"""
        query = """
        SELECT 
            s.series_uid,
            s.modality,
            s.series_description,
            COUNT(f.id) as file_count,
            MIN(f.created_at) as earliest_file,
            MAX(f.created_at) as latest_file
        FROM dicom_series s
        JOIN dicom_files f ON f.series_uid = s.series_uid
        WHERE 1=1
        """
        params = {}
        
        if 'modality' in filters:
            query += " AND s.modality = :modality"
            params['modality'] = filters['modality']
        
        if 'study_uid' in filters:
            query += " AND s.study_uid = :study_uid"
            params['study_uid'] = filters['study_uid']
        
        if 'patient_name' in filters:
            query += " AND s.patient_name ILIKE :patient_name"
            params['patient_name'] = f"%{filters['patient_name']}%"
        
        if 'date_from' in filters:
            query += " AND f.created_at >= :date_from"
            params['date_from'] = filters['date_from']
        
        query += " GROUP BY s.series_uid, s.modality, s.series_description"
        query += " ORDER BY latest_file DESC"
        
        if 'limit' in filters:
            query += " LIMIT :limit"
            params['limit'] = filters['limit']
        
        results = self.db.execute(query, params).fetchall()
        return [dict(row) for row in results]
    
    def get_series_files(self, series_uid: str) -> List[Dict]:
        """获取Series文件列表"""
        query = """
        SELECT 
            f.sop_instance_uid,
            f.file_path,
            f.file_size,
            f.checksum,
            f.created_at,
            loc.uri as storage_uri,
            loc.mode as storage_mode
        FROM dicom_files f
        JOIN storage_locations loc ON f.storage_location_id = loc.id
        WHERE f.series_uid = :series_uid
        ORDER BY f.instance_number
        """
        
        results = self.db.execute(query, {"series_uid": series_uid}).fetchall()
        return [dict(row) for row in results]
```

### 适配器使用示例

```python
def demonstrate_adapter_usage():
    """展示适配器使用"""
    
    # 1. 获取适配器
    source_adapter = AdapterRegistry.get("local_folder")
    
    # 2. 验证配置
    config = {
        "source_type": "local_folder",
        "folder_path": "/data/dicom",
        "recursive": True
    }
    
    is_valid, error = source_adapter.validate_config(config)
    if not is_valid:
        raise ValueError(f"Invalid config: {error}")
    
    # 3. 创建源
    source = source_adapter.create_source(config)
    
    # 4. 创建作业（使用调度器）
    job = scheduler.create_job(source, actor_id="user_123")
    
    # 5. 使用存储适配器
    storage_adapter = MinIOStorageAdapter(client, bucket="dicom")
    location = storage_adapter.store(
        "/tmp/file.dcm",
        "DICOM_MR/file.dcm",
        {"patient_name": "张三"}
    )
    
    # 6. 查询
    query_adapter = InternalQueryAdapter(db)
    series = query_adapter.query_series({
        "modality": "MR",
        "limit": 10
    })
```

---

## 8B: Workflow API - 多源输入支持

### REST API 完整规范

```yaml
openapi: 3.0.0
info:
  title: DICOM Ingestion API
  version: 1.0.0
  
paths:
  # ────────────────────────────────────────────────────────────────
  # Ingestion APIs
  # ────────────────────────────────────────────────────────────────
  
  /api/v1/ingest/folder:
    post:
      summary: 创建文件夹摄入作业
      security:
        - bearerAuth: []
      requestBody:
        content:
          application/json:
            schema:
              type: object
              required: [folder_path]
              properties:
                folder_path:
                  type: string
                  description: 绝对路径
                recursive:
                  type: boolean
                  default: true
                file_pattern:
                  type: string
                  default: "*.dcm"
                priority:
                  type: integer
                  minimum: 0
                  maximum: 9
                  default: 0
                dry_run:
                  type: boolean
                  default: false
                metadata:
                  type: object
                  description: 附加元数据
      responses:
        201:
          description: 作业已创建
          content:
            application/json:
              schema:
                type: object
                properties:
                  job_id:
                    type: string
                    format: uuid
                  status:
                    type: string
                    enum: [pending, duplicate]
                  estimated_files:
                    type: integer
                  message:
                    type: string
        409:
          description: 重复作业
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/Error'
              example:
                error: duplicate_job
                existing_job_id: "550e8400-e29b-41d4-a716-446655440000"
                message: "相似作业在5分钟内已创建"

  /api/v1/ingest/zip:
    post:
      summary: 创建ZIP归档摄入作业
      security:
        - bearerAuth: []
      requestBody:
        content:
          multipart/form-data:
            schema:
              type: object
              properties:
                file:
                  type: string
                  format: binary
                priority:
                  type: integer
                  default: 0
                extract_options:
                  type: object
      responses:
        201:
          description: ZIP摄入作业已创建

  /api/v1/ingest/manifest:
    post:
      summary: 创建清单文件摄入作业
      description: |
        通过清单文件批量摄入，清单格式：
        ```json
        {
          "files": [
            {"path": "/data/1.dcm", "metadata": {...}},
            {"path": "/data/2.dcm", "metadata": {...}}
          ]
        }
        ```
      security:
        - bearerAuth: []
      requestBody:
        content:
          application/json:
            schema:
              type: object
              required: [manifest]
              properties:
                manifest:
                  type: object
                validate_only:
                  type: boolean
      responses:
        201:
          description: 清单摄入作业已创建
        400:
          description: 清单验证失败

  /api/v1/ingest/jobs/{job_id}:
    get:
      summary: 查询作业状态
      security:
        - bearerAuth: []
      parameters:
        - name: job_id
          in: path
          required: true
          schema:
            type: string
            format: uuid
      responses:
        200:
          description: 作业状态
          content:
            application/json:
              schema:
                type: object
                properties:
                  id:
                    type: string
                  status:
                    type: string
                    enum: [pending, scanning, queued, in_progress, completed, failed, cancelled]
                  progress:
                    type: object
                    properties:
                      total:
                        type: integer
                      processed:
                        type: integer
                      failed:
                        type: integer
                      percentage:
                        type: number
                  stages:
                    type: object
                  created_at:
                    type: string
                    format: date-time
                  started_at:
                    type: string
                    format: date-time
                  completed_at:
                    type: string
                    format: date-time
                  source:
                    type: object
                    properties:
                      type:
                        type: string
                      path:
                        type: string
                  report:
                    type: object
                    description: 完成后的报告摘要

  /api/v1/ingest/jobs/{job_id}/cancel:
    post:
      summary: 取消作业
      security:
        - bearerAuth: []
      responses:
        200:
          description: 取消请求已接受
        409:
          description: 作业状态不允许取消

  # ────────────────────────────────────────────────────────────────
  # Query APIs
  # ────────────────────────────────────────────────────────────────
  
  /api/v1/series:
    get:
      summary: 查询Series列表
      security:
        - bearerAuth: []
      parameters:
        - name: modality
          in: query
          schema:
            type: string
        - name: study_uid
          in: query
          schema:
            type: string
        - name: patient_name
          in: query
          schema:
            type: string
        - name: date_from
          in: query
          schema:
            type: string
            format: date
        - name: date_to
          in: query
          schema:
            type: string
            format: date
        - name: limit
          in: query
          schema:
            type: integer
            default: 20
            maximum: 100
        - name: offset
          in: query
          schema:
            type: integer
            default: 0
      responses:
        200:
          description: Series列表
          content:
            application/json:
              schema:
                type: object
                properties:
                  total:
                    type: integer
                  items:
                    type: array
                    items:
                      type: object
                      properties:
                        series_uid:
                          type: string
                        modality:
                          type: string
                        series_description:
                          type: string
                        patient_name:
                          type: string
                        study_uid:
                          type: string
                        file_count:
                          type: integer
                        created_at:
                          type: string
                          format: date-time

  /api/v1/series/{series_uid}:
    get:
      summary: 获取Series详情
      security:
        - bearerAuth: []
      responses:
        200:
          description: Series详情

  /api/v1/series/{series_uid}/files:
    get:
      summary: 获取Series下的文件列表
      security:
        - bearerAuth: []
      responses:
        200:
          description: 文件列表

  /api/v1/studies:
    get:
      summary: 查询Study列表
      security:
        - bearerAuth: []
      responses:
        200:
          description: Study列表

  /api/v1/patients:
    get:
      summary: 查询Patient列表
      security:
        - bearerAuth: []
      responses:
        200:
          description: Patient列表

  # ────────────────────────────────────────────────────────────────
  # Conflict APIs
  # ────────────────────────────────────────────────────────────────
  
  /api/v1/conflicts:
    get:
      summary: 列出所有冲突
      security:
        - bearerAuth: []
      parameters:
        - name: status
          in: query
          schema:
            type: string
            enum: [detected, resolving, resolved]
        - name: type
          in: query
          schema:
            type: string
      responses:
        200:
          description: 冲突列表

  /api/v1/conflicts/{conflict_id}:
    get:
      summary: 获取冲突详情
      security:
        - bearerAuth: []
      responses:
        200:
          description: 冲突详情

  /api/v1/conflicts/{conflict_id}/resolve:
    post:
      summary: 解决冲突
      security:
        - bearerAuth: []
      requestBody:
        content:
          application/json:
            schema:
              type: object
              required: [resolution_strategy]
              properties:
                resolution_strategy:
                  type: string
                  enum: [merge, replace, skip, create_revision]
                metadata:
                  type: object
      responses:
        200:
          description: 冲突已解决
        202:
          description: 解决过程异步进行中
        409:
          description: 冲突状态冲突

components:
  securitySchemes:
    bearerAuth:
      type: http
      scheme: bearer
      bearerFormat: JWT
  
  schemas:
    Error:
      type: object
      properties:
        error:
          type: string
        message:
          type: string
        details:
          type: object
```

---

## 8C: Review Workflow 集成

### 工作流设计

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        Review Workflow                                       │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│   冲突检测                      QA审查                        审批流程       │
│      │                           │                            │           │
│      ▼                           ▼                            ▼           │
│  ┌───────┐                   ┌───────┐                    ┌───────┐        │
│  │自动检测│                   │人工审查│                    │多级审批│        │
│  └───┬───┘                   └───┬───┘                    └───┬───┘        │
│      │                           │                            │           │
│      ▼                           ▼                            ▼           │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                     Conflict Resolution Queue                          │   │
│  │  ┌────────┐  ┌────────┐  ┌────────┐  ┌────────┐  ┌────────┐        │   │
│  │  │低优先级│  │中等    │  │高优先级│  │紧急    │  │已解决  │        │   │
│  │  │        │  │        │  │        │  │        │  │        │        │   │
│  │  │ 等待   │  │ 审查中 │  │ 审查中 │  │ 立即处 │  │ 归档   │        │   │
│  │  │        │  │        │  │        │  │        │  │        │        │   │
│  │  └────────┘  └────────┘  └────────┘  └────────┘  └────────┘        │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 实现代码

```python
# workflow/review_workflow.py
from enum import Enum
from dataclasses import dataclass
from typing import List, Optional, Dict
from datetime import datetime

class ReviewStatus(Enum):
    PENDING_REVIEW = "pending_review"      # 待审查
    IN_REVIEW = "in_review"                # 审查中
    APPROVED = "approved"                  # 已批准
    REJECTED = "rejected"                  # 已拒绝
    RESOLVED = "resolved"                  # 已解决

class ConflictSeverity(Enum):
    LOW = "low"           # 可以自动处理
    MEDIUM = "medium"     # 需要人工确认
    HIGH = "high"         # 必须人工处理
    CRITICAL = "critical" # 阻止继续处理

@dataclass
class ReviewTask:
    """审查任务"""
    id: str
    conflict_id: str
    severity: ConflictSeverity
    assigned_to: Optional[str]
    status: ReviewStatus
    created_at: datetime
    updated_at: datetime
    review_notes: List[Dict] = None
    
@dataclass
class ApprovalStep:
    """审批步骤"""
    step_number: int
    approver_role: str
    approver_id: Optional[str]
    status: str  # pending, approved, rejected
    decided_at: Optional[datetime]
    notes: Optional[str]

class ReviewWorkflow:
    """
    审查工作流管理
    """
    
    def __init__(self, db_session, notification_service):
        self.db = db_session
        self.notifier = notification_service
    
    def create_review_task(
        self,
        conflict_id: str,
        severity: ConflictSeverity,
        auto_assign: bool = True
    ) -> ReviewTask:
        """创建审查任务"""
        
        task = ReviewTask(
            id=self._generate_task_id(),
            conflict_id=conflict_id,
            severity=severity,
            assigned_to=None,
            status=ReviewStatus.PENDING_REVIEW,
            created_at=datetime.now(),
            updated_at=datetime.now(),
            review_notes=[]
        )
        
        # 自动分配（根据严重性）
        if auto_assign and severity in [ConflictSeverity.HIGH, ConflictSeverity.CRITICAL]:
            task.assigned_to = self._assign_to_qa_lead()
            self.notifier.notify(
                user_id=task.assigned_to,
                message=f"高优先级冲突需要审查: {conflict_id}"
            )
        
        self._persist_task(task)
        return task
    
    def start_review(self, task_id: str, reviewer_id: str) -> bool:
        """开始审查"""
        task = self._get_task(task_id)
        
        if task.status != ReviewStatus.PENDING_REVIEW:
            return False
        
        task.status = ReviewStatus.IN_REVIEW
        task.assigned_to = reviewer_id
        task.updated_at = datetime.now()
        
        self._update_task(task)
        return True
    
    def submit_for_approval(
        self,
        task_id: str,
        resolution_strategy: str,
        notes: str
    ) -> List[ApprovalStep]:
        """提交审批"""
        task = self._get_task(task_id)
        
        # 根据严重性确定审批链
        if task.severity == ConflictSeverity.CRITICAL:
            approval_chain = [
                ApprovalStep(1, "qa_lead", None, "pending", None, None),
                ApprovalStep(2, "tech_lead", None, "pending", None, None),
                ApprovalStep(3, "product_manager", None, "pending", None, None)
            ]
        elif task.severity == ConflictSeverity.HIGH:
            approval_chain = [
                ApprovalStep(1, "qa_lead", None, "pending", None, None),
                ApprovalStep(2, "tech_lead", None, "pending", None, None)
            ]
        else:
            approval_chain = [
                ApprovalStep(1, "qa_lead", None, "pending", None, None)
            ]
        
        # 持久化审批链
        self._persist_approval_chain(task_id, approval_chain)
        
        # 通知第一级审批人
        first_step = approval_chain[0]
        approver = self._find_user_by_role(first_step.approver_role)
        if approver:
            self.notifier.notify(
                user_id=approver,
                message=f"冲突解决方案待审批: {task.conflict_id}"
            )
        
        return approval_chain
    
    def approve_step(
        self,
        task_id: str,
        step_number: int,
        approver_id: str,
        notes: str
    ) -> Dict:
        """审批步骤"""
        chain = self._get_approval_chain(task_id)
        step = next(s for s in chain if s.step_number == step_number)
        
        step.status = "approved"
        step.approver_id = approver_id
        step.decided_at = datetime.now()
        step.notes = notes
        
        self._update_approval_step(task_id, step)
        
        # 检查是否还有后续步骤
        next_step = next(
            (s for s in chain if s.step_number == step_number + 1),
            None
        )
        
        if next_step and next_step.status == "pending":
            # 通知下一级审批人
            approver = self._find_user_by_role(next_step.approver_role)
            if approver:
                self.notifier.notify(
                    user_id=approver,
                    message=f"冲突解决方案待审批 (Step {next_step.step_number}): {task_id}"
                )
            return {"status": "pending_next_step", "next_step": next_step.step_number}
        else:
            # 全部通过，可以执行解决
            return {"status": "fully_approved", "can_execute": True}
```

---

## 8D: 平台绑定 - Series/Study/Patient

### 绑定数据模型

```python
# binding/platform_binding.py
from dataclasses import dataclass
from typing import List, Optional, Dict
from datetime import datetime
from enum import Enum

class BindingStatus(Enum):
    ACTIVE = "active"           # 活跃绑定
    SUPERSEDED = "superseded" # 已被修订版替代
    MERGED = "merged"         # 已合并到其他记录
    DELETED = "deleted"       # 已删除

@dataclass
class PlatformBinding:
    """
    平台绑定记录
    内部技术绑定，用于追踪数据存储
    """
    id: str
    binding_type: str  # series, study, patient
    entity_uid: str    # SeriesUID/StudyUID/PatientID
    
    # 存储位置
    primary_location: Dict  # 主要存储位置
    replica_locations: List[Dict]  # 副本位置
    
    # 绑定元数据
    schema_version: str
    status: BindingStatus
    created_at: datetime
    updated_at: datetime
    superseded_by: Optional[str] = None  # 被哪个新绑定替代
    merged_into: Optional[str] = None    # 合并到哪个绑定
    
    # 修订历史
    revision_history: List[Dict] = None

@dataclass
class ProductBinding:
    """
    产品绑定记录
    面向用户的产品功能绑定
    """
    id: str
    binding_type: str  # series, study, patient
    entity_uid: str
    
    # 产品元数据
    display_name: Optional[str]
    description: Optional[str]
    tags: List[str]
    custom_metadata: Dict
    
    # 绑定状态
    status: str  # active, archived, hidden
    created_at: datetime
    updated_at: datetime
    
    # 关联的平台绑定
    platform_binding_id: str

class BindingManager:
    """绑定管理器"""
    
    def __init__(self, db_session):
        self.db = db_session
    
    def create_series_binding(
        self,
        series_uid: str,
        storage_location: Dict,
        parsed_tags: Dict
    ) -> PlatformBinding:
        """
        创建Series平台绑定
        
        决策 Gap-2: Saga 模式事务
        """
        binding = PlatformBinding(
            id=self._generate_binding_id(),
            binding_type="series",
            entity_uid=series_uid,
            primary_location=storage_location,
            replica_locations=[],
            schema_version="1.0",
            status=BindingStatus.ACTIVE,
            created_at=datetime.now(),
            updated_at=datetime.now(),
            revision_history=[{
                "action": "created",
                "timestamp": datetime.now().isoformat(),
                "tags_snapshot": parsed_tags
            }]
        )
        
        self._persist_binding(binding)
        return binding
    
    def create_revision(
        self,
        existing_binding_id: str,
        new_storage_location: Dict,
        new_tags: Dict,
        revision_reason: str
    ) -> PlatformBinding:
        """
        创建修订版绑定
        保留历史，创建新版本
        """
        # 1. 获取现有绑定
        existing = self._get_binding(existing_binding_id)
        
        # 2. 创建新绑定
        new_binding = PlatformBinding(
            id=self._generate_binding_id(),
            binding_type=existing.binding_type,
            entity_uid=existing.entity_uid,
            primary_location=new_storage_location,
            replica_locations=[],
            schema_version=existing.schema_version,
            status=BindingStatus.ACTIVE,
            created_at=datetime.now(),
            updated_at=datetime.now()
        )
        
        # 3. 标记旧绑定为被替代
        existing.status = BindingStatus.SUPERSEDED
        existing.superseded_by = new_binding.id
        existing.revision_history.append({
            "action": "superseded",
            "timestamp": datetime.now().isoformat(),
            "new_binding_id": new_binding.id,
            "reason": revision_reason
        })
        
        # 4. 持久化
        self._update_binding(existing)
        self._persist_binding(new_binding)
        
        return new_binding
    
    def merge_bindings(
        self,
        source_binding_id: str,
        target_binding_id: str,
        merge_strategy: str
    ) -> PlatformBinding:
        """
        合并两个绑定
        用于解决Series合并冲突
        """
        source = self._get_binding(source_binding_id)
        target = self._get_binding(target_binding_id)
        
        # 合并存储位置
        target.replica_locations.append(source.primary_location)
        target.replica_locations.extend(source.replica_locations)
        
        # 标记源绑定
        source.status = BindingStatus.MERGED
        source.merged_into = target.id
        
        self._update_binding(source)
        self._update_binding(target)
        
        return target
```

---

## 8E: CLI Admin Tools

### CLI设计

```python
# cli/admin_cli.py
import click
from typing import Optional

@click.group()
def dicom_ingest():
    """DICOM摄入管理CLI"""
    pass

# ────────────────────────────────────────────────────────────────
# 作业管理命令
# ────────────────────────────────────────────────────────────────

@dicom_ingest.group()
def job():
    """作业管理"""
    pass

@job.command(name="list")
@click.option('--status', help='按状态过滤')
@click.option('--limit', default=20, help='返回数量')
@click.option('--actor', help='按创建者过滤')
def list_jobs(status: Optional[str], limit: int, actor: Optional[str]):
    """列出摄入作业"""
    client = get_authenticated_client()  # 决策 Gap-7: 服务账户Token
    
    params = {'limit': limit}
    if status:
        params['status'] = status
    if actor:
        params['actor_id'] = actor
    
    jobs = client.get('/api/v1/ingest/jobs', params=params)
    
    click.echo(f"{'Job ID':<40} {'Status':<15} {'Progress':<10} {'Created':<20}")
    click.echo("-" * 90)
    
    for job in jobs['items']:
        progress = f"{job['progress']['processed']}/{job['progress']['total']}"
        click.echo(
            f"{job['id']:<40} "
            f"{job['status']:<15} "
            f"{progress:<10} "
            f"{job['created_at'][:19]:<20}"
        )

@job.command()
@click.argument('job_id')
def show(job_id: str):
    """显示作业详情"""
    client = get_authenticated_client()
    job = client.get(f'/api/v1/ingest/jobs/{job_id}')
    
    click.echo(f"Job ID: {job['id']}")
    click.echo(f"Status: {job['status']}")
    click.echo(f"Progress: {job['progress']['percentage']:.1f}%")
    click.echo(f"Files: {job['progress']['processed']}/{job['progress']['total']}")
    
    if job.get('report'):
        click.echo("\nSummary:")
        click.echo(f"  Successful: {job['report']['summary']['successful']}")
        click.echo(f"  Duplicates: {job['report']['summary']['duplicates']}")
        click.echo(f"  Conflicts: {job['report']['summary']['conflicts']}")

@job.command()
@click.argument('job_id')
@click.confirmation_option(prompt='确定要重试失败的文件?')
def retry(job_id: str):
    """重试作业中的失败项"""
    client = get_authenticated_client()
    
    result = client.post(f'/api/v1/ingest/jobs/{job_id}/retry')
    click.echo(f"重试已启动: {result['message']}")

@job.command()
@click.argument('job_id')
@click.confirmation_option(prompt='确定要取消此作业?')
def cancel(job_id: str):
    """取消作业"""
    client = get_authenticated_client()
    
    try:
        result = client.post(f'/api/v1/ingest/jobs/{job_id}/cancel')
        click.echo(f"作业已取消: {result['status']}")
    except APIError as e:
        if e.status_code == 409:
            click.echo(f"无法取消: {e.response.get('message')}")
        else:
            raise

# ────────────────────────────────────────────────────────────────
# 冲突管理命令
# ────────────────────────────────────────────────────────────────

@dicom_ingest.group()
def conflict():
    """冲突管理"""
    pass

@conflict.command(name="list")
@click.option('--job-id', help='按作业过滤')
@click.option('--status', default='detected', help='按状态过滤')
@click.option('--limit', default=20)
def list_conflicts(job_id: Optional[str], status: str, limit: int):
    """列出冲突"""
    client = get_authenticated_client()
    
    params = {'status': status, 'limit': limit}
    if job_id:
        params['job_id'] = job_id
    
    conflicts = client.get('/api/v1/conflicts', params=params)
    
    click.echo(f"Total conflicts: {conflicts['total']}")
    click.echo(f"{'Conflict ID':<30} {'Type':<20} {'Status':<15} {'Files':<10}")
    click.echo("-" * 80)
    
    for c in conflicts['items']:
        click.echo(
            f"{c['id']:<30} "
            f"{c['type']:<20} "
            f"{c['status']:<15} "
            f"{len(c.get('files', [])):<10}"
        )

@conflict.command()
@click.argument('conflict_id')
def show(conflict_id: str):
    """显示冲突详情"""
    client = get_authenticated_client()
    c = client.get(f'/api/v1/conflicts/{conflict_id}')
    
    click.echo(f"Conflict ID: {c['id']}")
    click.echo(f"Type: {c['type']}")
    click.echo(f"Severity: {c['severity']}")
    click.echo(f"Status: {c['status']}")
    click.echo(f"\nSeries UID: {c['series_uid']}")
    click.echo(f"Files: {len(c['files'])}")
    
    if c.get('details'):
        click.echo(f"\nDetails:")
        for key, value in c['details'].items():
            click.echo(f"  {key}: {value}")

@conflict.command()
@click.argument('conflict_id')
@click.option('--strategy', 
              type=click.Choice(['merge', 'replace', 'skip', 'create_revision']),
              prompt='解决策略')
@click.option('--dry-run', is_flag=True, help='预览解决结果')
def resolve(conflict_id: str, strategy: str, dry_run: bool):
    """解决冲突"""
    client = get_authenticated_client()
    
    if dry_run:
        preview = client.get(f'/api/v1/conflicts/{conflict_id}/preview')
        click.echo("解决预览:")
        click.echo(f"  影响Series: {preview['will_affect']['series_count']}")
        click.echo(f"  影响文件: {preview['will_affect']['file_count']}")
        if preview.get('warnings'):
            click.echo("\n警告:")
            for w in preview['warnings']:
                click.echo(f"  ⚠️  {w}")
        return
    
    # 实际解决
    try:
        result = client.post(
            f'/api/v1/conflicts/{conflict_id}/resolve',
            json={'resolution_strategy': strategy}
        )
        click.echo(f"冲突已解决: {result['status']}")
        click.echo(f"执行操作: {result['action_taken']}")
    except APIError as e:
        if e.status_code == 202:
            click.echo(f"解决过程异步进行中，Saga ID: {e.response.get('saga_id')}")
        elif e.status_code == 409:
            click.echo(f"冲突状态已变更，请刷新: {e.response.get('message')}")
        else:
            raise

# ────────────────────────────────────────────────────────────────
# 存储管理命令
# ────────────────────────────────────────────────────────────────

@dicom_ingest.group()
def storage():
    """存储管理"""
    pass

@storage.command()
@click.argument('series_uid')
def locate(series_uid: str):
    """查找Series存储位置"""
    client = get_authenticated_client()
    
    files = client.get(f'/api/v1/series/{series_uid}/files')
    
    click.echo(f"Series: {series_uid}")
    click.echo(f"Total files: {len(files)}\n")
    
    for f in files:
        click.echo(f"SOP: {f['sop_instance_uid'][:30]}...")
        click.echo(f"  Mode: {f['storage_mode']}")
        click.echo(f"  URI: {f['storage_uri'][:60]}...")
        click.echo(f"  Size: {f['file_size'] / 1024 / 1024:.2f} MB")
        click.echo()

# ────────────────────────────────────────────────────────────────
# 认证配置
# ────────────────────────────────────────────────────────────────

def get_authenticated_client():
    """获取认证客户端（决策 Gap-7）"""
    # 1. 尝试从环境获取服务账户token
    token = os.environ.get('DICOM_INGEST_TOKEN')
    
    if not token:
        # 2. 尝试从配置文件读取
        config_path = Path.home() / '.dicom_ingest' / 'config.json'
        if config_path.exists():
            with open(config_path) as f:
                config = json.load(f)
                token = config.get('token')
    
    if not token:
        click.echo("Error: 未配置认证token", err=True)
        click.echo("请设置 DICOM_INGEST_TOKEN 环境变量或运行 'dicom-ingest auth login'", err=True)
        raise click.Abort()
    
    return APIClient(
        base_url=os.environ.get('DICOM_INGEST_API', 'http://localhost:8080'),
        token=token
    )
```

---

## 8F: Authentication & Permissions

### 认证实现

```python
# auth/auth_system.py
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import jwt
from datetime import datetime, timedelta
from typing import Optional, Dict

security = HTTPBearer()

class AuthSystem:
    """
    认证与权限系统
    决策 Gap-7: Token-based认证
    """
    
    def __init__(self, secret_key: str, algorithm: str = "HS256"):
        self.secret_key = secret_key
        self.algorithm = algorithm
    
    def create_access_token(
        self,
        user_id: str,
        roles: List[str],
        expires_delta: Optional[timedelta] = None
    ) -> str:
        """创建访问token"""
        to_encode = {
            "sub": user_id,
            "roles": roles,
            "type": "access",
            "iat": datetime.utcnow(),
            "exp": datetime.utcnow() + (expires_delta or timedelta(hours=24))
        }
        return jwt.encode(to_encode, self.secret_key, algorithm=self.algorithm)
    
    def create_service_account_token(
        self,
        service_name: str,
        permissions: List[str],
        expires_delta: Optional[timedelta] = None
    ) -> str:
        """创建服务账户token（用于CLI/自动化）"""
        to_encode = {
            "sub": f"service:{service_name}",
            "permissions": permissions,
            "type": "service_account",
            "iat": datetime.utcnow(),
            "exp": datetime.utcnow() + (expires_delta or timedelta(days=90))
        }
        return jwt.encode(to_encode, self.secret_key, algorithm=self.algorithm)
    
    def verify_token(self, token: str) -> Dict:
        """验证token"""
        try:
            payload = jwt.decode(
                token, 
                self.secret_key, 
                algorithms=[self.algorithm]
            )
            return payload
        except jwt.ExpiredSignatureError:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token已过期"
            )
        except jwt.InvalidTokenError:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="无效的token"
            )


# FastAPI依赖
async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    auth: AuthSystem = Depends(get_auth_system)
) -> Dict:
    """获取当前用户（API端点依赖）"""
    return auth.verify_token(credentials.credentials)


async def require_role(required_roles: List[str]):
    """角色要求装饰器"""
    async def role_checker(user: Dict = Depends(get_current_user)):
        user_roles = user.get('roles', [])
        if not any(r in user_roles for r in required_roles):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"需要角色: {required_roles}"
            )
        return user
    return role_checker


# 使用示例
from fastapi import FastAPI

app = FastAPI()

@app.post("/api/v1/ingest/folder")
async def create_folder_ingest(
    request: FolderIngestRequest,
    user: Dict = Depends(get_current_user)
):
    """创建文件夹摄入 - 需要登录"""
    # 检查权限
    if 'ingest:create' not in user.get('permissions', []):
        raise HTTPException(403, "无摄入权限")
    
    # 创建作业...
    return {"job_id": "..."}


@app.post("/api/v1/admin/binding-migration")
async def admin_migration(
    user: Dict = Depends(require_role(['admin', 'super_admin']))
):
    """管理操作 - 需要管理员角色"""
    pass
```

---

## Phase 3 集成验证

### 端到端场景测试

```python
def test_phase3_end_to_end():
    """测试Phase 3完整流程"""
    
    # 1. 获取认证
    auth = AuthSystem(secret_key="test_key")
    user_token = auth.create_access_token(
        user_id="user_123",
        roles=["data_operator"],
        permissions=["ingest:create", "conflict:resolve"]
    )
    
    # 2. 创建文件夹摄入作业（通过API）
    client = APIClient(token=user_token)
    job = client.post("/api/v1/ingest/folder", json={
        "folder_path": "/data/test_dicom",
        "recursive": True
    })
    
    # 3. 等待完成并检查报告
    job_status = client.get(f"/api/v1/ingest/jobs/{job['job_id']}")
    assert job_status['status'] == 'completed'
    
    # 4. 查询摄入的数据
    series_list = client.get("/api/v1/series", params={
        "modality": "MR",
        "limit": 10
    })
    assert len(series_list['items']) > 0
    
    # 5. 如果有冲突，使用CLI风格解决
    conflicts = client.get(
        "/api/v1/conflicts",
        params={"job_id": job['job_id']}
    )
    
    if conflicts['total'] > 0:
        conflict = conflicts['items'][0]
        
        # 预览解决
        preview = client.get(
            f"/api/v1/conflicts/{conflict['id']}/preview"
        )
        
        # 执行解决（使用Saga事务）
        result = client.post(
            f"/api/v1/conflicts/{conflict['id']}/resolve",
            json={"resolution_strategy": "merge"}
        )
        
        # 验证解决
        resolved = client.get(f"/api/v1/conflicts/{conflict['id']}")
        assert resolved['status'] == 'resolved'
    
    print("Phase 3 end-to-end test passed!")
```

---

**文档状态**: Phase 3 详细设计 - 完成
**依赖**: Phase 1 & Phase 2
**下一步**: 实施开始

## 三阶段汇总

| Phase | 目标 | 主要交付 | 工期 |
|-------|-----|---------|-----|
| Phase 1 | 基础稳定 | 7G+7A+7B+7C | 3-4周 |
| Phase 2 | 摄入管道 | 7D+7E+7F | 3-4周 |
| Phase 3 | 产品表面 | 8A+8B+8C+8D+8E+8F | 3-4周 |

**总计**: 9-12周完成Batch 7+8全部功能
