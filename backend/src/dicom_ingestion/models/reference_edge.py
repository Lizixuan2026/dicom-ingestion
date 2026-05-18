"""
Reference Edge Model — DICOM reference relationship records.

This module provides the DicomReferenceEdge class which represents
reference relationships between DICOM instances (e.g., current
instance references another study/series/instance).
"""
from enum import Enum
from dataclasses import dataclass, field
from typing import Optional, Dict, Any, List
from datetime import datetime


class ReferenceRelationshipType(str, Enum):
    """Types of DICOM reference relationships."""
    REFERENCED_IMAGE = "referenced_image"  # ReferencedImageSequence
    REFERENCED_INSTANCE = "referenced_instance"  # ReferencedInstanceSequence
    SOURCE_INSTANCE = "source_instance"  # SourceInstanceSequence
    REFERENCED_STUDY = "referenced_study"  # ReferencedStudySequence
    REFERENCED_SERIES = "referenced_series"  # ReferencedSeriesSequence
    PRESENTATION = "presentation"  # ReferencedImageNavigationSequence
    WAVEFORM = "waveform"  # ReferencedWaveformSequence
    OTHER = "other"  # Other reference types


class ReferenceResolutionStatus(str, Enum):
    """Status for reference resolution."""
    UNRESOLVED = "unresolved"  # Target not found
    RESOLVED = "resolved"  # Target found and linked
    AMBIGUOUS = "ambiguous"  # Multiple candidates found
    EXTERNAL = "external"  # Target outside system boundary


@dataclass
class DicomReferenceEdge:
    """
    Represents a reference edge between DICOM instances.

    DICOM instances can reference other instances, series, or studies
    through various sequence types (ReferencedImageSequence, etc.).
    These edges are extracted and stored for query and traversal.

    Attributes:
        id: Unique edge identifier
        from_instance_id: The source instance
        relationship_type: Type of relationship
        to_study_instance_uid: Target StudyInstanceUID (if referencing study)
        to_series_instance_uid: Target SeriesInstanceUID (if referencing series)
        to_sop_instance_uid: Target SOPInstanceUID (if referencing instance)
        referenced_frame_number: Frame number for multi-frame references
        resolved_target_instance_id: Resolved target instance ID (if found)
        resolution_status: Current resolution status
        resolution_metadata: Additional resolution info
        created_at: When the edge was created
        updated_at: When the edge was last updated
    """
    id: int = 0
    from_instance_id: int = 0
    relationship_type: str = ReferenceRelationshipType.REFERENCED_IMAGE.value
    to_study_instance_uid: Optional[str] = None
    to_series_instance_uid: Optional[str] = None
    to_sop_instance_uid: Optional[str] = None
    referenced_frame_number: Optional[int] = None
    resolved_target_instance_id: Optional[int] = None
    resolution_status: str = ReferenceResolutionStatus.UNRESOLVED.value
    resolution_metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            "id": self.id,
            "from_instance_id": self.from_instance_id,
            "relationship_type": self.relationship_type,
            "to_study_instance_uid": self.to_study_instance_uid,
            "to_series_instance_uid": self.to_series_instance_uid,
            "to_sop_instance_uid": self.to_sop_instance_uid,
            "referenced_frame_number": self.referenced_frame_number,
            "resolved_target_instance_id": self.resolved_target_instance_id,
            "resolution_status": self.resolution_status,
            "resolution_metadata": self.resolution_metadata,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

    def mark_resolved(
        self,
        target_instance_id: int,
        metadata: Optional[Dict] = None,
    ) -> None:
        """
        Mark this reference as resolved.

        Args:
            target_instance_id: The resolved target instance ID
            metadata: Additional resolution metadata
        """
        self.resolved_target_instance_id = target_instance_id
        self.resolution_status = ReferenceResolutionStatus.RESOLVED.value
        if metadata:
            self.resolution_metadata.update(metadata)
        self.updated_at = datetime.utcnow()

    def mark_ambiguous(
        self,
        candidates: List[int],
        reason: str = "",
    ) -> None:
        """
        Mark this reference as ambiguous (multiple candidates).

        Args:
            candidates: List of candidate instance IDs
            reason: Reason for ambiguity
        """
        self.resolution_status = ReferenceResolutionStatus.AMBIGUOUS.value
        self.resolution_metadata["candidate_ids"] = candidates
        if reason:
            self.resolution_metadata["ambiguity_reason"] = reason
        self.updated_at = datetime.utcnow()

    def mark_external(self, reason: str = "") -> None:
        """
        Mark this reference as external (outside system boundary).

        Args:
            reason: Reason for external classification
        """
        self.resolution_status = ReferenceResolutionStatus.EXTERNAL.value
        if reason:
            self.resolution_metadata["external_reason"] = reason
        self.updated_at = datetime.utcnow()

    @property
    def is_resolved(self) -> bool:
        """True if this reference is resolved."""
        return self.resolution_status == ReferenceResolutionStatus.RESOLVED.value

    @property
    def target_uid_key(self) -> str:
        """
        Generate a unique key for this edge target.

        Used for deduplication of edges.
        """
        parts = [
            self.from_instance_id,
            self.relationship_type,
            self.to_study_instance_uid or "",
            self.to_series_instance_uid or "",
            self.to_sop_instance_uid or "",
            self.referenced_frame_number or "",
        ]
        return "|".join(str(p) for p in parts)

    @classmethod
    def from_parsed_reference(
        cls,
        from_instance_id: int,
        relationship_type: str,
        study_uid: Optional[str] = None,
        series_uid: Optional[str] = None,
        sop_uid: Optional[str] = None,
        frame_number: Optional[int] = None,
    ) -> "DicomReferenceEdge":
        """
        Factory method to create from parsed DICOM reference.

        Args:
            from_instance_id: Source instance
            relationship_type: Type of relationship
            study_uid: Target study UID
            series_uid: Target series UID
            sop_uid: Target SOP UID
            frame_number: Frame number if applicable

        Returns:
            DicomReferenceEdge instance
        """
        return cls(
            from_instance_id=from_instance_id,
            relationship_type=relationship_type,
            to_study_instance_uid=study_uid,
            to_series_instance_uid=series_uid,
            to_sop_instance_uid=sop_uid,
            referenced_frame_number=frame_number,
        )


@dataclass
class ReferenceEdgeSummary:
    """
    Summary of reference edges for an instance or job.

    Attributes:
        total_edges: Total number of reference edges
        resolved_count: Number of resolved references
        unresolved_count: Number of unresolved references
        by_relationship_type: Count by relationship type
        by_resolution_status: Count by resolution status
    """
    total_edges: int = 0
    resolved_count: int = 0
    unresolved_count: int = 0
    by_relationship_type: Dict[str, int] = field(default_factory=dict)
    by_resolution_status: Dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            "total_edges": self.total_edges,
            "resolved_count": self.resolved_count,
            "unresolved_count": self.unresolved_count,
            "by_relationship_type": self.by_relationship_type,
            "by_resolution_status": self.by_resolution_status,
        }


@dataclass
class ParsedReference:
    """
    A parsed reference from a DICOM dataset.

    Used during parsing before persistence to DB.

    Attributes:
        relationship_type: Type of relationship
        study_uid: Target StudyInstanceUID
        series_uid: Target SeriesInstanceUID
        sop_uid: Target SOPInstanceUID
        frame_number: Frame number for multi-frame references
    """
    relationship_type: str
    study_uid: Optional[str] = None
    series_uid: Optional[str] = None
    sop_uid: Optional[str] = None
    frame_number: Optional[int] = None

    def to_edge(
        self,
        from_instance_id: int,
    ) -> DicomReferenceEdge:
        """
        Convert to DicomReferenceEdge.

        Args:
            from_instance_id: Source instance ID

        Returns:
            DicomReferenceEdge
        """
        return DicomReferenceEdge.from_parsed_reference(
            from_instance_id=from_instance_id,
            relationship_type=self.relationship_type,
            study_uid=self.study_uid,
            series_uid=self.series_uid,
            sop_uid=self.sop_uid,
            frame_number=self.frame_number,
        )
