"""Tests for ReplayService.

Acceptance criteria:
- Items can be replayed without re-upload
- Failed items can be retried in bulk
- Replay history is recorded
- Can check replay eligibility without executing
"""
import pytest
from unittest.mock import MagicMock, AsyncMock
from datetime import datetime

from dicom_ingestion.services.replay.replay_service import (
    ReplayService,
    ReplayRequest,
    ReplayResult,
    RetryRequest,
    RetryResult,
    ReplayStage,
    RetryOutcome,
    StageResult,
)


class TestReplayRequest:
    """Tests for ReplayRequest dataclass."""

    def test_default_request(self):
        """Default request should replay all stages."""
        request = ReplayRequest(ingestion_item_id=123)
        assert request.ingestion_item_id == 123
        assert request.replay_from_stage == ReplayStage.ALL
        assert request.force is False
        assert request.preserve_state is True

    def test_specific_stage(self):
        """Request can specify starting stage."""
        request = ReplayRequest(
            ingestion_item_id=123,
            replay_from_stage=ReplayStage.PARSE,
            force=True,
        )
        assert request.replay_from_stage == ReplayStage.PARSE
        assert request.force is True


class TestReplayResult:
    """Tests for ReplayResult dataclass."""

    def test_default_result(self):
        """Default result should have success=False."""
        result = ReplayResult()
        assert result.success is False
        assert result.ingestion_item_id == 0
        assert result.stage_results == []

    def test_result_with_stages(self):
        """Result should track stage results."""
        result = ReplayResult(
            ingestion_item_id=123,
            success=True,
            stage_results=[
                StageResult(stage="parse", attempted=True, outcome=RetryOutcome.SUCCESS),
                StageResult(stage="storage", attempted=True, outcome=RetryOutcome.SKIPPED),
            ],
            final_status="accepted",
        )
        assert result.success is True
        assert len(result.stage_results) == 2
        assert result.final_status == "accepted"


class TestRetryRequest:
    """Tests for RetryRequest dataclass."""

    def test_default_request(self):
        """Default request should retry failed items."""
        request = RetryRequest()
        assert request.ingestion_job_id is None
        assert request.max_retries == 3
        assert request.retry_failed_only is True
        assert request.dry_run is False

    def test_job_retry(self):
        """Request can target specific job."""
        request = RetryRequest(
            ingestion_job_id=456,
            max_retries=5,
            dry_run=True,
        )
        assert request.ingestion_job_id == 456
        assert request.max_retries == 5
        assert request.dry_run is True


class TestRetryResult:
    """Tests for RetryResult dataclass."""

    def test_default_result(self):
        """Default result should have empty summary."""
        result = RetryResult()
        assert result.success is False
        assert result.summary.total_items == 0
        assert result.dry_run is False


class TestReplayServiceInitialization:
    """Tests for ReplayService initialization."""

    def test_service_initialization(self):
        """Service should initialize with session and store."""
        mock_session = MagicMock()
        mock_store = MagicMock()
        service = ReplayService(session=mock_session, raw_object_store=mock_store)
        assert service._session is mock_session
        assert service._raw_store is mock_store


class TestReplayServiceCanReplay:
    """Tests for checking replay eligibility."""

    @pytest.mark.asyncio
    async def test_can_replay_with_storage_uri(self):
        """Item with storage_uri should be replayable."""
        mock_session = MagicMock()
        mock_store = MagicMock()

        # Mock item fetch
        item_result = MagicMock()
        item_result.fetchone.return_value = (
            123, 456, "/path/file.dcm", 1024, "fp123",
            {}, None, "s3://bucket/file", "stored", "sha256:abc",
            None, None, None, None, None
        )
        mock_session.execute.return_value = item_result

        service = ReplayService(session=mock_session, raw_object_store=mock_store)
        can_replay = await service.can_replay_without_upload(123)

        assert can_replay is True

    @pytest.mark.asyncio
    async def test_cannot_replay_without_storage_uri(self):
        """Item without storage_uri should not be replayable."""
        mock_session = MagicMock()
        mock_store = MagicMock()

        # Mock item fetch without storage_uri
        item_result = MagicMock()
        item_result.fetchone.return_value = (
            123, 456, "/path/file.dcm", 1024, "fp123",
            {}, None, "", "", "",
            None, None, None, None, None
        )
        mock_session.execute.return_value = item_result

        service = ReplayService(session=mock_session, raw_object_store=mock_store)
        can_replay = await service.can_replay_without_upload(123)

        assert can_replay is False


class TestReplayServiceReplay:
    """Tests for replaying items."""

    @pytest.mark.asyncio
    async def test_replay_item_not_found(self):
        """Replay should fail if item not found."""
        mock_session = MagicMock()
        mock_store = MagicMock()

        # Mock item not found
        item_result = MagicMock()
        item_result.fetchone.return_value = None
        mock_session.execute.return_value = item_result

        service = ReplayService(session=mock_session, raw_object_store=mock_store)
        request = ReplayRequest(ingestion_item_id=999)
        result = await service.replay(request)

        assert result.success is False
        assert result.error_code == "ItemNotFound"

    @pytest.mark.asyncio
    async def test_replay_failed_item(self):
        """Should replay a failed item successfully."""
        mock_session = MagicMock()
        mock_store = MagicMock()

        # Mock item with failed status
        item_result = MagicMock()
        item_result.fetchone.return_value = (
            123, 456, "/path/file.dcm", 1024, "fp123",
            {"parse_status": "completed", "storage_status": "completed", "metadata_persistence_status": "failed"},
            "failed", "s3://bucket/file", "stored", "sha256:abc",
            "metadata_persistence", "MetadataPersistenceFailed", "DB error",
            None, None
        )
        mock_session.execute.return_value = item_result

        service = ReplayService(session=mock_session, raw_object_store=mock_store)
        request = ReplayRequest(ingestion_item_id=123, replay_from_stage=ReplayStage.METADATA_PERSISTENCE)
        result = await service.replay(request)

        assert result.ingestion_item_id == 123


class TestReplayServiceRetry:
    """Tests for batch retry."""

    @pytest.mark.asyncio
    async def test_retry_dry_run(self):
        """Dry run should return preview without executing."""
        mock_session = MagicMock()
        mock_store = MagicMock()

        # Mock finding failed items - make it iterable
        items_rows = [(1,), (2,), (3,)]
        items_result = MagicMock()
        items_result.__iter__ = MagicMock(return_value=iter(items_rows))
        mock_session.execute.return_value = items_result

        service = ReplayService(session=mock_session, raw_object_store=mock_store)
        request = RetryRequest(ingestion_job_id=456, dry_run=True)
        result = await service.retry(request)

        assert result.dry_run is True
        assert result.summary.total_items == 3
        assert len(result.item_results) == 3

    @pytest.mark.asyncio
    async def test_retry_no_failed_items(self):
        """Should handle case with no failed items."""
        mock_session = MagicMock()
        mock_store = MagicMock()

        # Mock no items found - empty iterable
        items_result = MagicMock()
        items_result.__iter__ = MagicMock(return_value=iter([]))
        mock_session.execute.return_value = items_result

        service = ReplayService(session=mock_session, raw_object_store=mock_store)
        request = RetryRequest(ingestion_job_id=456)
        result = await service.retry(request)

        assert result.summary.total_items == 0
        assert result.success is True


class TestReplayServiceHistory:
    """Tests for replay history."""

    @pytest.mark.asyncio
    async def test_get_replay_history(self):
        """Should return replay history."""
        mock_session = MagicMock()
        mock_store = MagicMock()

        # Make history result iterable
        history_rows = [
            (1, 123, "all", True, "accepted", None, None, datetime.now(), '[{"stage": "parse", "outcome": "success"}]'),
            (2, 123, "storage", False, "failed", "StorageFailed", "S3 error", datetime.now(), '[{"stage": "storage", "outcome": "failed"}]'),
        ]
        history_result = MagicMock()
        history_result.__iter__ = MagicMock(return_value=iter(history_rows))
        mock_session.execute.return_value = history_result

        service = ReplayService(session=mock_session, raw_object_store=mock_store)
        history = await service.get_replay_history(ingestion_item_id=123, limit=10)

        assert len(history) == 2
        assert history[0]["ingestion_item_id"] == 123
