"""
Tests for Batch 4 integration with CanonicalPersistenceService.

Acceptance criteria:
- Duplicate detection executes after observation creation
- Private tags are persisted with redaction policy applied
- Reference edges are extracted and stored
- Binding policy records are created
- All Batch 4 results are populated in PersistenceResult
"""
import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime

from dicom_ingestion.services.canonical.canonical_persistence import (
    CanonicalPersistenceService,
    PersistenceResult,
)


class TestPersistenceResultBatch4Fields:
    """Tests for PersistenceResult Batch 4 fields."""

    def test_result_has_duplicate_check_result(self):
        """PersistenceResult should have duplicate_check_result field."""
        result = PersistenceResult(
            duplicate_check_result={"has_duplicates": True}
        )
        assert result.duplicate_check_result["has_duplicates"] is True

    def test_result_has_private_tag_result(self):
        """PersistenceResult should have private_tag_result field."""
        result = PersistenceResult(
            private_tag_result={"persisted_count": 5}
        )
        assert result.private_tag_result["persisted_count"] == 5

    def test_result_has_reference_extraction_result(self):
        """PersistenceResult should have reference_extraction_result field."""
        result = PersistenceResult(
            reference_extraction_result={"extracted_count": 3}
        )
        assert result.reference_extraction_result["extracted_count"] == 3

    def test_result_has_binding_policy_result(self):
        """PersistenceResult should have binding_policy_result field."""
        result = PersistenceResult(
            binding_policy_result={"binding_id": 100}
        )
        assert result.binding_policy_result["binding_id"] == 100

    def test_result_has_canonical_policy_rationale(self):
        """PersistenceResult should record canonical policy rationale."""
        result = PersistenceResult(
            canonical_policy_rationale="first_observation_becomes_canonical"
        )
        assert result.canonical_policy_rationale == "first_observation_becomes_canonical"


class TestCanonicalPersistenceServiceBatch4Flags:
    """Tests for Batch 4 feature flags in CanonicalPersistenceService."""

    def test_batch4_flags_enabled_by_default(self):
        """All Batch 4 features should be enabled by default."""
        mock_session = MagicMock()
        mock_store = MagicMock()

        service = CanonicalPersistenceService(
            session=mock_session,
            raw_object_store=mock_store,
        )

        assert service._enable_duplicate_detection is True
        assert service._enable_private_tag_persistence is True
        assert service._enable_reference_extraction is True
        assert service._enable_binding_policy is True

    def test_batch4_flags_can_be_disabled(self):
        """Batch 4 features should be individually disableable."""
        mock_session = MagicMock()
        mock_store = MagicMock()

        service = CanonicalPersistenceService(
            session=mock_session,
            raw_object_store=mock_store,
            enable_duplicate_detection=False,
            enable_private_tag_persistence=False,
            enable_reference_extraction=False,
            enable_binding_policy=False,
        )

        assert service._enable_duplicate_detection is False
        assert service._enable_private_tag_persistence is False
        assert service._enable_reference_extraction is False
        assert service._enable_binding_policy is False


class TestCanonicalPersistenceServiceIntegration:
    """Tests for Batch 4 service integration."""

    def test_duplicate_service_lazy_initialization(self):
        """Duplicate detection service should be lazy-initialized."""
        mock_session = MagicMock()
        mock_store = MagicMock()

        service = CanonicalPersistenceService(
            session=mock_session,
            raw_object_store=mock_store,
        )

        # Initially None
        assert service._duplicate_service is None

        # Access triggers initialization
        with patch("dicom_ingestion.services.detection.duplicate_detection.DuplicateDetectionService") as mock_dup:
            mock_dup.return_value = MagicMock()
            dup_service = service._get_duplicate_service()
            assert dup_service is not None
            assert service._duplicate_service is not None

    def test_private_tag_service_lazy_initialization(self):
        """Private tag service should be lazy-initialized."""
        mock_session = MagicMock()
        mock_store = MagicMock()

        service = CanonicalPersistenceService(
            session=mock_session,
            raw_object_store=mock_store,
        )

        # Initially None
        assert service._private_tag_service is None

        # Access triggers initialization
        with patch("dicom_ingestion.services.persistence.private_tag_persistence.PrivateTagPersistenceService") as mock_pt:
            mock_pt.return_value = MagicMock()
            pt_service = service._get_private_tag_service()
            assert pt_service is not None
            assert service._private_tag_service is not None

    def test_reference_service_lazy_initialization(self):
        """Reference extraction service should be lazy-initialized."""
        mock_session = MagicMock()
        mock_store = MagicMock()

        service = CanonicalPersistenceService(
            session=mock_session,
            raw_object_store=mock_store,
        )

        # Initially None
        assert service._reference_service is None

        # Access triggers initialization
        with patch("dicom_ingestion.services.classifier.reference_extraction.ReferenceExtractionService") as mock_ref:
            mock_ref.return_value = MagicMock()
            ref_service = service._get_reference_service()
            assert ref_service is not None
            assert service._reference_service is not None

    def test_binding_service_lazy_initialization(self):
        """Binding policy service should be lazy-initialized."""
        mock_session = MagicMock()
        mock_store = MagicMock()

        service = CanonicalPersistenceService(
            session=mock_session,
            raw_object_store=mock_store,
        )

        # Initially None
        assert service._binding_service is None

        # Access triggers initialization
        with patch("dicom_ingestion.services.binding.binding_policy.BindingPolicyService") as mock_bind:
            mock_bind.return_value = MagicMock()
            bind_service = service._get_binding_service()
            assert bind_service is not None
            assert service._binding_service is not None


class TestBatch4ServicesDisabled:
    """Tests for when Batch 4 services are disabled."""

    def test_services_return_none_when_disabled(self):
        """Service getters should return None when features disabled."""
        mock_session = MagicMock()
        mock_store = MagicMock()

        service = CanonicalPersistenceService(
            session=mock_session,
            raw_object_store=mock_store,
            enable_duplicate_detection=False,
            enable_private_tag_persistence=False,
            enable_reference_extraction=False,
            enable_binding_policy=False,
        )

        assert service._get_duplicate_service() is None
        assert service._get_private_tag_service() is None
        assert service._get_reference_service() is None
        assert service._get_binding_service() is None


class TestBatch4ExecutionMethods:
    """Tests for Batch 4 execution helper methods."""

    def test_execute_duplicate_detection_handles_errors(self):
        """Duplicate detection errors should be caught and logged."""
        mock_session = MagicMock()
        mock_store = MagicMock()
        service = CanonicalPersistenceService(mock_session, mock_store)

        result = PersistenceResult()

        # Mock service that raises exception
        mock_dup_service = MagicMock()
        mock_dup_service.check_and_record_duplicates.side_effect = Exception("Test error")
        service._duplicate_service = mock_dup_service

        # Should not raise
        import asyncio
        asyncio.run(service._execute_duplicate_detection(
            result=result,
            instance_id=1,
            observation_id=2,
            item=MagicMock(),
            parsed_header=MagicMock(),
        ))

        # Error should be recorded
        assert "error" in result.duplicate_check_result

    def test_execute_private_tag_persistence_handles_errors(self):
        """Private tag persistence errors should be caught and logged."""
        mock_session = MagicMock()
        mock_store = MagicMock()
        service = CanonicalPersistenceService(mock_session, mock_store)

        result = PersistenceResult()

        # Mock service that raises exception
        mock_pt_service = MagicMock()
        mock_pt_service.persist_private_tags.side_effect = Exception("Test error")
        service._private_tag_service = mock_pt_service

        # Should not raise
        import asyncio
        asyncio.run(service._execute_private_tag_persistence(
            result=result,
            observation_id=2,
            parsed_header=MagicMock(),
        ))

        # Error should be recorded
        assert "error" in result.private_tag_result

    def test_execute_reference_extraction_handles_errors(self):
        """Reference extraction errors should be caught and logged."""
        mock_session = MagicMock()
        mock_store = MagicMock()
        service = CanonicalPersistenceService(mock_session, mock_store)

        result = PersistenceResult()

        # Mock service that raises exception
        mock_ref_service = MagicMock()
        mock_ref_service.extract_and_persist.side_effect = Exception("Test error")
        service._reference_service = mock_ref_service

        # Should not raise
        import asyncio
        asyncio.run(service._execute_reference_extraction(
            result=result,
            instance_id=1,
            observation_id=2,
            parsed_header=MagicMock(),
        ))

        # Error should be recorded
        assert "error" in result.reference_extraction_result

    def test_execute_binding_policy_handles_errors(self):
        """Binding policy errors should be caught and logged."""
        mock_session = MagicMock()
        mock_store = MagicMock()
        service = CanonicalPersistenceService(mock_session, mock_store)

        result = PersistenceResult()

        # Mock service that raises exception
        mock_bind_service = MagicMock()
        mock_bind_service.create_binding_record.side_effect = Exception("Test error")
        service._binding_service = mock_bind_service

        # Should not raise
        import asyncio
        asyncio.run(service._execute_binding_policy(
            result=result,
            instance_id=1,
            observation_id=2,
        ))

        # Error should be recorded
        assert "error" in result.binding_policy_result


class TestBindingContextHandling:
    """Tests for C4 binding context handling (v0.2 P0 fix)."""

    def test_binding_context_missing_uses_system_default(self):
        """Missing binding context should use system default with reason code."""
        from unittest.mock import AsyncMock
        mock_session = MagicMock()
        mock_store = MagicMock()
        service = CanonicalPersistenceService(mock_session, mock_store)

        result = PersistenceResult()

        # Mock binding service with AsyncMock
        mock_bind_service = MagicMock()
        mock_bind_result = MagicMock()
        mock_bind_result.binding_id = 100
        mock_bind_result.to_dict.return_value = {"binding_id": 100}
        mock_bind_service.create_binding_record = AsyncMock(return_value=mock_bind_result)
        service._binding_service = mock_bind_service

        # Execute without binding_context
        import asyncio
        asyncio.run(service._execute_binding_policy(
            result=result,
            instance_id=1,
            observation_id=2,
            binding_context=None,
        ))

        # Should record fallback info
        assert result.binding_policy_result["context_fallback"] == "system_default"
        assert result.binding_policy_result["context_fallback_reason"] == "BINDING_CONTEXT_MISSING"

    def test_binding_context_provided_uses_real_values(self):
        """Provided binding context should use real project_id/user_id."""
        from unittest.mock import AsyncMock
        mock_session = MagicMock()
        mock_store = MagicMock()
        service = CanonicalPersistenceService(mock_session, mock_store)

        result = PersistenceResult()

        # Mock binding service with AsyncMock
        mock_bind_service = MagicMock()
        mock_bind_result = MagicMock()
        mock_bind_result.binding_id = 101
        mock_bind_result.to_dict.return_value = {"binding_id": 101}
        mock_bind_service.create_binding_record = AsyncMock(return_value=mock_bind_result)
        service._binding_service = mock_bind_service

        # Create real binding context
        from dicom_ingestion.models.binding_policy import BindingContext
        ctx = BindingContext(
            project_id="proj-123",
            user_id="user-456",
            dataset_id="ds-789",
        )

        # Execute with binding_context
        import asyncio
        asyncio.run(service._execute_binding_policy(
            result=result,
            instance_id=1,
            observation_id=2,
            binding_context=ctx,
        ))

        # Should use provided context
        assert result.binding_policy_result["binding_id"] == 101
        # Verify service called with correct context
        call_args = mock_bind_service.create_binding_record.call_args
        assert call_args[1]["context"].project_id == "proj-123"
        assert call_args[1]["context"].user_id == "user-456"


class TestPixelDigestHandling:
    """Tests for C1 pixel digest handling (v0.2 P0 fix)."""

    def test_pixel_digest_passed_to_duplicate_detection(self):
        """pixel_digest from parsed header should be passed to duplicate detection."""
        from unittest.mock import AsyncMock
        mock_session = MagicMock()
        mock_store = MagicMock()
        service = CanonicalPersistenceService(mock_session, mock_store)

        result = PersistenceResult()

        # Mock duplicate service with AsyncMock
        mock_dup_service = MagicMock()
        mock_dup_result = MagicMock()
        mock_dup_result.has_duplicates = False
        mock_dup_result.to_dict.return_value = {"has_duplicates": False}
        mock_dup_service.check_and_record_duplicates = AsyncMock(return_value=mock_dup_result)
        service._duplicate_service = mock_dup_service

        # Create parsed header with pixel_digest
        mock_parsed_header = MagicMock()
        mock_parsed_header.required_tags = {"SOPInstanceUID": "1.2.3"}
        mock_parsed_header.pixel_digest = "sha256:pixelhash123"

        # Create mock item
        mock_item = MagicMock()
        mock_item.id = 1
        mock_item.raw_object_sha256 = "sha256:filehash456"

        # Execute duplicate detection
        import asyncio
        asyncio.run(service._execute_duplicate_detection(
            result=result,
            instance_id=10,
            observation_id=20,
            item=mock_item,
            parsed_header=mock_parsed_header,
        ))

        # Verify pixel_digest was passed
        call_args = mock_dup_service.check_and_record_duplicates.call_args
        assert call_args[0][0].pixel_digest == "sha256:pixelhash123"

    def test_pixel_digest_none_when_not_available(self):
        """pixel_digest should be None when not available in parsed header."""
        from unittest.mock import AsyncMock
        mock_session = MagicMock()
        mock_store = MagicMock()
        service = CanonicalPersistenceService(mock_session, mock_store)

        result = PersistenceResult()

        # Mock duplicate service with AsyncMock
        mock_dup_service = MagicMock()
        mock_dup_result = MagicMock()
        mock_dup_result.has_duplicates = False
        mock_dup_result.to_dict.return_value = {"has_duplicates": False}
        mock_dup_service.check_and_record_duplicates = AsyncMock(return_value=mock_dup_result)
        service._duplicate_service = mock_dup_service

        # Create parsed header without pixel_digest (None by default)
        mock_parsed_header = MagicMock()
        mock_parsed_header.required_tags = {"SOPInstanceUID": "1.2.3"}
        mock_parsed_header.pixel_digest = None

        # Create mock item
        mock_item = MagicMock()
        mock_item.id = 1
        mock_item.raw_object_sha256 = "sha256:filehash456"

        # Execute duplicate detection
        import asyncio
        asyncio.run(service._execute_duplicate_detection(
            result=result,
            instance_id=10,
            observation_id=20,
            item=mock_item,
            parsed_header=mock_parsed_header,
        ))

        # Verify pixel_digest is None
        call_args = mock_dup_service.check_and_record_duplicates.call_args
        assert call_args[0][0].pixel_digest is None
