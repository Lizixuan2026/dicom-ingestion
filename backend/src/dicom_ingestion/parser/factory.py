"""
DICOM Parser Factory

可扩展的DICOM解析框架，支持动态标签提取配置。
决策实施:
- Gap-5: OOM/大文件策略 - 流式头部解析 + 延迟像素数据加载
- Gap-8: MeasUID提取器接口 - 可配置提取器注册
"""
import hashlib
import io
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Type, Optional, List, Any
import logging

logger = logging.getLogger(__name__)


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
    def register_extractor(cls, extractor_class: Type):
        """注册自定义提取器"""
        instance = extractor_class()
        cls._extractors[instance.name] = extractor_class
        logger.info(f"Registered extractor: {instance.name}")
        return extractor_class

    @classmethod
    def load_schema(cls, schema_config: dict) -> dict:
        """加载标签Schema配置"""
        name = schema_config.get('name', 'default')
        cls._schemas[name] = schema_config
        return schema_config

    @classmethod
    def create_parser(cls, schema_name: str = "default"):
        """创建配置化解析器"""
        schema = cls._schemas.get(schema_name)
        if not schema:
            # 使用默认schema
            schema = cls._get_default_schema()
        return ConfigurableDicomParser(schema, cls._extractors)

    @classmethod
    def _get_default_schema(cls) -> dict:
        """获取默认Schema配置"""
        return {
            "schema_version": "1.0",
            "name": "default",
            "description": "默认DICOM标签提取配置",
            "extractors": {
                "standard": [
                    {"tag": "(0010,0010)", "alias": "patient_name", "required": True},
                    {"tag": "(0010,0020)", "alias": "patient_id"},
                    {"tag": "(0020,000D)", "alias": "study_uid", "required": True},
                    {"tag": "(0020,000E)", "alias": "series_uid", "required": True},
                    {"tag": "(0008,0018)", "alias": "sop_instance_uid", "required": True},
                    {"tag": "(0008,0060)", "alias": "modality", "required": True, "transform": "uppercase"},
                    {"tag": "(0008,0070)", "alias": "manufacturer"},
                    {"tag": "(0008,1090)", "alias": "manufacturer_model"},
                    {"tag": "(0008,103E)", "alias": "series_description"},
                    {"tag": "(0020,0011)", "alias": "series_number"},
                    {"tag": "(0020,0013)", "alias": "instance_number"},
                ],
                "private": [
                    {"name": "meas_uid_siemens", "extractor_class": "SiemensMeasUIDExtractor"},
                    {"name": "meas_uid_uih", "extractor_class": "UIHMeasUIDExtractor"},
                ]
            }
        }


class ConfigurableDicomParser:
    """配置驱动的DICOM解析器"""

    def __init__(self, schema: dict, extractors: Dict[str, Type]):
        self.schema = schema
        self.extractors = extractors
        self._extractor_instances: Dict[str, Any] = {}

    def parse(self, file_path: str) -> ParseResult:
        """
        解析DICOM文件

        决策 Gap-5: 流式头部解析 + 延迟像素数据加载
        """
        import pydicom

        warnings = []
        file_path_obj = Path(file_path)

        # 检查文件大小，大文件特殊处理
        file_size = file_path_obj.stat().st_size
        if file_size > 512 * 1024 * 1024:  # 512MB+
            warnings.append(f"Large file detected: {file_size / (1024*1024):.1f}MB")

        # 决策 Gap-5: 流式读取 - 仅加载元数据，延迟加载像素数据
        try:
            ds = pydicom.dcmread(
                file_path,
                defer_size="1KB",  # 大于1KB的数据元素延迟加载
                force=True,
                stop_before_pixels=True  # 先不读取像素数据
            )
        except Exception as e:
            raise ParseError(f"Failed to read DICOM file: {e}")

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
            extractor_name = private_config.get('name') or private_config.get('extractor_class', '').lower().replace('extractor', '')

            if extractor_name in self.extractors:
                extractor = self._get_extractor(extractor_name)

                try:
                    if extractor.can_extract(ds):
                        extracted = extractor.extract(ds)
                        tags.update(extracted)
                        extractors_used.append(extractor.name)
                except Exception as e:
                    logger.warning(f"Extractor {extractor.name} failed: {e}")

        # 文件元数据
        file_meta = {
            "file_size": file_size,
            "file_path": str(file_path),
            "transfer_syntax": str(ds.file_meta.TransferSyntaxUID) if hasattr(ds, 'file_meta') else None
        }

        return ParseResult(
            tags=tags,
            file_meta=file_meta,
            extractors_used=extractors_used,
            warnings=warnings,
            schema_version=self.schema.get('schema_version', '1.0')
        )

    def _extract_standard_tag(self, ds, config: dict) -> any:
        """提取标准DICOM标签"""
        tag_str = config['tag']
        # 解析 (gggg,eeee) 格式
        try:
            group, element = tag_str.strip('()').split(',')
            tag = (int(group, 16), int(element, 16))
        except (ValueError, IndexError):
            logger.warning(f"Invalid tag format: {tag_str}")
            return None

        value = ds.get(tag)
        if value is None:
            return None

        # 应用转换
        value_str = str(value)
        transform = config.get('transform')
        if transform == 'uppercase':
            value_str = value_str.upper()
        elif transform == 'lowercase':
            value_str = value_str.lower()

        return value_str

    def _get_extractor(self, name: str):
        """获取或创建提取器实例（单例）"""
        if name not in self._extractor_instances:
            self._extractor_instances[name] = self.extractors[name]()
        return self._extractor_instances[name]


class ParseError(Exception):
    """解析错误"""
    pass


# 自动注册提取器
def auto_register_extractors():
    """自动发现并注册所有提取器"""
    try:
        from .tag_extractors import SiemensMeasUIDExtractor, UIHMeasUIDExtractor

        DicomParserFactory.register_extractor(SiemensMeasUIDExtractor)
        DicomParserFactory.register_extractor(UIHMeasUIDExtractor)
    except ImportError as e:
        logger.warning(f"Failed to auto-register extractors: {e}")


# 模块加载时自动注册
auto_register_extractors()
