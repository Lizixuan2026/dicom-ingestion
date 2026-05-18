"""
Duplicate Detection Service — Detect and record duplicate facts.

This module provides the DuplicateDetectionService which detects identity
and content duplicates for DICOM instance observations and creates
persistent duplicate findings.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any, Optional, List, Dict

if TYPE_CHECKING:
    from sqlalchemy.orm import Session
    from dicom_ingestion.models.ingestion_item import IngestionItem
    from dicom_ingestion.models.duplicate_finding import (
        DicomDuplicateFinding,
        DuplicateFindingSummary,
    )

logger = logging.getLogger(__name__)


@dataclass
class DuplicateCheckResult:
    """
    Result of duplicate detection check.

    Attributes:
        has_duplicates: Whether any duplicates were found
        identity_duplicate: Identity duplicate finding if detected
        content_duplicates: List of content duplicate findings
        canonical_instance_id: The canonical instance for this SOP
        canonical_observation_id: The canonical observation for this SOP
    """
    has_duplicates: bool = False
    identity_duplicate: Optional[Any] = None  # DicomDuplicateFinding
    content_duplicates: List[Any] = field(default_factory=list)
    canonical_instance_id: Optional[int] = None
    canonical_observation_id: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            "has_duplicates": self.has_duplicates,
            "identity_duplicate": (
                self.identity_duplicate.to_dict() if self.identity_duplicate else None
            ),
            "content_duplicates": [
                d.to_dict() for d in self.content_duplicates
            ],
            "canonical_instance_id": self.canonical_instance_id,
            "canonical_observation_id": self.canonical_observation_id,
        }


@dataclass
class DuplicateDetectionContext:
    """
    Context for duplicate detection.

    Attributes:
        observation_id: The observation being checked
        instance_id: The logical instance ID
        sop_instance_uid: The SOP Instance UID
        whole_file_sha256: Hash of the file content
        pixel_digest: Hash of pixel data (if available)
        ingestion_item_id: The ingestion item that created this observation
    """
    observation_id: int
    instance_id: int
    sop_instance_uid: str
    whole_file_sha256: Optional[str] = None
    pixel_digest: Optional[str] = None
    ingestion_item_id: int = 0


class DuplicateDetectionService:
    """
    Service for detecting and recording duplicate facts.

    Responsibilities:
    - Detect identity duplicates (same SOPInstanceUID)
    - Detect content duplicates (same file hash or pixel digest)
    - Create persistent duplicate finding records
    - Preserve duplicate facts across replays
    - Never silently overwrite canonical observations

    Duplicate Detection Policy:
    - Identity duplicates: Same SOPInstanceUID seen before
    - Content duplicates: Same file hash or pixel digest
    - First observation becomes canonical (handled by canonical persistence)
    - Later observations create duplicate findings but don't replace canonical
    """

    def __init__(
        self,
        session: Session,
    ) -> None:
        """
        Initialize the duplicate detection service.

        Args:
            session: SQLAlchemy session for database operations
        """
        self._session = session
        self._logger = logger

    async def check_and_record_duplicates(
        self,
        context: DuplicateDetectionContext,
    ) -> DuplicateCheckResult:
        """
        Check for duplicates and record any findings.

        This is the main entry point for duplicate detection after
        an observation has been created.

        Args:
            context: Duplicate detection context with observation details

        Returns:
            DuplicateCheckResult with findings
        """
        result = DuplicateCheckResult()

        try:
            # Check for identity duplicate
            identity_result = await self._check_identity_duplicate(context)
            if identity_result:
                result.identity_duplicate = identity_result
                result.has_duplicates = True
                # Get canonical info from the matched instance
                result.canonical_instance_id = identity_result.matched_instance_id

            # Check for content duplicates (only if not already identity dup of same)
            content_results = await self._check_content_duplicates(context)
            if content_results:
                result.content_duplicates = content_results
                result.has_duplicates = True

            self._logger.info(
                "Duplicate check complete for observation %s: "
                "identity_dup=%s, content_dups=%d",
                context.observation_id,
                bool(result.identity_duplicate),
                len(result.content_duplicates),
            )

        except Exception as e:
            self._logger.exception(
                "Failed to check duplicates for observation %s",
                context.observation_id
            )
            # Don't fail the whole pipeline for duplicate check failure
            # Just log and continue without findings

        return result

    async def _check_identity_duplicate(
        self,
        context: DuplicateDetectionContext,
    ) -> Optional[Any]:
        """
        Check for identity duplicate (same SOPInstanceUID).

        An identity duplicate occurs when a different observation exists
        for the same logical instance (same SOPInstanceUID).

        Args:
            context: Duplicate detection context

        Returns:
            DicomDuplicateFinding if duplicate detected, None otherwise
        """
        from dicom_ingestion.models.duplicate_finding import (
            DicomDuplicateFinding,
            DuplicateType,
            DuplicateBasis,
        )

        # Check if this is the first observation for this instance
        # If observation_id is the only one for this instance, no identity dup
        result = self._session.execute(
            """
            SELECT COUNT(*) as cnt
            FROM dicom_instance_observations
            WHERE instance_id = :instance_id
            """,
            {"instance_id": context.instance_id}
        )
        count = result.fetchone()[0]

        if count <= 1:
            # This is the first observation for this instance
            self._logger.debug(
                "No identity duplicate for instance %s (first observation)",
                context.instance_id
            )
            return None

        # There are multiple observations - this is an identity duplicate
        # Get the first/canonical observation for this instance
        result = self._session.execute(
            """
            SELECT id, is_canonical
            FROM dicom_instance_observations
            WHERE instance_id = :instance_id
              AND is_canonical = TRUE
            LIMIT 1
            """,
            {"instance_id": context.instance_id}
        )
        row = result.fetchone()

        if not row:
            # No canonical observation found - this shouldn't happen
            # but handle gracefully
            self._logger.warning(
                "No canonical observation found for instance %s",
                context.instance_id
            )
            return None

        canonical_obs_id, _ = row

        self._logger.info(
            "Identity duplicate detected: observation %s is duplicate of "
            "canonical observation %s for instance %s",
            context.observation_id,
            canonical_obs_id,
            context.instance_id
        )

        # Create and persist the duplicate finding
        finding = DicomDuplicateFinding.identity_duplicate(
            observation_id=context.observation_id,
            matched_instance_id=context.instance_id,
        )

        finding_id = await self._persist_finding(finding)
        finding.id = finding_id

        return finding

    async def _check_content_duplicates(
        self,
        context: DuplicateDetectionContext,
    ) -> List[Any]:
        """
        Check for content duplicates (same file hash or pixel digest).

        Content duplicates are observations with the same content but
        potentially different SOPInstanceUIDs.

        Args:
            context: Duplicate detection context

        Returns:
            List of DicomDuplicateFinding for content duplicates
        """
        from dicom_ingestion.models.duplicate_finding import (
            DicomDuplicateFinding,
            DuplicateType,
            DuplicateBasis,
        )

        findings = []

        # Check whole_file_sha256 match
        if context.whole_file_sha256:
            sha_dups = await self._find_content_duplicates_by_hash(
                context,
                context.whole_file_sha256,
                DuplicateBasis.WHOLE_FILE_SHA256.value,
            )
            findings.extend(sha_dups)

        # Check pixel_digest match
        if context.pixel_digest:
            pixel_dups = await self._find_content_duplicates_by_hash(
                context,
                context.pixel_digest,
                DuplicateBasis.PIXEL_DIGEST.value,
            )
            findings.extend(pixel_dups)

        return findings

    async def _find_content_duplicates_by_hash(
        self,
        context: DuplicateDetectionContext,
        hash_value: str,
        basis: str,
    ) -> List[Any]:
        """
        Find content duplicates by hash value.

        Args:
            context: Duplicate detection context
            hash_value: The hash to match
            basis: Basis for the match (sha256 or pixel_digest)

        Returns:
            List of DicomDuplicateFinding
        """
        from dicom_ingestion.models.duplicate_finding import (
            DicomDuplicateFinding,
            DuplicateBasis,
        )

        findings = []

        # Find other observations with same hash but different observation_id
        column = (
            "whole_file_sha256"
            if basis == DuplicateBasis.WHOLE_FILE_SHA256.value
            else "pixel_digest"
        )

        result = self._session.execute(
            f"""
            SELECT id, instance_id
            FROM dicom_instance_observations
            WHERE {column} = :hash_value
              AND id != :observation_id
            """,
            {
                "hash_value": hash_value,
                "observation_id": context.observation_id,
            }
        )

        for row in result.fetchall():
            matched_obs_id, matched_inst_id = row

            self._logger.info(
                "Content duplicate detected by %s: observation %s matches %s",
                basis,
                context.observation_id,
                matched_obs_id
            )

            finding = DicomDuplicateFinding.content_duplicate(
                observation_id=context.observation_id,
                matched_observation_id=matched_obs_id,
                basis=basis,
            )

            finding_id = await self._persist_finding(finding)
            finding.id = finding_id
            findings.append(finding)

        return findings

    async def _persist_finding(
        self,
        finding: Any,  # DicomDuplicateFinding
    ) -> int:
        """
        Persist a duplicate finding to the database.

        Uses upsert to avoid creating duplicate findings on retries.

        Args:
            finding: The finding to persist

        Returns:
            The ID of the persisted finding
        """
        result = self._session.execute(
            """
            INSERT INTO dicom_duplicate_findings (
                observation_id,
                duplicate_type,
                basis,
                matched_instance_id,
                matched_observation_id,
                resolution_status,
                created_at,
                updated_at
            ) VALUES (
                :observation_id,
                :duplicate_type,
                :basis,
                :matched_instance_id,
                :matched_observation_id,
                :resolution_status,
                NOW(),
                NOW()
            )
            ON CONFLICT (
                observation_id, duplicate_type, basis,
                COALESCE(matched_instance_id, 0),
                COALESCE(matched_observation_id, 0)
            ) DO UPDATE SET
                updated_at = NOW()
            RETURNING id
            """,
            {
                "observation_id": finding.observation_id,
                "duplicate_type": finding.duplicate_type,
                "basis": finding.basis,
                "matched_instance_id": finding.matched_instance_id,
                "matched_observation_id": finding.matched_observation_id,
                "resolution_status": finding.resolution_status,
            }
        )
        return result.fetchone()[0]

    async def get_findings_for_observation(
        self,
        observation_id: int,
    ) -> List[Any]:
        """
        Get all duplicate findings for an observation.

        Args:
            observation_id: The observation ID

        Returns:
            List of DicomDuplicateFinding
        """
        from dicom_ingestion.models.duplicate_finding import DicomDuplicateFinding

        result = self._session.execute(
            """
            SELECT
                id,
                observation_id,
                duplicate_type,
                basis,
                matched_instance_id,
                matched_observation_id,
                resolution_status,
                created_at,
                updated_at
            FROM dicom_duplicate_findings
            WHERE observation_id = :observation_id
            ORDER BY created_at
            """,
            {"observation_id": observation_id}
        )

        findings = []
        for row in result.fetchall():
            finding = DicomDuplicateFinding(
                id=row[0],
                observation_id=row[1],
                duplicate_type=row[2],
                basis=row[3],
                matched_instance_id=row[4],
                matched_observation_id=row[5],
                resolution_status=row[6],
                created_at=row[7],
                updated_at=row[8],
            )
            findings.append(finding)

        return findings

    async def get_summary_for_job(
        self,
        job_id: int,
    ) -> Any:  # DuplicateFindingSummary
        """
        Get duplicate summary for an ingestion job.

        Args:
            job_id: The ingestion job ID

        Returns:
            DuplicateFindingSummary
        """
        from dicom_ingestion.models.duplicate_finding import (
            DuplicateFindingSummary,
            DuplicateType,
            ResolutionStatus,
        )

        result = self._session.execute(
            """
            SELECT
                df.duplicate_type,
                df.resolution_status,
                i.sop_instance_uid,
                COUNT(*) as cnt
            FROM dicom_duplicate_findings df
            JOIN dicom_instance_observations o ON o.id = df.observation_id
            JOIN dicom_instances i ON i.id = o.instance_id
            JOIN dicom_ingestion_items item ON item.id = o.ingestion_item_id
            WHERE item.ingestion_job_id = :job_id
            GROUP BY df.duplicate_type, df.resolution_status, i.sop_instance_uid
            """,
            {"job_id": job_id}
        )

        summary = DuplicateFindingSummary()
        by_sop: Dict[str, List[Dict]] = {}

        for row in result.fetchall():
            dup_type, resolution, sop_uid, count = row

            summary.total_findings += count

            if dup_type == DuplicateType.IDENTITY.value:
                summary.identity_duplicates += count
            elif dup_type == DuplicateType.CONTENT.value:
                summary.content_duplicates += count

            if resolution == ResolutionStatus.OPEN.value:
                summary.unresolved_count += count

            if sop_uid not in by_sop:
                by_sop[sop_uid] = []

            by_sop[sop_uid].append({
                "type": dup_type,
                "resolution": resolution,
                "count": count,
            })

        summary.by_sop_instance_uid = by_sop
        return summary

    async def resolve_finding(
        self,
        finding_id: int,
        resolution_reason: str = "",
    ) -> bool:
        """
        Mark a duplicate finding as resolved.

        Args:
            finding_id: The finding to resolve
            resolution_reason: Optional reason for resolution

        Returns:
            True if successful
        """
        self._session.execute(
            """
            UPDATE dicom_duplicate_findings
            SET resolution_status = 'resolved',
                updated_at = NOW()
            WHERE id = :finding_id
            """,
            {"finding_id": finding_id}
        )

        self._logger.info(
            "Resolved duplicate finding %s: %s",
            finding_id,
            resolution_reason or "no reason provided"
        )
        return True
