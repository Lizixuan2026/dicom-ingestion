"""Tests for ReindexWorkflow.

Acceptance criteria:
- Jobs can be created with various scopes
- Dry-run mode shows plan without executing
- Workflow executes in documented steps
- Jobs can be paused, resumed, and cancelled
- Results are tracked and reported
"""
import pytest
from unittest.mock import MagicMock, AsyncMock
from datetime import datetime

from dicom_ingestion.services.reindex.reindex_workflow import (
    ReindexWorkflow,
    ReindexJob,
    ReindexStep,
    ReindexStatus,
    ReindexResult,
    ReindexPlan,
    StepResult,
)


class TestReindexJob:
    """Tests for ReindexJob dataclass."""

    def test_default_job(self):
        """Default job should have all steps."""
        job = ReindexJob(name="Test Job", description="Test", created_by="admin")
        assert job.status == ReindexStatus.PENDING.value
        assert job.scope == "all"
        assert job.dry_run is False
        assert len(job.steps) == 7  # All workflow steps

    def test_custom_scope(self):
        """Job can have custom scope."""
        job = ReindexJob(
            name="Study Reindex",
            description="Reindex specific study",
            created_by="admin",
            scope="study",
            scope_params={"study_uid": "1.2.3"},
        )
        assert job.scope == "study"
        assert job.scope_params["study_uid"] == "1.2.3"


class TestReindexResult:
    """Tests for ReindexResult dataclass."""

    def test_default_result(self):
        """Default result should indicate failure."""
        result = ReindexResult()
        assert result.success is False
        assert result.status == ""
        assert result.step_results == []

    def test_completed_result(self):
        """Completed result should have all steps."""
        result = ReindexResult(
            success=True,
            status=ReindexStatus.COMPLETED.value,
            step_results=[
                StepResult(step="validate", status="success"),
                StepResult(step="analyze", status="success"),
            ],
            duration_seconds=120.5,
        )
        assert result.success is True
        assert len(result.step_results) == 2


class TestReindexPlan:
    """Tests for ReindexPlan dataclass."""

    def test_plan(self):
        """Plan should describe scope and estimate."""
        plan = ReindexPlan(
            scope_description="Study UID: 1.2.3",
            affected_instances=100,
            affected_studies=1,
            estimated_duration_minutes=10.5,
            warnings=["Large scope"],
        )
        assert plan.affected_instances == 100
        assert len(plan.warnings) == 1


class TestReindexWorkflowInitialization:
    """Tests for ReindexWorkflow initialization."""

    def test_workflow_initialization(self):
        """Workflow should initialize with session."""
        mock_session = MagicMock()
        workflow = ReindexWorkflow(session=mock_session)
        assert workflow._session is mock_session

    def test_workflow_with_projection_service(self):
        """Workflow can include projection service."""
        mock_session = MagicMock()
        mock_projection = MagicMock()
        workflow = ReindexWorkflow(
            session=mock_session,
            projection_service=mock_projection,
        )
        assert workflow._projection_service is mock_projection


class TestReindexWorkflowCreate:
    """Tests for creating reindex jobs."""

    def test_create_job(self):
        """Should create a new reindex job."""
        mock_session = MagicMock()

        # Mock insert returning ID
        result = MagicMock()
        result.fetchone.return_value = (1, datetime.now())
        mock_session.execute.return_value = result

        workflow = ReindexWorkflow(session=mock_session)

        import asyncio
        job = asyncio.run(workflow.create_job(
            name="Test Reindex",
            description="Test description",
            created_by="admin",
            scope="all",
        ))

        assert job.id == 1
        assert job.name == "Test Reindex"
        assert job.status == ReindexStatus.PENDING.value

    def test_create_job_with_custom_steps(self):
        """Should create job with custom steps."""
        mock_session = MagicMock()

        result = MagicMock()
        result.fetchone.return_value = (1, datetime.now())
        mock_session.execute.return_value = result

        workflow = ReindexWorkflow(session=mock_session)

        import asyncio
        job = asyncio.run(workflow.create_job(
            name="Quick Reindex",
            description="Skip backup",
            created_by="admin",
            steps=["validate", "rebuild_projections", "verify"],
        ))

        assert job.steps == ["validate", "rebuild_projections", "verify"]


class TestReindexWorkflowPlan:
    """Tests for reindex planning."""

    @pytest.mark.asyncio
    async def test_plan_all_scope(self):
        """Plan should describe 'all' scope."""
        mock_session = MagicMock()

        # Mock job fetch
        job_result = MagicMock()
        job_result.fetchone.return_value = (
            1, "Test", "Desc", "admin", "pending",
            "all", "{}", '["validate"]', 100, False,
            datetime.now(), None, None, 0.0, None
        )

        # Mock counts
        count_result = MagicMock()
        count_result.scalar.return_value = 500

        def mock_execute(sql, params=None):
            if "FROM dicom_index_jobs" in sql:
                return job_result
            return count_result

        mock_session.execute.side_effect = mock_execute

        workflow = ReindexWorkflow(session=mock_session)
        plan = await workflow.plan(job_id=1)

        assert plan is not None
        assert "all" in plan.scope_description.lower()
        assert plan.affected_instances == 500


class TestReindexWorkflowExecute:
    """Tests for executing reindex workflow."""

    @pytest.mark.asyncio
    async def test_execute_job_not_found(self):
        """Should fail if job not found."""
        mock_session = MagicMock()

        result = MagicMock()
        result.fetchone.return_value = None
        mock_session.execute.return_value = result

        workflow = ReindexWorkflow(session=mock_session)
        result = await workflow.execute(job_id=999)

        assert result.success is False
        assert "not found" in result.error_message.lower()

    @pytest.mark.asyncio
    async def test_execute_dry_run(self):
        """Dry run should complete without changes."""
        mock_session = MagicMock()
        mock_projection = MagicMock()

        # Mock job fetch
        job_result = MagicMock()
        job_result.fetchone.return_value = (
            1, "Test", "Desc", "admin", "pending",
            "all", "{}", '["validate", "analyze"]', 100, True,  # dry_run=True
            datetime.now(), None, None, 0.0, None
        )

        count_result = MagicMock()
        count_result.scalar.return_value = 100

        def mock_execute(sql, params=None):
            if "FROM dicom_index_jobs" in sql and "WHERE id" in sql:
                return job_result
            return count_result

        mock_session.execute.side_effect = mock_execute

        workflow = ReindexWorkflow(
            session=mock_session,
            projection_service=mock_projection,
        )
        result = await workflow.execute(job_id=1)

        # Should skip actual rebuild in dry run
        assert result.status == "dry_run_completed"


class TestReindexWorkflowControl:
    """Tests for job control operations."""

    def test_pause_job(self):
        """Should pause running job."""
        mock_session = MagicMock()
        workflow = ReindexWorkflow(session=mock_session)

        import asyncio
        success = asyncio.run(workflow.pause(job_id=1))

        assert success is True
        # Verify update was called
        mock_session.execute.assert_called()

    def test_cancel_job(self):
        """Should cancel job."""
        mock_session = MagicMock()
        workflow = ReindexWorkflow(session=mock_session)

        import asyncio
        success = asyncio.run(workflow.cancel(job_id=1))

        assert success is True


class TestReindexWorkflowStatus:
    """Tests for job status queries."""

    @pytest.mark.asyncio
    async def test_get_job_status(self):
        """Should return job status."""
        mock_session = MagicMock()

        # Need to match all 16 fields expected by _get_job
        result = MagicMock()
        result.fetchone.return_value = (
            1, "Test Reindex", "Test Desc", "admin", "running",
            "all", "{}", "[\"validate\"]", 100, False,
            datetime.now(), datetime.now(), None, 50.0, "rebuild_projections"
        )
        mock_session.execute.return_value = result

        workflow = ReindexWorkflow(session=mock_session)
        status = await workflow.get_job_status(job_id=1)

        assert status is not None
        assert status["id"] == 1
        assert status["status"] == "running"
        assert status["progress"] == 50.0
        assert status["current_step"] == "rebuild_projections"

    @pytest.mark.asyncio
    async def test_list_jobs(self):
        """Should list jobs."""
        mock_session = MagicMock()

        # Make result iterable
        rows = [
            (1, "Job 1", "completed", "all", False, datetime.now(), datetime.now(), datetime.now(), 100.0, None),
            (2, "Job 2", "running", "study", True, datetime.now(), datetime.now(), None, 50.0, "analyze"),
        ]
        result = MagicMock()
        result.__iter__ = MagicMock(return_value=iter(rows))
        mock_session.execute.return_value = result

        workflow = ReindexWorkflow(session=mock_session)
        jobs = await workflow.list_jobs(limit=10)

        assert len(jobs) == 2
        assert jobs[0]["status"] == "completed"
        assert jobs[1]["dry_run"] is True


class TestReindexWorkflowSteps:
    """Tests for individual workflow steps."""

    @pytest.mark.asyncio
    async def test_validate_step(self):
        """Validate step should check prerequisites."""
        mock_session = MagicMock()
        mock_projection = MagicMock()
        workflow = ReindexWorkflow(
            session=mock_session,
            projection_service=mock_projection,
        )

        job = ReindexJob(name="Test", description="", created_by="admin", steps=["validate"])
        step_result = StepResult(step="validate")

        await workflow._step_validate(job, False, step_result)

        assert step_result.status == "success"
        assert "passed" in step_result.message.lower()

    @pytest.mark.asyncio
    async def test_analyze_step(self):
        """Analyze step should count affected instances."""
        mock_session = MagicMock()

        count_result = MagicMock()
        count_result.scalar.return_value = 100
        mock_session.execute.return_value = count_result

        workflow = ReindexWorkflow(session=mock_session)

        job = ReindexJob(name="Test", description="", created_by="admin")
        step_result = StepResult(step="analyze")

        await workflow._step_analyze(job, False, step_result)

        assert step_result.status == "success"
        assert step_result.details["affected_instances"] == 100

    @pytest.mark.asyncio
    async def test_verify_step(self):
        """Verify step should check for missing projections."""
        mock_session = MagicMock()

        missing_result = MagicMock()
        missing_result.scalar.return_value = 0
        mock_session.execute.return_value = missing_result

        workflow = ReindexWorkflow(session=mock_session)

        job = ReindexJob(name="Test", description="", created_by="admin")
        step_result = StepResult(step="verify")

        await workflow._step_verify(job, False, step_result)

        assert step_result.status == "success"
        assert step_result.details["instances_without_projections"] == 0
