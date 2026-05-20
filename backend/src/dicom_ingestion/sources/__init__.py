"""Batch 7 ingest source abstractions."""
from .base import AnnotationRef, IngestSourceItem, SourceEnumerationResult, SourceKind
from .curated_manifest import CuratedUploadManifestSource
from .local_folder import LocalFolderSource
from .file_list_manifest import FileListManifestSource
from .zip_adapter import ZipArchiveSourceAdapter

__all__ = [
    "AnnotationRef",
    "IngestSourceItem",
    "SourceEnumerationResult",
    "SourceKind",
    "CuratedUploadManifestSource",
    "LocalFolderSource",
    "FileListManifestSource",
    "ZipArchiveSourceAdapter",
]
