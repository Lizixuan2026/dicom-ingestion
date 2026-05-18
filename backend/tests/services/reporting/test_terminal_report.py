"""Tests for terminal reporting service.

This module tests the TerminalReportService which is responsible for:
- Converting ingest outcomes into terminal candidate-level reports
- Aggregating per-upload summaries
- Providing machine-readable terminal status for success/partial/failure
"""

from typing import List
import pytest
from datetime import datetime

from dicom_ingestion.services.reporting.terminal_report import (
    TerminalReportService,
    TerminalReport,
    ItemTerminalReport,
    JobTerminalSummary,
    TerminalStatus,
    IngestClassification,
)
from dicom_ingestion.models.ingestion_item import IngestionItem, ItemStatusAxes, TerminalOutcome


class InMemoryTerminalReportRepository:
    def __init__(self):
        self.store = {}

    def upsert_report(self, report):
        self.store[report["summary"]["job_id"]] = report

    def get_report(self, job_id: int):
        return self.store.get(job_id)


@pytest.fixture
def report_repo():
    return InMemoryTerminalReportRepository()


@pytest.fixture
def report_service(report_repo):
    """Create a terminal report service fixture."""
    return TerminalReportService(repository=report_repo)


@pytest.fixture
def sample_items() -> List[IngestionItem]:
    """Create sample ingestion items with various outcomes."""
    items: List[IngestionItem] = []

    # Accepted item
    item1 = IngestionItem(
        id=1,
        ingestion_job_id=100,
        source_path="/upload/file1.dcm",
        byte_size=1024,
        item_fingerprint="fp1",
        status_axes=ItemStatusAxes(),
        terminal_outcome=TerminalOutcome.ACCEPTED.value,
        metadata={"instance_id": 101, "observation_id": 201},
    )
    items.append(item1)

    # Another accepted item
    item2 = IngestionItem(
        id=2,
        ingestion_job_id=100,
        source_path="/upload/file2.dcm",
        byte_size=2048,
        item_fingerprint="fp2",
        status_axes=ItemStatusAxes(),
        terminal_outcome=TerminalOutcome.ACCEPTED.value,
        metadata={"instance_id": 102, "observation_id": 202},
    )
    items.append(item2)

    # Rejected item
    item3 = IngestionItem(
        id=3,
        ingestion_job_id=100,
        source_path="/upload/file3.bad",
        byte_size=512,
        item_fingerprint="fp3",
        status_axes=ItemStatusAxes(),
        terminal_outcome=TerminalOutcome.REJECTED.value,
        error_code="DicomParseFailed",
        error_detail="Not a valid DICOM file",
    )
    items.append(item3)

    # Failed item
    item4 = IngestionItem(
        id=4,
        ingestion_job_id=100,
        source_path="/upload/file4.dcm",
        byte_size=1024,
        item_fingerprint="fp4",
        status_axes=ItemStatusAxes(),
        terminal_outcome=TerminalOutcome.FAILED.value,
        error_code="MetadataPersistenceFailed",
        error_detail="Database connection failed",
    )
    items.append(item4)

    return items


@pytest.fixture
def all_accepted_items() -> List[IngestionItem]:
    """Create items that are all accepted."""
    items: List[IngestionItem] = []
    for i in range(3):
        item = IngestionItem(
            id=i + 1,
            ingestion_job_id=100,
            source_path=f"/upload/file{i}.dcm",
            byte_size=1024,
            item_fingerprint=f"fp{i}",
            status_axes=ItemStatusAxes(),
            terminal_outcome=TerminalOutcome.ACCEPTED.value,
            metadata={"instance_id": 100 + i, "observation_id": 200 + i},
        )
        items.append(item)
    return items


@pytest.fixture
def all_failed_items() -> List[IngestionItem]:
    """Create items that are all failed/rejected."""
    items: List[IngestionItem] = []
    for i in range(3):
        item = IngestionItem(
            id=i + 1,
            ingestion_job_id=100,
            source_path=f"/upload/file{i}.bad",
            byte_size=512,
            item_fingerprint=f"fp{i}",
            status_axes=ItemStatusAxes(),
            terminal_outcome=TerminalOutcome.REJECTED.value if i % 2 == 0 else TerminalOutcome.FAILED.value,
            error_code="ParseFailed" if i % 2 == 0 else "StorageFailed",
        )
        items.append(item)
    return items


class TestTerminalReportService:
    """Test suite for TerminalReportService."""

    @pytest.mark.asyncio
    async def test_generate_job_report_success(
        self,
        report_service: TerminalReportService,
        all_accepted_items: List[IngestionItem],
    ):
        """Test generating report for all accepted items."""
        report = await report_service.generate_job_report(
            job_id=100,
            items=all_accepted_items,
            duplicate_count=0,
            unresolved_ref_count=0,
        )

        assert report.summary.total_items == 3
        assert report.summary.accepted_count == 3
        assert report.summary.rejected_count == 0
        assert report.summary.failed_count == 0
        assert report.summary.classification == IngestClassification.SUCCESS.value
        assert report.summary.report_ready is True
        assert len(report.items) == 3

    @pytest.mark.asyncio
    async def test_generate_job_report_partial(
        self,
        report_service: TerminalReportService,
        sample_items: List[IngestionItem],
    ):
        """Test generating report with mixed outcomes (partial success)."""
        report = await report_service.generate_job_report(
            job_id=100,
            items=sample_items,
            duplicate_count=2,
            unresolved_ref_count=1,
        )

        assert report.summary.total_items == 4
        assert report.summary.accepted_count == 2
        assert report.summary.rejected_count == 1
        assert report.summary.failed_count == 1
        assert report.summary.duplicate_findings == 2
        assert report.summary.unresolved_references == 1
        assert report.summary.classification == IngestClassification.PARTIAL.value

    @pytest.mark.asyncio
    async def test_generate_job_report_failure(
        self,
        report_service: TerminalReportService,
        all_failed_items: List[IngestionItem],
    ):
        """Test generating report for all failed items."""
        report = await report_service.generate_job_report(
            job_id=100,
            items=all_failed_items,
            duplicate_count=0,
            unresolved_ref_count=0,
        )

        assert report.summary.total_items == 3
        assert report.summary.accepted_count == 0
        assert report.summary.rejected_count == 2
        assert report.summary.failed_count == 1
        assert report.summary.classification == IngestClassification.FAILURE.value

    @pytest.mark.asyncio
    async def test_generate_job_report_empty(
        self,
        report_service: TerminalReportService,
    ):
        """Test generating report with no items."""
        report = await report_service.generate_job_report(
            job_id=100,
            items=[],
            duplicate_count=0,
            unresolved_ref_count=0,
        )

        assert report.summary.total_items == 0
        assert report.summary.classification == IngestClassification.FAILURE.value
        assert report.summary.report_ready is True

    @pytest.mark.asyncio
    async def test_get_report_after_generation(
        self,
        report_service: TerminalReportService,
        sample_items: List[IngestionItem],
    ):
        """Test retrieving a previously generated report."""
        await report_service.generate_job_report(
            job_id=100,
            items=sample_items,
        )

        retrieved = report_service.get_report(100)

        assert retrieved is not None
        assert retrieved.summary.job_id == 100
        assert retrieved.summary.total_items == 4

    def test_get_report_not_found(
        self,
        report_service: TerminalReportService,
    ):
        """Test retrieving non-existent report."""
        retrieved = report_service.get_report(999)
        assert retrieved is None

    @pytest.mark.asyncio
    async def test_query_items_by_status(
        self,
        report_service: TerminalReportService,
        sample_items: List[IngestionItem],
    ):
        """Test querying items by terminal status."""
        await report_service.generate_job_report(
            job_id=100,
            items=sample_items,
        )

        accepted = report_service.query_items_by_status(100, TerminalStatus.ACCEPTED.value)
        rejected = report_service.query_items_by_status(100, TerminalStatus.REJECTED.value)

        assert len(accepted) == 2
        assert len(rejected) == 1

    def test_query_items_by_status_no_report(
        self,
        report_service: TerminalReportService,
    ):
        """Test querying items when no report exists."""
        items = report_service.query_items_by_status(999, TerminalStatus.ACCEPTED.value)
        assert items == []

    @pytest.mark.asyncio
    async def test_is_terminal_status_queryable(
        self,
        report_service: TerminalReportService,
        sample_items: List[IngestionItem],
    ):
        """Test checking if terminal status is queryable."""
        # Before generation
        assert report_service.is_terminal_status_queryable(100) is False

        # After generation
        await report_service.generate_job_report(
            job_id=100,
            items=sample_items,
        )
        assert report_service.is_terminal_status_queryable(100) is True

    @pytest.mark.asyncio
    async def test_get_failure_summary(
        self,
        report_service: TerminalReportService,
        sample_items: List[IngestionItem],
    ):
        """Test getting failure summary for a job."""
        await report_service.generate_job_report(
            job_id=100,
            items=sample_items,
        )

        summary = report_service.get_failure_summary(100)

        assert summary["job_id"] == 100
        assert summary["total_failures"] == 2  # 1 rejected + 1 failed
        assert "DicomParseFailed" in summary["error_code_breakdown"]
        assert "MetadataPersistenceFailed" in summary["error_code_breakdown"]
        assert len(summary["failed_items"]) == 2

    def test_get_failure_summary_no_report(
        self,
        report_service: TerminalReportService,
    ):
        """Test getting failure summary when no report exists."""
        summary = report_service.get_failure_summary(999)
        assert "error" in summary

    @pytest.mark.asyncio
    async def test_generate_partial_report(
        self,
        report_service: TerminalReportService,
        all_accepted_items: List[IngestionItem],
    ):
        """Test generating a partial (in-progress) report."""
        report = await report_service.generate_partial_report(
            job_id=100,
            items=all_accepted_items,
            stage="parsing",
        )

        assert report.summary.report_ready is False
        assert report.summary.classification == "in_progress"
        assert report.metadata["report_type"] == "partial"
        assert report.metadata["stage"] == "parsing"

    @pytest.mark.asyncio
    async def test_item_report_includes_error_details(
        self,
        report_service: TerminalReportService,
    ):
        """Test that item reports include error details for failures."""
        item = IngestionItem(
            id=1,
            ingestion_job_id=100,
            source_path="/upload/file.dcm",
            byte_size=1024,
            item_fingerprint="fp1",
            status_axes=ItemStatusAxes(),
            terminal_outcome=TerminalOutcome.FAILED.value,
            error_code="StorageFailed",
            error_detail="Connection timeout after 30s",
        )

        report = await report_service.generate_job_report(
            job_id=100,
            items=[item],
        )

        item_report = report.items[0]
        assert item_report.error_code == "StorageFailed"
        assert item_report.error_detail == "Connection timeout after 30s"



    @pytest.mark.asyncio
    async def test_report_persists_across_service_restart(self, sample_items):
        repo = InMemoryTerminalReportRepository()
        service_a = TerminalReportService(repository=repo)
        await service_a.generate_job_report(job_id=100, items=sample_items)

        service_b = TerminalReportService(repository=repo)
        retrieved = service_b.get_report(100)

        assert retrieved is not None
        assert retrieved.summary.total_items == 4

    @pytest.mark.asyncio
    async def test_generate_same_job_overwrites_existing_report(self, sample_items):
        repo = InMemoryTerminalReportRepository()
        service = TerminalReportService(repository=repo)
        await service.generate_job_report(job_id=100, items=sample_items)
        await service.generate_job_report(job_id=100, items=sample_items[:2])

        retrieved = service.get_report(100)
        assert retrieved is not None
        assert retrieved.summary.total_items == 2
class TestItemTerminalReport:
    """Test suite for ItemTerminalReport."""

    def test_to_dict(self):
        """Test conversion to dictionary."""
        report = ItemTerminalReport(
            item_id=123,
            source_path="/upload/test.dcm",
            terminal_outcome=TerminalStatus.ACCEPTED.value,
            instance_id=456,
            observation_id=789,
            binding_status="completed",
            index_status="completed",
            processing_duration_ms=1500,
        )

        data = report.to_dict()

        assert data["item_id"] == 123
        assert data["source_path"] == "/upload/test.dcm"
        assert data["terminal_outcome"] == "accepted"
        assert data["instance_id"] == 456
        assert data["observation_id"] == 789
        assert data["processing_duration_ms"] == 1500


class TestJobTerminalSummary:
    """Test suite for JobTerminalSummary."""

    def test_to_dict(self):
        """Test conversion to dictionary."""
        summary = JobTerminalSummary(
            job_id=100,
            total_items=10,
            accepted_count=8,
            rejected_count=1,
            failed_count=1,
            classification=IngestClassification.PARTIAL.value,
            report_ready=True,
        )

        data = summary.to_dict()

        assert data["job_id"] == 100
        assert data["total_items"] == 10
        assert data["accepted_count"] == 8
        assert data["classification"] == "partial"
        assert data["report_ready"] is True
        assert "generated_at" in data


class TestTerminalStatus:
    """Test suite for TerminalStatus enum."""

    def test_status_values(self):
        """Test terminal status values."""
        assert TerminalStatus.ACCEPTED.value == "accepted"
        assert TerminalStatus.QUARANTINED.value == "quarantined"
        assert TerminalStatus.REJECTED.value == "rejected"
        assert TerminalStatus.FAILED.value == "failed"
        assert TerminalStatus.NONE.value == ""


class TestIngestClassification:
    """Test suite for IngestClassification enum."""

    def test_classification_values(self):
        """Test classification values."""
        assert IngestClassification.SUCCESS.value == "success"
        assert IngestClassification.PARTIAL.value == "partial"
        assert IngestClassification.FAILURE.value == "failure"
        assert IngestClassification.DUPLICATE.value == "duplicate"
        assert IngestClassification.CONFLICT.value == "conflict"
