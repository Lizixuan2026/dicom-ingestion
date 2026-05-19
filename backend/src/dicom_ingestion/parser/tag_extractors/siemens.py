"""
Siemens MeasUID Extractor

从Siemens设备DICOM文件中提取MeasUID（测量标识）。
Siemens私有标签通常位于 (0029,10xx) 块。
"""
import re
from typing import Dict, Any, Optional
from .base import TagExtractor, ExtractionError


class SiemensMeasUIDExtractor(TagExtractor):
    """Siemens设备MeasUID提取器"""

    name = "meas_uid_siemens"

    # Siemens私有标签常见位置
    PRIVATE_TAG_BLOCKS = [
        (0x0029, 0x1010),
        (0x0029, 0x1020),
        (0x0029, 0x1030),
        (0x0029, 0x1101),
        (0x0029, 0x1110),
    ]

    def can_extract(self, ds) -> bool:
        """
        检查是否为Siemens设备
        """
        manufacturer = str(ds.get((0x0008, 0x0070), "")).upper()
        modality = str(ds.get((0x0008, 0x0060), "")).upper()

        # Siemens可能的品牌名变体
        siemens_variants = ["SIEMENS", "SIEMENS HEALTHCARE", "SIEMENS MEDICAL"]
        is_siemens = any(variant in manufacturer for variant in siemens_variants)

        # 支持的检查类型
        supported_modalities = ["MR", "CT", "XA", "DX"]
        is_supported_modality = modality in supported_modalities

        return is_siemens and is_supported_modality

    def extract(self, ds) -> Dict[str, Any]:
        """
        提取MeasUID
        """
        meas_uid = None

        # 尝试各个私有标签位置
        for tag in self.PRIVATE_TAG_BLOCKS:
            if tag in ds:
                data = ds[tag].value
                # 解析私有数据块寻找MeasUID
                if isinstance(data, bytes):
                    meas_uid = self._parse_siemens_private_block(data)
                elif isinstance(data, str):
                    meas_uid = self._parse_siemens_string(data)

                if meas_uid:
                    break

        # 如果在私有标签没找到，尝试从CSA头部解析
        if not meas_uid:
            meas_uid = self._extract_from_csa_header(ds)

        if meas_uid:
            return {"meas_uid": meas_uid}
        return {}

    def _parse_siemens_private_block(self, data: bytes) -> Optional[str]:
        """
        解析Siemens私有数据块
        尝试多种编码和格式
        """
        # 尝试不同编码
        encodings = ['utf-8', 'latin-1', 'cp1252', 'iso-8859-1']

        for encoding in encodings:
            try:
                decoded = data.decode(encoding, errors='ignore')
                meas_uid = self._extract_meas_uid_from_text(decoded)
                if meas_uid:
                    return meas_uid
            except Exception:
                continue

        return None

    def _parse_siemens_string(self, data: str) -> Optional[str]:
        """从字符串解析MeasUID"""
        return self._extract_meas_uid_from_text(data)

    def _extract_meas_uid_from_text(self, text: str) -> Optional[str]:
        """
        从文本中提取MeasUID
        支持多种格式：
        - MeasUID: <value>
        - MeasUID=<value>
        - "MeasUID": "<value>"
        """
        if not text or "MeasUID" not in text:
            return None

        # 模式1: MeasUID: value (CSA格式)
        pattern1 = r'MeasUID[:\s=]+([A-Fa-f0-9\-]{8,64})'
        match = re.search(pattern1, text)
        if match:
            return match.group(1).strip()

        # 模式2: 简单的键值对
        pattern2 = r'"MeasUID"\s*:\s*"([A-Fa-f0-9\-]+)"'
        match = re.search(pattern2, text)
        if match:
            return match.group(1)

        # 模式3: 直接跟十六进制值
        pattern3 = r'MeasUID\s+([0-9a-fA-F]{16,64})'
        match = re.search(pattern3, text, re.IGNORECASE)
        if match:
            return match.group(1)

        return None

    def _extract_from_csa_header(self, ds) -> Optional[str]:
        """
        从CSA头部提取MeasUID
        CSA头部通常包含更完整的元数据
        """
        # CSA头部标签
        csa_tags = [
            (0x0029, 0x1010),  # CSA Image Header
            (0x0029, 0x1020),  # CSA Series Header
        ]

        for tag in csa_tags:
            if tag in ds:
                try:
                    data = ds[tag].value
                    if isinstance(data, bytes):
                        # CSA头部格式解析
                        meas_uid = self._parse_csa_header(data)
                        if meas_uid:
                            return meas_uid
                except Exception:
                    continue

        return None

    def _parse_csa_header(self, data: bytes) -> Optional[str]:
        """
        解析CSA头部格式
        CSA头部是Siemens特有的二进制格式
        """
        try:
            # 检查CSA头部签名
            if len(data) < 8:
                return None

            # 尝试文本解析（CSA头部通常包含可读的字符串部分）
            text_data = data.decode('latin-1', errors='ignore')
            return self._extract_meas_uid_from_text(text_data)

        except Exception:
            return None

    def get_supported_manufacturers(self) -> list:
        return ["SIEMENS", "SIEMENS HEALTHCARE", "SIEMENS MEDICAL"]

    def get_supported_modalities(self) -> list:
        return ["MR", "CT", "XA", "DX"]
