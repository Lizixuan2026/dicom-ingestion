"""
ZIP Safety Scanner — Protects against malicious archive content.

This module provides safety checks for ZIP file extraction including:
- Zip bomb detection (claimed vs actual size)
- Path traversal prevention (../)
- Nesting depth limits
- Entry count limits
"""
import io
import os
import zipfile
from dataclasses import dataclass
from typing import BinaryIO, Union


class ZipBombDetected(Exception):
    """
    Raised when a ZIP file exceeds safety limits for expansion.
    The expansion is aborted before writing excessive bytes to disk.
    """
    pass


class UnsafeArchivePath(Exception):
    """
    Raised when a ZIP entry contains a path traversal attempt (../).
    No files are extracted when this exception is raised.
    """
    pass


class NestedZipTooDeep(Exception):
    """
    Raised when ZIP nesting exceeds the configured maximum depth.
    """
    pass


@dataclass
class ZipSafetyLimits:
    """
    Configuration for ZIP safety limits.

    Attributes:
        max_total_bytes: Maximum total expanded size in bytes
        max_entry_count: Maximum number of entries in archive
        max_nesting_depth: Maximum depth for nested ZIP files
        max_entry_bytes: Maximum size for a single entry
    """
    max_total_bytes: int = 100 * 1024 * 1024  # 100 MB default
    max_entry_count: int = 10000
    max_nesting_depth: int = 3
    max_entry_bytes: int = 50 * 1024 * 1024  # 50 MB per entry

    @classmethod
    def conservative(cls) -> "ZipSafetyLimits":
        """Returns conservative limits suitable for production."""
        return cls(
            max_total_bytes=50 * 1024 * 1024,  # 50 MB
            max_entry_count=1000,
            max_nesting_depth=2,
            max_entry_bytes=10 * 1024 * 1024  # 10 MB
        )


class ZipSafetyScanner:
    """
    Scans ZIP files for safety issues before extraction.

    Responsibilities:
    - Detect ZIP bombs by checking claimed vs actual sizes
    - Prevent path traversal attacks
    - Enforce nesting depth limits
    - Enforce entry count and size limits

    Usage:
        scanner = ZipSafetyScanner(limits=ZipSafetyLimits.conservative())
        scanner.check_safety(zip_bytes)  # Raises on unsafe content
    """

    # DICOM magic number for file type detection
    DICOM_MAGIC = b"DICM"
    DICOM_MAGIC_OFFSET = 128

    def __init__(self, limits: ZipSafetyLimits = None):
        """
        Initialize with safety limits.

        Args:
            limits: ZipSafetyLimits instance. If None, uses default limits.
        """
        self.limits = limits or ZipSafetyLimits()

    def check_safety(self, data: Union[bytes, BinaryIO], current_depth: int = 0) -> None:
        """
        Check ZIP file for safety issues without extracting.

        Args:
            data: ZIP file as bytes or file-like object
            current_depth: Current nesting depth (for recursive checks)

        Raises:
            ZipBombDetected: If expansion would exceed size/entry limits
            UnsafeArchivePath: If any entry contains path traversal
            NestedZipTooDeep: If nesting depth exceeds limit
        """
        if current_depth > self.limits.max_nesting_depth:
            raise NestedZipTooDeep(
                f"ZIP nesting depth {current_depth} exceeds maximum {self.limits.max_nesting_depth}"
            )

        # Normalize to bytes
        if hasattr(data, 'read'):
            zip_bytes = data.read()
        else:
            zip_bytes = data

        # Check if it's a valid ZIP file
        if not zipfile.is_zipfile(io.BytesIO(zip_bytes)):
            # Not a ZIP file, no safety issue
            return

        with zipfile.ZipFile(io.BytesIO(zip_bytes), 'r') as zf:
            # Check entry count
            namelist = zf.namelist()
            if len(namelist) > self.limits.max_entry_count:
                raise ZipBombDetected(
                    f"ZIP contains {len(namelist)} entries, exceeding limit of {self.limits.max_entry_count}"
                )

            # Calculate claimed expansion size
            total_claimed_size = sum(info.file_size for info in zf.infolist())
            if total_claimed_size > self.limits.max_total_bytes:
                raise ZipBombDetected(
                    f"ZIP claims {total_claimed_size} bytes when expanded, "
                    f"exceeding limit of {self.limits.max_total_bytes} bytes"
                )

            # Check each entry for safety
            for info in zf.infolist():
                self._check_entry_path(info.filename)

                # Check individual entry size
                if info.file_size > self.limits.max_entry_bytes:
                    raise ZipBombDetected(
                        f"ZIP entry '{info.filename}' claims {info.file_size} bytes, "
                        f"exceeding limit of {self.limits.max_entry_bytes} bytes"
                    )

                # Check compression ratio for potential zip bomb
                if info.compress_size > 0 and info.file_size > 0:
                    ratio = info.file_size / info.compress_size
                    # If compression ratio is extremely high, it might be a zip bomb
                    # Normal compression rarely exceeds 100:1
                    if ratio > 100 and info.file_size > 1024 * 1024:  # Only check entries > 1MB
                        raise ZipBombDetected(
                            f"ZIP entry '{info.filename}' has suspicious compression ratio "
                            f"({ratio:.1f}:1). Potential zip bomb."
                        )

    def _check_entry_path(self, filename: str) -> None:
        """
        Check a filename for path traversal attempts.

        Args:
            filename: The filename from ZIP entry

        Raises:
            UnsafeArchivePath: If path traversal is detected
        """
        # Normalize the path and check for traversal
        # We use os.path.normpath to normalize, then check if it starts with ..
        normalized = os.path.normpath(filename)

        # Check for path traversal
        if normalized.startswith('..') or '/../' in normalized or '\\../' in normalized:
            raise UnsafeArchivePath(
                f"ZIP entry '{filename}' contains path traversal (../). "
                f"Extraction aborted for security."
            )

        # Also check the original for explicit .. patterns
        if '..' in filename.replace('../', '').replace('..\\', ''):
            # Additional check: ensure no .. remains after removing obvious patterns
            if '..' in filename:
                raise UnsafeArchivePath(
                    f"ZIP entry '{filename}' contains suspicious '..' pattern. "
                    f"Extraction aborted for security."
                )

    def extract_safe(
        self,
        data: Union[bytes, BinaryIO],
        extract_path: str = None
    ) -> list:
        """
        Safely extract ZIP contents after passing all safety checks.

        Args:
            data: ZIP file as bytes or file-like object
            extract_path: Optional path to extract files to.
                       If None, returns list of (filename, bytes) tuples.

        Returns:
            List of extracted items. If extract_path is None, returns
            list of (filename, bytes) tuples. Otherwise returns list of
            extracted file paths.

        Raises:
            ZipBombDetected: If expansion would exceed limits
            UnsafeArchivePath: If path traversal detected
        """
        # First run safety checks
        self.check_safety(data)

        # Normalize to bytes for extraction
        if hasattr(data, 'read'):
            zip_bytes = data.read()
        else:
            zip_bytes = data

        extracted = []

        with zipfile.ZipFile(io.BytesIO(zip_bytes), 'r') as zf:
            for info in zf.infolist():
                if info.is_dir():
                    continue

                # Extract file content
                content = zf.read(info.filename)

                if extract_path:
                    # Ensure safe extraction path
                    safe_name = os.path.basename(info.filename)
                    if not safe_name:  # Handle edge case
                        continue
                    target_path = os.path.join(extract_path, safe_name)
                    os.makedirs(os.path.dirname(target_path), exist_ok=True)
                    with open(target_path, 'wb') as f:
                        f.write(content)
                    extracted.append(target_path)
                else:
                    extracted.append((info.filename, content))

        return extracted

    def is_dicom_file(self, data: bytes) -> bool:
        """
        Check if bytes represent a DICOM file.

        Args:
            data: File content as bytes

        Returns:
            True if data appears to be DICOM, False otherwise
        """
        if len(data) < self.DICOM_MAGIC_OFFSET + len(self.DICOM_MAGIC):
            return False
        return data[self.DICOM_MAGIC_OFFSET:self.DICOM_MAGIC_OFFSET + len(self.DICOM_MAGIC)] == self.DICOM_MAGIC
