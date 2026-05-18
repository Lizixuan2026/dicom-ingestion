"""Review query service for DICOM ingestion.

This module provides the ReviewQueryService which exposes query interfaces
for ingest/review semantics, building on Batch 4 semantic facts.

D1: Review Queries - Query interfaces expose ingest/review semantics coherently.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Union

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


class ReviewStatus(str, Enum):
    """Status values for review views."""
    PENDING_REVIEW = "pending_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    QUARANTINED = "quarantined"
    NEEDS_ATTENTION = "needs_attention"


class IngestionOutcome(str, Enum):
    """Terminal outcomes for ingestion items."""
    ACCEPTED = "accepted"
    QUARANTINED = "quarantined"
    REJECTED = "rejected"
    FAILED = "failed"


@dataclass
class ItemReviewView:
    """Review view of a single ingestion item.

    This presents item state in review-friendly format with
    semantic facts from Batch 4 processing.
    """
    item_id: int
    job_id: int
    source_path: str
    byte_size: int
    fingerprint: str

    # Ingestion state
    status_axes: Dict[str, str] = field(default_factory=dict)
    terminal_outcome: Optional[str] = None
    is_complete: bool = False
    has_failures: bool = False

    # Batch 4 semantic facts
    duplicate_status: str = "unknown"  # From C1 duplicate detection
    private_tags_persisted: bool = False  # From C2 private tag persistence
    references_extracted: int = 0  # From C3 reference extraction
    binding_status: str = "unknown"  # From C4 binding policy

    # Review metadata
    review_status: str = ReviewStatus.PENDING_REVIEW.value
    review_notes: List[str] = field(default_factory=list)
    quarantine_reason: Optional[str] = None
    error_summary: Optional[str] = None

    # Timestamps
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


@dataclass
class JobReviewView:
    """Review view of an ingestion job."""
    job_id: int
    actor_id: str
    source_type: str
    job_status: str
    is_terminal: bool = False

    # Summary statistics
    total_items: int = 0
    completed_items: int = 0
    failed_items: int = 0
    quarantined_items: int = 0
    pending_items: int = 0

    # Error summary
    error_codes: Dict[str, int] = field(default_factory=dict)
    common_errors: List[str] = field(default_factory=list)

    # Timeline
    created_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    duration_seconds: Optional[float] = None

    # Items needing review
    items_needing_review: List[int] = field(default_factory=list)


@dataclass
class IngestionSummary:
    """Summary of ingestion state across jobs."""
    total_jobs: int = 0
    active_jobs: int = 0
    completed_jobs: int = 0
    failed_jobs: int = 0

    total_items: int = 0
    accepted_items: int = 0
    quarantined_items: int = 0
    rejected_items: int = 0
    failed_items: int = 0

    # Recent activity
    jobs_last_24h: int = 0
    items_last_24h: int = 0

    # Issues needing attention
    items_pending_review: int = 0
    jobs_with_failures: int = 0


@dataclass
class ConflictSummary:
    """Summary of series conflicts requiring review."""
    conflict_id: int
    series_uid: str
    conflict_type: str
    severity: str

    # Affected instances
    affected_instance_count: int = 0
    conflicting_values: List[str] = field(default_factory=list)

    # Resolution status
    resolution_strategy: Optional[str] = None
    resolved_at: Optional[datetime] = None

    @property
    def is_resolved(self) -> bool:
        """True if conflict has been resolved."""
        return self.resolution_strategy is not None and self.resolved_at is not None


@dataclass
class DuplicateFindingView:
    """View of duplicate detection findings."""
    finding_id: int
    observation_id: int
    instance_id: int
    sop_instance_uid: str

    # Duplicate classification
    duplicate_type: str  # content_hash, pixel_hash, sop_uid
    confidence: str  # certain, probable
    has_same_pixel_data: bool = False
    has_same_whole_file: bool = False

    # Related observations
    related_observation_ids: List[int] = field(default_factory=list)


class ReviewQueryService:
    """Service for review queries and ingestion state inspection.

    Responsibilities (D1):
    - Query ingestion items in review-friendly format
    - Summarize job state with semantic facts from Batch 4
    - Identify items needing manual review
    - Expose conflict and duplicate findings
    - Provide coherent ingest/review query interfaces

    Query Invariants:
    - All queries reflect current canonical state
    - Batch 4 semantic facts are included in views
    - Review status is computed from underlying state
    """

    def __init__(
        self,
        session: Session,
    ) -> None:
        """Initialize the review query service.

        Args:
            session: SQLAlchemy session for database operations
        """
        self._session = session
        self._logger = logger

    async def get_ingestion_summary(
        self,
        since: Optional[datetime] = None,
    ) -> IngestionSummary:
        """Get summary of ingestion state.

        Args:
            since: Only include data since this timestamp

        Returns:
            IngestionSummary with aggregated statistics
        """
        summary = IngestionSummary()

        try:
            # Job statistics
            job_stats_sql = """
                SELECT
                    COUNT(*) as total,
                    COUNT(*) FILTER (WHERE status NOT IN ('completed', 'failed', 'cancelled')) as active,
                    COUNT(*) FILTER (WHERE status = 'completed') as completed,
                    COUNT(*) FILTER (WHERE status = 'failed') as failed,
                    COUNT(*) FILTER (WHERE created_at >= NOW() - INTERVAL '24 hours') as recent
                FROM dicom_ingestion_jobs
                WHERE (:since IS NULL OR created_at >= :since)
            """
            job_result = self._session.execute(job_stats_sql, {"since": since})
            job_row = job_result.fetchone()

            if job_row:
                summary.total_jobs = job_row[0] or 0
                summary.active_jobs = job_row[1] or 0
                summary.completed_jobs = job_row[2] or 0
                summary.failed_jobs = job_row[3] or 0
                summary.jobs_last_24h = job_row[4] or 0

            # Item statistics
            item_stats_sql = """
                SELECT
                    COUNT(*) as total,
                    COUNT(*) FILTER (WHERE terminal_outcome = 'accepted') as accepted,
                    COUNT(*) FILTER (WHERE terminal_outcome = 'quarantined') as quarantined,
                    COUNT(*) FILTER (WHERE terminal_outcome = 'rejected') as rejected,
                    COUNT(*) FILTER (WHERE terminal_outcome = 'failed') as failed,
                    COUNT(*) FILTER (WHERE terminal_outcome IS NULL) as pending_review,
                    COUNT(*) FILTER (WHERE created_at >= NOW() - INTERVAL '24 hours') as recent
                FROM dicom_ingestion_items
                WHERE (:since IS NULL OR created_at >= :since)
            """
            item_result = self._session.execute(item_stats_sql, {"since": since})
            item_row = item_result.fetchone()

            if item_row:
                summary.total_items = item_row[0] or 0
                summary.accepted_items = item_row[1] or 0
                summary.quarantined_items = item_row[2] or 0
                summary.rejected_items = item_row[3] or 0
                summary.failed_items = item_row[4] or 0
                summary.items_pending_review = item_row[5] or 0
                summary.items_last_24h = item_row[6] or 0

            # Jobs with failures
            jobs_with_failures_sql = """
                SELECT COUNT(DISTINCT ingestion_job_id)
                FROM dicom_ingestion_items
                WHERE terminal_outcome = 'failed'
                  AND (:since IS NULL OR created_at >= :since)
            """
            failures_result = self._session.execute(jobs_with_failures_sql, {"since": since})
            summary.jobs_with_failures = failures_result.scalar() or 0

        except Exception as e:
            self._logger.exception("Failed to get ingestion summary")

        return summary

    async def get_job_review_view(
        self,
        job_id: int,
        include_items: bool = False,
    ) -> Optional[JobReviewView]:
        """Get review view of an ingestion job.

        Args:
            job_id: The job ID
            include_items: Whether to include detailed item list

        Returns:
            JobReviewView or None if job not found
        """
        try:
            # Get job info
            job_sql = """
                SELECT
                    id,
                    actor_id,
                    source_type,
                    status,
                    created_at,
                    completed_at,
                    EXTRACT(EPOCH FROM (completed_at - created_at)) as duration
                FROM dicom_ingestion_jobs
                WHERE id = :job_id
            """
            job_result = self._session.execute(job_sql, {"job_id": job_id})
            job_row = job_result.fetchone()

            if not job_row:
                return None

            view = JobReviewView(
                job_id=job_row[0],
                actor_id=job_row[1] or "",
                source_type=job_row[2] or "",
                job_status=job_row[3] or "",
                is_terminal=job_row[3] in ["completed", "failed", "cancelled"],
                created_at=job_row[4],
                completed_at=job_row[5],
                duration_seconds=job_row[6],
            )

            # Get item statistics
            item_stats_sql = """
                SELECT
                    COUNT(*) as total,
                    COUNT(*) FILTER (WHERE terminal_outcome = 'accepted') as completed,
                    COUNT(*) FILTER (WHERE terminal_outcome = 'failed') as failed,
                    COUNT(*) FILTER (WHERE terminal_outcome = 'quarantined') as quarantined,
                    COUNT(*) FILTER (WHERE terminal_outcome IS NULL) as pending,
                    array_agg(id) FILTER (WHERE terminal_outcome IS NULL OR terminal_outcome IN ('failed', 'quarantined')) as needs_review
                FROM dicom_ingestion_items
                WHERE ingestion_job_id = :job_id
            """
            stats_result = self._session.execute(item_stats_sql, {"job_id": job_id})
            stats_row = stats_result.fetchone()

            if stats_row:
                view.total_items = stats_row[0] or 0
                view.completed_items = stats_row[1] or 0
                view.failed_items = stats_row[2] or 0
                view.quarantined_items = stats_row[3] or 0
                view.pending_items = stats_row[4] or 0
                if stats_row[5]:
                    view.items_needing_review = stats_row[5]

            # Get error codes
            error_sql = """
                SELECT error_code, COUNT(*) as count
                FROM dicom_ingestion_items
                WHERE ingestion_job_id = :job_id
                  AND error_code IS NOT NULL
                  AND error_code != ''
                GROUP BY error_code
                ORDER BY count DESC
            """
            error_result = self._session.execute(error_sql, {"job_id": job_id})
            for row in error_result:
                view.error_codes[row[0]] = row[1]

            # Most common errors
            view.common_errors = list(view.error_codes.keys())[:5]

            return view

        except Exception as e:
            self._logger.exception("Failed to get job review view for %s", job_id)
            return None

    async def get_item_review_view(
        self,
        item_id: int,
    ) -> Optional[ItemReviewView]:
        """Get review view of an ingestion item with Batch 4 semantic facts.

        Args:
            item_id: The item ID

        Returns:
            ItemReviewView or None if item not found
        """
        try:
            # Get item info
            item_sql = """
                SELECT
                    i.id,
                    i.ingestion_job_id,
                    i.source_path,
                    i.byte_size,
                    i.item_fingerprint,
                    i.status_axes,
                    i.terminal_outcome,
                    i.error_code,
                    i.error_detail,
                    i.created_at,
                    i.updated_at,
                    i.completed_at
                FROM dicom_ingestion_items i
                WHERE i.id = :item_id
            """
            item_result = self._session.execute(item_sql, {"item_id": item_id})
            item_row = item_result.fetchone()

            if not item_row:
                return None

            view = ItemReviewView(
                item_id=item_row[0],
                job_id=item_row[1],
                source_path=item_row[2] or "",
                byte_size=item_row[3] or 0,
                fingerprint=item_row[4] or "",
                status_axes=item_row[5] or {},
                terminal_outcome=item_row[6],
                created_at=item_row[9],
                updated_at=item_row[10],
                completed_at=item_row[11],
            )

            # Determine if complete and if has failures
            if isinstance(view.status_axes, dict):
                view.is_complete = all(
                    v == "completed" for v in view.status_axes.values()
                )
                view.has_failures = any(
                    v == "failed" for v in view.status_axes.values()
                )

            # Build error summary
            if item_row[7]:  # error_code
                view.error_summary = f"{item_row[7]}: {item_row[8] or 'No details'}"

            # Get Batch 4 semantic facts from related tables
            await self._populate_batch4_facts(view, item_id)

            # Determine review status
            view.review_status = self._compute_review_status(view)

            return view

        except Exception as e:
            self._logger.exception("Failed to get item review view for %s", item_id)
            return None

    async def query_items_for_review(
        self,
        job_id: Optional[int] = None,
        review_status: Optional[str] = None,
        outcome: Optional[str] = None,
        has_failures: Optional[bool] = None,
        page: int = 1,
        per_page: int = 100,
    ) -> List[ItemReviewView]:
        """Query items needing review.

        Args:
            job_id: Filter by job ID
            review_status: Filter by review status
            outcome: Filter by terminal outcome
            has_failures: Filter by failure status
            page: Page number
            per_page: Items per page

        Returns:
            List of ItemReviewView
        """
        views = []

        try:
            # Build WHERE clause
            where_conditions = ["1=1"]
            params: Dict[str, Any] = {
                "limit": per_page,
                "offset": (page - 1) * per_page,
            }

            if job_id:
                where_conditions.append("ingestion_job_id = :job_id")
                params["job_id"] = job_id

            if outcome:
                where_conditions.append("terminal_outcome = :outcome")
                params["outcome"] = outcome
            elif outcome is None and review_status == ReviewStatus.PENDING_REVIEW.value:
                # Items without terminal outcome are pending review
                where_conditions.append("terminal_outcome IS NULL")

            if has_failures is True:
                where_conditions.append("""
                    (
                        status_axes->>'parse_status' = 'failed'
                        OR status_axes->>'storage_status' = 'failed'
                        OR status_axes->>'metadata_persistence_status' = 'failed'
                    )
                """)

            where_clause = " AND ".join(where_conditions)

            sql = f"""
                SELECT id
                FROM dicom_ingestion_items
                WHERE {where_clause}
                ORDER BY id
                LIMIT :limit OFFSET :offset
            """

            result = self._session.execute(sql, params)
            item_ids = [row[0] for row in result]

            # Fetch full views
            for item_id in item_ids:
                view = await self.get_item_review_view(item_id)
                if view:
                    # Filter by computed review status if specified
                    if review_status and view.review_status != review_status:
                        continue
                    views.append(view)

        except Exception as e:
            self._logger.exception("Failed to query items for review")

        return views

    async def get_conflict_summary(
        self,
        resolved_only: Optional[bool] = None,
        limit: int = 100,
    ) -> List[ConflictSummary]:
        """Get summary of series conflicts.

        Args:
            resolved_only: Filter by resolution status
            limit: Maximum records to return

        Returns:
            List of ConflictSummary
        """
        summaries = []

        try:
            where_conditions = ["1=1"]
            params: Dict[str, Any] = {"limit": limit}

            if resolved_only is True:
                where_conditions.append("resolution_strategy IS NOT NULL")
            elif resolved_only is False:
                where_conditions.append("resolution_strategy IS NULL")

            where_clause = " AND ".join(where_conditions)

            sql = f"""
                SELECT
                    id,
                    series_instance_uid,
                    conflict_type,
                    severity,
                    affected_instance_count,
                    conflicting_values,
                    resolution_strategy,
                    resolved_at
                FROM dicom_series_conflict_summaries
                WHERE {where_clause}
                ORDER BY
                    CASE severity
                        WHEN 'critical' THEN 1
                        WHEN 'warning' THEN 2
                        WHEN 'info' THEN 3
                        ELSE 4
                    END,
                    created_at DESC
                LIMIT :limit
            """

            result = self._session.execute(sql, params)

            for row in result:
                summary = ConflictSummary(
                    conflict_id=row[0],
                    series_uid=row[1] or "",
                    conflict_type=row[2] or "",
                    severity=row[3] or "",
                    affected_instance_count=row[4] or 0,
                    conflicting_values=row[5] or [],
                    resolution_strategy=row[6],
                    resolved_at=row[7],
                )
                summaries.append(summary)

        except Exception as e:
            self._logger.exception("Failed to get conflict summary")

        return summaries

    async def get_duplicate_findings(
        self,
        observation_id: Optional[int] = None,
        instance_id: Optional[int] = None,
        duplicate_type: Optional[str] = None,
        limit: int = 100,
    ) -> List[DuplicateFindingView]:
        """Get duplicate detection findings.

        Args:
            observation_id: Filter by observation ID
            instance_id: Filter by instance ID
            duplicate_type: Filter by duplicate type
            limit: Maximum records to return

        Returns:
            List of DuplicateFindingView
        """
        findings = []

        try:
            where_conditions = ["1=1"]
            params: Dict[str, Any] = {"limit": limit}

            if observation_id:
                where_conditions.append("observation_id = :obs_id")
                params["obs_id"] = observation_id

            if instance_id:
                where_conditions.append("instance_id = :inst_id")
                params["inst_id"] = instance_id

            if duplicate_type:
                where_conditions.append("duplicate_type = :dup_type")
                params["dup_type"] = duplicate_type

            where_clause = " AND ".join(where_conditions)

            sql = f"""
                SELECT
                    id,
                    observation_id,
                    instance_id,
                    sop_instance_uid,
                    duplicate_type,
                    confidence,
                    has_same_pixel_data,
                    has_same_whole_file,
                    related_observation_ids
                FROM dicom_duplicate_findings
                WHERE {where_clause}
                ORDER BY created_at DESC
                LIMIT :limit
            """

            result = self._session.execute(sql, params)

            for row in result:
                finding = DuplicateFindingView(
                    finding_id=row[0],
                    observation_id=row[1],
                    instance_id=row[2],
                    sop_instance_uid=row[3] or "",
                    duplicate_type=row[4] or "",
                    confidence=row[5] or "",
                    has_same_pixel_data=row[6] or False,
                    has_same_whole_file=row[7] or False,
                    related_observation_ids=row[8] or [],
                )
                findings.append(finding)

        except Exception as e:
            self._logger.exception("Failed to get duplicate findings")

        return findings

    async def _populate_batch4_facts(
        self,
        view: ItemReviewView,
        item_id: int,
    ) -> None:
        """Populate Batch 4 semantic facts into review view.

        Args:
            view: ItemReviewView to populate
            item_id: The item ID
        """
        try:
            # Get observation ID for this item
            obs_sql = """
                SELECT id, instance_id
                FROM dicom_instance_observations
                WHERE ingestion_item_id = :item_id
                LIMIT 1
            """
            obs_result = self._session.execute(obs_sql, {"item_id": item_id})
            obs_row = obs_result.fetchone()

            if not obs_row:
                return

            observation_id, instance_id = obs_row

            # Get duplicate findings
            dup_sql = """
                SELECT duplicate_type, confidence
                FROM dicom_duplicate_findings
                WHERE observation_id = :obs_id
                LIMIT 1
            """
            dup_result = self._session.execute(dup_sql, {"obs_id": observation_id})
            dup_row = dup_result.fetchone()

            if dup_row:
                view.duplicate_status = f"{dup_row[0]} ({dup_row[1]})"
            else:
                view.duplicate_status = "no_duplicates_found"

            # Get private tag count
            pt_sql = """
                SELECT COUNT(*)
                FROM dicom_private_tags
                WHERE observation_id = :obs_id
            """
            pt_result = self._session.execute(pt_sql, {"obs_id": observation_id})
            pt_count = pt_result.scalar() or 0
            view.private_tags_persisted = pt_count > 0

            # Get reference edges
            ref_sql = """
                SELECT COUNT(*)
                FROM dicom_reference_edges
                WHERE from_instance_id = :inst_id
            """
            ref_result = self._session.execute(ref_sql, {"inst_id": instance_id})
            view.references_extracted = ref_result.scalar() or 0

            # Get binding policy
            bp_sql = """
                SELECT binding_status, project_id, user_id
                FROM dicom_binding_policies
                WHERE instance_id = :inst_id
                LIMIT 1
            """
            bp_result = self._session.execute(bp_sql, {"inst_id": instance_id})
            bp_row = bp_result.fetchone()

            if bp_row:
                view.binding_status = bp_row[0] or "bound"
            else:
                view.binding_status = "unbound"

        except Exception as e:
            self._logger.warning("Failed to populate Batch 4 facts for item %s: %s", item_id, e)

    def _compute_review_status(self, view: ItemReviewView) -> str:
        """Compute review status from item state.

        Args:
            view: ItemReviewView

        Returns:
            ReviewStatus value
        """
        # Terminal outcomes map directly
        if view.terminal_outcome == IngestionOutcome.QUARANTINED.value:
            return ReviewStatus.QUARANTINED.value

        if view.terminal_outcome == IngestionOutcome.REJECTED.value:
            return ReviewStatus.REJECTED.value

        if view.terminal_outcome == IngestionOutcome.ACCEPTED.value:
            return ReviewStatus.APPROVED.value

        if view.terminal_outcome == IngestionOutcome.FAILED.value:
            return ReviewStatus.NEEDS_ATTENTION.value

        # No terminal outcome - check for issues
        if view.has_failures:
            return ReviewStatus.NEEDS_ATTENTION.value

        # Check if complete but no terminal outcome (shouldn't happen)
        if view.is_complete:
            return ReviewStatus.PENDING_REVIEW.value

        # Still in progress
        return ReviewStatus.PENDING_REVIEW.value

    async def export_review_report(
        self,
        job_id: Optional[int] = None,
        since: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        """Export comprehensive review report.

        Args:
            job_id: Filter by job ID
            since: Include data since this timestamp

        Returns:
            Dictionary with review report data
        """
        report = {
            "generated_at": datetime.utcnow().isoformat(),
            "filters": {
                "job_id": job_id,
                "since": since.isoformat() if since else None,
            },
            "summary": {},
            "jobs": [],
            "items_needing_review": [],
            "conflicts": [],
            "duplicates": [],
        }

        try:
            # Overall summary
            report["summary"] = await self.get_ingestion_summary(since=since)

            # Jobs
            if job_id:
                job_view = await self.get_job_review_view(job_id, include_items=True)
                if job_view:
                    report["jobs"].append(job_view)
            else:
                # Get recent jobs
                jobs_sql = """
                    SELECT id FROM dicom_ingestion_jobs
                    WHERE (:since IS NULL OR created_at >= :since)
                    ORDER BY created_at DESC
                    LIMIT 50
                """
                jobs_result = self._session.execute(jobs_sql, {"since": since})
                for row in jobs_result:
                    job_view = await self.get_job_review_view(row[0])
                    if job_view:
                        report["jobs"].append(job_view)

            # Items needing review
            report["items_needing_review"] = await self.query_items_for_review(
                job_id=job_id,
                review_status=ReviewStatus.NEEDS_ATTENTION.value,
                limit=100,
            )

            # Conflicts
            report["conflicts"] = await self.get_conflict_summary(
                resolved_only=False,
                limit=50,
            )

            # Duplicates
            report["duplicates"] = await self.get_duplicate_findings(
                limit=50,
            )

        except Exception as e:
            self._logger.exception("Failed to export review report")
            report["error"] = str(e)

        return report
