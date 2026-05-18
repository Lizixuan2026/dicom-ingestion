"""
Tests for PrivateTagPersistenceService (C2).

Acceptance criteria:
- Private tags persisted with raw bytes
- Redaction policy applied correctly
- Large values handled appropriately
- Interpretation applied when configured
"""
import pytest
from unittest.mock import MagicMock


class TestPrivateTagPersistenceResult:
    """Tests for PrivateTagPersistenceResult."""

    def test_default_result(self):
        """Default result should indicate no persistence."""
        from dicom_ingestion.services.persistence.private_tag_persistence import (
            PrivateTagPersistenceResult,
        )

        result = PrivateTagPersistenceResult()

        assert result.success is False
        assert result.persisted_count == 0
        assert result.redacted_count == 0

    def test_to_dict(self):
        """to_dict should serialize result."""
        from dicom_ingestion.services.persistence.private_tag_persistence import (
            PrivateTagPersistenceResult,
        )

        result = PrivateTagPersistenceResult(
            success=True,
            persisted_count=5,
            redacted_count=2,
            interpreted_count=1,
        )

        data = result.to_dict()

        assert data["success"] is True
        assert data["persisted_count"] == 5
        assert data["redacted_count"] == 2


class TestPrivateTagPersistenceServiceInterface:
    """Tests for PrivateTagPersistenceService interface."""

    def test_service_initialization(self):
        """Service should initialize with session and optional policy."""
        from dicom_ingestion.services.persistence.private_tag_persistence import (
            PrivateTagPersistenceService,
        )
        from dicom_ingestion.models.private_tag import PrivateTagPolicy

        mock_session = MagicMock()
        policy = PrivateTagPolicy(redact_creators=["PHI"])

        service = PrivateTagPersistenceService(
            session=mock_session,
            policy=policy,
        )

        assert service._session is mock_session
        assert service._policy.redact_creators == ["PHI"]

    def test_default_policy(self):
        """Service should use default policy if none provided."""
        from dicom_ingestion.services.persistence.private_tag_persistence import (
            PrivateTagPersistenceService,
        )

        mock_session = MagicMock()
        service = PrivateTagPersistenceService(session=mock_session)

        assert service._policy is not None
        assert service._policy.default_action == "preserve"
