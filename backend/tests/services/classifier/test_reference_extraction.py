"""
Tests for ReferenceExtractionService (C3).

Acceptance criteria:
- Reference sequences extracted from parsed DICOM
- Edges persisted with correct relationship types
- Immediate resolution attempted if target exists
- Unresolved references tracked for background resolution
"""
import pytest
from unittest.mock import MagicMock


class TestReferenceExtractionResult:
    """Tests for ReferenceExtractionResult."""

    def test_default_result(self):
        """Default result should indicate no extraction."""
        from dicom_ingestion.services.classifier.reference_extraction import (
            ReferenceExtractionResult,
        )

        result = ReferenceExtractionResult()

        assert result.success is False
        assert result.extracted_count == 0
        assert result.persisted_count == 0

    def test_to_dict(self):
        """to_dict should serialize result."""
        from dicom_ingestion.services.classifier.reference_extraction import (
            ReferenceExtractionResult,
        )

        result = ReferenceExtractionResult(
            success=True,
            extracted_count=3,
            persisted_count=3,
            resolved_count=2,
        )

        data = result.to_dict()

        assert data["success"] is True
        assert data["extracted_count"] == 3
        assert data["resolved_count"] == 2


class TestReferenceExtractionServiceInterface:
    """Tests for ReferenceExtractionService interface."""

    def test_service_initialization(self):
        """Service should initialize with session."""
        from dicom_ingestion.services.classifier.reference_extraction import (
            ReferenceExtractionService,
        )

        mock_session = MagicMock()
        service = ReferenceExtractionService(session=mock_session)

        assert service._session is mock_session

    def test_reference_sequences_defined(self):
        """Service should define known reference sequences."""
        from dicom_ingestion.services.classifier.reference_extraction import (
            ReferenceExtractionService,
        )

        mock_session = MagicMock()
        service = ReferenceExtractionService(session=mock_session)

        assert "ReferencedImageSequence" in service.REFERENCE_SEQUENCES
        assert "ReferencedStudySequence" in service.REFERENCE_SEQUENCES
