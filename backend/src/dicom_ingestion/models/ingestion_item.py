"""
Ingestion Item Model — State tracking for individual ingestion items.

This module provides the IngestionItem class with seven status axes
to track the processing state of each candidate file through the pipeline.
"""
from enum import Enum
from dataclasses import dataclass, field
from typing import Optional, Dict, Any
from datetime import datetime


class ItemStatusValue(str, Enum):
    """Status values for each axis."""
    # Pending/completion states
    PENDING = "pending"
    SEEN = "seen"
    COMPLETED = "completed"

    # Processing states
    IN_PROGRESS = "in_progress"
    AWAITING_RETRY = "awaiting_retry"

    # Outcome states
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    QUARANTINED = "quarantined"
    FAILED = "failed"


class TerminalOutcome(str, Enum):
    """
    Terminal outcome for an ingestion item.

    Once set, these values do not change.
    """
    NONE = ""               # Not yet determined
    ACCEPTED = "accepted"   # Successfully processed and accepted
    QUARANTINED = "quarantined"  # Quarantined for review
    REJECTED = "rejected"   # Rejected (non-DICOM, unsafe, etc.)
    FAILED = "failed"       # Processing failed (retryable)


@dataclass
class ItemStatusAxes:
    """
    The seven status axes for tracking ingestion item state.

    As defined in specification 010 section 8.2:

    1. scan_status: File discovery and safety scan
    2. parse_status: DICOM parsing and validation
    3. storage_status: Raw byte storage
    4. metadata_persistence_status: Study/Series/Instance persistence
    5. validation_status: Content validation
    6. binding_status: Platform binding
    7. index_status: Projection indexing

    Each axis tracks independently to allow granular state visibility
    and partial retry semantics.
    """
    # 1. File discovery and safety scan
    scan_status: str = ItemStatusValue.PENDING.value

    # 2. DICOM parsing and validation
    parse_status: str = ItemStatusValue.PENDING.value

    # 3. Raw byte storage (RawObjectStore)
    storage_status: str = ItemStatusValue.PENDING.value

    # 4. Study/Series/Instance persistence
    metadata_persistence_status: str = ItemStatusValue.PENDING.value

    # 5. Content validation (duplicate detection, etc.)
    validation_status: str = ItemStatusValue.PENDING.value

    # 6. Platform binding (patient/project association)
    binding_status: str = ItemStatusValue.PENDING.value

    # 7. Projection indexing (search/read views)
    index_status: str = ItemStatusValue.PENDING.value

    def all_completed(self) -> bool:
        """True if all axes are completed."""
        return all(
            status == ItemStatusValue.COMPLETED.value
            for status in [
                self.scan_status,
                self.parse_status,
                self.storage_status,
                self.metadata_persistence_status,
                self.validation_status,
                self.binding_status,
                self.index_status,
            ]
        )

    def any_failed(self) -> bool:
        """True if any axis is in failed state."""
        return any(
            status == ItemStatusValue.FAILED.value
            for status in [
                self.scan_status,
                self.parse_status,
                self.storage_status,
                self.metadata_persistence_status,
                self.validation_status,
                self.binding_status,
                self.index_status,
            ]
        )

    def to_dict(self) -> Dict[str, str]:
        """Convert to dictionary representation."""
        return {
            "scan_status": self.scan_status,
            "parse_status": self.parse_status,
            "storage_status": self.storage_status,
            "metadata_persistence_status": self.metadata_persistence_status,
            "validation_status": self.validation_status,
            "binding_status": self.binding_status,
            "index_status": self.index_status,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, str]) -> "ItemStatusAxes":
        """Create from dictionary representation."""
        return cls(
            scan_status=data.get("scan_status", ItemStatusValue.PENDING.value),
            parse_status=data.get("parse_status", ItemStatusValue.PENDING.value),
            storage_status=data.get("storage_status", ItemStatusValue.PENDING.value),
            metadata_persistence_status=data.get("metadata_persistence_status", ItemStatusValue.PENDING.value),
            validation_status=data.get("validation_status", ItemStatusValue.PENDING.value),
            binding_status=data.get("binding_status", ItemStatusValue.PENDING.value),
            index_status=data.get("index_status", ItemStatusValue.PENDING.value),
        )


@dataclass
class IngestionItem:
    """
    Represents a single candidate file in an ingestion job.

    Attributes:
        id: Unique item identifier
        ingestion_job_id: Parent job ID
        source_path: Original path in upload
        byte_size: File size in bytes
        item_fingerprint: Unique fingerprint for idempotency
        status_axes: Seven status axes tracking progress
        terminal_outcome: Final outcome (null until determined)
        storage_uri: URI to stored raw bytes
        raw_object_status: Status of raw object storage
        raw_object_sha256: SHA-256 of stored content
        last_retryable_stage: Last stage where retry is possible
        error_code: Error code if failed
        error_detail: Detailed error message
        series_ingestion_attempt_id: Link to Series attempt (if DICOM)
        created_at: Creation timestamp
        updated_at: Last update timestamp
        metadata: Additional item metadata
    """
    id: int = 0
    ingestion_job_id: int = 0
    source_path: str = ""
    byte_size: int = 0
    item_fingerprint: str = ""
    status_axes: ItemStatusAxes = field(default_factory=ItemStatusAxes)
    terminal_outcome: str = TerminalOutcome.NONE.value
    storage_uri: str = ""
    raw_object_status: str = ""
    raw_object_sha256: str = ""
    last_retryable_stage: str = ""
    error_code: str = ""
    error_detail: str = ""
    series_ingestion_attempt_id: Optional[int] = None
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
    metadata: Dict[str, Any] = field(default_factory=dict)

    # Error code constants
    ERROR_EMPTY_UPLOAD = "EmptyUploadRequest"
    ERROR_UPLOAD_TOO_LARGE = "UploadTooLarge"
    ERROR_ZIP_BOMB = "ZipBombDetected"
    ERROR_PATH_TRAVERSAL = "UnsafeArchivePath"
    ERROR_PARSE_FAILED = "DicomParseFailed"
    ERROR_MISSING_REQUIRED_TAG = "MissingRequiredDicomTag"
    ERROR_STORAGE_FAILED = "UploadPackageStoreFailed"
    ERROR_METADATA_PERSISTENCE_FAILED = "MetadataPersistenceFailed"

    @property
    def is_dicom(self) -> bool:
        """True if this item is identified as DICOM."""
        # A DICOM item would have been scanned and not rejected for being non-DICOM
        return self.status_axes.scan_status not in [
            ItemStatusValue.REJECTED.value,
            ItemStatusValue.FAILED.value
        ] or self.terminal_outcome == TerminalOutcome.ACCEPTED.value

    @property
    def is_terminal(self) -> bool:
        """True if item has reached terminal state."""
        return self.terminal_outcome != TerminalOutcome.NONE.value

    @property
    def can_retry(self) -> bool:
        """True if item can be retried."""
        # Can only retry if explicitly marked as FAILED outcome with a retryable stage
        if self.terminal_outcome == TerminalOutcome.FAILED.value:
            return bool(self.last_retryable_stage)
        # Cannot retry if already in any terminal state (other than FAILED)
        if self.is_terminal:
            return False
        # Can retry if any axis failed but not yet terminal
        return self.status_axes.any_failed()

    def update_status(self, axis: str, status: str) -> None:
        """
        Update a specific status axis.

        Args:
            axis: Axis name (scan_status, parse_status, etc.)
            status: New status value
        """
        if hasattr(self.status_axes, axis):
            setattr(self.status_axes, axis, status)
            self.updated_at = datetime.utcnow()
        else:
            raise ValueError(f"Invalid status axis: {axis}")

    def mark_seen(self) -> None:
        """Mark item as seen during scan."""
        self.status_axes.scan_status = ItemStatusValue.SEEN.value
        self.updated_at = datetime.utcnow()

    def mark_scanned(self, is_dicom: bool, error_reason: str = "") -> None:
        """
        Mark item as scanned.

        Args:
            is_dicom: True if identified as DICOM
            error_reason: Reason if rejected
        """
        if error_reason:
            self.status_axes.scan_status = ItemStatusValue.REJECTED.value
            self.error_code = error_reason
            self.terminal_outcome = TerminalOutcome.REJECTED.value
        elif is_dicom:
            self.status_axes.scan_status = ItemStatusValue.COMPLETED.value
        else:
            self.status_axes.scan_status = ItemStatusValue.REJECTED.value
            self.error_code = self.ERROR_PARSE_FAILED
            self.terminal_outcome = TerminalOutcome.REJECTED.value
        self.updated_at = datetime.utcnow()

    def mark_parsed(self, success: bool, error_code: str = "", error_detail: str = "") -> None:
        """
        Mark parsing complete.

        Args:
            success: True if parsing succeeded
            error_code: Error code if failed
            error_detail: Detailed error if failed
        """
        if success:
            self.status_axes.parse_status = ItemStatusValue.COMPLETED.value
        else:
            self.status_axes.parse_status = ItemStatusValue.FAILED.value
            self.error_code = error_code
            self.error_detail = error_detail
            self.last_retryable_stage = "parse"
        self.updated_at = datetime.utcnow()

    def mark_stored(self, uri: str, sha256: str) -> None:
        """
        Mark raw bytes stored.

        Args:
            uri: Storage URI
            sha256: Content hash
        """
        self.status_axes.storage_status = ItemStatusValue.COMPLETED.value
        self.storage_uri = uri
        self.raw_object_sha256 = sha256
        self.updated_at = datetime.utcnow()

    def mark_storage_failed(self, error_code: str) -> None:
        """Mark storage as failed."""
        self.status_axes.storage_status = ItemStatusValue.FAILED.value
        self.error_code = error_code
        self.last_retryable_stage = "storage"
        self.updated_at = datetime.utcnow()

    def mark_metadata_persisted(self) -> None:
        """Mark metadata persistence complete."""
        self.status_axes.metadata_persistence_status = ItemStatusValue.COMPLETED.value
        self.updated_at = datetime.utcnow()

    def mark_metadata_failed(self, error_code: str) -> None:
        """Mark metadata persistence as failed."""
        self.status_axes.metadata_persistence_status = ItemStatusValue.FAILED.value
        self.error_code = error_code
        self.last_retryable_stage = "metadata_persistence"
        self.updated_at = datetime.utcnow()

    def mark_validated(self) -> None:
        """Mark validation complete."""
        self.status_axes.validation_status = ItemStatusValue.COMPLETED.value
        self.updated_at = datetime.utcnow()

    def mark_bound(self) -> None:
        """Mark platform binding complete."""
        self.status_axes.binding_status = ItemStatusValue.COMPLETED.value
        self.updated_at = datetime.utcnow()

    def mark_indexed(self) -> None:
        """Mark indexing complete."""
        self.status_axes.index_status = ItemStatusValue.COMPLETED.value
        self.updated_at = datetime.utcnow()

    def set_terminal_outcome(self, outcome: TerminalOutcome, error_code: str = "", error_detail: str = "") -> None:
        """
        Set the terminal outcome for this item.

        Once set, the terminal outcome cannot be changed.

        Args:
            outcome: Final outcome
            error_code: Error code if failed/rejected
            error_detail: Detailed error message

        Raises:
            ValueError: If outcome is already set to a different value
        """
        if self.terminal_outcome != TerminalOutcome.NONE.value and self.terminal_outcome != outcome.value:
            raise ValueError(
                f"Cannot change terminal outcome from {self.terminal_outcome} to {outcome.value}"
            )

        self.terminal_outcome = outcome.value
        if error_code:
            self.error_code = error_code
        if error_detail:
            self.error_detail = error_detail
        self.updated_at = datetime.utcnow()

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            "id": self.id,
            "ingestion_job_id": self.ingestion_job_id,
            "source_path": self.source_path,
            "byte_size": self.byte_size,
            "item_fingerprint": self.item_fingerprint,
            "status_axes": self.status_axes.to_dict(),
            "terminal_outcome": self.terminal_outcome,
            "storage_uri": self.storage_uri,
            "raw_object_sha256": self.raw_object_sha256,
            "last_retryable_stage": self.last_retryable_stage,
            "error_code": self.error_code,
            "error_detail": self.error_detail,
            "series_ingestion_attempt_id": self.series_ingestion_attempt_id,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
