"""
Scan Service — Discovers DICOM candidates from upload packages.

This module provides the ScanService which scans upload packages
(folders or ZIP files) to discover candidate DICOM files, with
safety checks and proper classification of DICOM vs non-DICOM content.
"""
import io
import os
import zipfile
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional, Union, BinaryIO
from io import BytesIO

from .zip_safety import (
    ZipSafetyScanner,
    ZipSafetyLimits,
    ZipBombDetected,
    UnsafeArchivePath,
    NestedZipTooDeep
)


class ScanStatus(str, Enum):
    """Status values for scanned items."""
    SEEN = "seen"                    # Initial state
    PENDING = "pending"              # Waiting for processing
    REJECTED_NON_DICOM = "rejected_non_dicom"  # Not a DICOM file
    REJECTED_UNSAFE = "rejected_unsafe"        # Failed safety check
    ACCEPTED = "accepted"            # Valid DICOM candidate


@dataclass
class ScanItem:
    """
    Represents a discovered file candidate from scanning.

    Attributes:
        source_path: Original path/filename in the upload
        byte_size: Size in bytes
        item_bytes_or_uri: Either the bytes directly or a URI to retrieve them
        scan_status: Current scan status (seen, pending, rejected, accepted)
        is_dicom: Whether this appears to be a DICOM file
        error_reason: Reason for rejection if scan_status is rejected
        nested_depth: Nesting depth for items in ZIP files
    """
    source_path: str
    byte_size: int
    item_bytes_or_uri: Union[bytes, str]
    scan_status: ScanStatus = ScanStatus.SEEN
    is_dicom: bool = False
    error_reason: str = ""
    nested_depth: int = 0


@dataclass
class ScanManifest:
    """
    Result of scanning an upload package.

    Attributes:
        items: List of discovered ScanItem instances
        total_bytes_scanned: Total bytes processed
        total_items: Total number of items discovered
        dicom_count: Number of items identified as DICOM
        non_dicom_count: Number of items identified as non-DICOM
        rejected_count: Number of items rejected (unsafe or invalid)
        scan_errors: List of errors encountered during scanning
    """
    items: List[ScanItem] = field(default_factory=list)
    total_bytes_scanned: int = 0
    total_items: int = 0
    dicom_count: int = 0
    non_dicom_count: int = 0
    rejected_count: int = 0
    scan_errors: List[str] = field(default_factory=list)


class ScanService:
    """
    Service for scanning upload packages to discover DICOM candidates.

    Responsibilities:
    - Recursively list DICOM candidates from folders or ZIP files
    - Mark non-DICOM files with scan_status = rejected_non_dicom
    - Enforce ZIP safety: max bytes, max entries, max nesting depth
    - Detect path traversal entries and reject them
    - Surface parse and packaging failures without dropping other candidates

    Interface:
        ScanService.scan(upload_package) -> ScanManifest
          ScanManifest#items -> [{source_path, byte_size, item_bytes_or_uri}]

    Acceptance:
    - Recursively lists DICOM candidates from folder or ZIP
    - Non-DICOM files are listed with scan_status = rejected_non_dicom
    - ZIP expansion enforces max bytes, max entry count, max nesting depth
    - ZipBombDetected raised and logged before full extraction when limits exceeded
    - UnsafeArchivePath raised on path traversal entries (../)
    - Scanner with zip_bomb.zip fixture raises before writing > safety limit bytes
    - Scanner with zip_path_traversal.zip raises before extracting any file
    """

    # DICOM magic number for file type detection
    DICOM_MAGIC = b"DICM"
    DICOM_MAGIC_OFFSET = 128

    def __init__(self, safety_limits: ZipSafetyLimits = None):
        """
        Initialize the scan service.

        Args:
            safety_limits: ZipSafetyLimits for ZIP file scanning.
                         If None, uses default (conservative) limits.
        """
        self.safety_scanner = ZipSafetyScanner(limits=safety_limits or ZipSafetyLimits.conservative())

    def scan(
        self,
        upload_package,
        max_recursion_depth: int = 3
    ) -> ScanManifest:
        """
        Scan an upload package to discover DICOM candidates.

        Args:
            upload_package: An object with attributes:
                - uri: URI to retrieve the package bytes
                - content_hash: SHA-256 hash of content
                - size_bytes: Size in bytes
                - original_filename: Original filename (used to detect ZIP files)
            max_recursion_depth: Maximum depth for nested ZIP scanning

        Returns:
            ScanManifest with all discovered items and their statuses
        """
        manifest = ScanManifest()

        try:
            # Get the raw bytes from the package
            # This assumes the package has a method or attribute to get bytes
            # In practice, this might come from RawObjectStore.get(uri)
            package_bytes = self._get_package_bytes(upload_package)

            if package_bytes is None:
                manifest.scan_errors.append(f"Could not retrieve package bytes from {upload_package}")
                return manifest

            # Determine if this is a ZIP file
            is_zip = self._is_zip_file(package_bytes)

            if is_zip:
                # Scan ZIP contents with safety checks
                self._scan_zip_contents(
                    package_bytes,
                    manifest,
                    current_depth=0,
                    max_depth=max_recursion_depth
                )
            else:
                # Single file - check if DICOM
                self._scan_single_file(
                    package_bytes,
                    upload_package.original_filename or "unknown",
                    manifest
                )

        except ZipBombDetected as e:
            manifest.scan_errors.append(f"ZIP bomb detected: {e}")
            manifest.rejected_count += 1
        except UnsafeArchivePath as e:
            manifest.scan_errors.append(f"Unsafe archive path: {e}")
            manifest.rejected_count += 1
        except NestedZipTooDeep as e:
            manifest.scan_errors.append(f"ZIP nesting too deep: {e}")
            manifest.rejected_count += 1
        except Exception as e:
            manifest.scan_errors.append(f"Scan error: {e}")

        # Update manifest totals
        manifest.total_items = len(manifest.items)
        manifest.dicom_count = sum(1 for item in manifest.items if item.is_dicom)
        manifest.non_dicom_count = sum(1 for item in manifest.items if not item.is_dicom and item.scan_status != ScanStatus.REJECTED_UNSAFE)
        manifest.rejected_count = sum(1 for item in manifest.items if item.scan_status in [ScanStatus.REJECTED_UNSAFE, ScanStatus.REJECTED_NON_DICOM])

        return manifest

    def _get_package_bytes(self, upload_package) -> Optional[bytes]:
        """
        Extract bytes from upload package.

        Handles different package types:
        - Objects with .get_bytes() method
        - Objects with .uri attribute (requires external store)
        - Raw bytes
        - BytesIO objects
        """
        # If it's already bytes
        if isinstance(upload_package, bytes):
            return upload_package

        # If it's a BytesIO
        if hasattr(upload_package, 'getvalue'):
            return upload_package.getvalue()

        # If it has a get_bytes method
        if hasattr(upload_package, 'get_bytes'):
            return upload_package.get_bytes()

        # If it has a uri attribute, we need an object store
        # For now, assume the package provides access to bytes directly
        if hasattr(upload_package, 'bytes'):
            return upload_package.bytes

        # Try to read if file-like
        if hasattr(upload_package, 'read'):
            return upload_package.read()

        return None

    def _is_zip_file(self, data: bytes) -> bool:
        """Check if data is a ZIP file."""
        if len(data) < 4:
            return False
        return zipfile.is_zipfile(io.BytesIO(data))

    def _scan_zip_contents(
        self,
        zip_bytes: bytes,
        manifest: ScanManifest,
        current_depth: int = 0,
        max_depth: int = 3,
        prefix: str = ""
    ) -> None:
        """
        Recursively scan ZIP file contents.

        Args:
            zip_bytes: The ZIP file as bytes
            manifest: ScanManifest to append items to
            current_depth: Current nesting depth
            max_depth: Maximum allowed nesting depth
            prefix: Path prefix for nested ZIPs
        """
        try:
            # Run safety checks first
            self.safety_scanner.check_safety(zip_bytes, current_depth=current_depth)
        except (ZipBombDetected, UnsafeArchivePath, NestedZipTooDeep) as e:
            # Re-raise to be caught by caller
            raise

        with zipfile.ZipFile(io.BytesIO(zip_bytes), 'r') as zf:
            for info in zf.infolist():
                if info.is_dir():
                    continue

                # Build full source path
                source_path = f"{prefix}{info.filename}" if prefix else info.filename

                # Extract file content
                content = zf.read(info.filename)
                manifest.total_bytes_scanned += len(content)

                # Check if nested ZIP
                if self._is_zip_file(content) and current_depth < max_depth:
                    # Recursively scan nested ZIP
                    nested_prefix = f"{source_path}/"
                    try:
                        self._scan_zip_contents(
                            content,
                            manifest,
                            current_depth=current_depth + 1,
                            max_depth=max_depth,
                            prefix=nested_prefix
                        )
                    except (ZipBombDetected, UnsafeArchivePath, NestedZipTooDeep) as e:
                        # Log error but continue with other files
                        manifest.scan_errors.append(
                            f"Nested ZIP {source_path} failed safety check: {e}"
                        )
                        # Add as rejected item
                        manifest.items.append(ScanItem(
                            source_path=source_path,
                            byte_size=len(content),
                            item_bytes_or_uri=content,
                            scan_status=ScanStatus.REJECTED_UNSAFE,
                            error_reason=str(e),
                            nested_depth=current_depth + 1
                        ))
                else:
                    # Regular file - check if DICOM
                    self._classify_and_add_item(
                        content,
                        source_path,
                        manifest,
                        current_depth
                    )

    def _scan_single_file(
        self,
        file_bytes: bytes,
        filename: str,
        manifest: ScanManifest
    ) -> None:
        """
        Scan a single file and add to manifest.

        Args:
            file_bytes: File content as bytes
            filename: Original filename
            manifest: ScanManifest to append to
        """
        manifest.total_bytes_scanned += len(file_bytes)
        self._classify_and_add_item(file_bytes, filename, manifest, 0)

    def _classify_and_add_item(
        self,
        content: bytes,
        source_path: str,
        manifest: ScanManifest,
        nested_depth: int
    ) -> None:
        """
        Classify file as DICOM or non-DICOM and add to manifest.

        Args:
            content: File content as bytes
            source_path: Path/name of the file
            manifest: ScanManifest to append to
            nested_depth: Nesting depth
        """
        is_dicom = self._is_dicom_file(content)

        if is_dicom:
            scan_status = ScanStatus.PENDING  # Will be processed further
        else:
            scan_status = ScanStatus.REJECTED_NON_DICOM

        item = ScanItem(
            source_path=source_path,
            byte_size=len(content),
            item_bytes_or_uri=content,
            scan_status=scan_status,
            is_dicom=is_dicom,
            error_reason="" if is_dicom else "Not a DICOM file",
            nested_depth=nested_depth
        )

        manifest.items.append(item)

    def _is_dicom_file(self, data: bytes) -> bool:
        """
        Check if bytes represent a DICOM file.

        Uses the DICOM magic number (DICM) at offset 128.
        Also checks for valid minimum file size.

        Args:
            data: File content as bytes

        Returns:
            True if data appears to be DICOM, False otherwise
        """
        # Minimum size check
        if len(data) < self.DICOM_MAGIC_OFFSET + len(self.DICOM_MAGIC):
            return False

        # Check magic number
        magic_start = self.DICOM_MAGIC_OFFSET
        magic_end = magic_start + len(self.DICOM_MAGIC)
        return data[magic_start:magic_end] == self.DICOM_MAGIC
