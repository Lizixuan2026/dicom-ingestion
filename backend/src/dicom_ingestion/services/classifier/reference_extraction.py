"""
Reference Extraction Service — Extract and persist DICOM reference edges.

This module provides the ReferenceExtractionService which extracts
reference relationships from DICOM datasets (e.g., ReferencedImageSequence)
and persists them as queryable reference edges.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Optional, List, Dict, Set

from dicom_ingestion.models.reference_edge import (
    ReferenceRelationshipType,
    ReferenceResolutionStatus,
)

if TYPE_CHECKING:
    from sqlalchemy.orm import Session
    from dicom_ingestion.models.reference_edge import (
        DicomReferenceEdge,
        ParsedReference,
        ReferenceEdgeSummary,
    )

logger = logging.getLogger(__name__)


@dataclass
class ReferenceExtractionResult:
    """
    Result of reference extraction.

    Attributes:
        success: Whether extraction was successful
        extracted_count: Number of references extracted
        persisted_count: Number of edges persisted
        resolved_count: Number immediately resolved
        error_code: Error code if extraction failed
        error_detail: Detailed error message
    """
    success: bool = False
    extracted_count: int = 0
    persisted_count: int = 0
    resolved_count: int = 0
    error_code: str = ""
    error_detail: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            "success": self.success,
            "extracted_count": self.extracted_count,
            "persisted_count": self.persisted_count,
            "resolved_count": self.resolved_count,
            "error_code": self.error_code,
            "error_detail": self.error_detail,
        }


class ReferenceExtractionService:
    """
    Service for extracting and persisting DICOM reference edges.

    Responsibilities:
    - Extract reference sequences from parsed DICOM headers
    - Create persistent reference edge records
    - Attempt immediate resolution of references
    - Support deferred resolution for unresolved references
    - Preserve reference provenance across replays

    Reference Types Extracted:
    - ReferencedImageSequence
    - ReferencedInstanceSequence
    - SourceInstanceSequence
    - ReferencedStudySequence
    - ReferencedSeriesSequence
    - Other reference sequences

    Resolution Policy:
    - Attempt to resolve references immediately if target exists
    - Mark as UNRESOLVED if target not found
    - Support deferred resolution via background jobs
    """

    # DICOM sequence tags that contain references
    REFERENCE_SEQUENCES = {
        "ReferencedImageSequence": ReferenceRelationshipType.REFERENCED_IMAGE,
        "ReferencedInstanceSequence": ReferenceRelationshipType.REFERENCED_INSTANCE,
        "SourceInstanceSequence": ReferenceRelationshipType.SOURCE_INSTANCE,
        "ReferencedStudySequence": ReferenceRelationshipType.REFERENCED_STUDY,
        "ReferencedSeriesSequence": ReferenceRelationshipType.REFERENCED_SERIES,
        "ReferencedImageNavigationSequence": ReferenceRelationshipType.PRESENTATION,
        "ReferencedWaveformSequence": ReferenceRelationshipType.WAVEFORM,
    }

    def __init__(
        self,
        session: Session,
    ) -> None:
        """
        Initialize the reference extraction service.

        Args:
            session: SQLAlchemy session for database operations
        """
        self._session = session
        self._logger = logger

    async def extract_and_persist(
        self,
        from_instance_id: int,
        raw_tags: Dict[str, Any],
        resolve_immediately: bool = True,
    ) -> ReferenceExtractionResult:
        """
        Extract references from parsed DICOM and persist as edges.

        Args:
            from_instance_id: The source instance ID
            raw_tags: Raw DICOM tags dictionary
            resolve_immediately: Whether to attempt immediate resolution

        Returns:
            ReferenceExtractionResult with counts
        """
        result = ReferenceExtractionResult()

        try:
            # Extract references from tags
            parsed_refs = self._extract_references(raw_tags)
            result.extracted_count = len(parsed_refs)

            # Convert to edges and persist
            for parsed_ref in parsed_refs:
                edge = parsed_ref.to_edge(from_instance_id)

                # Attempt immediate resolution if requested
                if resolve_immediately:
                    await self._attempt_resolution(edge)
                    if edge.is_resolved:
                        result.resolved_count += 1

                # Persist the edge
                edge_id = await self._persist_edge(edge)
                edge.id = edge_id
                result.persisted_count += 1

            result.success = True

            self._logger.info(
                "Extracted %d references from instance %s, "
                "persisted %d, resolved %d",
                result.extracted_count,
                from_instance_id,
                result.persisted_count,
                result.resolved_count,
            )

        except Exception as e:
            self._logger.exception(
                "Failed to extract references for instance %s",
                from_instance_id
            )
            result.error_code = "ReferenceExtractionFailed"
            result.error_detail = str(e)

        return result

    def _extract_references(
        self,
        raw_tags: Dict[str, Any],
    ) -> List[Any]:  # List[ParsedReference]
        """
        Extract references from raw DICOM tags.

        Args:
            raw_tags: Dictionary of DICOM tags

        Returns:
            List of ParsedReference
        """
        from dicom_ingestion.models.reference_edge import (
            ParsedReference,
            ReferenceRelationshipType,
        )

        refs = []

        for seq_name, rel_type in self.REFERENCE_SEQUENCES.items():
            if seq_name in raw_tags:
                seq_value = raw_tags[seq_name]
                seq_refs = self._parse_sequence(
                    seq_name, seq_value, rel_type.value
                )
                refs.extend(seq_refs)

        # Also check for other reference patterns in raw tags
        other_refs = self._extract_other_references(raw_tags)
        refs.extend(other_refs)

        return refs

    def _parse_sequence(
        self,
        seq_name: str,
        seq_value: Any,
        relationship_type: str,
    ) -> List[Any]:  # List[ParsedReference]
        """
        Parse a reference sequence value.

        Args:
            seq_name: Sequence tag name
            seq_value: Sequence value (list of items or dict)
            relationship_type: Relationship type for these references

        Returns:
            List of ParsedReference
        """
        from dicom_ingestion.models.reference_edge import ParsedReference

        refs = []

        if not seq_value:
            return refs

        # Handle list of items
        if isinstance(seq_value, list):
            items = seq_value
        else:
            items = [seq_value]

        for item in items:
            if not isinstance(item, dict):
                continue

            # Extract UIDs from the sequence item
            study_uid = item.get("ReferencedStudyInstanceUID")
            series_uid = item.get("ReferencedSeriesInstanceUID")
            sop_uid = item.get("ReferencedSOPInstanceUID")

            # Frame number for multi-frame references
            frame_number = item.get("ReferencedFrameNumber")
            if frame_number:
                try:
                    frame_number = int(frame_number)
                except (ValueError, TypeError):
                    frame_number = None

            # Need at least one UID to be a valid reference
            if study_uid or series_uid or sop_uid:
                refs.append(ParsedReference(
                    relationship_type=relationship_type,
                    study_uid=study_uid,
                    series_uid=series_uid,
                    sop_uid=sop_uid,
                    frame_number=frame_number,
                ))

        return refs

    def _extract_other_references(
        self,
        raw_tags: Dict[str, Any],
    ) -> List[Any]:  # List[ParsedReference]
        """
        Extract other reference patterns from tags.

        Handles various DICOM reference patterns not covered by
        the main reference sequences.

        Args:
            raw_tags: Dictionary of DICOM tags

        Returns:
            List of ParsedReference
        """
        from dicom_ingestion.models.reference_edge import (
            ParsedReference,
            ReferenceRelationshipType,
        )

        refs = []

        # Check for standalone referenced SOP class/instance UIDs
        if "ReferencedSOPClassUID" in raw_tags and "ReferencedSOPInstanceUID" in raw_tags:
            refs.append(ParsedReference(
                relationship_type=ReferenceRelationshipType.REFERENCED_INSTANCE.value,
                sop_uid=raw_tags.get("ReferencedSOPInstanceUID"),
            ))

        return refs

    async def _attempt_resolution(
        self,
        edge: Any,  # DicomReferenceEdge
    ) -> None:
        """
        Attempt to resolve a reference edge to a target instance.

        Tries to find the target instance by SOPInstanceUID, then
        SeriesInstanceUID, then StudyInstanceUID.

        Args:
            edge: The edge to resolve
        """
        # Try to resolve by SOPInstanceUID first (most specific)
        if edge.to_sop_instance_uid:
            target_id = await self._find_instance_by_sop(
                edge.to_sop_instance_uid
            )
            if target_id:
                edge.mark_resolved(target_id, {"resolution_path": "sop_instance_uid"})
                return

        # Try by SeriesInstanceUID
        if edge.to_series_instance_uid:
            candidates = await self._find_instances_by_series(
                edge.to_series_instance_uid
            )
            if len(candidates) == 1:
                edge.mark_resolved(
                    candidates[0],
                    {"resolution_path": "series_instance_uid"}
                )
                return
            elif len(candidates) > 1:
                edge.mark_ambiguous(
                    candidates,
                    "Multiple instances found in referenced series"
                )
                return

        # Try by StudyInstanceUID
        if edge.to_study_instance_uid:
            candidates = await self._find_instances_by_study(
                edge.to_study_instance_uid
            )
            if len(candidates) == 1:
                edge.mark_resolved(
                    candidates[0],
                    {"resolution_path": "study_instance_uid"}
                )
                return
            elif len(candidates) > 1:
                edge.mark_ambiguous(
                    candidates,
                    "Multiple instances found in referenced study"
                )
                return

        # Could not resolve
        edge.resolution_status = ReferenceResolutionStatus.UNRESOLVED.value

    async def _find_instance_by_sop(
        self,
        sop_instance_uid: str,
    ) -> Optional[int]:
        """
        Find instance ID by SOPInstanceUID.

        Args:
            sop_instance_uid: The SOP Instance UID

        Returns:
            Instance ID if found, None otherwise
        """
        result = self._session.execute(
            """
            SELECT id FROM dicom_instances
            WHERE sop_instance_uid = :sop_uid
            LIMIT 1
            """,
            {"sop_uid": sop_instance_uid}
        )
        row = result.fetchone()
        return row[0] if row else None

    async def _find_instances_by_series(
        self,
        series_instance_uid: str,
    ) -> List[int]:
        """
        Find instance IDs by SeriesInstanceUID.

        Args:
            series_instance_uid: The Series Instance UID

        Returns:
            List of instance IDs
        """
        result = self._session.execute(
            """
            SELECT i.id
            FROM dicom_instances i
            JOIN dicom_series s ON s.id = i.series_id
            WHERE s.series_instance_uid = :series_uid
            """,
            {"series_uid": series_instance_uid}
        )
        return [row[0] for row in result.fetchall()]

    async def _find_instances_by_study(
        self,
        study_instance_uid: str,
    ) -> List[int]:
        """
        Find instance IDs by StudyInstanceUID.

        Args:
            study_instance_uid: The Study Instance UID

        Returns:
            List of instance IDs
        """
        result = self._session.execute(
            """
            SELECT i.id
            FROM dicom_instances i
            JOIN dicom_series s ON s.id = i.series_id
            JOIN dicom_studies st ON st.id = s.study_id
            WHERE st.study_instance_uid = :study_uid
            """,
            {"study_uid": study_instance_uid}
        )
        return [row[0] for row in result.fetchall()]

    async def _persist_edge(
        self,
        edge: Any,  # DicomReferenceEdge
    ) -> int:
        """
        Persist a reference edge to the database.

        Uses upsert to avoid duplicates on retries.

        Args:
            edge: The edge to persist

        Returns:
            The ID of the persisted edge
        """
        result = self._session.execute(
            """
            INSERT INTO dicom_reference_edges (
                from_instance_id,
                relationship_type,
                to_study_instance_uid,
                to_series_instance_uid,
                to_sop_instance_uid,
                referenced_frame_number,
                resolved_target_instance_id,
                resolution_status,
                created_at,
                updated_at
            ) VALUES (
                :from_instance_id,
                :relationship_type,
                :to_study_instance_uid,
                :to_series_instance_uid,
                :to_sop_instance_uid,
                :referenced_frame_number,
                :resolved_target_instance_id,
                :resolution_status,
                NOW(),
                NOW()
            )
            ON CONFLICT (
                from_instance_id, relationship_type,
                COALESCE(to_study_instance_uid, ''),
                COALESCE(to_series_instance_uid, ''),
                COALESCE(to_sop_instance_uid, ''),
                COALESCE(referenced_frame_number, 0)
            ) DO UPDATE SET
                resolved_target_instance_id = EXCLUDED.resolved_target_instance_id,
                resolution_status = EXCLUDED.resolution_status,
                updated_at = NOW()
            RETURNING id
            """,
            {
                "from_instance_id": edge.from_instance_id,
                "relationship_type": edge.relationship_type,
                "to_study_instance_uid": edge.to_study_instance_uid,
                "to_series_instance_uid": edge.to_series_instance_uid,
                "to_sop_instance_uid": edge.to_sop_instance_uid,
                "referenced_frame_number": edge.referenced_frame_number,
                "resolved_target_instance_id": edge.resolved_target_instance_id,
                "resolution_status": edge.resolution_status,
            }
        )
        return result.fetchone()[0]

    async def get_edges_for_instance(
        self,
        instance_id: int,
        relationship_type: Optional[str] = None,
    ) -> List[Any]:  # List[DicomReferenceEdge]
        """
        Get reference edges for an instance.

        Args:
            instance_id: The source instance ID
            relationship_type: Optional filter by relationship type

        Returns:
            List of DicomReferenceEdge
        """
        from dicom_ingestion.models.reference_edge import DicomReferenceEdge

        type_filter = ""
        params = {"instance_id": instance_id}

        if relationship_type:
            type_filter = "AND relationship_type = :rel_type"
            params["rel_type"] = relationship_type

        result = self._session.execute(
            f"""
            SELECT
                id,
                from_instance_id,
                relationship_type,
                to_study_instance_uid,
                to_series_instance_uid,
                to_sop_instance_uid,
                referenced_frame_number,
                resolved_target_instance_id,
                resolution_status,
                created_at,
                updated_at
            FROM dicom_reference_edges
            WHERE from_instance_id = :instance_id
            {type_filter}
            ORDER BY relationship_type, to_sop_instance_uid
            """,
            params
        )

        edges = []
        for row in result.fetchall():
            edge = DicomReferenceEdge(
                id=row[0],
                from_instance_id=row[1],
                relationship_type=row[2],
                to_study_instance_uid=row[3],
                to_series_instance_uid=row[4],
                to_sop_instance_uid=row[5],
                referenced_frame_number=row[6],
                resolved_target_instance_id=row[7],
                resolution_status=row[8],
                created_at=row[9],
                updated_at=row[10],
            )
            edges.append(edge)

        return edges

    async def get_unresolved_edges(
        self,
        limit: int = 100,
    ) -> List[Any]:  # List[DicomReferenceEdge]
        """
        Get unresolved reference edges for background resolution.

        Args:
            limit: Maximum number of edges to return

        Returns:
            List of unresolved DicomReferenceEdge
        """
        from dicom_ingestion.models.reference_edge import (
            DicomReferenceEdge,
            ReferenceResolutionStatus,
        )

        result = self._session.execute(
            """
            SELECT
                id,
                from_instance_id,
                relationship_type,
                to_study_instance_uid,
                to_series_instance_uid,
                to_sop_instance_uid,
                referenced_frame_number,
                resolved_target_instance_id,
                resolution_status,
                created_at,
                updated_at
            FROM dicom_reference_edges
            WHERE resolution_status = :unresolved_status
            ORDER BY created_at
            LIMIT :limit
            """,
            {
                "unresolved_status": ReferenceResolutionStatus.UNRESOLVED.value,
                "limit": limit,
            }
        )

        edges = []
        for row in result.fetchall():
            edge = DicomReferenceEdge(
                id=row[0],
                from_instance_id=row[1],
                relationship_type=row[2],
                to_study_instance_uid=row[3],
                to_series_instance_uid=row[4],
                to_sop_instance_uid=row[5],
                referenced_frame_number=row[6],
                resolved_target_instance_id=row[7],
                resolution_status=row[8],
                created_at=row[9],
                updated_at=row[10],
            )
            edges.append(edge)

        return edges

    async def resolve_unresolved_edges(
        self,
        batch_size: int = 100,
    ) -> int:
        """
        Attempt to resolve all unresolved edges.

        Background job entry point for deferred resolution.

        Args:
            batch_size: Number of edges to process

        Returns:
            Number of edges resolved
        """
        unresolved = await self.get_unresolved_edges(limit=batch_size)

        resolved_count = 0
        for edge in unresolved:
            old_status = edge.resolution_status
            await self._attempt_resolution(edge)

            if edge.is_resolved:
                # Update in database
                await self._persist_edge(edge)
                resolved_count += 1

        self._logger.info(
            "Resolved %d of %d unresolved reference edges",
            resolved_count,
            len(unresolved)
        )

        return resolved_count

    async def get_summary_for_instance(
        self,
        instance_id: int,
    ) -> Any:  # ReferenceEdgeSummary
        """
        Get reference summary for an instance.

        Args:
            instance_id: The instance ID

        Returns:
            ReferenceEdgeSummary
        """
        from dicom_ingestion.models.reference_edge import (
            ReferenceEdgeSummary,
            ReferenceResolutionStatus,
        )

        result = self._session.execute(
            """
            SELECT
                relationship_type,
                resolution_status,
                COUNT(*) as cnt
            FROM dicom_reference_edges
            WHERE from_instance_id = :instance_id
            GROUP BY relationship_type, resolution_status
            """,
            {"instance_id": instance_id}
        )

        summary = ReferenceEdgeSummary()
        by_type: Dict[str, int] = {}
        by_status: Dict[str, int] = {}

        for row in result.fetchall():
            rel_type, status, count = row

            summary.total_edges += count

            if rel_type not in by_type:
                by_type[rel_type] = 0
            by_type[rel_type] += count

            if status not in by_status:
                by_status[status] = 0
            by_status[status] += count

            if status == ReferenceResolutionStatus.RESOLVED.value:
                summary.resolved_count += count
            else:
                summary.unresolved_count += count

        summary.by_relationship_type = by_type
        summary.by_resolution_status = by_status
        return summary
