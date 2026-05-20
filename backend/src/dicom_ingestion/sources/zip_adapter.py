"""Adapter from the existing ZIP scanner to Batch 7 source items."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from dicom_ingestion.services.scanner.scan_service import ScanService

from .base import IngestSourceItem, SourceEnumerationResult, SourceKind


@dataclass
class BytesUploadPackage:
    """Small package shape accepted by existing ScanService."""

    bytes: bytes
    original_filename: str = "upload.zip"
    uri: str = ""
    content_hash: str = ""
    size_bytes: int = 0


class ZipArchiveSourceAdapter:
    """Expose existing ScanService ZIP output as IngestSourceItem objects."""

    def __init__(self, zip_bytes: bytes, *, filename: str = "upload.zip", scanner: ScanService | None = None) -> None:
        self.zip_bytes = zip_bytes
        self.filename = filename
        self.scanner = scanner or ScanService()

    @property
    def source_kind(self) -> str:
        return SourceKind.ZIP.value

    @property
    def source_label(self) -> str:
        return self.filename

    def enumerate(self) -> SourceEnumerationResult:
        package = BytesUploadPackage(bytes=self.zip_bytes, original_filename=self.filename, size_bytes=len(self.zip_bytes))
        manifest = self.scanner.scan(package)
        result = SourceEnumerationResult(source_kind=self.source_kind, source_label=self.source_label)
        result.errors.extend({"path": "", "error_code": "ZipScanError", "error_detail": error} for error in manifest.scan_errors)
        for item in manifest.items:
            payload = item.item_bytes_or_uri if isinstance(item.item_bytes_or_uri, bytes) else b""
            result.items.append(
                IngestSourceItem(
                    source_kind=self.source_kind,
                    original_relative_path=item.source_path,
                    size_bytes=item.byte_size,
                    open_bytes=lambda data=payload: data,
                    metadata={
                        "scan_status": item.scan_status.value if hasattr(item.scan_status, "value") else str(item.scan_status),
                        "is_dicom": item.is_dicom,
                        "error_reason": item.error_reason,
                        "nested_depth": item.nested_depth,
                    },
                )
            )
        return result
