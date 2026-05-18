"""
Tests for TagValidator.

Acceptance criteria:
- Returns :valid when all required tags present
- Returns :invalid when required tags missing
- Reports which specific tags are missing
"""
import pytest

from dicom_ingestion.services.parser import (
    TagValidator,
    ValidationResult,
    ValidationReport,
    ParsedDicomHeader
)
from dicom_ingestion.services.parser.tag_validator import quick_validate


class TestTagValidatorCreation:
    """Tests for validator creation."""

    def test_validator_default_required_tags(self):
        """Validator should have default required tags."""
        validator = TagValidator()
        assert len(validator.required_tags) > 0
        assert "SOPInstanceUID" in validator.required_tags

    def test_validator_accepts_custom_required_tags(self):
        """Validator should accept custom required tags."""
        custom_tags = ["Tag1", "Tag2"]
        validator = TagValidator(required_tags=custom_tags)
        assert validator.required_tags == custom_tags

    def test_validator_strict_mode(self):
        """Strict mode should not mutate required tag list."""
        validator = TagValidator(strict=True)
        assert validator.required_tags == TagValidator.REQUIRED_TAGS


class TestTagValidatorValidate:
    """Tests for validate method."""

    def test_valid_when_all_tags_present(self):
        """Should return VALID when all required tags present."""
        validator = TagValidator()
        header = ParsedDicomHeader(
            required_tags={
                "SOPClassUID": "1.2.3",
                "SOPInstanceUID": "1.2.4",
                "StudyInstanceUID": "1.2.5",
                "SeriesInstanceUID": "1.2.6",
            }
        )

        result = validator.validate(header)

        assert result == ValidationResult.VALID

    def test_invalid_when_required_tag_missing(self):
        """Should return INVALID when required tag missing."""
        validator = TagValidator()
        header = ParsedDicomHeader(
            required_tags={
                "SOPClassUID": "1.2.3",
                # Missing SOPInstanceUID
                "StudyInstanceUID": "1.2.5",
                "SeriesInstanceUID": "1.2.6",
            }
        )

        result = validator.validate(header)

        assert result == ValidationResult.INVALID

    def test_invalid_when_required_tag_empty(self):
        """Should return INVALID when required tag is empty."""
        validator = TagValidator()
        header = ParsedDicomHeader(
            required_tags={
                "SOPClassUID": "1.2.3",
                "SOPInstanceUID": "",  # Empty
                "StudyInstanceUID": "1.2.5",
                "SeriesInstanceUID": "1.2.6",
            }
        )

        result = validator.validate(header)

        assert result == ValidationResult.INVALID

    def test_incomplete_when_strict_recommended_missing(self):
        """In strict mode, missing recommended tags should be INCOMPLETE."""
        validator = TagValidator(strict=True)
        header = ParsedDicomHeader(
            required_tags={
                "SOPClassUID": "1.2.3",
                "SOPInstanceUID": "1.2.4",
                "StudyInstanceUID": "1.2.5",
                "SeriesInstanceUID": "1.2.6",
                # Missing recommended tags
            }
        )

        result = validator.validate(header)

        assert result == ValidationResult.INCOMPLETE

    def test_invalid_when_strict_required_missing(self):
        """In strict mode, missing required tags should still be INVALID."""
        validator = TagValidator(strict=True)
        header = ParsedDicomHeader(
            required_tags={
                "SOPClassUID": "1.2.3",
                # Missing SOPInstanceUID
                "StudyInstanceUID": "1.2.5",
                "SeriesInstanceUID": "1.2.6",
            }
        )

        result = validator.validate(header)

        assert result == ValidationResult.INVALID

    def test_valid_when_non_strict_recommended_missing(self):
        """In non-strict mode, missing recommended tags should still be VALID."""
        validator = TagValidator(strict=False)
        header = ParsedDicomHeader(
            required_tags={
                "SOPClassUID": "1.2.3",
                "SOPInstanceUID": "1.2.4",
                "StudyInstanceUID": "1.2.5",
                "SeriesInstanceUID": "1.2.6",
            }
        )

        result = validator.validate(header)

        assert result == ValidationResult.VALID


class TestTagValidatorValidateWithReport:
    """Tests for validate_with_report method."""

    def test_report_contains_missing_tags(self):
        """Report should list missing required tags."""
        validator = TagValidator()
        header = ParsedDicomHeader(
            required_tags={
                "SOPClassUID": "1.2.3",
                # Missing SOPInstanceUID and StudyInstanceUID
                "SeriesInstanceUID": "1.2.6",
            }
        )

        report = validator.validate_with_report(header)

        assert "SOPInstanceUID" in report.missing_tags
        assert "StudyInstanceUID" in report.missing_tags

    def test_report_contains_invalid_tags(self):
        """Report should list invalid tags."""
        validator = TagValidator()
        header = ParsedDicomHeader(
            required_tags={
                "SOPClassUID": "",  # Empty is invalid
                "SOPInstanceUID": "1.2.4",
                "StudyInstanceUID": "1.2.5",
                "SeriesInstanceUID": "1.2.6",
            }
        )

        report = validator.validate_with_report(header)

        assert "SOPClassUID" in report.invalid_tags

    def test_report_contains_warnings(self):
        """Report should contain warnings for missing recommended tags."""
        validator = TagValidator()
        header = ParsedDicomHeader(
            required_tags={
                "SOPClassUID": "1.2.3",
                "SOPInstanceUID": "1.2.4",
                "StudyInstanceUID": "1.2.5",
                "SeriesInstanceUID": "1.2.6",
                # Missing recommended tags
            }
        )

        report = validator.validate_with_report(header)

        assert len(report.warnings) > 0
        assert any("PatientID" in w for w in report.warnings)

    def test_strict_report_recommended_missing_is_warning_not_missing(self):
        """Strict mode should treat recommended missing tags as warnings."""
        validator = TagValidator(strict=True)
        header = ParsedDicomHeader(
            required_tags={
                "SOPClassUID": "1.2.3",
                "SOPInstanceUID": "1.2.4",
                "StudyInstanceUID": "1.2.5",
                "SeriesInstanceUID": "1.2.6",
            }
        )

        report = validator.validate_with_report(header)

        assert report.result == ValidationResult.INCOMPLETE
        assert "PatientID" not in report.missing_tags
        assert any("PatientID" in w for w in report.warnings)

    def test_non_strict_report_recommended_missing_can_be_valid(self):
        """Non-strict mode can be VALID even with recommended warnings."""
        validator = TagValidator(strict=False)
        header = ParsedDicomHeader(
            required_tags={
                "SOPClassUID": "1.2.3",
                "SOPInstanceUID": "1.2.4",
                "StudyInstanceUID": "1.2.5",
                "SeriesInstanceUID": "1.2.6",
            }
        )

        report = validator.validate_with_report(header)

        assert report.result == ValidationResult.VALID
        assert len(report.warnings) > 0

    def test_valid_report_has_no_issues(self):
        """Valid header should have empty issue lists."""
        validator = TagValidator()
        header = ParsedDicomHeader(
            required_tags={
                "SOPClassUID": "1.2.3",
                "SOPInstanceUID": "1.2.4",
                "StudyInstanceUID": "1.2.5",
                "SeriesInstanceUID": "1.2.6",
            }
        )

        report = validator.validate_with_report(header)

        assert report.is_valid() is True
        assert len(report.missing_tags) == 0
        assert len(report.invalid_tags) == 0


class TestTagValidatorGetMissingTags:
    """Tests for get_missing_tags method."""

    def test_returns_missing_tag_names(self):
        """Should return list of missing tag names."""
        validator = TagValidator()
        header = ParsedDicomHeader(
            required_tags={
                "SOPClassUID": "1.2.3",
                # Missing SOPInstanceUID
                "StudyInstanceUID": "1.2.5",
                "SeriesInstanceUID": "1.2.6",
            }
        )

        missing = validator.get_missing_tags(header)

        assert "SOPInstanceUID" in missing
        assert "SOPClassUID" not in missing


class TestTagValidatorUidValidation:
    """Tests for UID format validation."""

    def test_valid_uid_format(self):
        """Should validate correct UID format."""
        validator = TagValidator()
        assert validator.validate_uid_format("1.2.840.10008.1.1") is True
        assert validator.validate_uid_format("1.2.3") is True

    def test_invalid_uid_format_no_dots(self):
        """Should reject UID without dots."""
        validator = TagValidator()
        assert validator.validate_uid_format("12345") is False

    def test_invalid_uid_format_single_part(self):
        """Should reject UID with single part."""
        validator = TagValidator()
        assert validator.validate_uid_format("1") is False

    def test_invalid_uid_format_non_numeric(self):
        """Should reject UID with non-numeric parts."""
        validator = TagValidator()
        assert validator.validate_uid_format("1.2.abc") is False

    def test_empty_uid_invalid(self):
        """Empty UID should be invalid."""
        validator = TagValidator()
        assert validator.validate_uid_format("") is False


class TestTagValidatorValidateUids:
    """Tests for validate_uids method."""

    def test_no_errors_for_valid_uids(self):
        """Should return no errors for valid UIDs."""
        validator = TagValidator()
        header = ParsedDicomHeader(
            raw_tags={
                "SOPInstanceUID": "1.2.840.10008.1.1",
                "StudyInstanceUID": "1.2.3.4.5",
            }
        )

        errors = validator.validate_uids(header)

        assert len(errors) == 0

    def test_error_for_invalid_uid_format(self):
        """Should return error for invalid UID format."""
        validator = TagValidator()
        header = ParsedDicomHeader(
            raw_tags={
                "SOPInstanceUID": "invalid-uid-format",
            }
        )

        errors = validator.validate_uids(header)

        assert len(errors) > 0
        assert any("SOPInstanceUID" in e for e in errors)


class TestQuickValidate:
    """Tests for quick_validate convenience function."""

    def test_quick_validate_true_for_valid(self):
        """quick_validate should return True for valid header."""
        header = ParsedDicomHeader(
            required_tags={
                "SOPClassUID": "1.2.3",
                "SOPInstanceUID": "1.2.4",
                "StudyInstanceUID": "1.2.5",
                "SeriesInstanceUID": "1.2.6",
            }
        )

        assert quick_validate(header) is True

    def test_quick_validate_false_for_invalid(self):
        """quick_validate should return False for invalid header."""
        header = ParsedDicomHeader(
            required_tags={
                "SOPClassUID": "1.2.3",
                # Missing required tags
            }
        )

        assert quick_validate(header) is False

    def test_quick_validate_accepts_dict(self):
        """quick_validate should accept plain dict."""
        header = {
            "SOPClassUID": "1.2.3",
            "SOPInstanceUID": "1.2.4",
            "StudyInstanceUID": "1.2.5",
            "SeriesInstanceUID": "1.2.6",
        }

        assert quick_validate(header) is True


class TestValidationReport:
    """Tests for ValidationReport class."""

    def test_is_valid_true_for_valid(self):
        """is_valid should be True for VALID result."""
        report = ValidationReport(result=ValidationResult.VALID)
        assert report.is_valid() is True

    def test_is_valid_false_for_invalid(self):
        """is_valid should be False for INVALID result."""
        report = ValidationReport(result=ValidationResult.INVALID)
        assert report.is_valid() is False

    def test_is_valid_false_for_incomplete(self):
        """is_valid should be False for INCOMPLETE result."""
        report = ValidationReport(result=ValidationResult.INCOMPLETE)
        assert report.is_valid() is False
