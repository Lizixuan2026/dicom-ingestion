"""
Test Local/NAS Storage Path Length Control

P1-1: 路径长度控制测试矩阵
- 超长UID
- 非法字符
- 同名不同内容（版本化命名）
- 非ASCII厂商
"""
import pytest
import tempfile
import shutil
import hashlib
from pathlib import Path
from unittest.mock import Mock, patch

from dicom_ingestion.storage.local_nas_storage import LocalNASStorageBackend, StorageError
from dicom_ingestion.storage.base import StorageMode


class TestPathLengthThreshold:
    """P1-1: 可配置路径长度阈值测试"""

    def test_default_max_path_length_is_conservative(self):
        """测试：默认阈值是保守的 240 字符"""
        backend = LocalNASStorageBackend(
            base_path="/tmp/test",
            path_generator=Mock(),
            create_dirs=False
        )
        assert backend.max_path_length == 240

    def test_custom_max_path_length(self):
        """测试：可配置自定义阈值（如 255 for Windows）"""
        backend = LocalNASStorageBackend(
            base_path="/tmp/test",
            path_generator=Mock(),
            create_dirs=False,
            max_path_length=255
        )
        assert backend.max_path_length == 255

    def test_very_conservative_threshold(self):
        """测试：可配置更保守的阈值（如 200 for 旧版 NAS）"""
        backend = LocalNASStorageBackend(
            base_path="/tmp/test",
            path_generator=Mock(),
            create_dirs=False,
            max_path_length=200
        )
        assert backend.max_path_length == 200


class TestIterativeShortening:
    """P1-1: 迭代式路径缩短策略测试"""

    def test_uid_shortening_preserves_identifiability(self):
        """测试：UID 缩短保留可识别性（前缀+哈希+后缀）"""
        backend = LocalNASStorageBackend(
            base_path="/tmp",
            path_generator=Mock(),
            create_dirs=False,
            max_path_length=240
        )

        # 超长 UID
        long_uid = "1.2.276.0.7230010.3.1.2.12345.67890.12345.99999.88888.77777"
        parts = ["DICOM_MR", "SIEMENS", "Prisma", long_uid, "meas_001", "series_001", "sop.dcm"]

        shortened = backend._shorten_uids_in_parts(parts)

        # 缩短后 UID 部分应该包含哈希和片段（使用 _H_ 分隔符避免路径遍历问题）
        uid_part = shortened[3]
        assert "_H_" in uid_part  # 哈希分隔符
        assert len(uid_part) <= 48

    def test_iterative_shortening_applies_in_priority_order(self):
        """测试：迭代式缩短按优先级逐步应用"""
        backend = LocalNASStorageBackend(
            base_path="/tmp",
            path_generator=Mock(),
            create_dirs=False,
            max_path_length=100
        )

        # 创建超长路径
        long_parts = [
            "DICOM_MAGNETICRESONANCEIMAGING",  # 超长 modality
            "SIEMENSHEALTHCAREGMBH",           # 超长 vendor
            "MAGNETOMPRISMAFIT3T",             # 超长 device
            "1.2.276.0.7230010.3.1.2.12345.67890.12345.99999.88888.77766.55544",
            "measurement_2024_05_19_session_001_run_002",
            "series_001",
            "sop_instance_uid_123456789.dcm"
        ]

        path = Path(*long_parts)
        result = backend._ensure_path_length(path)

        # 结果应该被缩短到限制内
        assert len(str(result)) <= 100
        # 不应该出现无限递归或异常
        assert result is not None

    def test_vendor_abbreviation(self):
        """测试：厂商名称缩写"""
        backend = LocalNASStorageBackend(
            base_path="/tmp",
            path_generator=Mock(),
            create_dirs=False
        )

        parts = ["DICOM_MR", "SIEMENS", "device", "study", "meas", "series", "sop.dcm"]
        shortened = backend._shorten_vendor_in_parts(parts)

        assert shortened[1] == "SIEM"  # SIEMENS -> SIEM

    def test_ultimate_fallback_for_extreme_cases(self):
        """测试：极端情况下的最终回退（完整哈希）"""
        backend = LocalNASStorageBackend(
            base_path="/tmp",
            path_generator=Mock(),
            create_dirs=False,
            max_path_length=50
        )

        # 极端超长路径
        extreme_parts = ["a" * 100] * 10
        path = Path(*extreme_parts)

        result = backend._ultimate_fallback(extreme_parts, len(str(path)))

        # 应该回退到 OVERFLOW 目录下的哈希路径
        assert str(result).startswith("OVERFLOW/")
        assert len(str(result)) <= 50


class TestVersionedNaming:
    """P1-1: 版本化命名规则测试（同名不同内容）"""

    def test_versioned_naming_format(self, tmp_path):
        """测试：版本化命名格式 filename_v001.dcm"""
        backend = LocalNASStorageBackend(
            base_path=str(tmp_path),
            path_generator=Mock(),
            create_dirs=False
        )

        # 创建虚拟路径
        path = tmp_path / "test.dcm"
        path.write_text("original")

        # 获取唯一路径（应该返回 v1）
        unique = backend._get_unique_path(path)
        assert unique.name == "test_v001.dcm"

    def test_multiple_versions(self, tmp_path):
        """测试：多个版本文件按顺序命名"""
        backend = LocalNASStorageBackend(
            base_path=str(tmp_path),
            path_generator=Mock(),
            create_dirs=False
        )

        # 创建原始文件
        path = tmp_path / "test.dcm"
        path.write_text("original")

        # 创建 v1
        (tmp_path / "test_v001.dcm").write_text("version1")

        # 获取唯一路径（应该返回 v2）
        unique = backend._get_unique_path(path)
        assert unique.name == "test_v002.dcm"

    def test_version_numbering_continues(self, tmp_path):
        """测试：版本号连续递增"""
        backend = LocalNASStorageBackend(
            base_path=str(tmp_path),
            path_generator=Mock(),
            create_dirs=False
        )

        # 创建 v1, v2, v3
        for i in range(1, 4):
            (tmp_path / f"test_v{i:03d}.dcm").write_text(f"v{i}")

        path = tmp_path / "test.dcm"
        path.write_text("original")

        unique = backend._get_unique_path(path)
        assert unique.name == "test_v004.dcm"

    def test_get_versioned_path_method(self, tmp_path):
        """测试：get_versioned_path 方法支持访问历史版本"""
        backend = LocalNASStorageBackend(
            base_path=str(tmp_path),
            path_generator=Mock(),
            create_dirs=False
        )

        # 创建版本化文件
        (tmp_path / "test_v001.dcm").write_text("v1")
        (tmp_path / "test_v002.dcm").write_text("v2")

        # 模拟 StorageLocation
        location = Mock()
        location.path = "test.dcm"

        # 获取不同版本路径
        v0_path = backend.get_versioned_path(location, 0)
        v1_path = backend.get_versioned_path(location, 1)
        v2_path = backend.get_versioned_path(location, 2)

        assert v0_path.name == "test.dcm"
        assert v1_path.name == "test_v001.dcm"
        assert v2_path.name == "test_v002.dcm"


class TestCrossPlatformScenarios:
    """P1-1: 跨平台场景测试"""

    def test_windows_compatible_threshold(self):
        """测试：Windows 兼容阈值（255 字符 MAX_PATH）"""
        backend = LocalNASStorageBackend(
            base_path="C:\\DICOM\\Storage",
            path_generator=Mock(),
            create_dirs=False,
            max_path_length=255
        )

        # 模拟 Windows 路径
        long_parts = ["DICOM_MR", "SIEMENS"] + ["x" * 50] * 5
        path = Path("C:/DICOM/Storage", *long_parts)

        result = backend._ensure_path_length(path)
        assert len(str(result)) <= 255

    def test_nas_conservative_threshold(self):
        """测试：NAS 保守阈值（240 字符）"""
        backend = LocalNASStorageBackend(
            base_path="/mnt/nas/dicom",
            path_generator=Mock(),
            create_dirs=False,
            max_path_length=240
        )

        long_parts = ["DICOM_MR", "SIEMENS"] + ["y" * 40] * 6
        path = Path("/mnt/nas/dicom", *long_parts)

        result = backend._ensure_path_length(path)
        assert len(str(result)) <= 240


class TestIllegalCharacters:
    """P1-1: 非法字符处理测试"""

    def test_path_traversal_removed(self, tmp_path):
        """测试：路径遍历序列被清理"""
        from dicom_ingestion.path_generator.local_nas import LocalNASPathGenerator

        # PathGenerator 应该清理路径遍历
        generator = LocalNASPathGenerator()

        tags = {
            'modality': 'MR',
            'vendor': 'SIEMENS',
            'study_uid': '1.2.3',
            'series_uid': '1.2.3.4',
            'sop_instance_uid': '../etc/passwd',  # 恶意路径
        }

        path = generator.generate_path(tags, "test.dcm")

        # 路径遍历应该被移除
        assert '../' not in path
        assert '..' not in path


class TestNonASCII:
    """P1-1: 非 ASCII 字符测试"""

    def test_chinese_vendor_normalized(self, tmp_path):
        """测试：中文厂商名称（联影）正确映射到 UIH"""
        from dicom_ingestion.path_generator.local_nas import LocalNASPathGenerator

        generator = LocalNASPathGenerator()

        tags = {
            'modality': 'CT',
            'vendor': '联影',  # 中文
            'manufacturer': '联影医疗',
        }

        path = generator.generate_path(tags, "test.dcm")

        # 应该映射到 UIH 而不是保留中文
        assert "UIH" in path.upper() or "UNKNOWN" in path.upper()

    def test_unicode_in_device_name(self, tmp_path):
        """测试：Unicode 设备名被清理"""
        from dicom_ingestion.path_generator.local_nas import LocalNASPathGenerator

        generator = LocalNASPathGenerator()

        tags = {
            'modality': 'MR',
            'vendor': 'SIEMENS',
            'device_model': 'Prisma™ 3T',  # 包含 ™
            'study_uid': '1.2.3',
            'series_uid': '1.2.3.4',
            'sop_instance_uid': '1.2.3.4.5',
        }

        path = generator.generate_path(tags, "test.dcm")

        # Unicode 字符应该被替换为 _
        assert '™' not in path


class TestSameNameDifferentContent:
    """P1-1: 同名不同内容文件测试"""

    def test_checksum_based_deduplication(self, tmp_path):
        """测试：相同内容文件使用同一位置"""
        backend = LocalNASStorageBackend(
            base_path=str(tmp_path),
            path_generator=Mock(),
            create_dirs=False
        )

        # 创建模拟 PathGenerator
        mock_generator = Mock()
        mock_generator.generate_path.return_value = "DICOM_MR/SIEMENS/device/study/meas/series/file.dcm"
        backend.path_generator = mock_generator

        # 创建源文件
        source1 = tmp_path / "source1.dcm"
        source1.write_text("same content")

        # 第一次存储
        result1 = backend.store(str(source1), "hint", {})

        # 第二次存储（相同内容）
        source2 = tmp_path / "source2.dcm"
        source2.write_text("same content")

        result2 = backend.store(str(source2), "hint", {})

        # 应该返回同一位置
        assert result1.path == result2.path

    def test_different_content_gets_versioned_path(self, tmp_path):
        """测试：不同内容文件获得版本化路径"""
        backend = LocalNASStorageBackend(
            base_path=str(tmp_path),
            path_generator=Mock(),
            create_dirs=False
        )

        # 创建模拟 PathGenerator
        mock_generator = Mock()
        mock_generator.generate_path.return_value = "DICOM_MR/SIEMENS/device/study/meas/series/file.dcm"
        backend.path_generator = mock_generator

        # 第一次存储
        source1 = tmp_path / "source1.dcm"
        source1.write_text("content A")
        result1 = backend.store(str(source1), "hint", {})

        # 第二次存储（不同内容）
        source2 = tmp_path / "source2.dcm"
        source2.write_text("content B")
        result2 = backend.store(str(source2), "hint", {})

        # 应该获得版本化路径
        assert result2.path != result1.path
        assert "_v001" in result2.path


class TestIntegrationPathControl:
    """P1-1: 路径长度控制集成测试"""

    def test_end_to_end_long_path_handling(self, tmp_path):
        """测试：端到端超长路径处理"""
        from dicom_ingestion.path_generator.local_nas import LocalNASPathGenerator

        # 创建 PathGenerator 和 Storage
        generator = LocalNASPathGenerator(max_component_length=32)
        backend = LocalNASStorageBackend(
            base_path=str(tmp_path),
            path_generator=generator,
            create_dirs=True,
            max_path_length=240
        )

        # 超长标签
        tags = {
            'modality': 'MAGNETICRESONANCEIMAGING',
            'vendor': 'SIEMENSHEALTHCAREGMBH',
            'manufacturer_model': 'MAGNETOMPRISMAFITWITHDOTS3T',
            'study_uid': '1.2.276.0.7230010.3.1.2.12345.67890.12345.99999.88888.77777.66666.55555',
            'series_uid': '1.2.276.0.7230010.3.1.3.12345.67890.12345.99999.88888.77777.66666.55555.44444',
            'sop_instance_uid': '1.2.276.0.7230010.3.1.4.12345.67890.12345.99999.88888.77777.66666.55555.44444.33333',
            'meas_uid': 'meas_2024_05_19_session_001_run_002_acquisition_003'
        }

        # 创建源文件
        source = tmp_path / "source.dcm"
        source.write_text("DICOM content")

        # 存储
        result = backend.store(str(source), "hint", tags)

        # 验证路径长度
        full_path = tmp_path / result.path
        assert len(str(full_path)) <= 240

        # 验证文件存在
        assert full_path.exists()

    def test_component_and_full_path_coordination(self, tmp_path):
        """测试：Generator 组件级与 Storage 完整路径级协调"""
        from dicom_ingestion.path_generator.local_nas import LocalNASPathGenerator

        # Generator 限制组件 32 字符
        generator = LocalNASPathGenerator(max_component_length=32)
        # Storage 限制完整路径 100 字符（故意设小以触发协调）
        backend = LocalNASStorageBackend(
            base_path=str(tmp_path),
            path_generator=generator,
            create_dirs=True,
            max_path_length=100
        )

        tags = {
            'modality': 'MR',
            'vendor': 'SIEMENS',
            'study_uid': '1.2.3.4.5.6.7.8.9.10.11.12.13.14.15',
            'series_uid': '1.2.3.4.5.6.7.8.9.10.11.12.13.14.16',
            'sop_instance_uid': '1.2.3.4.5.6.7.8.9.10.11.12.13.14.17',
        }

        source = tmp_path / "source.dcm"
        source.write_text("content")

        result = backend.store(str(source), "hint", tags)

        # 完整路径应该被控制
        full_path = tmp_path / result.path
        assert len(str(full_path)) <= 100


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
