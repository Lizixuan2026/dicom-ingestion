"""
Tests for SeriesConflict models (C4).

Acceptance criteria:
- SeriesIngestionAttempt tracks upload attempts
- SeriesConflictSummary classifies conflicts
- Resolution actions update status correctly
"""
import pytest
from datetime import datetime

from dicom_ingestion.models.series_conflict import (
    SeriesIngestionAttempt,
    SeriesConflictSummary,
    SeriesConflictClassification,
    SeriesConflictStatus,
    ConflictClassificationResult,
    ConflictResolutionResult,
)


class TestSeriesIngestionAttempt:
    """Tests for SeriesIngestionAttempt model."""

    def test_creation(self):
        """Attempt should track Series upload info."""
        attempt = SeriesIngestionAttempt(
            id=1,
            ingestion_job_id=100,
            study_instance_uid="1.2.3",
            series_instance_uid="1.2.3.4",
            uploaded_sop_count=50,
        )

        assert attempt.series_instance_uid == "1.2.3.4"
        assert attempt.uploaded_sop_count == 50

    def test_to_dict(self):
        """to_dict should include all fields."""
        attempt = SeriesIngestionAttempt(
            study_instance_uid="1.2.3",
            series_instance_uid="1.2.3.4",
        )

        data = attempt.to_dict()

        assert data["study_instance_uid"] == "1.2.3"
        assert data["series_instance_uid"] == "1.2.3.4"


class TestSeriesConflictSummary:
    """Tests for SeriesConflictSummary model."""

    def test_default_status_is_open(self):
        """Default status should be open."""
        summary = SeriesConflictSummary()

        assert summary.status == SeriesConflictStatus.OPEN.value
        assert summary.is_resolved is False

    def test_mark_kept_existing(self):
        """mark_kept_existing should update status."""
        summary = SeriesConflictSummary()
        summary.mark_kept_existing("user-1")

        assert summary.status == SeriesConflictStatus.KEPT_EXISTING.value
        assert summary.resolution_action == "keep_existing"
        assert summary.resolved_by == "user-1"
        assert summary.resolved_at is not None
        assert summary.is_resolved is True

    def test_mark_promoted_uploaded(self):
        """mark_promoted_uploaded should update status."""
        summary = SeriesConflictSummary()
        summary.mark_promoted_uploaded("admin-1")

        assert summary.status == SeriesConflictStatus.PROMOTED_UPLOADED.value
        assert summary.resolution_action == "promote_uploaded"
        assert summary.is_resolved is True

    def test_mark_auto_deduped(self):
        """mark_auto_deduped should update status."""
        summary = SeriesConflictSummary()
        summary.mark_auto_deduped()

        assert summary.status == SeriesConflictStatus.AUTO_DEDUPED.value
        assert summary.is_resolved is True
        assert summary.can_resolve is False  # Auto-deduped can't be resolved manually

    def test_can_resolve_for_open(self):
        """Open non-exact-duplicate conflicts can be resolved."""
        summary = SeriesConflictSummary(
            status=SeriesConflictStatus.OPEN.value,
            classification=SeriesConflictClassification.PARTIAL_OVERLAP.value,
        )

        assert summary.can_resolve is True

    def test_cannot_resolve_exact_duplicate(self):
        """Exact duplicate conflicts cannot be manually resolved."""
        summary = SeriesConflictSummary(
            status=SeriesConflictStatus.OPEN.value,
            classification=SeriesConflictClassification.EXACT_DUPLICATE.value,
        )

        assert summary.can_resolve is False

    def test_to_dict(self):
        """to_dict should include all fields."""
        summary = SeriesConflictSummary(
            id=1,
            classification=SeriesConflictClassification.CONTENT_CONFLICT.value,
            existing_sop_count=40,
            uploaded_sop_count=50,
            overlap_sop_count=30,
            conflicting_sop_count=5,
            overlap_ratio=0.6,
        )

        data = summary.to_dict()

        assert data["classification"] == SeriesConflictClassification.CONTENT_CONFLICT.value
        assert data["overlap_ratio"] == 0.6
        assert data["conflicting_sop_count"] == 5


class TestConflictClassificationResult:
    """Tests for ConflictClassificationResult."""

    def test_to_dict(self):
        """to_dict should include classification details."""
        result = ConflictClassificationResult(
            classification=SeriesConflictClassification.CONTENT_CONFLICT.value,
            existing_series_id=50,
            existing_sop_count=40,
            uploaded_sop_count=50,
            overlap_sop_count=30,
            conflicting_sop_count=5,
            overlap_ratio=0.6,
            reason="5 SOP(s) have content conflicts",
        )

        data = result.to_dict()

        assert data["classification"] == "content_conflict"
        assert data["overlap_ratio"] == 0.6
        assert "content conflicts" in data["reason"]


class TestConflictResolutionResult:
    """Tests for ConflictResolutionResult."""

    def test_success_result(self):
        """Successful resolution should have action info."""
        summary = SeriesConflictSummary(
            status=SeriesConflictStatus.KEPT_EXISTING.value,
        )
        result = ConflictResolutionResult(
            success=True,
            action="keep_existing",
            updated_summary=summary,
        )

        data = result.to_dict()

        assert data["success"] is True
        assert data["action"] == "keep_existing"

    def test_failure_result(self):
        """Failed resolution should have error info."""
        result = ConflictResolutionResult(
            success=False,
            action="promote_uploaded",
            error_code="PromotionFailed",
            error_detail="Transaction failed",
        )

        data = result.to_dict()

        assert data["success"] is False
        assert data["error_code"] == "PromotionFailed"
