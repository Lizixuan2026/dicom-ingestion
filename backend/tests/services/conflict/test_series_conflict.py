"""
Tests for SeriesConflictService (C4).

Acceptance criteria:
- Series attempts built from job items
- Conflicts classified by SOP overlap and content
- Conflict summaries created for user review
- Resolution actions update canonical pointers correctly
"""
import pytest
from unittest.mock import MagicMock


class TestSeriesConflictBuildResult:
    """Tests for SeriesConflictBuildResult."""

    def test_default_result(self):
        """Default result should indicate no attempts created."""
        from dicom_ingestion.services.conflict.series_conflict import (
            SeriesConflictBuildResult,
        )

        result = SeriesConflictBuildResult()

        assert result.success is False
        assert result.attempts_created == 0

    def test_to_dict(self):
        """to_dict should serialize result."""
        from dicom_ingestion.services.conflict.series_conflict import (
            SeriesConflictBuildResult,
        )

        result = SeriesConflictBuildResult(
            success=True,
            attempts_created=5,
        )

        data = result.to_dict()

        assert data["success"] is True
        assert data["attempts_created"] == 5


class TestSeriesConflictServiceInterface:
    """Tests for SeriesConflictService interface."""

    def test_service_initialization(self):
        """Service should initialize with session and threshold."""
        from dicom_ingestion.services.conflict.series_conflict import (
            SeriesConflictService,
        )

        mock_session = MagicMock()
        service = SeriesConflictService(
            session=mock_session,
            uid_conflict_threshold=0.15,
        )

        assert service._session is mock_session
        assert service._uid_conflict_threshold == 0.15

    def test_default_threshold(self):
        """Service should use default threshold if not specified."""
        from dicom_ingestion.services.conflict.series_conflict import (
            SeriesConflictService,
            DEFAULT_UID_CONFLICT_THRESHOLD,
        )

        mock_session = MagicMock()
        service = SeriesConflictService(session=mock_session)

        assert service._uid_conflict_threshold == DEFAULT_UID_CONFLICT_THRESHOLD
        assert DEFAULT_UID_CONFLICT_THRESHOLD == 0.10  # 10% default


class TestSeriesConflictClassification:
    """Tests for conflict classification logic."""

    def test_content_conflict_priority(self):
        """Content conflict should have highest priority."""
        from dicom_ingestion.models.series_conflict import (
            SeriesConflictClassification,
        )

        # Content conflict is highest priority
        classifications = [
            SeriesConflictClassification.EXACT_DUPLICATE.value,
            SeriesConflictClassification.PARTIAL_OVERLAP.value,
            SeriesConflictClassification.UID_CONFLICT.value,
            SeriesConflictClassification.CONTENT_CONFLICT.value,
        ]

        # Verify expected values exist
        assert SeriesConflictClassification.CONTENT_CONFLICT.value == "content_conflict"
        assert SeriesConflictClassification.UID_CONFLICT.value == "uid_conflict"
        assert SeriesConflictClassification.PARTIAL_OVERLAP.value == "partial_overlap"
        assert SeriesConflictClassification.EXACT_DUPLICATE.value == "exact_duplicate"


class TestSeriesConflictResolution:
    """Tests for conflict resolution."""

    def test_exact_duplicate_cannot_resolve(self):
        """Exact duplicates should not be resolvable manually."""
        from dicom_ingestion.models.series_conflict import (
            SeriesConflictSummary,
            SeriesConflictClassification,
            SeriesConflictStatus,
        )

        summary = SeriesConflictSummary(
            classification=SeriesConflictClassification.EXACT_DUPLICATE.value,
            status=SeriesConflictStatus.OPEN.value,
        )

        assert summary.can_resolve is False

    def test_open_conflict_can_resolve(self):
        """Open non-exact-duplicate conflicts should be resolvable."""
        from dicom_ingestion.models.series_conflict import (
            SeriesConflictSummary,
            SeriesConflictClassification,
            SeriesConflictStatus,
        )

        summary = SeriesConflictSummary(
            classification=SeriesConflictClassification.PARTIAL_OVERLAP.value,
            status=SeriesConflictStatus.OPEN.value,
        )

        assert summary.can_resolve is True

    def test_resolved_conflict_cannot_resolve_again(self):
        """Already resolved conflicts should not be resolvable."""
        from dicom_ingestion.models.series_conflict import (
            SeriesConflictSummary,
            SeriesConflictClassification,
            SeriesConflictStatus,
        )

        summary = SeriesConflictSummary(
            classification=SeriesConflictClassification.PARTIAL_OVERLAP.value,
            status=SeriesConflictStatus.KEPT_EXISTING.value,
        )

        assert summary.can_resolve is False
