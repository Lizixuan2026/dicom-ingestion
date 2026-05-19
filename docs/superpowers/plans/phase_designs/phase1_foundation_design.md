# Phase 1: 基础稳定 - 详细设计

**目标**: 建立稳定的平台基础组件，确保解析、存储、路径生成核心能力就绪
**交付顺序**: 7G → 7A → 7B → 7C
**预计工期**: 3-4 周

---

## 7G: Binding Vocabulary Cleanup

### 目标
统一术语系统，消除平台绑定与产品绑定概念混淆

### 实现步骤

**Step 1: 术语映射表 (1 天)**
```yaml
# config/binding_vocabulary_v2.yaml
version: "2.0"
terms:
  platform_binding:
    alias: ["技术绑定", "存储绑定", "内部引用"]
    description: 系统内部用于追踪数据存储位置的技术标识
    scope: 内部系统，对用户不可见
    
  product_binding:
    alias: ["业务绑定", "客户绑定", "应用绑定"]
    description: 面向用户的产品功能，关联数据到具体业务场景
    scope: 用户可见，可管理
    
  deprecated:
    - term: "object_binding"
      reason: 与product_binding混淆
      migration: 重命名为platform_binding
    - term: "instance_binding"
      reason: 语义不清
      migration: 根据上下文选择platform_binding或product_binding
```

**Step 2: 代码重命名 (1 天)**
```python
# 重命名策略：使用IDE重构工具，保留提交历史

# 文件重命名
object_binding.py → platform_binding.py
InstanceBindingService → PlatformBindingService

# 数据库迁移
ALTER TABLE object_bindings RENAME TO platform_bindings;
ALTER TABLE platform_bindings ADD COLUMN binding_type VARCHAR(32) DEFAULT 'storage';
```

**Step 3: API兼容性层 (1 天)**
```python
# platform_binding/compat_layer.py
from typing import Optional
import warnings

class ObjectBindingCompat:
    """
    临时兼容层，允许旧API调用逐步迁移
    计划在 v1.2 移除
    """
    
    def __init__(self, platform_binding_service):
        self._service = platform_binding_service
        
    def get_object_binding(self, object_id: str):
        warnings.warn(
            "ObjectBinding API已弃用，请迁移到 PlatformBinding",
            DeprecationWarning,
            stacklevel=2
        )
        return self._service.get_platform_binding(object_id)
```

### 验收标准
- [ ] 所有代码文件使用新术语
- [ ] 数据库Schema更新完成
- [ ] 旧API通过兼容层仍可工作（标记为deprecated）
- [ ] 术语文档已同步到所有开发团队

---

## 7A: Parser Seam + Tag Schema

### 目标
建立可扩展的DICOM解析框架，支持动态标签提取配置

### 核心组件设计

**1. Tag Schema 配置系统**
```yaml
# schemas/tag_schema_v1.yaml
schema_version: "1.0"
name: "default_dicom_schema"
description: "标准DICOM标签提取配置"

extractors:
  # 标准标签 - 必填
  standard:
    - tag: "(0010,0010)"  # PatientName
      alias: "patient_name"
      required: true
      
    - tag: "(0020,000D)"  # StudyInstanceUID
      alias: "study_uid"
      required: true
      validation:
        pattern: "^1.2\\.\\d+\\.\\d+$"
        
    - tag: "(0020,000E)"  # SeriesInstanceUID
      alias: "series_uid"
      required: true
      
    - tag: "(0008,0060)"  # Modality
      alias: "modality"
      required: true
      transform: "uppercase"
      
  # 设备元数据
  device:
    - tag: "(0008,0070)"  # Manufacturer
      alias: "vendor"
      
    - tag: "(0008,1090)"  # ManufacturerModelName
      alias: "device_model"
      
  # 私有标签 - MeasUID提取器
  private:
    - name: "meas_uid_siemens"
      selector:
        manufacturer: "SIEMENS"
        modality: ["MR", "CT"]
      block: "(0029,10)"  # 私有数据块
      extractor_class: "SiemensMeasUIDExtractor"
      output_key: "meas_uid"
      
    - name: "meas_uid_uih"
      selector:
        manufacturer: "UIH"
        modality: ["MR"]
      block: "(0029,xx)"  # 动态检测
      extractor_class: "UIHMeasUIDExtractor"
      output_key: "meas_uid"
```

**2. Extractor 接口定义**
```python
# parser/tag_extractors/base.py
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional
import pydicom

class TagExtractor(ABC):
    """
    标签提取器基类
    所有自定义提取器必须继承此类
    """
    
    @property
    @abstractmethod
    def name(self) -> str:
        """提取器唯一标识名"""
        pass
    
    @abstractmethod
    def can_extract(self, ds: pydicom.Dataset) -> bool:
        """
        检查此提取器是否适用于给定DICOM数据集
        
        Args:
            ds: pydicom Dataset对象
            
        Returns:
            True如果可以提取，False跳过
        """
        pass
    
    @abstractmethod
    def extract(self, ds: pydicom.Dataset) -> Dict[str, Any]:
        """
        执行提取
        
        Args:
            ds: pydicom Dataset对象
            
        Returns:
            提取的标签字典 {alias: value}
            
        Raises:
            ExtractionError: 提取失败时抛出
        """
        pass
    
    def validate(self, value: Any) -> bool:
        """
        可选：验证提取值
        默认返回True
        """
        return True


class SiemensMeasUIDExtractor(TagExtractor):
    """Siemens设备MeasUID提取器"""
    
    name = "meas_uid_siemens"
    
    def can_extract(self, ds: pydicom.Dataset) -> bool:
        manufacturer = str(ds.get((0x0008, 0x0070), "")).upper()
        modality = str(ds.get((0x0008, 0x0060), "")).upper()
        return "SIEMENS" in manufacturer and modality in ["MR", "CT"]
    
    def extract(self, ds: pydicom.Dataset) -> Dict[str, Any]:
        # Siemens私有标签通常在 (0029,10xx) 块
        # 需要遍历寻找meas_uid字段
        meas_uid = None
        
        # 常见位置尝试
        for tag in [(0x0029, 0x1010), (0x0029, 0x1020), (0x0029, 0x1030)]:
            if tag in ds:
                data = ds[tag].value
                # 解析私有数据块寻找MeasUID
                if isinstance(data, bytes):
                    meas_uid = self._parse_siemens_private_block(data)
                    if meas_uid:
                        break
        
        return {"meas_uid": meas_uid} if meas_uid else {}
    
    def _parse_siemens_private_block(self, data: bytes) -> Optional[str]:
        """解析Siemens私有数据块"""
        # 实现细节：解析CSA头部或其他私有格式
        # 简化版：查找"MeasUID"字符串模式
        try:
            decoded = data.decode('utf-8', errors='ignore')
            # 提取逻辑根据实际Siemens格式调整
            if "MeasUID" in decoded:
                # 提取后续值
                idx = decoded.find("MeasUID") + len("MeasUID")
                # 假设MeasUID是32字符十六进制
                potential_uid = decoded[idx:idx+32].strip()
                if len(potential_uid) >= 16:
                    return potential_uid
        except:
            pass
        return None


class UIHMeasUIDExtractor(TagExtractor):
    """UIH联影设备MeasUID提取器"""
    
    name = "meas_uid_uih"
    
    def can_extract(self, ds: pydicom.Dataset) -> bool:
        manufacturer = str(ds.get((0x0008, 0x0070), "")).upper()
        return "UIH" in manufacturer or "UNITED IMAGING" in manufacturer
    
    def extract(self, ds: pydicom.Dataset) -> Dict[str, Any]:
        # UIH私有标签位置
        # 需要在实际数据上测试确定
        meas_uid = None
        
        # 尝试常见位置
        for tag in [(0x0029, 0x0010), (0x0029, 0x0020), (0x0029, 0x1101)]:
            if tag in ds:
                data = ds[tag].value
                meas_uid = self._parse_uih_private_block(data)
                if meas_uid:
                    break
        
        return {"meas_uid": meas_uid} if meas_uid else {}
    
    def _parse_uih_private_block(self, data) -> Optional[str]:
        """解析UIH私有数据块"""
        if isinstance(data, str):
            return data.strip() if len(data.strip()) > 10 else None
        elif isinstance(data, bytes):
            try:
                decoded = data.decode('utf-8', errors='ignore').strip()
                return decoded if len(decoded) > 10 else None
            except:
                return None
        return None
```

**3. Parser Factory 实现**
```python
# parser/factory.py
from typing import Dict, Type, Optional, List
from dataclasses import dataclass
import yaml
import pydicom

@dataclass
class ParseResult:
    """解析结果数据类"""
    tags: Dict[str, any]
    file_meta: Dict[str, any]
    extractors_used: List[str]
    warnings: List[str]
    schema_version: str

class DicomParserFactory:
    """
    DICOM解析器工厂
    支持动态配置的标签提取
    """
    
    _extractors: Dict[str, Type] = {}
    _schemas: Dict[str, dict] = {}
    
    @classmethod
    def register_extractor(cls, extractor_class: Type[TagExtractor]):
        """注册自定义提取器"""
        instance = extractor_class()
        cls._extractors[instance.name] = extractor_class
        return extractor_class
    
    @classmethod
    def load_schema(cls, schema_path: str) -> dict:
        """加载标签Schema配置"""
        with open(schema_path, 'r') as f:
            schema = yaml.safe_load(f)
            cls._schemas[schema['name']] = schema
            return schema
    
    @classmethod
    def create_parser(cls, schema_name: str = "default_dicom_schema"):
        """创建配置化解析器"""
        schema = cls._schemas.get(schema_name)
        if not schema:
            raise ValueError(f"Unknown schema: {schema_name}")
        return ConfigurableDicomParser(schema, cls._extractors)


class ConfigurableDicomParser:
    """配置驱动的DICOM解析器"""
    
    def __init__(self, schema: dict, extractors: Dict[str, Type]):
        self.schema = schema
        self.extractors = extractors
        self._extractor_instances: Dict[str, TagExtractor] = {}
    
    def parse(self, file_path: str) -> ParseResult:
        """
        解析DICOM文件
        
        决策 Gap-5 实施: 流式头部解析 + 延迟像素数据加载
        """
        warnings = []
        
        # 流式读取 - 仅加载元数据，延迟加载像素数据
        ds = pydicom.dcmread(
            file_path,
            defer_size="1KB",  # 大于1KB的数据元素延迟加载
            force=True,
            stop_before_pixels=True  # 先不读取像素数据
        )
        
        # 检查文件大小，大文件特殊处理
        file_size = Path(file_path).stat().st_size
        if file_size > 512 * 1024 * 1024:  # 512MB+
            warnings.append(f"Large file detected: {file_size / (1024*1024):.1f}MB")
        
        tags = {}
        extractors_used = []
        
        # 1. 提取标准标签
        for std_config in self.schema.get('extractors', {}).get('standard', []):
            value = self._extract_standard_tag(ds, std_config)
            if value is not None:
                tags[std_config['alias']] = value
        
        # 2. 提取设备元数据
        for device_config in self.schema.get('extractors', {}).get('device', []):
            value = self._extract_standard_tag(ds, device_config)
            if value is not None:
                tags[device_config['alias']] = value
        
        # 3. 私有标签 - 使用匹配提取器
        for private_config in self.schema.get('extractors', {}).get('private', []):
            extractor_name = private_config.get('extractor_class', '').replace('Extractor', '').lower()
            
            if extractor_name in self.extractors:
                extractor = self._get_extractor(extractor_name)
                
                if extractor.can_extract(ds):
                    extracted = extractor.extract(ds)
                    tags.update(extracted)
                    extractors_used.append(extractor.name)
        
        # 文件元数据
        file_meta = {
            "file_size": file_size,
            "file_path": file_path,
            "transfer_syntax": str(ds.file_meta.TransferSyntaxUID) if hasattr(ds, 'file_meta') else None
        }
        
        return ParseResult(
            tags=tags,
            file_meta=file_meta,
            extractors_used=extractors_used,
            warnings=warnings,
            schema_version=self.schema.get('schema_version', '1.0')
        )
    
    def _extract_standard_tag(self, ds: pydicom.Dataset, config: dict) -> any:
        """提取标准DICOM标签"""
        tag_str = config['tag']
        # 解析 (gggg,eeee) 格式
        group, element = tag_str.strip('()').split(',')
        tag = (int(group, 16), int(element, 16))
        
        value = ds.get(tag)
        if value is None:
            return None
        
        # 应用转换
        transform = config.get('transform')
        if transform == 'uppercase':
            value = str(value).upper()
        elif transform == 'lowercase':
            value = str(value).lower()
        
        return str(value) if value else None
    
    def _get_extractor(self, name: str) -> TagExtractor:
        """获取或创建提取器实例（单例）"""
        if name not in self._extractor_instances:
            self._extractor_instances[name] = self.extractors[name]()
        return self._extractor_instances[name]


# 自动注册提取器
def auto_register_extractors():
    """自动发现并注册所有提取器"""
    import importlib
    import pkgutil
    
    package = importlib.import_module('parser.tag_extractors')
    
    for _, name, _ in pkgutil.iter_modules(package.__path__):
        if name.endswith('_extractor'):
            module = importlib.import_module(f'parser.tag_extractors.{name}')
            for attr_name in dir(module):
                attr = getattr(module, attr_name)
                if (isinstance(attr, type) and 
                    issubclass(attr, TagExtractor) and 
                    attr is not TagExtractor):
                    DicomParserFactory.register_extractor(attr)

auto_register_extractors()
```

**4. Schema 版本管理**
```python
# parser/schema_manager.py
from typing import Dict, Optional
import json
from datetime import datetime

class SchemaManager:
    """
    Schema版本管理
    决策 Gap-4 实施: 按需重解析（Lazy）+ 投影标记陈旧
    """
    
    def __init__(self, db_session):
        self.db = db_session
    
    def check_schema_compatibility(
        self, 
        current_schema: str, 
        stored_schema: str
    ) -> bool:
        """检查存储的Schema是否与当前兼容"""
        current = self._parse_version(current_schema)
        stored = self._parse_version(stored_schema)
        
        # 主版本变更需要重解析
        if current[0] != stored[0]:
            return False
        
        # 次版本变更 - 检查是否有新增必填字段
        if current[1] > stored[1]:
            return self._check_additions_required(current_schema, stored_schema)
        
        return True
    
    def mark_stale_projections(self, schema_version: str):
        """
        标记使用旧Schema的投影为陈旧
        异步任务会按需重解析
        """
        query = """
        UPDATE dicom_series 
        SET projection_status = 'stale',
            stale_reason = 'schema_updated',
            needs_reparse = TRUE,
            updated_at = NOW()
        WHERE extracted_schema_version != :schema_version
          AND projection_status = 'current'
        """
        self.db.execute(query, {"schema_version": schema_version})
        
        # 记录统计
        affected = self.db.rowcount
        logger.info(f"Marked {affected} projections as stale due to schema update")
        
        return affected
    
    def _parse_version(self, version: str) -> tuple:
        """解析版本号 x.y.z"""
        parts = version.split('.')
        return tuple(int(p) for p in parts[:3])
    
    def _check_additions_required(self, current: str, stored: str) -> bool:
        """检查是否有新增必填字段"""
        # 获取两个版本的Schema差异
        current_schema = self._load_schema_config(current)
        stored_schema = self._load_schema_config(stored)
        
        # 检查是否有新的required字段
        for category in ['standard', 'device', 'private']:
            current_fields = {
                e['alias'] for e in current_schema.get('extractors', {}).get(category, [])
                if e.get('required', False)
            }
            stored_fields = {
                e['alias'] for e in stored_schema.get('extractors', {}).get(category, [])
                if e.get('required', False)
            }
            
            new_required = current_fields - stored_fields
            if new_required:
                return False  # 有新的必填字段，需要重解析
        
        return True
```

### 验收标准
- [ ] Tag Schema配置可动态加载
- [ ] Siemens/UIH MeasUID提取器正确识别对应设备
- [ ] 新解析框架可扩展，注册新提取器无需修改核心代码
- [ ] 流式解析大文件不OOM
- [ ] Schema版本变更自动标记投影陈旧

---

## 7B: Dual Storage Backend

### 目标
实现双存储模式：对象存储（MinIO/S3）用于系统处理，本地/NAS存储用于人可读归档

### 架构设计

```
┌─────────────────────────────────────────────────────────────────┐
│                    StorageBackend (Abstract)                    │
├─────────────────────────────────────────────────────────────────┤
│  + store(file_path, dest_path) -> StorageLocation               │
│  + retrieve(location) -> file_stream                            │
│  + delete(location) -> bool                                     │
│  + exists(location) -> bool                                     │
│  + get_metadata(location) -> dict                               │
└─────────────────────────────────────────────────────────────────┘
                              ▲
              ┌───────────────┴───────────────┐
              │                               │
┌───────────────────────────┐   ┌───────────────────────────────┐
│   ObjectStorageBackend    │   │   LocalNASStorageBackend      │
├───────────────────────────┤   ├───────────────────────────────┤
│  - minio_client           │   │  - base_path                    │
│  - bucket_name            │   │  - path_generator               │
├───────────────────────────┤   ├───────────────────────────────┤
│  + store()                │   │  + store()                      │
│  + retrieve()             │   │  + retrieve()                   │
│  + generate_hash_path()   │   │  + generate_hierarchical_path() │
└───────────────────────────┘   └───────────────────────────────┘
```

### 实现代码

**1. 抽象基类**
```python
# storage/base.py
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import BinaryIO, Optional, Dict
from enum import Enum

class StorageMode(Enum):
    OBJECT = "object"      # MinIO/S3
    LOCAL_NAS = "local_nas"  # 本地/NAS

@dataclass
class StorageLocation:
    mode: StorageMode
    uri: str                    # 存储URI
    path: str                   # 实际路径/对象键
    bucket: Optional[str]     # 对象存储bucket
    metadata: Dict              # 存储元数据
    checksum: str               # 校验和

class StorageBackend(ABC):
    """存储后端抽象基类"""
    
    @abstractmethod
    def store(
        self, 
        source_path: str, 
        destination_hint: str,
        metadata: Optional[Dict] = None
    ) -> StorageLocation:
        """
        存储文件
        
        Args:
            source_path: 源文件本地路径
            destination_hint: 目标路径提示（可能包含命名建议）
            metadata: 附加元数据
            
        Returns:
            StorageLocation对象
        """
        pass
    
    @abstractmethod
    def retrieve(self, location: StorageLocation) -> BinaryIO:
        """检索文件为流"""
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
    def get_metadata(self, location: StorageLocation) -> Dict:
        """获取存储元数据"""
        pass
```

**2. 对象存储实现**
```python
# storage/object_storage.py
import hashlib
import io
from pathlib import Path
from typing import BinaryIO, Optional, Dict
import minio
from minio.error import S3Error

class ObjectStorageBackend(StorageBackend):
    """
    MinIO/S3对象存储后端
    使用哈希路径避免文件系统限制
    """
    
    def __init__(
        self,
        endpoint: str,
        access_key: str,
        secret_key: str,
        bucket_name: str,
        secure: bool = True,
        prefix: str = "dicom"
    ):
        self.client = minio.Minio(
            endpoint,
            access_key=access_key,
            secret_key=secret_key,
            secure=secure
        )
        self.bucket = bucket_name
        self.prefix = prefix
        
        # 确保bucket存在
        if not self.client.bucket_exists(bucket_name):
            self.client.make_bucket(bucket_name)
    
    def store(
        self,
        source_path: str,
        destination_hint: str,
        metadata: Optional[Dict] = None
    ) -> StorageLocation:
        """
        存储到对象存储
        路径格式: {prefix}/{hash_prefix}/{hash_suffix}/{filename}.dcm
        """
        # 计算文件哈希
        file_hash = self._calculate_file_hash(source_path)
        
        # 生成哈希路径 (前2位作为前缀，避免单个目录过大)
        hash_prefix = file_hash[:2]
        hash_suffix = file_hash[2:]
        
        # 从hint提取文件名
        filename = Path(destination_hint).name
        if not filename.endswith('.dcm'):
            filename += '.dcm'
        
        object_key = f"{self.prefix}/{hash_prefix}/{hash_suffix}/{filename}"
        
        # 准备元数据
        tags = metadata or {}
        tags['x-amz-meta-original-hint'] = destination_hint
        tags['x-amz-meta-content-hash'] = file_hash
        
        # 上传
        self.client.fput_object(
            self.bucket,
            object_key,
            source_path,
            tags=tags
        )
        
        # 构建URI
        uri = f"s3://{self.bucket}/{object_key}"
        
        return StorageLocation(
            mode=StorageMode.OBJECT,
            uri=uri,
            path=object_key,
            bucket=self.bucket,
            metadata=tags,
            checksum=file_hash
        )
    
    def retrieve(self, location: StorageLocation) -> BinaryIO:
        """从对象存储检索"""
        response = self.client.get_object(
            location.bucket or self.bucket,
            location.path
        )
        return io.BytesIO(response.read())
    
    def delete(self, location: StorageLocation) -> bool:
        """从对象存储删除"""
        try:
            self.client.remove_object(
                location.bucket or self.bucket,
                location.path
            )
            return True
        except S3Error:
            return False
    
    def exists(self, location: StorageLocation) -> bool:
        """检查对象是否存在"""
        try:
            self.client.stat_object(
                location.bucket or self.bucket,
                location.path
            )
            return True
        except S3Error:
            return False
    
    def get_metadata(self, location: StorageLocation) -> Dict:
        """获取对象元数据"""
        stat = self.client.stat_object(
            location.bucket or self.bucket,
            location.path
        )
        return {
            "size": stat.size,
            "etag": stat.etag,
            "last_modified": stat.last_modified,
            "metadata": stat.metadata
        }
    
    def _calculate_file_hash(self, file_path: str) -> str:
        """计算文件SHA256哈希"""
        sha256_hash = hashlib.sha256()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                sha256_hash.update(chunk)
        return sha256_hash.hexdigest()
```

**3. 本地/NAS存储实现**
```python
# storage/local_nas_storage.py
import shutil
import hashlib
from pathlib import Path
from typing import BinaryIO, Optional, Dict
import os

class LocalNASStorageBackend(StorageBackend):
    """
    本地/NAS存储后端
    支持层级路径，保持人可读
    """
    
    def __init__(
        self,
        base_path: str,
        path_generator,  # PathGenerator实例
        create_dirs: bool = True,
        copy_mode: bool = True  # True=复制, False=移动
    ):
        self.base_path = Path(base_path)
        self.path_generator = path_generator
        self.copy_mode = copy_mode
        
        if create_dirs:
            self.base_path.mkdir(parents=True, exist_ok=True)
    
    def store(
        self,
        source_path: str,
        destination_hint: str,
        metadata: Optional[Dict] = None
    ) -> StorageLocation:
        """
        存储到本地/NAS
        使用层级路径: DICOM_{MODALITY}/{VENDOR}/{DEVICE}/{StudyUID}/{MeasUID}/{SeriesUID}/{SOP}.dcm
        """
        source = Path(source_path)
        
        # 使用path_generator生成层级路径
        relative_path = self.path_generator.generate_path(
            dicom_tags=metadata or {},
            original_filename=source.name
        )
        
        # 检查路径长度限制 (决策 Gap-1)
        full_path = self._ensure_path_length(self.base_path / relative_path)
        
        # 确保目录存在
        full_path.parent.mkdir(parents=True, exist_ok=True)
        
        # 复制或移动文件
        if self.copy_mode:
            shutil.copy2(source_path, full_path)
        else:
            shutil.move(source_path, full_path)
        
        # 计算校验和
        checksum = self._calculate_file_hash(str(full_path))
        
        # 构建URI
        uri = f"file://{full_path.absolute()}"
        
        return StorageLocation(
            mode=StorageMode.LOCAL_NAS,
            uri=uri,
            path=str(full_path.relative_to(self.base_path)),
            bucket=None,
            metadata={
                "original_hint": destination_hint,
                **(metadata or {})
            },
            checksum=checksum
        )
    
    def retrieve(self, location: StorageLocation) -> BinaryIO:
        """检索本地文件"""
        full_path = self.base_path / location.path
        return open(full_path, 'rb')
    
    def delete(self, location: StorageLocation) -> bool:
        """删除本地文件"""
        try:
            full_path = self.base_path / location.path
            full_path.unlink()
            return True
        except OSError:
            return False
    
    def exists(self, location: StorageLocation) -> bool:
        """检查文件是否存在"""
        full_path = self.base_path / location.path
        return full_path.exists()
    
    def get_metadata(self, location: StorageLocation) -> Dict:
        """获取文件元数据"""
        full_path = self.base_path / location.path
        stat = full_path.stat()
        return {
            "size": stat.st_size,
            "mtime": stat.st_mtime,
            "mode": stat.st_mode
        }
    
    def _ensure_path_length(self, path: Path, max_length: int = 4096) -> Path:
        """
        确保路径长度不超过限制
        决策 Gap-1: 路径长度限制处理
        """
        str_path = str(path)
        if len(str_path) <= max_length:
            return path
        
        # 路径过长，使用哈希缩短
        # 保留基础层级，对最深层使用哈希
        parts = path.parts
        if len(parts) > 4:
            # 对最后几个部分使用哈希
            to_hash = '/'.join(parts[-3:])
            hash_suffix = hashlib.sha256(to_hash.encode()).hexdigest()[:16]
            new_parts = parts[:-3] + (f"HASH_{hash_suffix}",)
            new_path = Path(*new_parts)
            
            # 递归检查
            if len(str(new_path)) > max_length:
                # 仍然过长，进一步缩短
                return self._ensure_path_length(new_path, max_length)
            return new_path
        
        return path
    
    def _calculate_file_hash(self, file_path: str) -> str:
        """计算文件SHA256哈希"""
        sha256_hash = hashlib.sha256()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                sha256_hash.update(chunk)
        return sha256_hash.hexdigest()
```

**4. 存储管理器（统一入口）**
```python
# storage/manager.py
from typing import Dict, Optional, List
import os

class StorageManager:
    """
    统一存储管理器
    协调双存储模式
    """
    
    def __init__(
        self,
        object_backend: Optional[StorageBackend] = None,
        local_backend: Optional[StorageBackend] = None,
        dual_write: bool = False  # 是否双写
    ):
        self.object_backend = object_backend
        self.local_backend = local_backend
        self.dual_write = dual_write
    
    def store_for_processing(
        self,
        file_path: str,
        metadata: Dict
    ) -> StorageLocation:
        """
        存储到处理存储（对象存储）
        系统内部使用，优化处理速度
        """
        if not self.object_backend:
            raise RuntimeError("Object storage not configured")
        
        return self.object_backend.store(
            file_path,
            metadata.get('suggested_path', ''),
            metadata
        )
    
    def store_for_archive(
        self,
        file_path: str,
        metadata: Dict
    ) -> StorageLocation:
        """
        存储到归档存储（本地/NAS）
        人可读路径，便于直接访问
        """
        if not self.local_backend:
            raise RuntimeError("Local/NAS storage not configured")
        
        return self.local_backend.store(
            file_path,
            metadata.get('suggested_path', ''),
            metadata
        )
    
    def dual_store(
        self,
        file_path: str,
        metadata: Dict
    ) -> Dict[str, StorageLocation]:
        """
        双模式存储
        同时存储到对象存储和本地/NAS
        返回两个Location
        """
        results = {}
        
        if self.object_backend:
            results['object'] = self.store_for_processing(file_path, metadata)
        
        if self.local_backend:
            results['local'] = self.store_for_archive(file_path, metadata)
        
        return results
    
    def retrieve(self, location: StorageLocation) -> BinaryIO:
        """根据Location类型自动选择后端检索"""
        if location.mode == StorageMode.OBJECT and self.object_backend:
            return self.object_backend.retrieve(location)
        elif location.mode == StorageMode.LOCAL_NAS and self.local_backend:
            return self.local_backend.retrieve(location)
        else:
            raise ValueError(f"Unsupported storage mode: {location.mode}")
    
    def delete(self, location: StorageLocation) -> bool:
        """根据Location类型删除"""
        if location.mode == StorageMode.OBJECT and self.object_backend:
            return self.object_backend.delete(location)
        elif location.mode == StorageMode.LOCAL_NAS and self.local_backend:
            return self.local_backend.delete(location)
        return False
```

### 验收标准
- [ ] 对象存储使用哈希路径
- [ ] 本地/NAS使用层级路径
- [ ] 路径长度超限自动使用哈希缩短
- [ ] 双存储模式同时工作
- [ ] 存储位置URI可唯一标识文件

---

## 7C: Local/NAS Path Generator

### 目标
根据DICOM标签生成人可读的层级路径

### 路径模板设计

**模板格式**
```
DICOM_{MODALITY}/{VENDOR}/{DEVICE}/{StudyUID[:8]}/{MeasUID}/{SeriesUID[:8]}/{SOP}.dcm
```

**各组件处理规则**

| 组件 | 来源标签 | 处理方式 | 示例 |
|-----|---------|---------|------|
| MODALITY | (0008,0060) | 大写，默认"UNKNOWN" | "MR", "CT" |
| VENDOR | (0008,0070) | 清理特殊字符，默认"GENERIC" | "SIEMENS", "UIH" |
| DEVICE | (0008,1090) | 清理特殊字符，可选 | "Prisma" |
| StudyUID | (0020,000D) | 前8字符 | "1.2.3..." → "1.2.3..." |
| MeasUID | 私有标签提取 | 优先使用，回退SeriesUID | "meas_001" |
| SeriesUID | (0020,000E) | 前8字符 | "1.2.3..." → "1.2.3..." |
| SOP | (0008,0018) | 完整UID | "1.2.840..." |

### 实现代码

```python
# path_generator/local_nas.py
import re
import hashlib
from typing import Dict, Optional
from dataclasses import dataclass

@dataclass
class PathComponents:
    """路径组件数据类"""
    modality: str
    vendor: str
    device: Optional[str]
    study_uid: str
    meas_uid: Optional[str]
    series_uid: str
    sop_uid: str

class LocalNASPathGenerator:
    """
    本地/NAS层级路径生成器
    生成人可读的DICOM存储路径
    """
    
    # 路径模板
    TEMPLATE = (
        "DICOM_{modality}/{vendor}/{device}/{study_uid}/{meas_uid}/{series_uid}/{sop_uid}.dcm"
    )
    
    # 默认回退值
    DEFAULTS = {
        'modality': 'UNKNOWN',
        'vendor': 'GENERIC',
        'device': 'GENERIC',
    }
    
    # 厂商名称映射（清理用）
    VENDOR_CLEANUP = {
        'SIEMENS': ['SIEMENS', 'SIEMENS HEALTHCARE', 'SIEMENS MEDICAL'],
        'GE': ['GE', 'GE HEALTHCARE', 'GENERAL ELECTRIC'],
        'PHILIPS': ['PHILIPS', 'PHILIPS HEALTHCARE'],
        'UIH': ['UIH', 'UNITED IMAGING', 'UNITED IMAGING HEALTHCARE'],
        'CANON': ['CANON', 'CANON MEDICAL', 'TOSHIBA'],
        'HITACHI': ['HITACHI', 'HITACHI MEDICAL'],
    }
    
    def __init__(self, max_component_length: int = 64):
        self.max_length = max_component_length
    
    def generate_path(self, dicom_tags: Dict, original_filename: str) -> str:
        """
        根据DICOM标签生成存储路径
        
        Args:
            dicom_tags: 解析的DICOM标签字典
            original_filename: 原始文件名（作为后备）
            
        Returns:
            相对路径字符串
        """
        components = self._extract_components(dicom_tags)
        
        # 如果缺少关键组件，使用原始文件名模式
        if not components.sop_uid:
            return self._fallback_path(original_filename)
        
        # 应用清理
        cleaned = self._clean_components(components)
        
        # 生成路径
        path = self.TEMPLATE.format(
            modality=cleaned.modality,
            vendor=cleaned.vendor,
            device=cleaned.device or 'GENERIC',
            study_uid=cleaned.study_uid,
            meas_uid=cleaned.meas_uid or cleaned.series_uid,
            series_uid=cleaned.series_uid,
            sop_uid=cleaned.sop_uid
        )
        
        # 确保路径安全
        return self._sanitize_path(path)
    
    def _extract_components(self, tags: Dict) -> PathComponents:
        """从DICOM标签提取路径组件"""
        # Modality - 必填
        modality = str(tags.get('modality', '')).upper()
        if not modality:
            modality = str(tags.get('Modality', '')).upper()
        
        # Vendor - 清理厂商名称
        vendor = str(tags.get('vendor', ''))
        if not vendor:
            vendor = str(tags.get('Manufacturer', ''))
        
        # Device - 可选
        device = tags.get('device_model') or tags.get('ManufacturerModelName')
        
        # UIDs - 各种可能的标签名
        study_uid = tags.get('study_uid') or tags.get('StudyInstanceUID', '')
        series_uid = tags.get('series_uid') or tags.get('SeriesInstanceUID', '')
        sop_uid = tags.get('sop_instance_uid') or tags.get('SOPInstanceUID', '')
        
        # MeasUID - 优先从meas_uid字段，这是提取器输出的
        meas_uid = tags.get('meas_uid')
        
        return PathComponents(
            modality=modality,
            vendor=vendor,
            device=device,
            study_uid=study_uid,
            meas_uid=meas_uid,
            series_uid=series_uid,
            sop_uid=sop_uid
        )
    
    def _clean_components(self, components: PathComponents) -> PathComponents:
        """清理路径组件"""
        # 清理Modality
        modality = components.modality or self.DEFAULTS['modality']
        modality = re.sub(r'[^A-Z0-9]', '', modality)[:8]  # 只允许字母数字
        
        # 清理Vendor - 映射到标准名称
        vendor = self._normalize_vendor(components.vendor)
        vendor = re.sub(r'[^A-Za-z0-9_-]', '_', vendor)[:32]
        
        # 清理Device
        device = None
        if components.device:
            device = str(components.device)
            device = re.sub(r'[^A-Za-z0-9_-]', '_', device)[:32]
        
        # 截断UIDs
        study_uid = self._truncate_uid(components.study_uid, 8)
        series_uid = self._truncate_uid(components.series_uid, 8)
        sop_uid = self._sanitize_sop_uid(components.sop_uid)
        
        # MeasUID - 优先使用，需要清理
        meas_uid = None
        if components.meas_uid:
            meas_uid = str(components.meas_uid)
            meas_uid = re.sub(r'[^A-Za-z0-9_-]', '_', meas_uid)[:64]
        
        return PathComponents(
            modality=modality,
            vendor=vendor,
            device=device,
            study_uid=study_uid,
            meas_uid=meas_uid,
            series_uid=series_uid,
            sop_uid=sop_uid
        )
    
    def _normalize_vendor(self, vendor: str) -> str:
        """标准化厂商名称"""
        vendor_upper = vendor.upper()
        
        for standard, aliases in self.VENDOR_CLEANUP.items():
            for alias in aliases:
                if alias in vendor_upper:
                    return standard
        
        # 未匹配到，返回清理后的原始值
        return vendor.upper() if vendor else self.DEFAULTS['vendor']
    
    def _truncate_uid(self, uid: str, length: int) -> str:
        """截断UID，保留识别性"""
        if not uid:
            return 'UNKNOWN'
        # 使用UID的最后部分，通常更有区分性
        parts = uid.split('.')
        if len(parts) > 2:
            # 取最后两段
            short = '.'.join(parts[-2:])
        else:
            short = uid
        
        return short[:length + 10]  # 稍微宽松一点
    
    def _sanitize_sop_uid(self, uid: str) -> str:
        """清理SOP UID用于文件名"""
        if not uid:
            return 'unknown'
        # 替换文件名非法字符
        return re.sub(r'[^A-Za-z0-9.]', '_', uid)
    
    def _sanitize_path(self, path: str) -> str:
        """确保路径安全，移除任何危险字符"""
        # 移除任何尝试目录遍历的序列
        path = path.replace('../', '').replace('..\\', '')
        path = path.replace('./', '').replace('.\\', '')
        # 移除前导斜杠
        path = path.lstrip('/\\')
        return path
    
    def _fallback_path(self, original_filename: str) -> str:
        """当无法提取组件时的后备路径"""
        # 使用原始文件名，但确保安全
        safe_name = re.sub(r'[^A-Za-z0-9._-]', '_', original_filename)
        return f"DICOM_UNKNOWN/GENERIC/GENERIC/{safe_name}"


# 使用示例
def example_usage():
    """路径生成器使用示例"""
    generator = LocalNASPathGenerator()
    
    # Siemens MR 示例
    siemens_tags = {
        'modality': 'MR',
        'vendor': 'SIEMENS',
        'device_model': 'Prisma',
        'study_uid': '1.2.276.0.7230010.3.1.2.12345.67890.12345',
        'series_uid': '1.2.276.0.7230010.3.1.3.12345.67890.12345.1',
        'sop_instance_uid': '1.2.276.0.7230010.3.1.4.12345.67890.12345.1.1',
        'meas_uid': 'meas_20240519_001'
    }
    
    path = generator.generate_path(siemens_tags, "IM-0001-0001.dcm")
    print(f"Siemens path: {path}")
    # 输出: DICOM_MR/SIEMENS/Prisma/12345.67890/meas_20240519_001/12345.67890.12345.1/1.2.276.0.7230010.3.1.4.12345.67890.12345.1.1.dcm
    
    # 缺少MeasUID的情况
    no_meas_tags = siemens_tags.copy()
    del no_meas_tags['meas_uid']
    
    path = generator.generate_path(no_meas_tags, "IM-0001-0001.dcm")
    print(f"No meas_uid path: {path}")
    # 输出: DICOM_MR/SIEMENS/Prisma/12345.67890/12345.67890.12345.1/12345.67890.12345.1/...
```

### 验收标准
- [ ] 路径结构符合模板要求
- [ ] 缺失标签使用合理默认值
- [ ] MeasUID存在时优先使用
- [ ] 厂商名称正确归一化
- [ ] 路径组件清理后无非法字符
- [ ] 超长UID截断保留识别性

---

## Phase 1 集成验证

### 集成测试场景

**场景1: 完整数据流**
```python
# 测试完整数据流

def test_full_phase1_flow():
    """测试Phase 1完整数据流"""
    
    # 1. 加载Tag Schema
    schema = DicomParserFactory.load_schema("schemas/tag_schema_v1.yaml")
    
    # 2. 创建解析器
    parser = DicomParserFactory.create_parser("default_dicom_schema")
    
    # 3. 解析DICOM
    result = parser.parse("/path/to/siemens_mr.dcm")
    assert 'meas_uid' in result.tags  # 确认MeasUID被提取
    
    # 4. 生成路径
    path_gen = LocalNASPathGenerator()
    local_path = path_gen.generate_path(result.tags, "siemens_mr.dcm")
    assert "SIEMENS" in local_path
    assert result.tags.get('meas_uid') in local_path or result.tags.get('series_uid') in local_path
    
    # 5. 存储到对象存储
    obj_backend = ObjectStorageBackend(
        endpoint="minio:9000",
        access_key="minioadmin",
        secret_key="minioadmin",
        bucket_name="dicom-processing"
    )
    obj_location = obj_backend.store(
        "/path/to/siemens_mr.dcm",
        local_path,
        result.tags
    )
    assert obj_location.mode == StorageMode.OBJECT
    assert obj_location.checksum is not None
    
    # 6. 存储到本地/NAS
    local_backend = LocalNASStorageBackend(
        base_path="/mnt/nas/dicom-archive",
        path_generator=path_gen
    )
    local_location = local_backend.store(
        "/path/to/siemens_mr.dcm",
        local_path,
        result.tags
    )
    assert local_location.mode == StorageMode.LOCAL_NAS
    assert "DICOM_MR" in local_location.path
    
    print("Phase 1 integration test passed!")
```

### 性能基准

| 组件 | 测试项 | 目标 |
|-----|-------|-----|
| 解析器 | 标准文件解析 (<100MB) | < 500ms |
| 解析器 | 大文件流式解析 (1GB) | 不OOM，内存<200MB |
| 存储 | 对象存储上传 (100MB) | < 5s (本地MinIO) |
| 存储 | 本地存储复制 (100MB) | < 2s (NAS写入) |
| 路径生成 | 单次生成 | < 1ms |

---

## Phase 1 决策实施清单

基于CEO审查决策，Phase 1需要实施以下决策：

| 决策 | 实施位置 | 检查点 |
|-----|---------|-------|
| Gap-1: 路径长度限制 | `LocalNASStorageBackend._ensure_path_length()` | 超长路径触发哈希缩短 |
| Gap-4: Schema版本 | `SchemaManager.mark_stale_projections()` | 版本变更标记陈旧 |
| Gap-5: OOM处理 | `ConfigurableDicomParser.parse()` | `stop_before_pixels=True` |
| Gap-7: 用户决策 | `SiemensMeasUIDExtractor` + `UIHMeasUIDExtractor` | 可配置提取器注册 |

---

**文档状态**: Phase 1 详细设计 - 完成
**下一步**: Phase 2 设计（摄入管道）
