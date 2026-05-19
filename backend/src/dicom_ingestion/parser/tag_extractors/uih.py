"""
UIH (United Imaging Healthcare) MeasUID Extractor

从联影设备DICOM文件中提取MeasUID（测量标识）。
UIH私有标签位置需要基于实际设备数据测试确定。
"""
import re
from typing import Dict, Any, Optional
from .base import TagExtractor, ExtractionError


class UIHMeasUIDExtractor(TagExtractor):
    """UIH联影设备MeasUID提取器"""

    name = "meas_uid_uih"

    # UIH私有标签可能位置（基于常见模式和实际测试）
    PRIVATE_TAG_BLOCKS = [
        (0x0029, 0x0010),
        (0x0029, 0x0020),
        (0x0029, 0x1101),
        (0x0029, 0x1110),
        (0x0065, 0x0010),  # UIH可能的私有组
        (0x0065, 0x0020),
    ]

    # 序列描述中可能包含MeasUID的模式
    SERIES_DESC_PATTERNS = [
        r'Meas[_-]?UID[:\s=]+([A-Fa-f0-9\-]{8,64})',
        r'测量ID[:\s=]+([A-Fa-f0-9\-]{8,64})',
    ]

    def can_extract(self, ds) -> bool:
        """
        检查是否为UIH设备
        """
        manufacturer = str(ds.get((0x0008, 0x0070), "")).upper()
        modality = str(ds.get((0x0008, 0x0060), "")).upper()

        # UIH可能的品牌名变体
        uih_variants = [
            "UIH",
            "UNITED IMAGING",
            "UNITED IMAGING HEALTHCARE",
            "联影",
            "上海联影"
        ]
        is_uih = any(variant in manufacturer for variant in uih_variants)

        # 主要支持的检查类型
        supported_modalities = ["MR", "CT", "DR", "CR", "XR"]
        is_supported_modality = modality in supported_modalities

        return is_uih and is_supported_modality

    def extract(self, ds) -> Dict[str, Any]:
        """
        提取MeasUID
        尝试多种来源
        """
        meas_uid = None

        # 1. 尝试私有标签
        meas_uid = self._extract_from_private_tags(ds)

        # 2. 如果私有标签没找到，尝试从序列描述解析
        if not meas_uid:
            meas_uid = self._extract_from_series_description(ds)

        # 3. 尝试从其他元数据字段
        if not meas_uid:
            meas_uid = self._extract_from_metadata(ds)

        if meas_uid:
            return {"meas_uid": self._clean_meas_uid(meas_uid)}
        return {}

    def _extract_from_private_tags(self, ds) -> Optional[str]:
        """从私有标签提取"""
        for tag in self.PRIVATE_TAG_BLOCKS:
            if tag in ds:
                try:
                    data = ds[tag].value
                    meas_uid = self._parse_uih_private_data(data)
                    if meas_uid:
                        return meas_uid
                except Exception:
                    continue
        return None

    def _parse_uih_private_data(self, data) -> Optional[str]:
        """
        解析UIH私有数据
        支持字符串和字节格式
        """
        if isinstance(data, str):
            # 直接字符串格式
            return self._extract_meas_uid_pattern(data)
        elif isinstance(data, bytes):
            # 字节格式 - 尝试多种编码
            encodings = ['utf-8', 'gbk', 'gb2312', 'latin-1']
            for encoding in encodings:
                try:
                    decoded = data.decode(encoding, errors='ignore')
                    meas_uid = self._extract_meas_uid_pattern(decoded)
                    if meas_uid:
                        return meas_uid
                except Exception:
                    continue
        return None

    def _extract_meas_uid_pattern(self, text: str) -> Optional[str]:
        """
        从文本中提取MeasUID模式
        """
        if not text:
            return None

        # 匹配MeasUID格式
        patterns = [
            r'MeasUID[:\s=]+([A-Fa-f0-9\-]{8,64})',
            r'Meas[_-]?UID[:\s=]+([A-Fa-f0-9\-]{8,64})',
            r'"MeasUID"\s*:\s*"([A-Fa-f0-9\-]+)"',
            r'MeasUID\s+([0-9a-fA-F]{16,64})',
        ]

        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return match.group(1).strip()

        return None

    def _extract_from_series_description(self, ds) -> Optional[str]:
        """
        从序列描述中提取MeasUID
        某些UIH设备可能在序列描述中包含测量ID
        """
        series_desc = str(ds.get((0x0008, 0x103E), ""))
        if not series_desc:
            return None

        for pattern in self.SERIES_DESC_PATTERNS:
            match = re.search(pattern, series_desc, re.IGNORECASE)
            if match:
                return match.group(1)

        return None

    def _extract_from_metadata(self, ds) -> Optional[str]:
        """
        从其他可能的元数据字段提取
        """
        # 尝试检查注释字段
        comments = str(ds.get((0x0040, 0x0275), ""))  # Request Attributes Sequence
        if comments:
            meas_uid = self._extract_meas_uid_pattern(comments)
            if meas_uid:
                return meas_uid

        # 尝试检查图像注释
        image_comments = str(ds.get((0x0020, 0x4000), ""))  # Image Comments
        if image_comments:
            meas_uid = self._extract_meas_uid_pattern(image_comments)
            if meas_uid:
                return meas_uid

        return None

    def _clean_meas_uid(self, meas_uid: str) -> str:
        """
        清理MeasUID值
        移除空格、特殊字符等
        """
        if not meas_uid:
            return meas_uid

        # 移除空格和换行
        cleaned = meas_uid.strip().replace('\n', '').replace('\r', '')

        # 移除常见分隔符
        cleaned = cleaned.replace('-', '').replace('_', '')

        return cleaned

    def get_supported_manufacturers(self) -> list:
        return [
            "UIH",
            "UNITED IMAGING",
            "UNITED IMAGING HEALTHCARE",
            "上海联影医疗科技有限公司"
        ]

    def get_supported_modalities(self) -> list:
        return ["MR", "CT", "DR", "CR", "XR", "MG"]
