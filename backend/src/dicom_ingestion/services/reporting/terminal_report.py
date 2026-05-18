"""Terminal reporting service for DICOM ingestion.

This module provides the TerminalReportService which converts ingest outcomes
into terminal candidate-level reports with per-upload summaries.

Consistency semantics: strong consistency for reads after generate_job_report in
the same database transaction boundary. Persistence in DB is the source of truth;
in-memory cache is an optional best-effort acceleration layer with TTL/LRU bounds.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import TYPE_CHECKING, Any, Optional


if TYPE_CHECKING:
    from dicom_ingestion.models.ingestion_item import IngestionItem
    from dicom_ingestion.repositories.terminal_report_repository import TerminalReportRepository

logger = logging.getLogger(__name__)


class TerminalStatus(str, Enum):
    """Terminal status values for ingestion items.

    These represent the final, immutable outcome of processing.
    """
    NONE = ""                    # Not yet determined
    ACCEPTED = "accepted"        # Successfully processed and accepted
    QUARANTINED = "quarantined"  # Quarantined for review
    REJECTED = "rejected"        # Rejected (non-DICOM, unsafe, etc.)
    FAILED = "failed"            # Processing failed (retryable)


class IngestClassification(str, Enum):
    """Classification of ingest outcomes.

    Provides additional context beyond terminal status.
    """
    SUCCESS = "success"          # Complete success
    PARTIAL = "partial"          # Partial success (some items failed)
    FAILURE = "failure"          # Complete failure
    DUPLICATE = "duplicate"      # Duplicate detection
    CONFLICT = "conflict"        # Series conflict detected


@dataclass
class ItemTerminalReport:
    """Terminal report for a single ingestion item.

    Attributes:
        item_id: Item identifier
        source_path: Original source path
        terminal_outcome: Final outcome status
        error_code: Error code if failed/rejected
        error_detail: Detailed error message
        instance_id: Associated instance ID (if accepted)
        observation_id: Associated observation ID (if accepted)
        binding_status: Platform binding status
        index_status: Projection index status
        processing_duration_ms: Processing time in milliseconds
    """
    item_id: int
    source_path: str
    terminal_outcome: str
    error_code: str = ""
    error_detail: str = ""
    instance_id: Optional[int] = None
    observation_id: Optional[int] = None
    binding_status: str = "pending"
    index_status: str = "pending"
    processing_duration_ms: Optional[int] = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            "item_id": self.item_id,
            "source_path": self.source_path,
            "terminal_outcome": self.terminal_outcome,
            "error_code": self.error_code,
            "error_detail": self.error_detail,
            "instance_id": self.instance_id,
            "observation_id": self.observation_id,
            "binding_status": self.binding_status,
            "index_status": self.index_status,
            "processing_duration_ms": self.processing_duration_ms,
        }


@dataclass
class JobTerminalSummary:
    """Terminal summary for an entire ingestion job.

    Attributes:
        job_id: Job identifier
        total_items: Total number of items
        accepted_count: Number of accepted items
        quarantined_count: Number of quarantined items
        rejected_count: Number of rejected items
        failed_count: Number of failed items
        duplicate_findings: Number of duplicate findings
        unresolved_references: Number of unresolved references
        classification: Overall job classification
        report_ready: True if report is complete
        generated_at: Timestamp when report was generated
    """
    job_id: int
    total_items: int = 0
    accepted_count: int = 0
    quarantined_count: int = 0
    rejected_count: int = 0
    failed_count: int = 0
    duplicate_findings: int = 0
    unresolved_references: int = 0
    classification: str = ""
    report_ready: bool = False
    generated_at: datetime = field(default_factory=datetime.utcnow)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            "job_id": self.job_id,
            "total_items": self.total_items,
            "accepted_count": self.accepted_count,
            "quarantined_count": self.quarantined_count,
            "rejected_count": self.rejected_count,
            "failed_count": self.failed_count,
            "duplicate_findings": self.duplicate_findings,
            "unresolved_references": self.unresolved_references,
            "classification": self.classification,
            "report_ready": self.report_ready,
            "generated_at": self.generated_at.isoformat(),
        }


@dataclass
class TerminalReport:
    """Complete terminal report for a job.

    Contains both the job-level summary and item-level details.
    """
    summary: JobTerminalSummary
    items: list[ItemTerminalReport] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            "summary": self.summary.to_dict(),
            "items": [item.to_dict() for item in self.items],
            "metadata": self.metadata,
        }


class TerminalReportService:
    """Service for generating terminal reports of ingestion results.

    Responsibilities:
    - Convert ingest outcomes into terminal candidate-level reports
    - Aggregate per-upload summaries
    - Guarantee machine-readable terminal status for success/partial/failure

    The terminal status, once set, never changes. This provides a
    stable, queryable record of what happened during ingestion.
    """

    def __init__(self, repository: Optional["TerminalReportRepository"] = None, cache_ttl_seconds: int = 120, cache_max_size: int = 128) -> None:
        """Initialize the terminal report service."""
        self._logger = logger
        self._repository = repository
        self._cache_ttl = timedelta(seconds=cache_ttl_seconds)
        self._cache_max_size = cache_max_size
        self._reports: dict[int, tuple[datetime, TerminalReport]] = {}

    async def generate_job_report(
        self,
        job_id: int,
        items: list[IngestionItem],
        duplicate_count: int = 0,
        unresolved_ref_count: int = 0,
    ) -> TerminalReport:
        """Generate a terminal report for a completed job.

        Args:
            job_id: The ingestion job ID
            items: List of ingestion items
            duplicate_count: Number of duplicate findings
            unresolved_ref_count: Number of unresolved references

        Returns:
            Complete terminal report
        """
        self._logger.info("Generating terminal report for job %d with %d items", job_id, len(items))

        # Generate item reports
        item_reports = [self._create_item_report(item) for item in items]

        # Calculate summary statistics
        summary = self._calculate_summary(
            job_id=job_id,
            item_reports=item_reports,
            duplicate_count=duplicate_count,
            unresolved_ref_count=unresolved_ref_count,
        )

        # Build complete report
        report = TerminalReport(
            summary=summary,
            items=item_reports,
            metadata={
                "report_version": "1.0",
                "report_type": "terminal",
            },
        )

        # Persist as source of truth and update best-effort cache
        if self._repository is not None:
            self._repository.upsert_report(report.to_dict())
        self._cache_report(job_id, report)

        self._logger.info(
            "Generated report for job %d: total=%d, accepted=%d, rejected=%d, failed=%d",
            job_id, summary.total_items, summary.accepted_count,
            summary.rejected_count, summary.failed_count
        )

        return report

    def _create_item_report(self, item: IngestionItem) -> ItemTerminalReport:
        """Create terminal report for a single item.

        Args:
            item: Ingestion item

        Returns:
            Item terminal report
        """
        # Extract status from item
        terminal_outcome = item.terminal_outcome

        # Get binding and index status from status axes
        binding_status = item.status_axes.binding_status if item.status_axes else "pending"
        index_status = item.status_axes.index_status if item.status_axes else "pending"

        # Get instance/observation IDs from metadata if available
        instance_id = item.metadata.get("instance_id") if item.metadata else None
        observation_id = item.metadata.get("observation_id") if item.metadata else None

        return ItemTerminalReport(
            item_id=item.id,
            source_path=item.source_path,
            terminal_outcome=terminal_outcome,
            error_code=item.error_code,
            error_detail=item.error_detail,
            instance_id=instance_id,
            observation_id=observation_id,
            binding_status=binding_status,
            index_status=index_status,
        )

    def _calculate_summary(
        self,
        job_id: int,
        item_reports: list[ItemTerminalReport],
        duplicate_count: int,
        unresolved_ref_count: int,
    ) -> JobTerminalSummary:
        """Calculate job-level summary statistics.

        Args:
            job_id: Job ID
            item_reports: List of item reports
            duplicate_count: Number of duplicates
            unresolved_ref_count: Number of unresolved references

        Returns:
            Job summary
        """
        total = len(item_reports)
        accepted = sum(1 for r in item_reports if r.terminal_outcome == TerminalStatus.ACCEPTED.value)
        quarantined = sum(1 for r in item_reports if r.terminal_outcome == TerminalStatus.QUARANTINED.value)
        rejected = sum(1 for r in item_reports if r.terminal_outcome == TerminalStatus.REJECTED.value)
        failed = sum(1 for r in item_reports if r.terminal_outcome == TerminalStatus.FAILED.value)

        # Determine classification
        if total == 0:
            classification = IngestClassification.FAILURE.value
        elif accepted == total:
            classification = IngestClassification.SUCCESS.value
        elif accepted > 0:
            classification = IngestClassification.PARTIAL.value
        else:
            classification = IngestClassification.FAILURE.value

        return JobTerminalSummary(
            job_id=job_id,
            total_items=total,
            accepted_count=accepted,
            quarantined_count=quarantined,
            rejected_count=rejected,
            failed_count=failed,
            duplicate_findings=duplicate_count,
            unresolved_references=unresolved_ref_count,
            classification=classification,
            report_ready=True,
        )

    async def generate_partial_report(
        self,
        job_id: int,
        items: list[IngestionItem],
        stage: str,
    ) -> TerminalReport:
        """Generate a partial report for items at a specific processing stage.

        This is useful for reporting progress during long-running jobs.

        Args:
            job_id: Job ID
            items: Items at this stage
            stage: Processing stage name

        Returns:
            Partial terminal report
        """
        item_reports = [self._create_item_report(item) for item in items]

        summary = JobTerminalSummary(
            job_id=job_id,
            total_items=len(items),
            classification="in_progress",
            report_ready=False,
        )

        report = TerminalReport(
            summary=summary,
            items=item_reports,
            metadata={
                "report_version": "1.0",
                "report_type": "partial",
                "stage": stage,
            },
        )

        return report

    def _cache_report(self, job_id: int, report: TerminalReport) -> None:
        self._reports[job_id] = (datetime.utcnow(), report)
        if len(self._reports) > self._cache_max_size:
            oldest = min(self._reports.items(), key=lambda kv: kv[1][0])[0]
            self._reports.pop(oldest, None)

    def _get_cached_report(self, job_id: int) -> Optional[TerminalReport]:
        cached = self._reports.get(job_id)
        if not cached:
            return None
        cached_at, report = cached
        if datetime.utcnow() - cached_at > self._cache_ttl:
            self._reports.pop(job_id, None)
            return None
        return report

    def _deserialize_report(self, payload: dict[str, Any]) -> TerminalReport:
        summary_payload = payload["summary"]
        summary = JobTerminalSummary(
            job_id=summary_payload["job_id"],
            total_items=summary_payload["total_items"],
            accepted_count=summary_payload["accepted_count"],
            quarantined_count=summary_payload["quarantined_count"],
            rejected_count=summary_payload["rejected_count"],
            failed_count=summary_payload["failed_count"],
            duplicate_findings=summary_payload["duplicate_findings"],
            unresolved_references=summary_payload["unresolved_references"],
            classification=summary_payload["classification"],
            report_ready=summary_payload["report_ready"],
            generated_at=summary_payload["generated_at"] if isinstance(summary_payload["generated_at"], datetime) else datetime.fromisoformat(summary_payload["generated_at"]),
        )
        items = [ItemTerminalReport(**{k: v for k, v in item.items() if k in ItemTerminalReport.__dataclass_fields__}) for item in payload.get("items", [])]
        return TerminalReport(summary=summary, items=items, metadata=payload.get("metadata") or {})

    def get_report(self, job_id: int) -> Optional[TerminalReport]:
        report = self._get_cached_report(job_id)
        if report:
            return report
        if self._repository is None:
            return None
        payload = self._repository.get_report(job_id)
        if payload is None:
            return None
        report = self._deserialize_report(payload)
        self._cache_report(job_id, report)
        return report

    def get_all_reports(self) -> dict[int, TerminalReport]:
        return {job_id: report for job_id, (_, report) in self._reports.items()}

    def query_items_by_status(self, job_id: int, status: str) -> list[ItemTerminalReport]:
        report = self.get_report(job_id)
        if not report:
            return []
        return [item for item in report.items if item.terminal_outcome == status]

    def is_terminal_status_queryable(self, job_id: int) -> bool:
        report = self.get_report(job_id)
        if not report:
            return False
        return report.summary.report_ready

    def get_failure_summary(self, job_id: int) -> dict[str, Any]:
        """Get summary of failures for a job.

        Args:
            job_id: Job ID

        Returns:
            Dictionary with failure summary
        """
        report = self.get_report(job_id)
        if not report:
            return {"error": "Report not found"}

        failures = [
            item for item in report.items
            if item.terminal_outcome in (TerminalStatus.FAILED.value, TerminalStatus.REJECTED.value)
        ]

        # Group by error code
        error_codes: dict[str, int] = {}
        for failure in failures:
            code = failure.error_code or "UNKNOWN"
            error_codes[code] = error_codes.get(code, 0) + 1

        return {
            "job_id": job_id,
            "total_failures": len(failures),
            "error_code_breakdown": error_codes,
            "failed_items": [item.to_dict() for item in failures],
        }
