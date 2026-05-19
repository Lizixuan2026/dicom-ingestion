"""
DICOM Parser Module

可扩展的DICOM解析框架，支持动态标签提取配置。

核心组件:
- TagExtractor: 标签提取器基类
- DicomParserFactory: 解析器工厂
- ConfigurableDicomParser: 配置驱动的解析器

决策实施:
- Gap-5: OOM/大文件策略 - 流式头部解析 + 延迟像素数据加载
- Gap-8: MeasUID提取器 - Siemens/UIH设备支持
"""
from .tag_extractors.base import TagExtractor, ExtractionError
from .factory import DicomParserFactory, ConfigurableDicomParser, ParseResult

__all__ = [
    "TagExtractor",
    "ExtractionError",
    "DicomParserFactory",
    "ConfigurableDicomParser",
    "ParseResult",
]
