"""
Local/NAS Path Generator

生成人可读的层级路径: DICOM_{MODALITY}/{VENDOR}/{DEVICE}/{StudyUID}/{MeasUID}/{SeriesUID}/{SOP}.dcm

P1-1: 与 Storage 层统一长度职责
"""
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

    P1-1: 与 Storage 层统一长度职责
    - Generator 负责组件级长度控制（单个组件不超限制）
    - Storage 负责完整路径长度控制（处理超长路径回退）
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
        'SIEMENS': ['SIEMENS', 'SIEMENS HEALTHCARE', 'SIEMENS MEDICAL', 'SIEMENS HEALTHINEERS'],
        'GE': ['GE', 'GE HEALTHCARE', 'GENERAL ELECTRIC', 'GENERAL ELECTRIC HEALTHCARE'],
        'PHILIPS': ['PHILIPS', 'PHILIPS HEALTHCARE', 'PHILIPS MEDICAL'],
        'UIH': ['UIH', 'UNITED IMAGING', 'UNITED IMAGING HEALTHCARE', '联影'],
        'CANON': ['CANON', 'CANON MEDICAL', 'CANON MEDICAL SYSTEMS', 'TOSHIBA', 'TOSHIBA MEDICAL'],
        'HITACHI': ['HITACHI', 'HITACHI MEDICAL', 'HITACHI HEALTHCARE'],
        'AGFA': ['AGFA', 'AGFA HEALTHCARE'],
        'CARESTREAM': ['CARESTREAM', 'CARESTREAM HEALTH'],
        'FUJIFILM': ['FUJIFILM', 'FUJIFILM MEDICAL', 'FUJI'],
    }

    # P1-1: 组件长度限制（与 Storage 层协调）
    DEFAULT_MAX_COMPONENT_LENGTH = 48  # 保守值，确保完整路径不超 240

    def __init__(self, max_component_length: Optional[int] = None):
        """
        初始化路径生成器

        Args:
            max_component_length: 路径组件最大长度（默认48，建议32-64）
                                 完整路径限制由 Storage 层处理
        """
        self.max_component_length = max_component_length or self.DEFAULT_MAX_COMPONENT_LENGTH

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
            vendor = str(tags.get('manufacturer', ''))
            if not vendor:
                vendor = str(tags.get('Manufacturer', ''))

        # Device - 可选
        device = tags.get('device_model') or tags.get('manufacturer_model') or tags.get('ManufacturerModelName')

        # UIDs - 各种可能的标签名
        study_uid = (tags.get('study_uid') or
                    tags.get('study_instance_uid') or
                    tags.get('StudyInstanceUID', ''))

        series_uid = (tags.get('series_uid') or
                     tags.get('series_instance_uid') or
                     tags.get('SeriesInstanceUID', ''))

        sop_uid = (tags.get('sop_instance_uid') or
                  tags.get('sop_uid') or
                  tags.get('SOPInstanceUID', ''))

        # MeasUID - 优先从meas_uid字段，这是提取器输出的
        meas_uid = tags.get('meas_uid') or tags.get('MeasUID')

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
        """
        清理路径组件

        P1-1: 所有组件应用 max_component_length 限制
        """
        max_len = self.max_component_length

        # 清理Modality (较短，固定8字符)
        modality = components.modality or self.DEFAULTS['modality']
        modality = re.sub(r'[^A-Z0-9]', '', modality)[:8]

        # 清理Vendor - 映射到标准名称
        vendor = self._normalize_vendor(components.vendor)
        vendor = re.sub(r'[^A-Za-z0-9_-]', '_', vendor)[:min(16, max_len)]

        # 清理Device
        device = None
        if components.device:
            device = str(components.device)
            device = re.sub(r'[^A-Za-z0-9_-]', '_', device)[:max_len]

        # P1-1: 截断UIDs - 使用配置的组件长度限制
        uid_limit = min(32, max_len)  # UID 可稍长但仍受限
        study_uid = self._truncate_uid(components.study_uid, uid_limit)
        series_uid = self._truncate_uid(components.series_uid, uid_limit)
        sop_uid = self._sanitize_sop_uid(components.sop_uid, max_len)

        # MeasUID - 优先使用，需要清理
        meas_uid = None
        if components.meas_uid:
            meas_uid = str(components.meas_uid)
            meas_uid = re.sub(r'[^A-Za-z0-9_-]', '_', meas_uid)[:max_len]

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
        if not vendor:
            return self.DEFAULTS['vendor']

        vendor_upper = vendor.upper()

        for standard, aliases in self.VENDOR_CLEANUP.items():
            for alias in aliases:
                if alias in vendor_upper:
                    return standard

        # 未匹配到，返回清理后的原始值
        return vendor.upper()[:32]

    def _truncate_uid(self, uid: str, length: Optional[int] = None) -> str:
        """
        截断UID，保留识别性

        P1-1: 使用配置的 max_component_length 确保组件不超长
        """
        if not uid:
            return 'UNKNOWN'

        max_len = length or self.max_component_length

        # 使用UID的最后部分，通常更有区分性
        parts = uid.split('.')
        if len(parts) > 2:
            # 取最后两段
            short = '.'.join(parts[-2:])
        else:
            short = uid

        # P1-1: 严格限制长度
        return short[:max_len]

    def _sanitize_sop_uid(self, uid: str, max_len: Optional[int] = None) -> str:
        """
        清理SOP UID用于文件名

        P1-1: 使用配置的组件长度限制
        """
        if not uid:
            return 'unknown'

        limit = max_len or self.max_component_length

        # 替换文件名非法字符
        cleaned = re.sub(r'[^A-Za-z0-9.]', '_', uid)

        # P1-1: 限制长度（保留后缀.dcm前的部分）
        return cleaned[:limit]

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

        # 如果文件名过长，使用哈希
        if len(safe_name) > 64:
            hash_part = hashlib.sha256(safe_name.encode()).hexdigest()[:16]
            safe_name = f"file_{hash_part}.dcm"

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

    # 缺少MeasUID的情况
    no_meas_tags = siemens_tags.copy()
    del no_meas_tags['meas_uid']

    path = generator.generate_path(no_meas_tags, "IM-0001-0001.dcm")
    print(f"No meas_uid path: {path}")

    # GE CT 示例
    ge_tags = {
        'modality': 'CT',
        'vendor': 'GE HEALTHCARE',
        'device_model': 'Discovery',
        'study_uid': '1.2.840.113619.2.123.456.789',
        'series_uid': '1.2.840.113619.2.123.456.789.1',
        'sop_instance_uid': '1.2.840.113619.2.123.456.789.1.1'
    }

    path = generator.generate_path(ge_tags, "IM-0001-0001.dcm")
    print(f"GE path: {path}")


if __name__ == "__main__":
    example_usage()
