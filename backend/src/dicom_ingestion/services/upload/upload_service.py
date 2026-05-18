"""
Upload Service — Package Persistence for DICOM ingestion.

This module provides the UploadService which accepts upload input,
persists raw bytes to object storage, and returns an UploadPackage
with a URI pointing to the stored bytes.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import BinaryIO


class UploadPackageStoreFailed(Exception):
    """
    Raised when raw byte storage fails.
    No partial state is left when this exception is raised.
    """
    pass


@dataclass
class UploadPackage:
    """
    Represents a stored upload package.

    Attributes:
        uri: URI pointing to the stored bytes in object storage
        content_hash: SHA-256 hash of the stored content
        size_bytes: Size of the content in bytes
        original_filename: Original filename if available (for ZIP files, this is the raw ZIP)
    """
    uri: str
    content_hash: str
    size_bytes: int
    original_filename: str = ""


class UploadService:
    """
    Service for accepting and persisting upload packages.

    Responsibilities:
    - Accept raw bytes or file-like objects
    - Calculate content hash for integrity
    - Persist to RawObjectStore before returning
    - Handle ZIP inputs: store raw ZIP before expansion

    Interface:
        UploadService.accept(input_data, filename="", original_filename="") -> UploadPackage
    """

    def __init__(self, object_store):
        """
        Initialize with a RawObjectStore instance.

        Args:
            object_store: An object implementing the RawObjectStore interface
                         (put, get, exists, delete methods)
        """
        self._object_store = object_store

    def accept(
        self,
        input_data: bytes | BinaryIO,
        filename: str = "",
        original_filename: str = ""
    ) -> UploadPackage:
        """
        Accept upload input and persist raw bytes to object storage.

        This method is atomic - either the bytes are fully stored and a
        valid UploadPackage is returned, or UploadPackageStoreFailed is raised
        with no partial state left.

        Args:
            input_data: Raw bytes or a binary file-like object containing the upload
            filename: Optional identifier for logging/debugging
            original_filename: Original filename from upload (preserved for ZIP files)

        Returns:
            UploadPackage with URI pointing to stored bytes

        Raises:
            UploadPackageStoreFailed: If storage operation fails
            ValueError: If input_data is empty or not bytes/binary file-like
        """
        try:
            # Normalize input to bytes
            if isinstance(input_data, bytes):
                data = input_data
            elif hasattr(input_data, "read"):
                # Binary file-like object
                data = input_data.read()
            else:
                raise ValueError(f"Unsupported input type: {type(input_data)}")

            # Validate non-empty
            if not data:
                raise ValueError("Empty upload not allowed")

            # Calculate content hash
            content_hash = hashlib.sha256(data).hexdigest()
            size_bytes = len(data)

            # Store in object store (idempotent operation)
            result = self._object_store.put(data, content_hash=content_hash)
            uri = result.get("uri")

            if not uri:
                raise UploadPackageStoreFailed("Object store did not return a URI")

            # Verify storage succeeded
            if not self._object_store.exists(uri):
                raise UploadPackageStoreFailed(f"Storage verification failed for URI: {uri}")

            return UploadPackage(
                uri=uri,
                content_hash=content_hash,
                size_bytes=size_bytes,
                original_filename=original_filename or filename
            )

        except (IOError, OSError) as e:
            raise UploadPackageStoreFailed(f"Storage I/O error: {e}") from e
        except ValueError:
            # ValueError indicates invalid input (empty, wrong type, etc.)
            # Re-raise without wrapping to maintain contract
            raise
        except Exception as e:
            if isinstance(e, UploadPackageStoreFailed):
                raise
            raise UploadPackageStoreFailed(f"Unexpected error during upload: {e}") from e

    def get_package(self, package: UploadPackage) -> bytes:
        """
        Retrieve the raw bytes for a stored package.

        Args:
            package: UploadPackage with valid URI

        Returns:
            Raw bytes from storage

        Raises:
            UploadPackageStoreFailed: If retrieval fails
        """
        data = self._object_store.get(package.uri)
        if data is None:
            raise UploadPackageStoreFailed(f"Package not found at URI: {package.uri}")
        return data
