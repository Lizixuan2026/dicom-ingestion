"""Input validation and sanitization for DICOM ingestion."""

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Protocol


@dataclass
class ValidationResult:
    """Result of input validation."""
    is_valid: bool
    errors: Dict[str, str] = field(default_factory=dict)
    sanitized: Optional[str] = None


class Validator(Protocol):
    """Protocol for validators."""
    def validate(self, value: str) -> ValidationResult:
        ...


class PathValidator:
    """Validates file paths for security issues."""
    
    MAX_LENGTH = 4096
    TRAVERSAL_PATTERN = re.compile(r"\.\./|\.\.\\|^/|^\\")
    NULL_BYTE_PATTERN = re.compile(r"\x00")
    CONTROL_CHAR_PATTERN = re.compile(r"[\x00-\x1f\x7f-\x9f]")
    
    def validate(self, path: str) -> ValidationResult:
        """Validate a file path."""
        errors: Dict[str, str] = {}
        
        if not path:
            errors["empty"] = "Path cannot be empty"
            return ValidationResult(is_valid=False, errors=errors)
        
        if len(path) > self.MAX_LENGTH:
            errors["too_long"] = f"Path exceeds maximum length of {self.MAX_LENGTH}"
        
        if self.NULL_BYTE_PATTERN.search(path):
            errors["null_byte"] = "Path contains null bytes"
        
        if self.CONTROL_CHAR_PATTERN.search(path):
            errors["control_chars"] = "Path contains control characters"
        
        if self.TRAVERSAL_PATTERN.search(path):
            errors["path_traversal"] = "Path contains traversal attempts"
        
        dangerous = ["//", "\\\\", "..", "~", "$"]
        for pattern in dangerous:
            if pattern in path:
                errors[f"dangerous_{pattern}"] = f"Path contains dangerous pattern: {pattern}"
                break
        
        return ValidationResult(
            is_valid=len(errors) == 0,
            errors=errors,
            sanitized=self._sanitize(path) if errors else path
        )
    
    def _sanitize(self, path: str) -> str:
        """Attempt to sanitize a path (best effort)."""
        sanitized = path.replace("\x00", "")
        sanitized = self.CONTROL_CHAR_PATTERN.sub("", sanitized)
        sanitized = sanitized.replace("../", "").replace("..\\", "")
        return sanitized


class UidValidator:
    """Validates DICOM UIDs (Unique Identifiers)."""
    
    MAX_LENGTH = 64
    UID_PATTERN = re.compile(r"^[0-9]+(\.[0-9]+)*$")
    
    def validate(self, uid: str) -> ValidationResult:
        """Validate a DICOM UID."""
        errors: Dict[str, str] = {}
        
        if not uid:
            errors["empty"] = "UID cannot be empty"
            return ValidationResult(is_valid=False, errors=errors)
        
        if len(uid) > self.MAX_LENGTH:
            errors["too_long"] = f"UID exceeds maximum length of {self.MAX_LENGTH}"
        
        if not self.UID_PATTERN.match(uid):
            errors["invalid_characters"] = "UID must contain only digits and dots"
        
        if ".." in uid:
            errors["consecutive_dots"] = "UID cannot contain consecutive dots"
        
        if uid.startswith("."):
            errors["starts_with_dot"] = "UID cannot start with a dot"
        if uid.endswith("."):
            errors["ends_with_dot"] = "UID cannot end with a dot"
        
        return ValidationResult(is_valid=len(errors) == 0, errors=errors)


class InputValidator:
    """Main input validation service."""
    
    def __init__(self):
        self._validators: Dict[str, Validator] = {
            "path": PathValidator(),
            "uid": UidValidator(),
        }
    
    def validate_path(self, path: str) -> ValidationResult:
        """Validate a file path."""
        return self._validators["path"].validate(path)
    
    def validate_uid(self, uid: str) -> ValidationResult:
        """Validate a DICOM UID."""
        return self._validators["uid"].validate(uid)
    
    def validate_upload_filename(self, filename: str) -> ValidationResult:
        """Validate an upload filename with additional checks."""
        path_result = self.validate_path(filename)
        errors = dict(path_result.errors)
        
        if filename.count(".") > 2:
            errors["multiple_extensions"] = "Filename has multiple extensions"
        
        return ValidationResult(
            is_valid=len(errors) == 0,
            errors=errors,
            sanitized=path_result.sanitized
        )
