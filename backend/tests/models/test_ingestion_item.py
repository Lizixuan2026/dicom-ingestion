"""
Tests for IngestionItem and ItemStatusAxes.

Acceptance criteria:
- Item has all seven axes as stored columns (not computed)
- Item terminal_outcome is null until one of: accepted, quarantined, rejected, failed
- last_retryable_stage is set before terminal_outcome=failed
"""
import pytest
from datetime import datetime

from dicom_ingestion.models import (
    IngestionItem,
    ItemStatusAxes,
    ItemStatusValue,
    TerminalOutcome
)


class TestItemStatusAxes:
    """Tests for ItemStatusAxes (seven status axes)."""

    def test_default_axes_are_pending(self):
        """All axes should default to PENDING."""
        axes = ItemStatusAxes()
        assert axes.scan_status == ItemStatusValue.PENDING.value
        assert axes.parse_status == ItemStatusValue.PENDING.value
        assert axes.storage_status == ItemStatusValue.PENDING.value
        assert axes.metadata_persistence_status == ItemStatusValue.PENDING.value
        assert axes.validation_status == ItemStatusValue.PENDING.value
        assert axes.binding_status == ItemStatusValue.PENDING.value
        assert axes.index_status == ItemStatusValue.PENDING.value

    def test_all_completed_true_when_complete(self):
        """all_completed should be True when all axes complete."""
        axes = ItemStatusAxes(
            scan_status=ItemStatusValue.COMPLETED.value,
            parse_status=ItemStatusValue.COMPLETED.value,
            storage_status=ItemStatusValue.COMPLETED.value,
            metadata_persistence_status=ItemStatusValue.COMPLETED.value,
            validation_status=ItemStatusValue.COMPLETED.value,
            binding_status=ItemStatusValue.COMPLETED.value,
            index_status=ItemStatusValue.COMPLETED.value,
        )
        assert axes.all_completed() is True

    def test_all_completed_false_when_pending(self):
        """all_completed should be False when any axis pending."""
        axes = ItemStatusAxes(
            scan_status=ItemStatusValue.COMPLETED.value,
            parse_status=ItemStatusValue.PENDING.value,  # Not complete
        )
        assert axes.all_completed() is False

    def test_any_failed_true_when_failed(self):
        """any_failed should be True when any axis failed."""
        axes = ItemStatusAxes(
            scan_status=ItemStatusValue.COMPLETED.value,
            parse_status=ItemStatusValue.FAILED.value,
        )
        assert axes.any_failed() is True

    def test_to_dict_roundtrip(self):
        """to_dict/from_dict should preserve values."""
        axes = ItemStatusAxes(
            scan_status=ItemStatusValue.COMPLETED.value,
            parse_status=ItemStatusValue.FAILED.value,
        )
        data = axes.to_dict()
        restored = ItemStatusAxes.from_dict(data)

        assert restored.scan_status == axes.scan_status
        assert restored.parse_status == axes.parse_status


class TestIngestionItemCreation:
    """Tests for creating IngestionItem instances."""

    def test_item_has_required_fields(self):
        """Item should have all required fields."""
        item = IngestionItem(
            id=1,
            ingestion_job_id=100,
            source_path="study/series/image.dcm",
            byte_size=12345,
            item_fingerprint="abc123"
        )
        assert item.id == 1
        assert item.ingestion_job_id == 100
        assert item.source_path == "study/series/image.dcm"
        assert item.byte_size == 12345
        assert item.item_fingerprint == "abc123"

    def test_item_has_seven_axes(self):
        """Item should have seven status axes."""
        item = IngestionItem()
        axes = item.status_axes

        # Verify all seven axes exist
        assert hasattr(axes, 'scan_status')
        assert hasattr(axes, 'parse_status')
        assert hasattr(axes, 'storage_status')
        assert hasattr(axes, 'metadata_persistence_status')
        assert hasattr(axes, 'validation_status')
        assert hasattr(axes, 'binding_status')
        assert hasattr(axes, 'index_status')

    def test_terminal_outcome_default_none(self):
        """terminal_outcome should default to NONE."""
        item = IngestionItem()
        assert item.terminal_outcome == TerminalOutcome.NONE.value

    def test_item_has_timestamps(self):
        """Item should have created_at and updated_at."""
        before = datetime.utcnow()
        item = IngestionItem()
        after = datetime.utcnow()

        assert before <= item.created_at <= after
        assert before <= item.updated_at <= after


class TestIngestionItemStatusUpdates:
    """Tests for status axis updates."""

    def test_update_status_changes_axis(self):
        """update_status should change specific axis."""
        item = IngestionItem()
        item.update_status("scan_status", ItemStatusValue.COMPLETED.value)

        assert item.status_axes.scan_status == ItemStatusValue.COMPLETED.value

    def test_update_status_updates_timestamp(self):
        """update_status should update updated_at timestamp."""
        item = IngestionItem()
        before = item.updated_at

        import time
        time.sleep(0.01)  # Small delay
        item.update_status("parse_status", ItemStatusValue.COMPLETED.value)

        assert item.updated_at > before

    def test_update_invalid_axis_raises(self):
        """update_status with invalid axis should raise."""
        item = IngestionItem()
        with pytest.raises(ValueError, match="Invalid status axis"):
            item.update_status("invalid_axis", "value")


class TestIngestionItemStateTracking:
    """Tests for item state tracking methods."""

    def test_default_item_is_not_dicom(self):
        """Newly created items should not be considered DICOM before scan completes."""
        item = IngestionItem()

        assert item.is_dicom is False

    def test_mark_seen(self):
        """mark_seen should set scan_status to SEEN."""
        item = IngestionItem()
        item.mark_seen()
        assert item.status_axes.scan_status == ItemStatusValue.SEEN.value

    def test_mark_scanned_accepted(self):
        """mark_scanned for DICOM should complete scan."""
        item = IngestionItem()
        item.mark_scanned(is_dicom=True)

        assert item.status_axes.scan_status == ItemStatusValue.COMPLETED.value
        assert item.is_dicom is True

    def test_mark_scanned_rejected(self):
        """mark_scanned for non-DICOM should reject and not be considered DICOM."""
        item = IngestionItem()
        item.mark_scanned(is_dicom=False, error_reason="Not a DICOM file")

        assert item.status_axes.scan_status == ItemStatusValue.REJECTED.value
        assert item.terminal_outcome == TerminalOutcome.REJECTED.value
        assert item.error_code == "Not a DICOM file"
        assert item.is_dicom is False

    def test_mark_scanned_rejected_uses_default_not_dicom_error_code(self):
        """mark_scanned for non-DICOM without reason should use default reject code."""
        item = IngestionItem()
        item.mark_scanned(is_dicom=False)

        assert item.status_axes.scan_status == ItemStatusValue.REJECTED.value
        assert item.terminal_outcome == TerminalOutcome.REJECTED.value
        assert item.error_code == IngestionItem.ERROR_NOT_DICOM

    def test_mark_parsed_success(self):
        """mark_parsed success should complete parse_status."""
        item = IngestionItem()
        item.mark_parsed(success=True)

        assert item.status_axes.parse_status == ItemStatusValue.COMPLETED.value

    def test_mark_parsed_failure(self):
        """mark_parsed failure should set error and retry stage."""
        item = IngestionItem()
        item.mark_parsed(
            success=False,
            error_code="ParseError",
            error_detail="Invalid DICOM header"
        )

        assert item.status_axes.parse_status == ItemStatusValue.FAILED.value
        assert item.error_code == "ParseError"
        assert item.error_detail == "Invalid DICOM header"
        assert item.last_retryable_stage == "parse"

    def test_mark_stored(self):
        """mark_stored should complete storage and set URI."""
        item = IngestionItem()
        item.mark_stored(
            uri="/storage/abc123",
            sha256="def456"
        )

        assert item.status_axes.storage_status == ItemStatusValue.COMPLETED.value
        assert item.storage_uri == "/storage/abc123"
        assert item.raw_object_sha256 == "def456"

    def test_mark_storage_failed(self):
        """mark_storage_failed should set retry stage."""
        item = IngestionItem()
        item.mark_storage_failed("S3ConnectionError")

        assert item.status_axes.storage_status == ItemStatusValue.FAILED.value
        assert item.error_code == "S3ConnectionError"
        assert item.last_retryable_stage == "storage"

    def test_mark_metadata_persisted(self):
        """mark_metadata_persisted should complete metadata persistence."""
        item = IngestionItem()
        item.mark_metadata_persisted()

        assert item.status_axes.metadata_persistence_status == ItemStatusValue.COMPLETED.value

    def test_mark_metadata_failed(self):
        """mark_metadata_failed should set retry stage."""
        item = IngestionItem()
        item.mark_metadata_failed("DBConnectionError")

        assert item.status_axes.metadata_persistence_status == ItemStatusValue.FAILED.value
        assert item.last_retryable_stage == "metadata_persistence"

    def test_mark_validated(self):
        """mark_validated should complete validation."""
        item = IngestionItem()
        item.mark_validated()

        assert item.status_axes.validation_status == ItemStatusValue.COMPLETED.value

    def test_mark_bound(self):
        """mark_bound should complete binding."""
        item = IngestionItem()
        item.mark_bound()

        assert item.status_axes.binding_status == ItemStatusValue.COMPLETED.value

    def test_mark_indexed(self):
        """mark_indexed should complete indexing."""
        item = IngestionItem()
        item.mark_indexed()

        assert item.status_axes.index_status == ItemStatusValue.COMPLETED.value


class TestIngestionItemTerminalOutcome:
    """Tests for terminal outcome handling."""

    def test_terminal_outcome_starts_null(self):
        """terminal_outcome should start as NONE (empty)."""
        item = IngestionItem()
        assert item.terminal_outcome == TerminalOutcome.NONE.value
        assert item.is_terminal is False

    def test_set_terminal_outcome_accepted(self):
        """set_terminal_outcome to ACCEPTED."""
        item = IngestionItem()
        item.set_terminal_outcome(TerminalOutcome.ACCEPTED)

        assert item.terminal_outcome == TerminalOutcome.ACCEPTED.value
        assert item.is_terminal is True

    def test_set_terminal_outcome_rejected(self):
        """set_terminal_outcome to REJECTED with error."""
        item = IngestionItem()
        item.set_terminal_outcome(
            TerminalOutcome.REJECTED,
            error_code="NotDicom",
            error_detail="File is not a valid DICOM"
        )

        assert item.terminal_outcome == TerminalOutcome.REJECTED.value
        assert item.error_code == "NotDicom"
        assert item.error_detail == "File is not a valid DICOM"

    def test_cannot_change_terminal_outcome(self):
        """Cannot change terminal outcome once set."""
        item = IngestionItem()
        item.set_terminal_outcome(TerminalOutcome.ACCEPTED)

        with pytest.raises(ValueError, match="Cannot change terminal outcome"):
            item.set_terminal_outcome(TerminalOutcome.REJECTED)

    def test_same_outcome_is_idempotent(self):
        """Setting same outcome again is allowed."""
        item = IngestionItem()
        item.set_terminal_outcome(TerminalOutcome.ACCEPTED)
        item.set_terminal_outcome(TerminalOutcome.ACCEPTED)  # Should not raise

        assert item.terminal_outcome == TerminalOutcome.ACCEPTED.value

    def test_can_retry_with_last_retryable_stage(self):
        """can_retry should be True when last_retryable_stage is set."""
        item = IngestionItem()
        item.last_retryable_stage = "parse"
        item.terminal_outcome = TerminalOutcome.FAILED.value

        assert item.can_retry is True

    def test_cannot_retry_when_not_failed(self):
        """can_retry should be False when not in failed state."""
        item = IngestionItem()
        item.last_retryable_stage = "parse"
        # terminal_outcome is NONE

        assert item.can_retry is False


class TestIngestionItemSerialization:
    """Tests for item serialization."""

    def test_to_dict_contains_required_fields(self):
        """to_dict should contain all required fields."""
        item = IngestionItem(
            id=1,
            source_path="test.dcm",
            byte_size=100,
        )
        data = item.to_dict()

        assert "id" in data
        assert "source_path" in data
        assert "byte_size" in data
        assert "status_axes" in data
        assert "terminal_outcome" in data

    def test_to_dict_timestamps_are_strings(self):
        """to_dict should convert timestamps to ISO format strings."""
        item = IngestionItem()
        data = item.to_dict()

        assert isinstance(data["created_at"], str)
        assert isinstance(data["updated_at"], str)


class TestIngestionItemSevenAxesStorage:
    """Tests to verify seven axes are stored, not computed."""

    def test_axes_are_stored_columns(self):
        """All seven axes should be stored as columns in ItemStatusAxes."""
        item = IngestionItem()
        axes = item.status_axes

        # Verify each axis can be independently set and retrieved
        axes.scan_status = "custom1"
        axes.parse_status = "custom2"
        axes.storage_status = "custom3"
        axes.metadata_persistence_status = "custom4"
        axes.validation_status = "custom5"
        axes.binding_status = "custom6"
        axes.index_status = "custom7"

        assert axes.scan_status == "custom1"
        assert axes.parse_status == "custom2"
        assert axes.storage_status == "custom3"
        assert axes.metadata_persistence_status == "custom4"
        assert axes.validation_status == "custom5"
        assert axes.binding_status == "custom6"
        assert axes.index_status == "custom7"

    def test_axes_persist_in_item(self):
        """Axes values should persist in the item."""
        item = IngestionItem()
        item.update_status("scan_status", ItemStatusValue.COMPLETED.value)
        item.update_status("parse_status", ItemStatusValue.FAILED.value)

        # Verify values are stored
        assert item.status_axes.scan_status == ItemStatusValue.COMPLETED.value
        assert item.status_axes.parse_status == ItemStatusValue.FAILED.value


class TestIngestionItemRetrySemantics:
    """Tests for retry semantics."""

    def test_retryable_stage_set_on_parse_failure(self):
        """last_retryable_stage should be set on parse failure."""
        item = IngestionItem()
        item.mark_parsed(success=False, error_code="ParseError")

        assert item.last_retryable_stage == "parse"

    def test_retryable_stage_set_on_storage_failure(self):
        """last_retryable_stage should be set on storage failure."""
        item = IngestionItem()
        item.mark_storage_failed("S3Error")

        assert item.last_retryable_stage == "storage"

    def test_retryable_stage_set_on_metadata_failure(self):
        """last_retryable_stage should be set on metadata failure."""
        item = IngestionItem()
        item.mark_metadata_failed("DBError")

        assert item.last_retryable_stage == "metadata_persistence"

    def test_no_retry_when_not_failed(self):
        """Cannot retry when not in failed state."""
        item = IngestionItem()
        item.mark_parsed(success=True)

        assert item.can_retry is False

    def test_no_retry_after_terminal_outcome(self):
        """Cannot retry after terminal outcome set."""
        item = IngestionItem()
        item.mark_parsed(success=False, error_code="ParseError")
        item.set_terminal_outcome(TerminalOutcome.REJECTED)

        assert item.can_retry is False
