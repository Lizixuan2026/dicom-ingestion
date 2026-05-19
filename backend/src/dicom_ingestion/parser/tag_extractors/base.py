"""
Tag Extractor Base Class

定义标签提取器的标准接口。
决策 Gap-8: 用户选择 A - 完整可配置提取器接口
"""
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional


class ExtractionError(Exception):
    """标签提取错误"""
    pass


class TagExtractor(ABC):
    """
    标签提取器基类

    所有自定义提取器必须继承此类。
    决策 Gap-8: 用户选择 A - 完整可配置提取器接口
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """提取器唯一标识名"""
        pass

    @abstractmethod
    def can_extract(self, ds) -> bool:
        """
        检查此提取器是否适用于给定DICOM数据集

        Args:
            ds: pydicom Dataset对象

        Returns:
            True如果可以提取，False跳过
        """
        pass

    @abstractmethod
    def extract(self, ds) -> Dict[str, Any]:
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

    def get_supported_manufacturers(self) -> list:
        """
        返回支持的设备厂商列表
        用于文档和UI展示
        """
        return []

    def get_supported_modalities(self) -> list:
        """
        返回支持的检查类型列表
        """
        return []
