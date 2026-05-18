"""Tests for ProjectionService.

Acceptance criteria:
- Projections can be built from source-of-truth canonical data
- Projections can be queried with filtering and pagination
- Projections can be rebuilt in bulk
- Projection statistics are available
"""
import pytest
from unittest.mock import MagicMock, AsyncMock
from datetime import datetime

from dicom_ingestion.services.projection.projection_service import (
    ProjectionService,
    ProjectionBuildResult,
    ProjectionQueryResult,
    ProjectionRebuildRequest,
)


class TestProjectionBuildResult:
    """Tests for ProjectionBuildResult dataclass."""

    def test_default_result(self):
        """Default result should have success=False."""
        result = ProjectionBuildResult()
        assert result.success is False
        assert result.instance_id is None

    def test_successful_result(self):
        """Successful result should have success=True."""
        result = ProjectionBuildResult(
            success=True,
            instance_id=123,
            projection_version="1.0.0",
            source_checksum="abc123",
        )
        assert result.success is True
        assert result.instance_id == 123
        assert result.projection_version == "1.0.0"


class TestProjectionQueryResult:
    """Tests for ProjectionQueryResult dataclass."""

    def test_default_result(self):
        """Default result should have empty items list."""
        result = ProjectionQueryResult()
        assert result.items == []
        assert result.total_count == 0
        assert result.has_more is False

    def test_result_with_items(self):
        """Result should store items correctly."""
        result = ProjectionQueryResult(
            items=[{"instance_id": 1}, {"instance_id": 2}],
            total_count=10,
            has_more=True,
        )
        assert len(result.items) == 2
        assert result.total_count == 10
        assert result.has_more is True


class TestProjectionRebuildRequest:
    """Tests for ProjectionRebuildRequest dataclass."""

    def test_default_request(self):
        """Default request should rebuild all."""
        request = ProjectionRebuildRequest()
        assert request.instance_ids is None
        assert request.force is False
        assert request.batch_size == 100

    def test_specific_instances(self):
        """Request can specify instance IDs."""
        request = ProjectionRebuildRequest(
            instance_ids=[1, 2, 3],
            force=True,
            batch_size=50,
        )
        assert request.instance_ids == [1, 2, 3]
        assert request.force is True
        assert request.batch_size == 50


class TestProjectionServiceInitialization:
    """Tests for ProjectionService initialization."""

    def test_service_initialization(self):
        """Service should initialize with session."""
        mock_session = MagicMock()
        service = ProjectionService(session=mock_session)
        assert service._session is mock_session


class TestProjectionServiceBuild:
    """Tests for building projections."""

    @pytest.mark.asyncio
    async def test_build_fails_without_canonical_data(self):
        """Build should fail if no canonical data exists."""
        mock_session = MagicMock()
        mock_result = MagicMock()
        mock_result.fetchone.return_value = None
        mock_session.execute.return_value = mock_result

        service = ProjectionService(session=mock_session)
        result = await service.build_projection(instance_id=999)

        assert result.success is False
        assert result.error_code == "CanonicalDataNotFound"

    @pytest.mark.asyncio
    async def test_build_success_with_mock_data(self):
        """Build should succeed with valid canonical data."""
        mock_session = MagicMock()

        # Mock fetch query for canonical data
        fetch_result = MagicMock()
        fetch_result.fetchone.return_value = (
            1, "1.2.3", "1.2.840.10008.5.1.4.1.1.2", 100,
            10, "1.2.4", "CT", "CT",
            100, "1.2.5", datetime(2024, 1, 1),
            "P123", "Test Patient",
            1000, "sha256:abc", None, None, True,
            "proj-123", "user-456", "bound"
        )

        # Mock _should_rebuild query - return None to indicate rebuild needed
        should_rebuild_result = MagicMock()
        should_rebuild_result.fetchone.return_value = None

        # Mock upsert query
        upsert_result = MagicMock()

        def mock_execute(sql, params):
            if "FROM dicom_instances i" in sql:
                return fetch_result
            elif "FROM dicom_core_projections" in sql and "projection_source_checksum" in sql:
                return should_rebuild_result
            return upsert_result

        mock_session.execute.side_effect = mock_execute

        service = ProjectionService(session=mock_session)
        result = await service.build_projection(instance_id=1)

        assert result.success is True
        assert result.instance_id == 1
        assert result.projection_version == "1.0.0"
        assert result.source_checksum != ""


class TestProjectionServiceQuery:
    """Tests for querying projections."""

    @pytest.mark.asyncio
    async def test_query_with_filters(self):
        """Query should apply filters correctly."""
        mock_session = MagicMock()

        count_result = MagicMock()
        count_result.scalar.return_value = 2

        # Make query result iterable (the service uses iteration, not fetchall)
        query_rows = [
            (1, "1.2.3", "1.2.4", "1.2.5", "CT", datetime(2024, 1, 1), "CT", "bound", None, "pending", "1.0.0", "1.0.0", datetime.now(), "sha256:abc"),
            (2, "1.2.3", "1.2.4b", "1.2.6", "MR", datetime(2024, 1, 2), "MR", "bound", None, "pending", "1.0.0", "1.0.0", datetime.now(), "sha256:def"),
        ]
        query_result = MagicMock()
        query_result.__iter__ = MagicMock(return_value=iter(query_rows))

        def mock_execute(sql, params):
            if "COUNT(*)" in sql:
                return count_result
            return query_result

        mock_session.execute.side_effect = mock_execute

        service = ProjectionService(session=mock_session)
        result = await service.query_projections(
            study_instance_uid="1.2.3",
            modality="CT",
        )

        assert result.total_count == 2
        assert len(result.items) == 2
        assert result.items[0]["modality"] == "CT"


class TestProjectionServiceStats:
    """Tests for projection statistics."""

    @pytest.mark.asyncio
    async def test_get_stats(self):
        """Should return projection statistics."""
        mock_session = MagicMock()

        # Make version result iterable
        version_rows = [("1.0.0", 100), ("0.9.0", 20)]
        version_result = MagicMock()
        version_result.__iter__ = MagicMock(return_value=iter(version_rows))

        missing_result = MagicMock()
        missing_result.scalar.return_value = 5

        total_result = MagicMock()
        total_result.scalar.return_value = 125

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

        assert stats["total_projections"] == 120
        assert stats["instances_without_projections"] == 5
        assert stats["total_canonical_instances"] == 125


class TestProjectionServiceRebuild:
    """Tests for rebuilding projections."""

    @pytest.mark.asyncio
    async def test_rebuild_with_instance_ids(self):
        """Rebuild should process specified instances."""
        mock_session = MagicMock()

        # Mock empty projection check (no existing projection)
        existing_result = MagicMock()
        existing_result.fetchone.return_value = None

        # Mock fetch query for canonical data
        fetch_result = MagicMock()
        fetch_result.fetchone.return_value = (
            1, "1.2.3", "1.2.840.10008.5.1.4.1.1.2", 100,
            10, "1.2.4", "CT", "CT",
            100, "1.2.5", datetime(2024, 1, 1),
            "P123", "Test Patient",
            1000, "sha256:abc", None, None, True,
            "proj-123", "user-456", "bound"
        )

        call_count = 0
        def mock_execute(sql, params):
            nonlocal call_count
            call_count += 1
            if "FROM dicom_core_projections" in sql and "projection_source_checksum" in sql:
                return existing_result
            return fetch_result

        mock_session.execute.side_effect = mock_execute

        service = ProjectionService(session=mock_session)
        request = ProjectionRebuildRequest(instance_ids=[1, 2])
        results = await service.rebuild_projections(request)

        assert len(results) == 2
        assert all(r.instance_id in [1, 2] for r in results)
