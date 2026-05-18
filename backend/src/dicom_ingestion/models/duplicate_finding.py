"""
Duplicate Finding Model — Records of duplicate detection findings.

This module provides the DicomDuplicateFinding class which represents
duplicate detection results for DICOM instance observations.
"""
from enum import Enum
from dataclasses import dataclass, field
from typing import Optional, Dict, Any
from datetime import datetime


class DuplicateType(str, Enum):
    """Types of duplicate findings."""
    IDENTITY = "identity"  # Same SOPInstanceUID
    CONTENT = "content"    # Same whole_file_sha256 or pixel_digest


class DuplicateBasis(str, Enum):
    """Basis for duplicate detection."""
    SOP_INSTANCE_UID = "sop_instance_uid"  # Identity duplicate
    WHOLE_FILE_SHA256 = "whole_file_sha256"  # Content duplicate
    PIXEL_DIGEST = "pixel_digest"  # Content duplicate by pixel data


class ResolutionStatus(str, Enum):
    """Resolution status for duplicate findings."""
    OPEN = "open"  # Finding recorded, no resolution yet
    RESOLVED = "resolved"  # Explicitly resolved
    AUTO_ACCEPTED = "auto_accepted"  # Auto-accepted per policy


@dataclass
class DicomDuplicateFinding:
    """
    Represents a duplicate finding for a DICOM instance observation.

    Duplicate findings are created when an observation matches an existing
    instance or observation based on identity (SOPInstanceUID) or content
    (file hash or pixel digest).

    Attributes:
        id: Unique finding identifier
        observation_id: The observation this finding is for
        duplicate_type: Type of duplicate (identity or content)
        basis: Basis for the duplicate detection
        matched_instance_id: The matched logical instance (if identity dup)
        matched_observation_id: The matched observation (if content dup)
        resolution_status: Current resolution status
        resolution_metadata: Additional metadata about resolution
        created_at: When the finding was created
        updated_at: When the finding was last updated
    """
    id: int = 0
    observation_id: int = 0
    duplicate_type: str = DuplicateType.IDENTITY.value
    basis: str = DuplicateBasis.SOP_INSTANCE_UID.value
    matched_instance_id: Optional[int] = None
    matched_observation_id: Optional[int] = None
    resolution_status: str = ResolutionStatus.OPEN.value
    resolution_metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)

    def mark_resolved(self, reason: str = "") -> None:
        """
        Mark this finding as resolved.

        Args:
            reason: Optional resolution reason
        """
        self.resolution_status = ResolutionStatus.RESOLVED.value
        if reason:
            self.resolution_metadata["resolution_reason"] = reason
        self.updated_at = datetime.utcnow()

    def mark_auto_accepted(self, policy: str = "") -> None:
        """
        Mark this finding as auto-accepted per policy.

        Args:
            policy: The policy that auto-accepted this duplicate
        """
        self.resolution_status = ResolutionStatus.AUTO_ACCEPTED.value
        if policy:
            self.resolution_metadata["auto_accept_policy"] = policy
        self.updated_at = datetime.utcnow()

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            "id": self.id,
            "observation_id": self.observation_id,
            "duplicate_type": self.duplicate_type,
            "basis": self.basis,
            "matched_instance_id": self.matched_instance_id,
            "matched_observation_id": self.matched_observation_id,
            "resolution_status": self.resolution_status,
            "resolution_metadata": self.resolution_metadata,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

    @classmethod
    def identity_duplicate(
        cls,
        observation_id: int,
        matched_instance_id: int,
    ) -> "DicomDuplicateFinding":
        """
        Factory method for creating an identity duplicate finding.

        Identity duplicates occur when the same SOPInstanceUID is
        seen in multiple observations.

        Args:
            observation_id: The new observation
            matched_instance_id: The existing instance with same SOPInstanceUID

        Returns:
            DicomDuplicateFinding configured as identity duplicate
        """
        return cls(
            observation_id=observation_id,
            duplicate_type=DuplicateType.IDENTITY.value,
            basis=DuplicateBasis.SOP_INSTANCE_UID.value,
            matched_instance_id=matched_instance_id,
            matched_observation_id=None,
            resolution_status=ResolutionStatus.OPEN.value,
        )

    @classmethod
    def content_duplicate(
        cls,
        observation_id: int,
        matched_observation_id: int,
        basis: str = DuplicateBasis.WHOLE_FILE_SHA256.value,
    ) -> "DicomDuplicateFinding":
        """
        Factory method for creating a content duplicate finding.

        Content duplicates occur when two observations have the same
        file hash or pixel digest but potentially different SOPInstanceUIDs.

        Args:
            observation_id: The new observation
            matched_observation_id: The observation with same content
            basis: Basis for content match (whole_file_sha256 or pixel_digest)

        Returns:
            DicomDuplicateFinding configured as content duplicate
        """
        return cls(
            observation_id=observation_id,
            duplicate_type=DuplicateType.CONTENT.value,
            basis=basis,
            matched_instance_id=None,
            matched_observation_id=matched_observation_id,
            resolution_status=ResolutionStatus.OPEN.value,
        )


@dataclass
class DuplicateFindingSummary:
    """
    Summary of duplicate findings for a job or set of items.

    Attributes:
        total_findings: Total number of duplicate findings
        identity_duplicates: Count of identity duplicates
        content_duplicates: Count of content duplicates
        unresolved_count: Count of unresolved findings
        by_sop_instance_uid: Dict mapping SOP UIDs to their findings
    """
    total_findings: int = 0
    identity_duplicates: int = 0
    content_duplicates: int = 0
    unresolved_count: int = 0
    by_sop_instance_uid: Dict[str, list] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            "total_findings": self.total_findings,
            "identity_duplicates": self.identity_duplicates,
            "content_duplicates": self.content_duplicates,
            "unresolved_count": self.unresolved_count,
            "by_sop_instance_uid": self.by_sop_instance_uid,
        }
