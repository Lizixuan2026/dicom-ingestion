"""
Tag Validator — Validates DICOM tag requirements.

This module provides the TagValidator which validates that a parsed
DICOM header contains all required tags and meets content requirements.
"""
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
from enum import Enum


class ValidationResult(str, Enum):
    """Validation result types."""
    VALID = "valid"
    INVALID = "invalid"
    INCOMPLETE = "incomplete"


@dataclass
class ValidationReport:
    """
    Report from tag validation.

    Attributes:
        result: Overall validation result
        missing_tags: List of missing required tag names
        invalid_tags: Dictionary of tag names to error messages
        warnings: List of warning messages
    """
    result: ValidationResult = ValidationResult.VALID
    missing_tags: List[str] = field(default_factory=list)
    invalid_tags: Dict[str, str] = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)

    def is_valid(self) -> bool:
        """True if validation passed."""
        return self.result == ValidationResult.VALID


class TagValidator:
    """
    Service for validating DICOM tags.

    Responsibilities:
    - Check presence of required tags
    - Validate tag value formats
    - Report missing or invalid tags

    Interface:
        TagValidator.validate(parsed_header) -> :valid | :invalid
        TagValidator#missing_tags -> Array[String]

    Acceptance:
    - Returns :valid when all required tags present
    - Returns :invalid when required tags missing
    - Reports which specific tags are missing
    """

    # Required tags for a valid DICOM
    REQUIRED_TAGS = [
        "SOPClassUID",
        "SOPInstanceUID",
        "StudyInstanceUID",
        "SeriesInstanceUID",
    ]

    # Tags that should be present for complete metadata
    RECOMMENDED_TAGS = [
        "PatientID",
        "PatientName",
        "StudyDate",
        "Modality",
        "SeriesNumber",
        "InstanceNumber",
    ]

    def __init__(
        self,
        required_tags: Optional[List[str]] = None,
        strict: bool = False
    ):
        """
        Initialize the validator.

        Args:
            required_tags: List of required tag names. If None, uses default.
            strict: If True, missing recommended tags downgrade result to INCOMPLETE.
        """
        self.required_tags = required_tags or self.REQUIRED_TAGS.copy()
        self.strict = strict

    def validate(self, parsed_header) -> ValidationResult:
        """
        Validate a parsed DICOM header.

        Args:
            parsed_header: ParsedDicomHeader or similar object with required_tags dict

        Returns:
            ValidationResult: VALID, INVALID, or INCOMPLETE
        """
        # Get the required tags from the header
        if hasattr(parsed_header, 'required_tags'):
            header_tags = parsed_header.required_tags
        elif hasattr(parsed_header, 'raw_tags'):
            header_tags = parsed_header.raw_tags
        else:
            header_tags = parsed_header if isinstance(parsed_header, dict) else {}

        # Check for missing required tags
        missing = []
        for tag_name in self.required_tags:
            if tag_name not in header_tags or not header_tags[tag_name]:
                missing.append(tag_name)

        if missing:
            return ValidationResult.INVALID

        # In strict mode, check recommended tags
        if self.strict:
            missing_recommended = []
            for tag_name in self.RECOMMENDED_TAGS:
                if tag_name not in header_tags or not header_tags[tag_name]:
                    missing_recommended.append(tag_name)

            if missing_recommended:
                return ValidationResult.INCOMPLETE

        return ValidationResult.VALID

    def validate_with_report(self, parsed_header) -> ValidationReport:
        """
        Validate and return detailed report.

        Args:
            parsed_header: ParsedDicomHeader or similar

        Returns:
            ValidationReport with detailed information
        """
        report = ValidationReport()

        # Get tags from header
        if hasattr(parsed_header, 'required_tags'):
            header_tags = parsed_header.required_tags
        elif hasattr(parsed_header, 'raw_tags'):
            header_tags = parsed_header.raw_tags
        else:
            header_tags = parsed_header if isinstance(parsed_header, dict) else {}

        # Check required tags
        for tag_name in self.required_tags:
            if tag_name not in header_tags:
                report.missing_tags.append(tag_name)
            elif not header_tags[tag_name]:
                report.invalid_tags[tag_name] = "Empty value"

        # Check recommended tags (as warnings)
        for tag_name in self.RECOMMENDED_TAGS:
            if tag_name not in header_tags:
                report.warnings.append(f"Recommended tag '{tag_name}' is missing")

        # Determine result
        if report.missing_tags or report.invalid_tags:
            report.result = ValidationResult.INVALID
        elif self.strict and report.warnings:
            report.result = ValidationResult.INCOMPLETE
        else:
            report.result = ValidationResult.VALID

        return report

    def get_missing_tags(self, parsed_header) -> List[str]:
        """
        Get list of missing required tags.

        Args:
            parsed_header: ParsedDicomHeader or similar

        Returns:
            List of missing tag names
        """
        report = self.validate_with_report(parsed_header)
        return report.missing_tags

    def validate_uid_format(self, uid: str) -> bool:
        """
        Validate UID format.

        UIDs should be dot-separated numbers.

        Args:
            uid: UID string to validate

        Returns:
            True if format is valid
        """
        if not uid:
            return False

        parts = uid.split(".")
        if len(parts) < 2:
            return False

        for part in parts:
            if not part.isdigit():
                return False

        return True

    def validate_uids(self, parsed_header) -> List[str]:
        """
        Validate UID formats in header.

        Args:
            parsed_header: ParsedDicomHeader

        Returns:
            List of UID validation errors
        """
        errors = []
        uid_tags = ["SOPInstanceUID", "StudyInstanceUID", "SeriesInstanceUID", "FrameOfReferenceUID"]

        tags_dict = parsed_header.raw_tags if hasattr(parsed_header, 'raw_tags') else {}

        for tag_name in uid_tags:
            if tag_name in tags_dict:
                uid = tags_dict[tag_name]
                if uid and not self.validate_uid_format(uid):
                    errors.append(f"Invalid UID format in {tag_name}: {uid}")

        return errors


# Convenience function for quick validation
def quick_validate(parsed_header) -> bool:
    """
    Quick validation of a parsed DICOM header.

    Args:
        parsed_header: ParsedDicomHeader or dict with tags

    Returns:
        True if valid, False otherwise
    """
    validator = TagValidator()
    return validator.validate(parsed_header) == ValidationResult.VALID
