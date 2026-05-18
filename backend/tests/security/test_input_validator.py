import pytest
from dicom_ingestion.security.input_validator import (
    InputValidator, ValidationResult, PathValidator, UidValidator
)


class TestPathValidator:
    def test_valid_path(self):
        validator = PathValidator()
        result = validator.validate("folder/file.dcm")
        assert result.is_valid
        assert not result.errors

    def test_path_traversal(self):
        validator = PathValidator()
        result = validator.validate("../../../etc/passwd")
        assert not result.is_valid
        assert "path_traversal" in result.errors

    def test_null_bytes(self):
        validator = PathValidator()
        result = validator.validate("file\x00.dcm")
        assert not result.is_valid
        assert "null_byte" in result.errors


class TestUidValidator:
    def test_valid_uid(self):
        validator = UidValidator()
        result = validator.validate("1.2.840.10008.1.2.1")
        assert result.is_valid

    def test_invalid_uid_characters(self):
        validator = UidValidator()
        result = validator.validate("1.2.abc.10008")
        assert not result.is_valid
        assert "invalid_characters" in result.errors

    def test_uid_too_long(self):
        validator = UidValidator()
        result = validator.validate("1." + "2." * 100)
        assert not result.is_valid
        assert "too_long" in result.errors


class TestInputValidator:
    def test_validate_upload_filename(self):
        validator = InputValidator()
        result = validator.validate_upload_filename("test.dcm")
        assert result.is_valid
