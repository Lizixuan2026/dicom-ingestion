"""Tests for Batch 5 v0.1 review fixes.

P1-1: SQL alias consistency in scope queries
P1-2: JSON field deserialization compatibility
"""
import pytest
from unittest.mock import MagicMock
from datetime import datetime
import json

from dicom_ingestion.services.reindex.reindex_workflow import (
    ReindexWorkflow,
    ReindexJob,
    ReindexStatus,
)


class TestSQLAliasConsistency:
    """Tests for P1-1: SQL alias consistency fix."""

    @pytest.mark.asyncio
    async def test_plan_with_scope_all_uses_correct_alias(self):
        """plan() with scope=all should use 'i' alias consistently."""
        mock_session = MagicMock()

        # Mock job fetch with scope=all
        job_result = MagicMock()
        job_result.fetchone.return_value = (
            1, "Test", "Desc", "admin", "pending",
            "all", "{}", '["validate"]', 100, False,
            datetime.now(), None, None, 0.0, None
        )

        # Track executed SQL to verify alias usage
        executed_sqls = []
        def mock_execute(sql, params=None):
            executed_sqls.append(sql)
            result = MagicMock()
            result.scalar.return_value = 100
            return result

        mock_session.execute.side_effect = mock_execute

        workflow = ReindexWorkflow(session=mock_session)
        plan = await workflow.plan(job_id=1)

        assert plan is not None
        assert plan.affected_instances == 100

        # Verify all SQL queries use 'i' alias
        for sql in executed_sqls:
            if "FROM dicom_instances" in sql and "WHERE" in sql:
                # Should use 'i.' prefix for column references in WHERE
                if "current_canonical_observation_id" in sql:
                    assert "i.current_canonical_observation_id" in sql, \
                        f"SQL missing 'i' alias: {sql}"

    @pytest.mark.asyncio
    async def test_analyze_step_with_scope_all(self):
        """_step_analyze with scope=all should work correctly."""
        mock_session = MagicMock()

        count_result = MagicMock()
        count_result.scalar.return_value = 50
        mock_session.execute.return_value = count_result

        workflow = ReindexWorkflow(session=mock_session)

        from dicom_ingestion.services.reindex.reindex_workflow import StepResult
        job = ReindexJob(
            name="Test",
            description="",
            created_by="admin",
            scope="all",
            steps=["validate", "analyze"]
        )
        step_result = StepResult(step="analyze")

        await workflow._step_analyze(job, False, step_result)

        assert step_result.status == "success"
        assert step_result.details["affected_instances"] == 50


class TestJSONFieldCompatibility:
    """Tests for P1-2: JSON field deserialization compatibility."""

    @pytest.mark.asyncio
    async def test_get_job_with_string_json_fields(self):
        """_get_job should handle string JSON fields."""
        mock_session = MagicMock()

        # Return string JSON fields (as stored in DB)
        job_result = MagicMock()
        job_result.fetchone.return_value = (
            1, "Test Job", "Description", "admin", "pending",
            "study", '{"study_uid": "1.2.3"}', '["validate", "analyze"]', 100, False,
            datetime.now(), None, None, 0.0, None
        )
        mock_session.execute.return_value = job_result

        workflow = ReindexWorkflow(session=mock_session)
        job = await workflow._get_job(1)

        assert job is not None
        assert job.id == 1
        assert job.scope_params == {"study_uid": "1.2.3"}
        assert job.steps == ["validate", "analyze"]

    @pytest.mark.asyncio
    async def test_get_job_with_parsed_json_fields(self):
        """_get_job should handle already-parsed dict/list fields."""
        mock_session = MagicMock()

        # Return already-parsed dict/list fields (some drivers do this)
        job_result = MagicMock()
        job_result.fetchone.return_value = (
            1, "Test Job", "Description", "admin", "pending",
            "study", {"study_uid": "1.2.3"}, ["validate", "analyze"], 100, False,
            datetime.now(), None, None, 0.0, None
        )
        mock_session.execute.return_value = job_result

        workflow = ReindexWorkflow(session=mock_session)
        job = await workflow._get_job(1)

        assert job is not None
        assert job.id == 1
        assert job.scope_params == {"study_uid": "1.2.3"}
        assert job.steps == ["validate", "analyze"]

    @pytest.mark.asyncio
    async def test_get_job_with_null_json_fields(self):
        """_get_job should handle null JSON fields."""
        mock_session = MagicMock()

        # Return None for JSON fields
        job_result = MagicMock()
        job_result.fetchone.return_value = (
            1, "Test Job", "Description", "admin", "pending",
            "all", None, None, 100, False,
            datetime.now(), None, None, 0.0, None
        )
        mock_session.execute.return_value = job_result

        workflow = ReindexWorkflow(session=mock_session)
        job = await workflow._get_job(1)

        assert job is not None
        assert job.scope_params == {}
        assert job.steps == []

    @pytest.mark.asyncio
    async def test_get_job_with_empty_string_json_fields(self):
        """_get_job should handle empty string JSON fields."""
        mock_session = MagicMock()

        # Return empty strings for JSON fields
        job_result = MagicMock()
        job_result.fetchone.return_value = (
            1, "Test Job", "Description", "admin", "pending",
            "all", "", "", 100, False,
            datetime.now(), None, None, 0.0, None
        )
        mock_session.execute.return_value = job_result

        workflow = ReindexWorkflow(session=mock_session)
        job = await workflow._get_job(1)

        assert job is not None
        assert job.scope_params == {}
        assert job.steps == []
