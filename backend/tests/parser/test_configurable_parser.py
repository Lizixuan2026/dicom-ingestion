"""
Test ConfigurableDicomParser

Task B: 强制 required 标签校验测试
"""
import pytest
from unittest.mock import Mock, MagicMock, patch
from pathlib import Path
import tempfile
import os

# P1-2: 统一 pydicom 依赖策略 - 缺少时跳过测试
try:
    import pydicom
    HAS_PYDICOM = True
except ImportError:
    HAS_PYDICOM = False
    pydicom = None

from dicom_ingestion.parser.factory import (
    ConfigurableDicomParser,
    DicomParserFactory,
    ParseResult,
    ParseError,
)
from dicom_ingestion.parser.tag_extractors.base import TagExtractor


pytestmark = pytest.mark.skipif(not HAS_PYDICOM, reason="pydicom not installed")


class TestRequiredTagValidation:
    """Task B: required 标签强制校验测试"""

    def test_parse_success_when_all_required_present(self, tmp_path):
        """测试：所有 required 标签存在时解析成功"""
        # 创建 mock DICOM 数据集
        mock_ds = Mock()
        mock_ds.file_meta = Mock()
        mock_ds.file_meta.TransferSyntaxUID = "1.2.840.10008.1.2"
        mock_ds.get = Mock(side_effect=lambda tag: {
            (0x0010, 0x0010): "Test Patient",  # patient_name (required)
            (0x0020, 0x000D): "1.2.3.4.5",      # study_uid (required)
            (0x0020, 0x000E): "1.2.3.4.6",      # series_uid (required)
            (0x0008, 0x0018): "1.2.3.4.7",      # sop_instance_uid (required)
            (0x0008, 0x0060): "MR",             # modality (required)
        }.get(tag))

        schema = {
            "schema_version": "1.0",
            "extractors": {
                "standard": [
                    {"tag": "(0010,0010)", "alias": "patient_name", "required": True},
                    {"tag": "(0020,000D)", "alias": "study_uid", "required": True},
                    {"tag": "(0020,000E)", "alias": "series_uid", "required": True},
                    {"tag": "(0008,0018)", "alias": "sop_instance_uid", "required": True},
                    {"tag": "(0008,0060)", "alias": "modality", "required": True},
                ]
            }
        }

        parser = ConfigurableDicomParser(schema, {})

        # Mock pydicom.dcmread
        with patch('pydicom.dcmread', return_value=mock_ds):
            with patch.object(Path, 'stat', return_value=Mock(st_size=1024)):
                result = parser.parse("/fake/path.dcm")

        assert result.success is True
        assert len(result.errors) == 0
        assert result.tags['patient_name'] == "Test Patient"
        assert result.tags['modality'] == "MR"  # transform: uppercase

    def test_parse_fails_when_required_tag_missing(self, tmp_path):
        """测试：required 标签缺失时解析失败"""
        mock_ds = Mock()
        mock_ds.file_meta = Mock()
        mock_ds.file_meta.TransferSyntaxUID = "1.2.840.10008.1.2"
        # 缺少 patient_name (required)
        mock_ds.get = Mock(side_effect=lambda tag: {
            (0x0020, 0x000D): "1.2.3.4.5",      # study_uid
            (0x0020, 0x000E): "1.2.3.4.6",      # series_uid
            (0x0008, 0x0018): "1.2.3.4.7",      # sop_instance_uid
            (0x0008, 0x0060): "MR",             # modality
        }.get(tag))

        schema = {
            "schema_version": "1.0",
            "extractors": {
                "standard": [
                    {"tag": "(0010,0010)", "alias": "patient_name", "required": True},
                    {"tag": "(0020,000D)", "alias": "study_uid", "required": True},
                    {"tag": "(0020,000E)", "alias": "series_uid", "required": True},
                    {"tag": "(0008,0018)", "alias": "sop_instance_uid", "required": True},
                    {"tag": "(0008,0060)", "alias": "modality", "required": True},
                ]
            }
        }

        parser = ConfigurableDicomParser(schema, {})

        with patch('pydicom.dcmread', return_value=mock_ds):
            with patch.object(Path, 'stat', return_value=Mock(st_size=1024)):
                result = parser.parse("/fake/path.dcm")

        # Task B: required 缺失时解析必须失败
        assert result.success is False
        assert len(result.errors) == 1
        assert "patient_name" in result.errors[0]
        assert "Missing required tags" in result.errors[0]

    def test_parse_fails_with_multiple_missing_required(self):
        """测试：多个 required 标签缺失时，错误信息包含所有缺失字段"""
        mock_ds = Mock()
        mock_ds.file_meta = Mock()
        mock_ds.file_meta.TransferSyntaxUID = "1.2.840.10008.1.2"
        # 只提供部分 required 字段
        mock_ds.get = Mock(side_effect=lambda tag: {
            (0x0008, 0x0060): "CT",  # modality
        }.get(tag))

        schema = {
            "schema_version": "1.0",
            "extractors": {
                "standard": [
                    {"tag": "(0010,0010)", "alias": "patient_name", "required": True},
                    {"tag": "(0020,000D)", "alias": "study_uid", "required": True},
                    {"tag": "(0020,000E)", "alias": "series_uid", "required": True},
                    {"tag": "(0008,0018)", "alias": "sop_instance_uid", "required": True},
                    {"tag": "(0008,0060)", "alias": "modality", "required": True},
                ]
            }
        }

        parser = ConfigurableDicomParser(schema, {})

        with patch('pydicom.dcmread', return_value=mock_ds):
            with patch.object(Path, 'stat', return_value=Mock(st_size=1024)):
                result = parser.parse("/fake/path.dcm")

        assert result.success is False
        # 错误信息应包含所有缺失字段
        error_msg = result.errors[0]
        assert "patient_name" in error_msg
        assert "study_uid" in error_msg
        assert "series_uid" in error_msg
        assert "sop_instance_uid" in error_msg


class TestOptionalTagHandling:
    """Task B: optional 标签处理测试"""

    def test_optional_missing_does_not_fail(self):
        """测试：optional 标签缺失不会导致解析失败"""
        mock_ds = Mock()
        mock_ds.file_meta = Mock()
        mock_ds.file_meta.TransferSyntaxUID = "1.2.840.10008.1.2"
        # 提供所有 required，但 optional 缺失
        mock_ds.get = Mock(side_effect=lambda tag: {
            (0x0010, 0x0010): "Test Patient",  # patient_name (required)
            (0x0020, 0x000D): "1.2.3.4.5",      # study_uid (required)
            (0x0020, 0x000E): "1.2.3.4.6",      # series_uid (required)
            (0x0008, 0x0018): "1.2.3.4.7",      # sop_instance_uid (required)
            (0x0008, 0x0060): "MR",             # modality (required)
            # manufacturer (optional) - 缺失
        }.get(tag))

        schema = {
            "schema_version": "1.0",
            "extractors": {
                "standard": [
                    {"tag": "(0010,0010)", "alias": "patient_name", "required": True},
                    {"tag": "(0020,000D)", "alias": "study_uid", "required": True},
                    {"tag": "(0020,000E)", "alias": "series_uid", "required": True},
                    {"tag": "(0008,0018)", "alias": "sop_instance_uid", "required": True},
                    {"tag": "(0008,0060)", "alias": "modality", "required": True},
                    {"tag": "(0008,0070)", "alias": "manufacturer", "required": False},  # optional
                ]
            }
        }

        parser = ConfigurableDicomParser(schema, {})

        with patch('pydicom.dcmread', return_value=mock_ds):
            with patch.object(Path, 'stat', return_value=Mock(st_size=1024)):
                result = parser.parse("/fake/path.dcm")

        # optional 缺失不应导致失败
        assert result.success is True
        assert "manufacturer" not in result.tags
        assert len(result.errors) == 0


class TestTransformValidation:
    """Task B: transform 功能测试"""

    def test_uppercase_transform(self):
        """测试：uppercase transform 生效"""
        mock_ds = Mock()
        mock_ds.file_meta = Mock()
        mock_ds.file_meta.TransferSyntaxUID = "1.2.840.10008.1.2"
        mock_ds.get = Mock(side_effect=lambda tag: {
            (0x0010, 0x0010): "Test Patient",
            (0x0020, 0x000D): "1.2.3.4.5",
            (0x0020, 0x000E): "1.2.3.4.6",
            (0x0008, 0x0018): "1.2.3.4.7",
            (0x0008, 0x0060): "mr",  # 小写输入
        }.get(tag))

        schema = {
            "schema_version": "1.0",
            "extractors": {
                "standard": [
                    {"tag": "(0010,0010)", "alias": "patient_name", "required": True},
                    {"tag": "(0020,000D)", "alias": "study_uid", "required": True},
                    {"tag": "(0020,000E)", "alias": "series_uid", "required": True},
                    {"tag": "(0008,0018)", "alias": "sop_instance_uid", "required": True},
                    {"tag": "(0008,0060)", "alias": "modality", "required": True, "transform": "uppercase"},
                ]
            }
        }

        parser = ConfigurableDicomParser(schema, {})

        with patch('pydicom.dcmread', return_value=mock_ds):
            with patch.object(Path, 'stat', return_value=Mock(st_size=1024)):
                result = parser.parse("/fake/path.dcm")

        assert result.success is True
        assert result.tags['modality'] == "MR"  # 已转为大写

    def test_lowercase_transform(self):
        """测试：lowercase transform 生效"""
        mock_ds = Mock()
        mock_ds.file_meta = Mock()
        mock_ds.file_meta.TransferSyntaxUID = "1.2.840.10008.1.2"
        mock_ds.get = Mock(side_effect=lambda tag: {
            (0x0010, 0x0010): "Test Patient",
            (0x0020, 0x000D): "1.2.3.4.5",
            (0x0020, 0x000E): "1.2.3.4.6",
            (0x0008, 0x0018): "1.2.3.4.7",
            (0x0008, 0x0060): "MR",
            (0x0008, 0x103E): "T1 WEIGHTED",  # series_description - 大写
        }.get(tag))

        schema = {
            "schema_version": "1.0",
            "extractors": {
                "standard": [
                    {"tag": "(0010,0010)", "alias": "patient_name", "required": True},
                    {"tag": "(0020,000D)", "alias": "study_uid", "required": True},
                    {"tag": "(0020,000E)", "alias": "series_uid", "required": True},
                    {"tag": "(0008,0018)", "alias": "sop_instance_uid", "required": True},
                    {"tag": "(0008,0060)", "alias": "modality", "required": True},
                    {"tag": "(0008,103E)", "alias": "series_description", "transform": "lowercase"},
                ]
            }
        }

        parser = ConfigurableDicomParser(schema, {})

        with patch('pydicom.dcmread', return_value=mock_ds):
            with patch.object(Path, 'stat', return_value=Mock(st_size=1024)):
                result = parser.parse("/fake/path.dcm")

        assert result.success is True
        assert result.tags['series_description'] == "t1 weighted"  # 已转为小写


class TestPrivateExtractorErrorIsolation:
    """Task B: private extractor 异常隔离测试"""

    def test_extractor_exception_is_warning_not_failure(self):
        """测试：提取器异常作为 warning，不影响整体解析成功"""
        mock_ds = Mock()
        mock_ds.file_meta = Mock()
        mock_ds.file_meta.TransferSyntaxUID = "1.2.840.10008.1.2"
        mock_ds.get = Mock(side_effect=lambda tag: {
            (0x0010, 0x0010): "Test Patient",
            (0x0020, 0x000D): "1.2.3.4.5",
            (0x0020, 0x000E): "1.2.3.4.6",
            (0x0008, 0x0018): "1.2.3.4.7",
            (0x0008, 0x0060): "MR",
            (0x0008, 0x0070): "SIEMENS",
        }.get(tag))

        # 创建一个会抛出异常的提取器
        class FailingExtractor(TagExtractor):
            name = "failing_extractor"

            def can_extract(self, ds):
                return True  # 声称可以处理

            def extract(self, ds):
                raise RuntimeError("Simulated extraction failure")

        schema = {
            "schema_version": "1.0",
            "extractors": {
                "standard": [
                    {"tag": "(0010,0010)", "alias": "patient_name", "required": True},
                    {"tag": "(0020,000D)", "alias": "study_uid", "required": True},
                    {"tag": "(0020,000E)", "alias": "series_uid", "required": True},
                    {"tag": "(0008,0018)", "alias": "sop_instance_uid", "required": True},
                    {"tag": "(0008,0060)", "alias": "modality", "required": True},
                ],
                "private": [
                    {"name": "failing_extractor"},
                ]
            }
        }

        parser = ConfigurableDicomParser(schema, {"failing_extractor": FailingExtractor})

        with patch('pydicom.dcmread', return_value=mock_ds):
            with patch.object(Path, 'stat', return_value=Mock(st_size=1024)):
                result = parser.parse("/fake/path.dcm")

        # Task B: 提取器异常不应导致解析失败
        assert result.success is True
        # 但应该有 warning
        assert len(result.warnings) == 1
        assert "failing_extractor" in result.warnings[0]
        assert "failed" in result.warnings[0]


class TestDefaultSchemaPatientName:
    """P2-1: 默认 schema 中 patient_name 为 optional"""

    def test_missing_patient_name_does_not_fail_by_default(self):
        """测试：默认 schema 下缺少 PatientName 不导致解析失败"""
        mock_ds = Mock()
        mock_ds.file_meta = Mock()
        mock_ds.file_meta.TransferSyntaxUID = "1.2.840.10008.1.2"
        # 缺少 patient_name，但其他 required 都在
        mock_ds.get = Mock(side_effect=lambda tag: {
            (0x0020, 0x000D): "1.2.3.4.5",      # study_uid (required)
            (0x0020, 0x000E): "1.2.3.4.6",      # series_uid (required)
            (0x0008, 0x0018): "1.2.3.4.7",      # sop_instance_uid (required)
            (0x0008, 0x0060): "MR",             # modality (required)
        }.get(tag))

        # 使用默认 schema（通过 factory 获取）
        from dicom_ingestion.parser.factory import DicomParserFactory
        default_schema = DicomParserFactory._get_default_schema()
        parser = ConfigurableDicomParser(default_schema, {})

        with patch('pydicom.dcmread', return_value=mock_ds):
            with patch.object(Path, 'stat', return_value=Mock(st_size=1024)):
                result = parser.parse("/fake/path.dcm")

        # P2-1: 默认 intake 不因 PatientName 缺失失败
        assert result.success is True
        assert len(result.errors) == 0
        assert 'patient_name' not in result.tags

    def test_custom_schema_can_require_patient_name(self):
        """测试：自定义 schema 可以将 PatientName 设为 required"""
        mock_ds = Mock()
        mock_ds.file_meta = Mock()
        mock_ds.file_meta.TransferSyntaxUID = "1.2.840.10008.1.2"
        # 缺少 patient_name
        mock_ds.get = Mock(side_effect=lambda tag: {
            (0x0020, 0x000D): "1.2.3.4.5",
            (0x0020, 0x000E): "1.2.3.4.6",
            (0x0008, 0x0018): "1.2.3.4.7",
            (0x0008, 0x0060): "MR",
        }.get(tag))

        custom_schema = {
            "schema_version": "1.0",
            "extractors": {
                "standard": [
                    {"tag": "(0010,0010)", "alias": "patient_name", "required": True},
                    {"tag": "(0020,000D)", "alias": "study_uid", "required": True},
                    {"tag": "(0020,000E)", "alias": "series_uid", "required": True},
                    {"tag": "(0008,0018)", "alias": "sop_instance_uid", "required": True},
                    {"tag": "(0008,0060)", "alias": "modality", "required": True},
                ]
            }
        }

        parser = ConfigurableDicomParser(custom_schema, {})

        with patch('pydicom.dcmread', return_value=mock_ds):
            with patch.object(Path, 'stat', return_value=Mock(st_size=1024)):
                result = parser.parse("/fake/path.dcm")

        # 自定义 schema 要求 patient_name，缺失时应失败
        assert result.success is False
        assert "patient_name" in result.errors[0]

    def test_missing_study_series_sop_uid_still_fails(self):
        """测试：默认 schema 下缺少 DICOM identity UID 仍失败"""
        mock_ds = Mock()
        mock_ds.file_meta = Mock()
        mock_ds.file_meta.TransferSyntaxUID = "1.2.840.10008.1.2"
        # 有 patient_name，但缺少 study_uid
        mock_ds.get = Mock(side_effect=lambda tag: {
            (0x0010, 0x0010): "Test Patient",
            (0x0020, 0x000E): "1.2.3.4.6",      # series_uid
            (0x0008, 0x0018): "1.2.3.4.7",      # sop_instance_uid
            (0x0008, 0x0060): "MR",             # modality
        }.get(tag))

        from dicom_ingestion.parser.factory import DicomParserFactory
        default_schema = DicomParserFactory._get_default_schema()
        parser = ConfigurableDicomParser(default_schema, {})

        with patch('pydicom.dcmread', return_value=mock_ds):
            with patch.object(Path, 'stat', return_value=Mock(st_size=1024)):
                result = parser.parse("/fake/path.dcm")

        # DICOM identity UID 缺失仍应失败
        assert result.success is False
        assert "study_uid" in result.errors[0]


class TestParseErrorStructure:
    """Task B: ParseError 结构化错误信息测试"""

    def test_parse_error_contains_missing_fields(self):
        """测试：ParseError 包含缺失字段详情"""
        error = ParseError(
            message="Missing required tags",
            missing_required=[
                {'alias': 'patient_name', 'tag': '(0010,0010)', 'description': 'Required tag (0010,0010) (patient_name) is missing'},
                {'alias': 'study_uid', 'tag': '(0020,000D)', 'description': 'Required tag (0020,000D) (study_uid) is missing'},
            ],
            file_path="/test/file.dcm"
        )

        error_dict = error.to_dict()

        assert error_dict['error_type'] == 'ParseError'
        assert error_dict['error_code'] == 'REQUIRED_TAGS_MISSING'
        assert error_dict['file_path'] == "/test/file.dcm"
        assert len(error_dict['missing_required']) == 2
        assert error_dict['missing_required'][0]['alias'] == 'patient_name'

    def test_parse_error_str_format(self):
        """测试：ParseError 字符串格式包含缺失字段"""
        error = ParseError(
            message="Missing required tags",
            missing_required=[
                {'alias': 'patient_name', 'tag': '(0010,0010)', 'description': '...'},
            ],
            file_path="/test/file.dcm"
        )

        error_str = str(error)
        assert "patient_name" in error_str
        assert "ParseError" in error_str


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
