"""
Tests for BindingPolicyService (C4).

Acceptance criteria:
- Binding records created for new instances
- Binding executed with platform integration
- Failed bindings can be retried
- Binding status tracked independently from ingest
"""
import pytest
from unittest.mock import MagicMock


class TestBindingPolicyServiceInterface:
    """Tests for BindingPolicyService interface."""

    def test_service_initialization(self):
        """Service should initialize with session and optional platform client."""
        from dicom_ingestion.services.binding.binding_policy import (
            BindingPolicyService,
        )

        mock_session = MagicMock()
        mock_client = MagicMock()

        service = BindingPolicyService(
            session=mock_session,
            platform_client=mock_client,
        )

        assert service._session is mock_session
        assert service._platform is mock_client

    def test_service_without_platform_client(self):
        """Service should work without platform client (stub mode)."""
        from dicom_ingestion.services.binding.binding_policy import (
            BindingPolicyService,
        )

        mock_session = MagicMock()
        service = BindingPolicyService(session=mock_session)

        assert service._platform is None
