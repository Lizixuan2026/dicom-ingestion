"""Integration tests for Batch 5 (Query + Replay).

Acceptance criteria:
- C5: Projections rebuild from source-of-truth events/state
- C6: Retry/replay does not require end-user re-upload
- D1: Query interfaces expose ingest/review semantics coherently
- D3: Reindex/rebuild workflow is executable via documented operator steps

This test suite validates the Batch 5 implementation.
"""
import pytest
from unittest.mock import MagicMock, AsyncMock
from datetime import datetime

from dicom_ingestion.services.projection import (
    ProjectionService,
    ProjectionBuildResult,
    ProjectionRebuildRequest,
)
from dicom_ingestion.services.replay import (
    ReplayService,
    ReplayRequest,
    RetryRequest,
    ReplayStage,
)
from dicom_ingestion.services.queries import (
    ReviewQueryService,
    ReviewStatus,
)
from dicom_ingestion.services.reindex import (
    ReindexWorkflow,
    ReindexJob,
    ReindexStatus,
)


class TestC5ProjectionFoundation:
    """Tests for C5: Projection Foundation.

    Acceptance criteria:
    - Projections can be built from source-of-truth
    - Projections can be rebuilt from canonical data
    - Projection queries expose semantic facts
    """

    @pytest.mark.asyncio
    async def test_projection_builds_from_canonical_source(self):
        """C5: Projections rebuild from source-of-truth events/state."""
        mock_session = MagicMock()

        # Setup mock canonical data
        fetch_result = MagicMock()
        fetch_result.fetchone.return_value = (
            1, "1.2.3", "1.2.840.10008.5.1.4.1.1.2", 100,
            10, "1.2.4", "CT", "CT",
            100, "1.2.5", datetime(2024, 1, 1),
            "P123", "Test Patient",
            1000, "sha256:abc", None, None, True,
            "proj-123", "user-456", "bound"
        )

        # Mock empty existing projection
        existing_result = MagicMock()
        existing_result.fetchone.return_value = None

        def mock_execute(sql, params):
            if "FROM dicom_instances i" in sql:
                return fetch_result
            return existing_result

        mock_session.execute.side_effect = mock_execute

        service = ProjectionService(session=mock_session)
        result = await service.build_projection(instance_id=1)

        assert result.success is True
        assert result.instance_id == 1
        assert result.source_checksum != ""

    @pytest.mark.asyncio
    async def test_projection_query_exposes_semantic_facts(self):
        """C5: Projection queries expose semantic facts from Batch 4."""
        mock_session = MagicMock()

        count_result = MagicMock()
        count_result.scalar.return_value = 1

        query_result = MagicMock()
        query_result.fetchall.return_value = [
            (1, "1.2.3", "1.2.4", "1.2.5", "CT", datetime(2024, 1, 1), "CT", "bound",
             {"has_duplicates": False}, "resolved", "1.0.0", "1.0.0", datetime.now(), "sha256:abc"),
        ]

        def mock_execute(sql, params):
            if "COUNT(*)" in sql:
                return count_result
            return query_result

        mock_session.execute.side_effect = mock_execute

        service = ProjectionService(session=mock_session)
        result = await service.query_projections(modality="CT")

        assert result.total_count == 1
        assert len(result.items) == 1
        # Check that duplicate_flags (from Batch 4 C1) are exposed
        assert "duplicate_flags" in result.items[0]
        # Check that binding_status (from Batch 4 C4) is exposed
        assert result.items[0]["binding_status"] == "bound"

    @pytest.mark.asyncio
    async def test_projection_stats_show_coverage(self):
        """C5: Projection stats show coverage of canonical data."""
        mock_session = MagicMock()

        version_result = MagicMock()
        version_result.fetchall.return_value = [("1.0.0", 100)]

        missing_result = MagicMock()
        missing_result.scalar.return_value = 0

        total_result = MagicMock()
        total_result.scalar.return_value = 100

        def mock_execute(sql, params=None):
            if "GROUP BY projection_version" in sql:
                return version_result
            elif "p.instance_id IS NULL" in sql:
                return missing_result
            elif "WHERE current_canonical_observation_id IS NOT NULL" in sql:
                return total_result
            return MagicMock()

        mock_session.execute.side_effect = mock_execute

        service = ProjectionService(session=mock_session)
        stats = await service.get_projection_stats()

        assert stats["total_projections"] == 100
        assert stats["instances_without_projections"] == 0
        assert stats["coverage_percentage"] == 100.0


class TestC6RetryReplayFoundation:
    """Tests for C6: Retry/Replay Foundation.

    Acceptance criteria:
    - Retry/replay does not require end-user re-upload
    - Raw bytes are read from storage
    - Replay history is recorded
    """

    @pytest.mark.asyncio
    async def test_replay_uses_storage_not_upload(self):
        """C6: Replay reads raw bytes from storage, not re-upload."""
        mock_session = MagicMock()
        mock_store = MagicMock()

        # Item with storage URI
        item_result = MagicMock()
        item_result.fetchone.return_value = (
            123, 456, "/path/file.dcm", 1024, "fp123",
            {"scan_status": "completed", "storage_status": "completed"},
            "failed", "s3://bucket/file", "stored", "sha256:abc",
            "metadata_persistence", "MetadataPersistenceFailed", "DB error",
            None, None
        )
        mock_session.execute.return_value = item_result

        service = ReplayService(session=mock_session, raw_object_store=mock_store)
        can_replay = await service.can_replay_without_upload(123)

        # Should be replayable because it has storage_uri
        assert can_replay is True

    @pytest.mark.asyncio
    async def test_replay_history_recorded(self):
        """C6: Replay operations are recorded in history."""
        mock_session = MagicMock()
        mock_store = MagicMock()

        # Mock replay history query
        history_result = MagicMock()
        history_result.fetchall.return_value = [
            (1, 123, "all", True, "accepted", None, None, datetime.now(), '[]'),
        ]
        mock_session.execute.return_value = history_result

        service = ReplayService(session=mock_session, raw_object_store=mock_store)
        history = await service.get_replay_history(ingestion_item_id=123)

        assert len(history) == 1
        assert history[0]["ingestion_item_id"] == 123
        assert history[0]["success"] is True

    @pytest.mark.asyncio
    async def test_bulk_retry_without_reupload(self):
        """C6: Bulk retry operates without requiring re-upload."""
        mock_session = MagicMock()
        mock_store = MagicMock()

        # Mock finding failed items with storage URIs
        items_result = MagicMock()
        items_result.fetchall.return_value = [(1,), (2,), (3,)]
        mock_session.execute.return_value = items_result

        service = ReplayService(session=mock_session, raw_object_store=mock_store)
        request = RetryRequest(ingestion_job_id=456, dry_run=True)
        result = await service.retry(request)

        # All items should be retriable (have storage URIs)
        assert result.summary.total_items == 3


class TestD1ReviewQueries:
    """Tests for D1: Review Queries.

    Acceptance criteria:
    - Query interfaces expose ingest/review semantics coherently
    - Batch 4 semantic facts are included in review views
    """

    @pytest.mark.asyncio
    async def test_review_query_includes_batch4_facts(self):
        """D1: Review views include Batch 4 semantic facts."""
        mock_session = MagicMock()

        # Mock item query
        item_result = MagicMock()
        item_result.fetchone.return_value = (
            1, 2, "/test.dcm", 1024, "fp123",
            {"scan_status": "completed", "parse_status": "completed"},
            None, None, None,
            datetime.now(), datetime.now(), None
        )

        # Mock Batch 4 facts queries
        obs_result = MagicMock()
        obs_result.fetchone.return_value = (100, 50)

        dup_result = MagicMock()
        dup_result.fetchone.return_value = ("content_hash", "certain")

        count_result = MagicMock()
        count_result.scalar.return_value = 5

        def mock_execute(sql, params=None):
            if "FROM dicom_ingestion_items i" in sql:
                return item_result
            elif "FROM dicom_instance_observations" in sql:
                return obs_result
            elif "FROM dicom_duplicate_findings" in sql:
                return dup_result
            return count_result

        mock_session.execute.side_effect = mock_execute

        service = ReviewQueryService(session=mock_session)
        view = await service.get_item_review_view(item_id=1)

        # Check Batch 4 C1: duplicate detection
        assert view.duplicate_status != "unknown"

        # Check Batch 4 C2: private tags
        assert view.private_tags_persisted is True

        # Check Batch 4 C3: reference edges
        assert view.references_extracted == 5

        # Check Batch 4 C4: binding status
        assert view.binding_status == "bound"

    @pytest.mark.asyncio
    async def test_review_status_computed_coherently(self):
        """D1: Review status is computed consistently from state."""
        mock_session = MagicMock()

        # Item with terminal outcome
        item_result = MagicMock()
        item_result.fetchone.return_value = (
            1, 2, "/test.dcm", 1024, "fp123",
            {"scan_status": "completed"},
            "quarantined", None, None,
            datetime.now(), datetime.now(), None
        )

        obs_result = MagicMock()
        obs_result.fetchone.return_value = None

        def mock_execute(sql, params=None):
            if "FROM dicom_ingestion_items" in sql:
                return item_result
            return obs_result

        mock_session.execute.side_effect = mock_execute

        service = ReviewQueryService(session=mock_session)
        view = await service.get_item_review_view(item_id=1)

        # Quarantined items should have quarantined review status
        assert view.review_status == ReviewStatus.QUARANTINED.value

    @pytest.mark.asyncio
    async def test_ingest_review_semantics_exposed(self):
        """D1: Query interfaces expose ingest/review semantics."""
        mock_session = MagicMock()

        # Summary statistics
        job_result = MagicMock()
        job_result.fetchone.return_value = (10, 2, 7, 1, 3)
        mock_session.execute.return_value = job_result

        service = ReviewQueryService(session=mock_session)
        summary = await service.get_ingestion_summary()

        # Should expose ingestion semantics
        assert summary.total_items >= 0
        assert summary.accepted_items >= 0
        assert summary.quarantined_items >= 0
        assert summary.items_pending_review >= 0


class TestD3ReindexWorkflow:
    """Tests for D3: Operational Reindex/Rebuild.

    Acceptance criteria:
    - Reindex/rebuild workflow is executable via documented operator steps
    - Dry-run mode allows preview before execution
    - Jobs can be paused, resumed, and cancelled
    """

    def test_reindex_job_creation(self):
        """D3: Operators can create reindex jobs."""
        mock_session = MagicMock()

        result = MagicMock()
        result.fetchone.return_value = (1, datetime.now())
        mock_session.execute.return_value = result

        workflow = ReindexWorkflow(session=mock_session)

        import asyncio
        job = asyncio.run(workflow.create_job(
            name="Operator Reindex",
            description="Rebuilding projections after schema change",
            created_by="operator@example.com",
            scope="study",
            scope_params={"study_uid": "1.2.3.4"},
        ))

        assert job.id == 1
        assert job.created_by == "operator@example.com"
        assert job.scope == "study"

    @pytest.mark.asyncio
    async def test_dry_run_shows_plan(self):
        """D3: Dry-run mode shows plan without executing."""
        mock_session = MagicMock()

        job_result = MagicMock()
        job_result.fetchone.return_value = (
            1, "Test", "Desc", "admin", "pending",
            "all", "{}", '["validate", "analyze"]', 100, True,  # dry_run=True
            datetime.now(), None, None, 0.0, None
        )

        count_result = MagicMock()
        count_result.scalar.return_value = 1000

        def mock_execute(sql, params=None):
            if "FROM dicom_index_jobs" in sql and "WHERE id" in sql:
                return job_result
            return count_result

        mock_session.execute.side_effect = mock_execute

        workflow = ReindexWorkflow(session=mock_session)
        result = await workflow.execute(job_id=1)

        # Dry run should complete without making changes
        assert "dry_run" in result.status
        # All steps should be skipped in dry run
        for step in result.step_results:
            assert step.status == "skipped"

    @pytest.mark.asyncio
    async def test_workflow_steps_are_documented(self):
        """D3: Workflow executes in documented steps."""
        mock_session = MagicMock()

        job_result = MagicMock()
        job_result.fetchone.return_value = (
            1, "Test", "Desc", "admin", "pending",
            "all", "{}",
            '["validate", "analyze", "backup", "rebuild_projections", "verify", "cleanup"]',
            100, False,
            datetime.now(), None, None, 0.0, None
        )

        count_result = MagicMock()
        count_result.scalar.return_value = 100

        def mock_execute(sql, params=None):
            if "FROM dicom_index_jobs" in sql and "WHERE id" in sql:
                return job_result
            return count_result

        mock_session.execute.side_effect = mock_execute

        workflow = ReindexWorkflow(session=mock_session)
        plan = await workflow.plan(job_id=1)

        # Plan should list all workflow steps
        expected_steps = [
            "validate",
            "analyze",
            "backup",
            "rebuild_projections",
            "verify",
            "cleanup",
        ]
        for step in expected_steps:
            assert step in plan.steps

    def test_job_control_operations(self):
        """D3: Jobs can be paused, resumed, and cancelled."""
        mock_session = MagicMock()
        workflow = ReindexWorkflow(session=mock_session)

        import asyncio

        # Pause
        paused = asyncio.run(workflow.pause(job_id=1))
        assert paused is True

        # Cancel
        cancelled = asyncio.run(workflow.cancel(job_id=1))
        assert cancelled is True


class TestBatch5Integration:
    """Integration tests combining Batch 5 components."""

    @pytest.mark.asyncio
    async def test_end_to_end_reindex_and_query(self):
        """End-to-end: Reindex projections then query results."""
        mock_session = MagicMock()
        mock_projection = MagicMock()

        # Create reindex job
        job_result = MagicMock()
        job_result.fetchone.return_value = (1, datetime.now())

        count_result = MagicMock()
        count_result.scalar.return_value = 10

        def mock_execute(sql, params=None):
            if "RETURNING id" in sql:
                return job_result
            return count_result

        mock_session.execute.side_effect = mock_execute

        # Create workflow
        workflow = ReindexWorkflow(
            session=mock_session,
            projection_service=mock_projection,
        )

        import asyncio
        job = asyncio.run(workflow.create_job(
            name="Batch 5 Integration Test",
            description="Testing C5 and D3 together",
            created_by="test",
        ))

        assert job.id == 1

    @pytest.mark.asyncio
    async def test_replay_then_review(self):
        """Integration: Replay item then review updated state."""
        mock_session = MagicMock()
        mock_store = MagicMock()

        # Item that can be replayed
        item_result = MagicMock()
        item_result.fetchone.return_value = (
            123, 456, "/path/file.dcm", 1024, "fp123",
            {"scan_status": "completed"},
            "failed", "s3://bucket/file", "stored", "sha256:abc",
            "parse", "ParseFailed", "Parse error",
            None, None
        )
        mock_session.execute.return_value = item_result

        # Replay service
        replay_service = ReplayService(session=mock_session, raw_object_store=mock_store)

        # Check can replay
        can_replay = await replay_service.can_replay_without_upload(123)
        assert can_replay is True

        # Review service
        review_service = ReviewQueryService(session=mock_session)
        item_view = await review_service.get_item_review_view(123)

        assert item_view is not None
        assert item_view.item_id == 123
