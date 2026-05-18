"""
Tests for DuplicateDetectionService (C1).

Acceptance criteria:
- Identity duplicates detected by SOPInstanceUID match
- Content duplicates detected by file hash match
- Findings persisted with correct types
- Retry creates no duplicate findings
"""
import pytest
from unittest.mock import MagicMock, create_autospec

# Mock SQLAlchemy session for unit tests


class TestDuplicateDetectionContext:
    """Tests for DuplicateDetectionContext dataclass."""

    def test_context_creation(self):
        """Context should hold detection parameters."""
        from dicom_ingestion.services.detection.duplicate_detection import (
            DuplicateDetectionContext,
        )

        ctx = DuplicateDetectionContext(
            observation_id=100,
            instance_id=50,
            sop_instance_uid="1.2.3.4",
            whole_file_sha256="abc123",
            pixel_digest="pixel456",
            ingestion_item_id=75,
        )

        assert ctx.observation_id == 100
        assert ctx.sop_instance_uid == "1.2.3.4"
        assert ctx.whole_file_sha256 == "abc123"


class TestDuplicateCheckResult:
    """Tests for DuplicateCheckResult dataclass."""

    def test_default_no_duplicates(self):
        """Default result should indicate no duplicates."""
        from dicom_ingestion.services.detection.duplicate_detection import (
            DuplicateCheckResult,
        )

        result = DuplicateCheckResult()

        assert result.has_duplicates is False
        assert result.identity_duplicate is None
        assert result.content_duplicates == []

    def test_to_dict(self):
        """to_dict should serialize result."""
        from dicom_ingestion.services.detection.duplicate_detection import (
            DuplicateCheckResult,
        )

        result = DuplicateCheckResult(
            has_duplicates=True,
            canonical_instance_id=50,
        )

        data = result.to_dict()

        assert data["has_duplicates"] is True
        assert data["canonical_instance_id"] == 50


class TestDuplicateDetectionServiceInterface:
    """Tests for DuplicateDetectionService interface."""

    def test_service_initialization(self):
        """Service should initialize with session."""
        from dicom_ingestion.services.detection.duplicate_detection import (
            DuplicateDetectionService,
        )

        mock_session = MagicMock()
        service = DuplicateDetectionService(session=mock_session)

        assert service._session is mock_session
