"""
Series Conflict Model — Series-level conflict detection and resolution.

This module provides models for Series-level conflict management:
- SeriesIngestionAttempt: Tracks Series upload attempts
- SeriesConflictSummary: Summarizes conflicts for user review
"""
from enum import Enum
from dataclasses import dataclass, field
from typing import Optional, Dict, Any, List
from datetime import datetime


class SeriesConflictClassification(str, Enum):
    """Classification types for Series conflicts."""
    EXACT_DUPLICATE = "exact_duplicate"      # Identical SOP sets and content
    PARTIAL_OVERLAP = "partial_overlap"      # Some SOPs overlap, no content conflicts
    CONTENT_CONFLICT = "content_conflict"    # Same SOP, different content
    UID_CONFLICT = "uid_conflict"            # Disjoint SOP sets (UID reuse suspected)


class SeriesConflictStatus(str, Enum):
    """Status values for Series conflict resolution."""
    OPEN = "open"                           # Conflict detected, awaiting decision
    KEPT_EXISTING = "kept_existing"          # User chose to keep existing Series
    PROMOTED_UPLOADED = "promoted_uploaded"  # User promoted uploaded Series
    AUTO_DEDUPED = "auto_deduped"           # Auto-deduped as exact duplicate


@dataclass
class SeriesIngestionAttempt:
    """
    Represents a Series upload attempt within an ingestion job.

    Bridges file-level items to Series-level conflict review.

    Attributes:
        id: Unique attempt identifier
        ingestion_job_id: Parent job ID
        study_instance_uid: Study Instance UID
        series_instance_uid: Series Instance UID
        uploaded_sop_count: Number of SOPs in this attempt
        created_at: When the attempt was recorded
        updated_at: When the attempt was last updated
    """
    id: int = 0
    ingestion_job_id: int = 0
    study_instance_uid: str = ""
    series_instance_uid: str = ""
    uploaded_sop_count: int = 0
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            "id": self.id,
            "ingestion_job_id": self.ingestion_job_id,
            "study_instance_uid": self.study_instance_uid,
            "series_instance_uid": self.series_instance_uid,
            "uploaded_sop_count": self.uploaded_sop_count,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


@dataclass
class SeriesConflictSummary:
    """
    Summary of Series-level conflict for user review.

    This is a user-facing projection over SOP-level findings.

    Attributes:
        id: Unique summary identifier
        series_ingestion_attempt_id: The attempt being summarized
        existing_series_id: ID of the existing Series (if exists)
        classification: Conflict classification
        existing_sop_count: SOP count in existing Series
        uploaded_sop_count: SOP count in uploaded Series
        overlap_sop_count: SOPs present in both
        new_sop_count: New SOPs in upload not in existing
        missing_sop_count: SOPs in existing not in upload
        conflicting_sop_count: SOPs with content conflicts
        overlap_ratio: Ratio of overlap (for UID conflict detection)
        status: Conflict resolution status
        resolution_action: Action taken to resolve
        resolved_at: When the conflict was resolved
        resolved_by: User who resolved the conflict
        created_at: When the summary was created
        updated_at: When the summary was last updated
    """
    id: int = 0
    series_ingestion_attempt_id: int = 0
    existing_series_id: Optional[int] = None
    classification: str = ""
    existing_sop_count: int = 0
    uploaded_sop_count: int = 0
    overlap_sop_count: int = 0
    new_sop_count: int = 0
    missing_sop_count: int = 0
    conflicting_sop_count: int = 0
    overlap_ratio: float = 0.0
    status: str = SeriesConflictStatus.OPEN.value
    resolution_action: Optional[str] = None
    resolved_at: Optional[datetime] = None
    resolved_by: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            "id": self.id,
            "series_ingestion_attempt_id": self.series_ingestion_attempt_id,
            "existing_series_id": self.existing_series_id,
            "classification": self.classification,
            "existing_sop_count": self.existing_sop_count,
            "uploaded_sop_count": self.uploaded_sop_count,
            "overlap_sop_count": self.overlap_sop_count,
            "new_sop_count": self.new_sop_count,
            "missing_sop_count": self.missing_sop_count,
            "conflicting_sop_count": self.conflicting_sop_count,
            "overlap_ratio": self.overlap_ratio,
            "status": self.status,
            "resolution_action": self.resolution_action,
            "resolved_at": self.resolved_at.isoformat() if self.resolved_at else None,
            "resolved_by": self.resolved_by,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

    @property
    def is_resolved(self) -> bool:
        """True if this conflict has been resolved."""
        return self.status in {
            SeriesConflictStatus.KEPT_EXISTING.value,
            SeriesConflictStatus.PROMOTED_UPLOADED.value,
            SeriesConflictStatus.AUTO_DEDUPED.value,
        }

    @property
    def can_resolve(self) -> bool:
        """True if this conflict can be resolved via API."""
        return (
            self.status == SeriesConflictStatus.OPEN.value and
            self.classification != SeriesConflictClassification.EXACT_DUPLICATE.value
        )

    def mark_kept_existing(
        self,
        resolved_by: str,
    ) -> None:
        """
        Mark conflict as resolved by keeping existing Series.

        Args:
            resolved_by: User who made the decision
        """
        self.status = SeriesConflictStatus.KEPT_EXISTING.value
        self.resolution_action = "keep_existing"
        self.resolved_by = resolved_by
        self.resolved_at = datetime.utcnow()
        self.updated_at = datetime.utcnow()

    def mark_promoted_uploaded(
        self,
        resolved_by: str,
    ) -> None:
        """
        Mark conflict as resolved by promoting uploaded Series.

        Args:
            resolved_by: User who made the decision
        """
        self.status = SeriesConflictStatus.PROMOTED_UPLOADED.value
        self.resolution_action = "promote_uploaded"
        self.resolved_by = resolved_by
        self.resolved_at = datetime.utcnow()
        self.updated_at = datetime.utcnow()

    def mark_auto_deduped(self) -> None:
        """Mark as auto-deduped (exact duplicate)."""
        self.status = SeriesConflictStatus.AUTO_DEDUPED.value
        self.updated_at = datetime.utcnow()


@dataclass
class ConflictClassificationResult:
    """
    Result of Series conflict classification.

    Attributes:
        classification: The determined classification
        existing_series_id: ID of existing series (if found)
        existing_sop_count: Count of SOPs in existing series
        uploaded_sop_count: Count of SOPs in uploaded series
        overlap_sop_count: Count of overlapping SOPs
        conflicting_sop_count: Count of SOPs with content conflicts
        overlap_ratio: Calculated overlap ratio
        reason: Reason for classification
    """
    classification: str = ""
    existing_series_id: Optional[int] = None
    existing_sop_count: int = 0
    uploaded_sop_count: int = 0
    overlap_sop_count: int = 0
    conflicting_sop_count: int = 0
    overlap_ratio: float = 0.0
    reason: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            "classification": self.classification,
            "existing_series_id": self.existing_series_id,
            "existing_sop_count": self.existing_sop_count,
            "uploaded_sop_count": self.uploaded_sop_count,
            "overlap_sop_count": self.overlap_sop_count,
            "conflicting_sop_count": self.conflicting_sop_count,
            "overlap_ratio": self.overlap_ratio,
            "reason": self.reason,
        }


@dataclass
class ConflictResolutionResult:
    """
    Result of conflict resolution action.

    Attributes:
        success: Whether resolution succeeded
        action: Action taken
        error_code: Error code if failed
        error_detail: Error detail if failed
        updated_summary: The updated conflict summary
    """
    success: bool = False
    action: str = ""
    error_code: str = ""
    error_detail: str = ""
    updated_summary: Optional[Any] = None  # SeriesConflictSummary

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            "success": self.success,
            "action": self.action,
            "error_code": self.error_code,
            "error_detail": self.error_detail,
            "updated_summary": (
                self.updated_summary.to_dict() if self.updated_summary else None
            ),
        }
