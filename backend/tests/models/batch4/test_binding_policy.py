"""
Tests for DicomBindingPolicy model (C4).

Acceptance criteria:
- Binding status tracks independently from ingest
- Successful binding records target info
- Failed binding preserves error info
- Retry count tracked
"""
import pytest
from datetime import datetime

from dicom_ingestion.models.binding_policy import (
    DicomBindingPolicy,
    BindingContext,
    BindingResult,
    BindingStatus,
    BindingTargetType,
    BindingPolicySummary,
)


class TestDicomBindingPolicy:
    """Tests for DicomBindingPolicy model."""

    def test_default_status_is_pending(self):
        """Default binding status should be pending."""
        policy = DicomBindingPolicy()

        assert policy.binding_status == BindingStatus.PENDING.value
        assert policy.retry_count == 0

    def test_mark_bound(self):
        """mark_bound should update status and record target."""
        policy = DicomBindingPolicy()
        policy.mark_bound(
            target_type=BindingTargetType.ASSET.value,
            target_id="asset-123",
            target_uri="/assets/123",
            metadata={"project_id": "proj-1"},
        )

        assert policy.is_bound is True
        assert policy.target_type == BindingTargetType.ASSET.value
        assert policy.target_id == "asset-123"
        assert policy.bound_at is not None
        assert policy.binding_metadata["project_id"] == "proj-1"

    def test_mark_failed(self):
        """mark_failed should record error info."""
        policy = DicomBindingPolicy()
        policy.mark_failed("PlatformAPIError", "Asset creation failed")

        assert policy.binding_status == BindingStatus.FAILED.value
        assert policy.error_code == "PlatformAPIError"
        assert policy.error_detail == "Asset creation failed"

    def test_can_retry(self):
        """can_retry should be true for failed/retryable states."""
        policy = DicomBindingPolicy(binding_status=BindingStatus.FAILED.value)
        assert policy.can_retry is True

        policy.retry_count = 5  # Max retries reached
        assert policy.can_retry is False

    def test_increment_retry(self):
        """increment_retry should increase count."""
        policy = DicomBindingPolicy()
        policy.increment_retry()
        policy.increment_retry()

        assert policy.retry_count == 2


class TestBindingContext:
    """Tests for BindingContext."""

    def test_to_dict(self):
        """to_dict should include context info."""
        ctx = BindingContext(
            project_id="proj-1",
            dataset_id="ds-1",
            user_id="user-1",
            binding_preferences={"auto_annotate": True},
        )

        data = ctx.to_dict()

        assert data["project_id"] == "proj-1"
        assert data["dataset_id"] == "ds-1"
        assert data["binding_preferences"]["auto_annotate"] is True


class TestBindingResult:
    """Tests for BindingResult."""

    def test_success_result(self):
        """Successful result should have target info."""
        result = BindingResult(
            success=True,
            binding_id=1,
            target_type=BindingTargetType.ASSET.value,
            target_id="asset-123",
        )

        data = result.to_dict()

        assert data["success"] is True
        assert data["target_type"] == BindingTargetType.ASSET.value

    def test_failure_result(self):
        """Failed result should have error info."""
        result = BindingResult(
            success=False,
            error_code="APIError",
            error_detail="Connection timeout",
        )

        data = result.to_dict()

        assert data["success"] is False
        assert data["error_code"] == "APIError"


class TestBindingPolicySummary:
    """Tests for BindingPolicySummary."""

    def test_to_dict(self):
        """to_dict should include all counts."""
        summary = BindingPolicySummary(
            total_instances=10,
            bound_count=7,
            failed_count=2,
            pending_count=1,
            by_target_type={"asset": 7},
        )

        data = summary.to_dict()

        assert data["total_instances"] == 10
        assert data["bound_count"] == 7
        assert data["by_target_type"]["asset"] == 7
