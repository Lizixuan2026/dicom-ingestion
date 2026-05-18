"""
Series Conflict Service — Classify and resolve Series-level conflicts.

This module provides the SeriesConflictService which:
- Builds Series ingestion attempts from job items
- Classifies Series conflicts based on SOP-level findings
- Supports user resolution of conflicts
- Executes canonical pointer updates for promotions
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Optional, List, Dict, Set, Tuple

if TYPE_CHECKING:
    from sqlalchemy.orm import Session
    from dicom_ingestion.models.series_conflict import (
        SeriesIngestionAttempt,
        SeriesConflictSummary,
        ConflictClassificationResult,
        ConflictResolutionResult,
        SeriesConflictClassification,
        SeriesConflictStatus,
    )

logger = logging.getLogger(__name__)


# Threshold for UID conflict detection (10% default)
DEFAULT_UID_CONFLICT_THRESHOLD = 0.10


@dataclass
class SeriesConflictBuildResult:
    """Result of building Series attempts from a job."""
    success: bool = False
    attempts_created: int = 0
    error_code: str = ""
    error_detail: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "attempts_created": self.attempts_created,
            "error_code": self.error_code,
            "error_detail": self.error_detail,
        }


class SeriesConflictService:
    """
    Service for Series-level conflict detection and resolution.

    Responsibilities:
    - Build Series ingestion attempts from job items
    - Classify conflicts based on SOP overlap and content comparison
    - Create conflict summaries for user review
    - Execute resolution actions (keep_existing, promote_uploaded)
    - Update canonical pointers on promotion

    Classification Rules (in priority order):
    1. content_conflict: Any SOP with conflicting content hash
    2. uid_conflict: Overlap ratio < threshold (suggests UID reuse)
    3. partial_overlap: SOPs intersect but not identical
    4. exact_duplicate: Identical SOP sets and content hashes
    """

    def __init__(
        self,
        session: Session,
        uid_conflict_threshold: float = DEFAULT_UID_CONFLICT_THRESHOLD,
    ) -> None:
        """
        Initialize the Series conflict service.

        Args:
            session: SQLAlchemy session for database operations
            uid_conflict_threshold: Threshold for UID conflict detection
        """
        self._session = session
        self._uid_conflict_threshold = uid_conflict_threshold
        self._logger = logger

    async def build_attempts_from_job(
        self,
        job_id: int,
    ) -> SeriesConflictBuildResult:
        """
        Build Series ingestion attempts from a completed job.

        Groups accepted items by SeriesInstanceUID and creates
        attempt records.

        Args:
            job_id: The ingestion job ID

        Returns:
            SeriesConflictBuildResult
        """
        result = SeriesConflictBuildResult()

        try:
            # Get all accepted items with SeriesInstanceUID from the job
            items_result = self._session.execute(
                """
                SELECT
                    i.id,
                    i.series_ingestion_attempt_id,
                    o.raw_tag_set_json->>'SeriesInstanceUID' as series_uid,
                    o.raw_tag_set_json->>'StudyInstanceUID' as study_uid
                FROM dicom_ingestion_items i
                JOIN dicom_instance_observations o ON o.ingestion_item_id = i.id
                WHERE i.ingestion_job_id = :job_id
                  AND i.terminal_outcome = 'accepted'
                  AND o.raw_tag_set_json->>'SeriesInstanceUID' IS NOT NULL
                """,
                {"job_id": job_id}
            )

            items = items_result.fetchall()

            # Group by SeriesInstanceUID
            by_series: Dict[str, List[int]] = {}
            series_to_study: Dict[str, str] = {}

            for item_id, attempt_id, series_uid, study_uid in items:
                if series_uid not in by_series:
                    by_series[series_uid] = []
                    series_to_study[series_uid] = study_uid or ""
                by_series[series_uid].append(item_id)

            # Create attempt records
            for series_uid, item_ids in by_series.items():
                attempt_id = await self._create_or_update_attempt(
                    job_id=job_id,
                    series_uid=series_uid,
                    study_uid=series_to_study.get(series_uid, ""),
                    item_count=len(item_ids),
                )

                # Link items to attempt
                await self._link_items_to_attempt(item_ids, attempt_id)

                result.attempts_created += 1

            result.success = True

            self._logger.info(
                "Created %d Series attempts for job %s",
                result.attempts_created,
                job_id
            )

        except Exception as e:
            self._logger.exception("Failed to build Series attempts for job %s", job_id)
            result.error_code = "SeriesAttemptBuildFailed"
            result.error_detail = str(e)

        return result

    async def classify_conflict(
        self,
        attempt_id: int,
    ) -> ConflictClassificationResult:
        """
        Classify conflict for a Series ingestion attempt.

        Analyzes SOP overlap and content conflicts to determine
        the conflict classification.

        Args:
            attempt_id: The Series ingestion attempt ID

        Returns:
            ConflictClassificationResult
        """
        from dicom_ingestion.models.series_conflict import (
            ConflictClassificationResult,
            SeriesConflictClassification,
        )

        result = ConflictClassificationResult()

        try:
            # Get attempt details
            attempt = await self._get_attempt(attempt_id)
            if not attempt:
                result.reason = "Attempt not found"
                return result

            result.uploaded_sop_count = attempt.uploaded_sop_count

            # Check if Series exists
            existing_series = await self._find_existing_series(
                attempt.series_instance_uid
            )

            if not existing_series:
                # No existing Series - no conflict
                result.reason = "No existing Series"
                return result

            result.existing_series_id = existing_series["id"]

            # Get SOP sets for comparison
            uploaded_sops = await self._get_uploaded_sops(attempt_id)
            existing_sops = await self._get_existing_sops(result.existing_series_id)

            result.existing_sop_count = len(existing_sops)

            # Calculate overlap
            uploaded_sop_uids = set(s["sop_uid"] for s in uploaded_sops)
            existing_sop_uids = set(s["sop_uid"] for s in existing_sops)

            overlap_uids = uploaded_sop_uids & existing_sop_uids
            result.overlap_sop_count = len(overlap_uids)

            # Check for content conflicts
            conflicting_count = 0
            for uid in overlap_uids:
                uploaded_hash = next(
                    (s["sha256"] for s in uploaded_sops if s["sop_uid"] == uid),
                    None
                )
                existing_hash = next(
                    (s["sha256"] for s in existing_sops if s["sop_uid"] == uid),
                    None
                )
                if uploaded_hash and existing_hash and uploaded_hash != existing_hash:
                    conflicting_count += 1

            result.conflicting_sop_count = conflicting_count

            # Calculate overlap ratio
            max_sops = max(len(uploaded_sop_uids), len(existing_sop_uids))
            result.overlap_ratio = (
                result.overlap_sop_count / max_sops if max_sops > 0 else 0
            )

            # Apply classification rules (in priority order)
            if conflicting_count > 0:
                result.classification = SeriesConflictClassification.CONTENT_CONFLICT.value
                result.reason = f"{conflicting_count} SOP(s) have content conflicts"
            elif result.overlap_ratio < self._uid_conflict_threshold:
                result.classification = SeriesConflictClassification.UID_CONFLICT.value
                result.reason = (
                    f"Overlap ratio {result.overlap_ratio:.2%} below threshold "
                    f"{self._uid_conflict_threshold:.2%}"
                )
            elif result.overlap_sop_count < max_sops:
                result.classification = SeriesConflictClassification.PARTIAL_OVERLAP.value
                result.reason = "Partial SOP overlap without content conflicts"
            else:
                result.classification = SeriesConflictClassification.EXACT_DUPLICATE.value
                result.reason = "Identical SOP sets and content hashes"

            # Create or update conflict summary
            await self._create_or_update_summary(attempt_id, result)

        except Exception as e:
            self._logger.exception(
                "Failed to classify conflict for attempt %s",
                attempt_id
            )
            result.reason = f"Classification failed: {e}"

        return result

    async def resolve_conflict(
        self,
        summary_id: int,
        action: str,
        resolved_by: str,
    ) -> ConflictResolutionResult:
        """
        Resolve a Series conflict.

        Supported actions:
        - keep_existing: Keep the existing Series, reject upload
        - promote_uploaded: Promote uploaded observations as canonical

        Args:
            summary_id: The conflict summary ID
            action: Resolution action
            resolved_by: User performing the resolution

        Returns:
            ConflictResolutionResult
        """
        from dicom_ingestion.models.series_conflict import (
            ConflictResolutionResult,
            SeriesConflictSummary,
            SeriesConflictStatus,
            SeriesConflictClassification,
        )

        result = ConflictResolutionResult()
        result.action = action

        try:
            # Get the summary
            summary = await self._get_summary(summary_id)
            if not summary:
                result.error_code = "ConflictSummaryNotFound"
                result.error_detail = f"Summary {summary_id} not found"
                return result

            # Validate action
            if summary.classification == SeriesConflictClassification.EXACT_DUPLICATE.value:
                result.error_code = "CannotResolveAutoDeduped"
                result.error_detail = "Exact duplicates are auto-deduped and cannot be manually resolved"
                return result

            if summary.is_resolved:
                if summary.status == SeriesConflictStatus.AUTO_DEDUPED.value:
                    result.error_code = "AlreadyAutoDeduped"
                    result.error_detail = "This conflict was auto-deduped"
                elif action == summary.resolution_action:
                    # Same action - idempotent success
                    result.success = True
                    result.updated_summary = summary
                    return result
                else:
                    result.error_code = "ConflictAlreadyResolved"
                    result.error_detail = (
                        f"Conflict already resolved with action '{summary.resolution_action}'"
                    )
                return result

            if action not in ["keep_existing", "promote_uploaded"]:
                result.error_code = "InvalidAction"
                result.error_detail = f"Action '{action}' is not supported"
                return result

            # Execute the resolution
            if action == "keep_existing":
                summary.mark_kept_existing(resolved_by)
                await self._update_summary(summary)
                result.success = True

            elif action == "promote_uploaded":
                # This requires updating canonical pointers
                success = await self._execute_promotion(summary)
                if success:
                    summary.mark_promoted_uploaded(resolved_by)
                    await self._update_summary(summary)
                    result.success = True
                else:
                    result.error_code = "PromotionFailed"
                    result.error_detail = "Failed to promote uploaded Series"

            result.updated_summary = summary

        except Exception as e:
            self._logger.exception("Failed to resolve conflict %s", summary_id)
            result.error_code = "ConflictResolutionFailed"
            result.error_detail = str(e)

        return result

    async def _execute_promotion(
        self,
        summary: Any,  # SeriesConflictSummary
    ) -> bool:
        """
        Execute promotion of uploaded Series to canonical.

        Updates is_canonical flags on all observations in the Series.
        This is an all-or-nothing transaction.

        Args:
            summary: The conflict summary

        Returns:
            True if successful
        """
        try:
            # Get attempt details
            attempt = await self._get_attempt(summary.series_ingestion_attempt_id)
            if not attempt:
                return False

            # Get uploaded observations for this attempt
            observations = await self._get_observations_for_attempt(attempt.id)

            # Update each observation to be canonical
            # First, mark all existing observations as non-canonical
            # Then mark uploaded observations as canonical
            for obs in observations:
                # Update observation
                self._session.execute(
                    """
                    UPDATE dicom_instance_observations
                    SET is_canonical = TRUE,
                        updated_at = NOW()
                    WHERE id = :obs_id
                    """,
                    {"obs_id": obs["id"]}
                )

                # Update instance's canonical pointer
                self._session.execute(
                    """
                    UPDATE dicom_instances
                    SET current_canonical_observation_id = :obs_id,
                        updated_at = NOW()
                    WHERE id = :instance_id
                    """,
                    {
                        "obs_id": obs["id"],
                        "instance_id": obs["instance_id"],
                    }
                )

            self._logger.info(
                "Promoted %d observations to canonical for Series attempt %s",
                len(observations),
                attempt.id
            )
            return True

        except Exception as e:
            self._logger.exception("Failed to execute promotion")
            return False

    async def _create_or_update_attempt(
        self,
        job_id: int,
        series_uid: str,
        study_uid: str,
        item_count: int,
    ) -> int:
        """Create or update a Series ingestion attempt."""
        result = self._session.execute(
            """
            INSERT INTO dicom_series_ingestion_attempts (
                ingestion_job_id,
                study_instance_uid,
                series_instance_uid,
                uploaded_sop_count,
                created_at,
                updated_at
            ) VALUES (
                :job_id,
                :study_uid,
                :series_uid,
                :item_count,
                NOW(),
                NOW()
            )
            ON CONFLICT (ingestion_job_id, series_instance_uid) DO UPDATE SET
                uploaded_sop_count = EXCLUDED.uploaded_sop_count,
                updated_at = NOW()
            RETURNING id
            """,
            {
                "job_id": job_id,
                "study_uid": study_uid,
                "series_uid": series_uid,
                "item_count": item_count,
            }
        )
        return result.fetchone()[0]

    async def _link_items_to_attempt(
        self,
        item_ids: List[int],
        attempt_id: int,
    ) -> None:
        """Link ingestion items to a Series attempt."""
        for item_id in item_ids:
            self._session.execute(
                """
                UPDATE dicom_ingestion_items
                SET series_ingestion_attempt_id = :attempt_id,
                    updated_at = NOW()
                WHERE id = :item_id
                """,
                {
                    "item_id": item_id,
                    "attempt_id": attempt_id,
                }
            )

    async def _get_attempt(
        self,
        attempt_id: int,
    ) -> Optional[Any]:  # Optional[SeriesIngestionAttempt]
        """Get a Series ingestion attempt by ID."""
        from dicom_ingestion.models.series_conflict import SeriesIngestionAttempt

        result = self._session.execute(
            """
            SELECT
                id,
                ingestion_job_id,
                study_instance_uid,
                series_instance_uid,
                uploaded_sop_count,
                created_at,
                updated_at
            FROM dicom_series_ingestion_attempts
            WHERE id = :attempt_id
            """,
            {"attempt_id": attempt_id}
        )

        row = result.fetchone()
        if not row:
            return None

        return SeriesIngestionAttempt(
            id=row[0],
            ingestion_job_id=row[1],
            study_instance_uid=row[2],
            series_instance_uid=row[3],
            uploaded_sop_count=row[4],
            created_at=row[5],
            updated_at=row[6],
        )

    async def _find_existing_series(
        self,
        series_uid: str,
    ) -> Optional[Dict]:
        """Find an existing Series by UID."""
        result = self._session.execute(
            """
            SELECT id, series_instance_uid
            FROM dicom_series
            WHERE series_instance_uid = :series_uid
            LIMIT 1
            """,
            {"series_uid": series_uid}
        )

        row = result.fetchone()
        if row:
            return {"id": row[0], "series_uid": row[1]}
        return None

    async def _get_uploaded_sops(
        self,
        attempt_id: int,
    ) -> List[Dict]:
        """Get SOPs uploaded in a Series attempt."""
        result = self._session.execute(
            """
            SELECT
                i.sop_instance_uid,
                o.whole_file_sha256
            FROM dicom_instances i
            JOIN dicom_instance_observations o ON o.instance_id = i.id
            JOIN dicom_ingestion_items item ON item.id = o.ingestion_item_id
            WHERE item.series_ingestion_attempt_id = :attempt_id
            """,
            {"attempt_id": attempt_id}
        )

        return [
            {"sop_uid": row[0], "sha256": row[1]}
            for row in result.fetchall()
        ]

    async def _get_existing_sops(
        self,
        series_id: int,
    ) -> List[Dict]:
        """Get SOPs in an existing Series."""
        result = self._session.execute(
            """
            SELECT
                i.sop_instance_uid,
                o.whole_file_sha256
            FROM dicom_instances i
            JOIN dicom_instance_observations o ON o.instance_id = i.id
            WHERE i.series_id = :series_id
              AND o.is_canonical = TRUE
            """,
            {"series_id": series_id}
        )

        return [
            {"sop_uid": row[0], "sha256": row[1]}
            for row in result.fetchall()
        ]

    async def _get_observations_for_attempt(
        self,
        attempt_id: int,
    ) -> List[Dict]:
        """Get observations for a Series attempt."""
        result = self._session.execute(
            """
            SELECT
                o.id,
                o.instance_id
            FROM dicom_instance_observations o
            JOIN dicom_ingestion_items item ON item.id = o.ingestion_item_id
            WHERE item.series_ingestion_attempt_id = :attempt_id
            """,
            {"attempt_id": attempt_id}
        )

        return [
            {"id": row[0], "instance_id": row[1]}
            for row in result.fetchall()
        ]

    async def _create_or_update_summary(
        self,
        attempt_id: int,
        classification: Any,  # ConflictClassificationResult
    ) -> None:
        """Create or update a conflict summary."""
        from dicom_ingestion.models.series_conflict import (
            SeriesConflictClassification,
            SeriesConflictStatus,
        )

        # Determine initial status
        status = SeriesConflictStatus.OPEN.value
        if classification.classification == SeriesConflictClassification.EXACT_DUPLICATE.value:
            status = SeriesConflictStatus.AUTO_DEDUPED.value

        self._session.execute(
            """
            INSERT INTO dicom_series_conflict_summaries (
                series_ingestion_attempt_id,
                existing_series_id,
                classification,
                existing_sop_count,
                uploaded_sop_count,
                overlap_sop_count,
                new_sop_count,
                missing_sop_count,
                conflicting_sop_count,
                overlap_ratio,
                status,
                created_at,
                updated_at
            ) VALUES (
                :attempt_id,
                :existing_series_id,
                :classification,
                :existing_sop_count,
                :uploaded_sop_count,
                :overlap_sop_count,
                :new_sop_count,
                :missing_sop_count,
                :conflicting_sop_count,
                :overlap_ratio,
                :status,
                NOW(),
                NOW()
            )
            ON CONFLICT (series_ingestion_attempt_id) DO UPDATE SET
                classification = EXCLUDED.classification,
                existing_sop_count = EXCLUDED.existing_sop_count,
                uploaded_sop_count = EXCLUDED.uploaded_sop_count,
                overlap_sop_count = EXCLUDED.overlap_sop_count,
                new_sop_count = EXCLUDED.new_sop_count,
                missing_sop_count = EXCLUDED.missing_sop_count,
                conflicting_sop_count = EXCLUDED.conflicting_sop_count,
                overlap_ratio = EXCLUDED.overlap_ratio,
                status = EXCLUDED.status,
                updated_at = NOW()
            """,
            {
                "attempt_id": attempt_id,
                "existing_series_id": classification.existing_series_id,
                "classification": classification.classification,
                "existing_sop_count": classification.existing_sop_count,
                "uploaded_sop_count": classification.uploaded_sop_count,
                "overlap_sop_count": classification.overlap_sop_count,
                "new_sop_count": classification.uploaded_sop_count - classification.overlap_sop_count,
                "missing_sop_count": classification.existing_sop_count - classification.overlap_sop_count,
                "conflicting_sop_count": classification.conflicting_sop_count,
                "overlap_ratio": classification.overlap_ratio,
                "status": status,
            }
        )

    async def _get_summary(
        self,
        summary_id: int,
    ) -> Optional[Any]:  # Optional[SeriesConflictSummary]
        """Get a conflict summary by ID."""
        from dicom_ingestion.models.series_conflict import SeriesConflictSummary

        result = self._session.execute(
            """
            SELECT
                id,
                series_ingestion_attempt_id,
                existing_series_id,
                classification,
                existing_sop_count,
                uploaded_sop_count,
                overlap_sop_count,
                new_sop_count,
                missing_sop_count,
                conflicting_sop_count,
                overlap_ratio,
                status,
                resolution_action,
                resolved_at,
                resolved_by,
                created_at,
                updated_at
            FROM dicom_series_conflict_summaries
            WHERE id = :summary_id
            """,
            {"summary_id": summary_id}
        )

        row = result.fetchone()
        if not row:
            return None

        return SeriesConflictSummary(
            id=row[0],
            series_ingestion_attempt_id=row[1],
            existing_series_id=row[2],
            classification=row[3],
            existing_sop_count=row[4],
            uploaded_sop_count=row[5],
            overlap_sop_count=row[6],
            new_sop_count=row[7],
            missing_sop_count=row[8],
            conflicting_sop_count=row[9],
            overlap_ratio=row[10],
            status=row[11],
            resolution_action=row[12],
            resolved_at=row[13],
            resolved_by=row[14],
            created_at=row[15],
            updated_at=row[16],
        )

    async def _update_summary(
        self,
        summary: Any,  # SeriesConflictSummary
    ) -> None:
        """Update a conflict summary."""
        self._session.execute(
            """
            UPDATE dicom_series_conflict_summaries
            SET status = :status,
                resolution_action = :resolution_action,
                resolved_at = :resolved_at,
                resolved_by = :resolved_by,
                updated_at = NOW()
            WHERE id = :summary_id
            """,
            {
                "summary_id": summary.id,
                "status": summary.status,
                "resolution_action": summary.resolution_action,
                "resolved_at": summary.resolved_at,
                "resolved_by": summary.resolved_by,
            }
        )

    async def get_conflicts_for_job(
        self,
        job_id: int,
    ) -> List[Any]:  # List[SeriesConflictSummary]
        """Get all conflict summaries for a job."""
        from dicom_ingestion.models.series_conflict import SeriesConflictSummary

        result = self._session.execute(
            """
            SELECT
                s.id,
                s.series_ingestion_attempt_id,
                s.existing_series_id,
                s.classification,
                s.existing_sop_count,
                s.uploaded_sop_count,
                s.overlap_sop_count,
                s.new_sop_count,
                s.missing_sop_count,
                s.conflicting_sop_count,
                s.overlap_ratio,
                s.status,
                s.resolution_action,
                s.resolved_at,
                s.resolved_by,
                s.created_at,
                s.updated_at
            FROM dicom_series_conflict_summaries s
            JOIN dicom_series_ingestion_attempts a ON a.id = s.series_ingestion_attempt_id
            WHERE a.ingestion_job_id = :job_id
            ORDER BY s.created_at
            """,
            {"job_id": job_id}
        )

        summaries = []
        for row in result.fetchall():
            summaries.append(SeriesConflictSummary(
                id=row[0],
                series_ingestion_attempt_id=row[1],
                existing_series_id=row[2],
                classification=row[3],
                existing_sop_count=row[4],
                uploaded_sop_count=row[5],
                overlap_sop_count=row[6],
                new_sop_count=row[7],
                missing_sop_count=row[8],
                conflicting_sop_count=row[9],
                overlap_ratio=row[10],
                status=row[11],
                resolution_action=row[12],
                resolved_at=row[13],
                resolved_by=row[14],
                created_at=row[15],
                updated_at=row[16],
            ))

        return summaries
