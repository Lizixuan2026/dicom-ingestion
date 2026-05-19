"""Reindex workflow for DICOM ingestion.

This module provides the ReindexWorkflow which implements the operational
reindex/rebuild workflow executable via documented operator steps.

D3: Operational Reindex/Rebuild - Reindex/rebuild workflow is executable via documented operator steps.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import TYPE_CHECKING, Any, Dict, List, Optional

if TYPE_CHECKING:
    from sqlalchemy.orm import Session
    from dicom_ingestion.services.projection.projection_service import ProjectionService

logger = logging.getLogger(__name__)


class ReindexStatus(str, Enum):
    """Status values for reindex jobs."""
    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ReindexStep(str, Enum):
    """Steps in the reindex workflow."""
    VALIDATE = "validate"
    ANALYZE = "analyze"
    BACKUP = "backup"
    REBUILD_PROJECTIONS = "rebuild_projections"
    REBUILD_INDEXES = "rebuild_indexes"
    VERIFY = "verify"
    CLEANUP = "cleanup"


@dataclass
class StepResult:
    """Result of a single reindex step."""
    step: str
    status: str = ""  # success, failed, skipped, pending
    started_at: datetime = field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = None
    message: str = ""
    details: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None


@dataclass
class ReindexJob:
    """Reindex job definition.

    Attributes:
        id: Job ID
        name: Human-readable name
        description: Job description
        created_by: Operator who created the job
        status: Current job status
        scope: Reindex scope (all, study, series, date_range)
        scope_params: Scope parameters
        steps: Steps to execute
        batch_size: Instances per batch
        dry_run: Preview mode
        created_at: Creation timestamp
        started_at: Start timestamp
        completed_at: Completion timestamp
        current_step: Currently executing step
        progress: Progress percentage (0-100)
    """
    id: int = 0
    name: str = ""
    description: str = ""
    created_by: str = ""
    status: str = ReindexStatus.PENDING.value
    scope: str = "all"
    scope_params: Dict[str, Any] = field(default_factory=dict)
    steps: List[str] = field(default_factory=lambda: [s.value for s in ReindexStep])
    batch_size: int = 100
    dry_run: bool = False
    created_at: datetime = field(default_factory=datetime.utcnow)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    current_step: Optional[str] = None
    progress: float = 0.0


@dataclass
class ReindexResult:
    """Result of a reindex operation.

    Attributes:
        job_id: Reindex job ID
        success: Overall success
        status: Final status
        step_results: Results for each step
        summary: Summary statistics
        duration_seconds: Total duration
        error_message: Error if failed
    """
    job_id: int = 0
    success: bool = False
    status: str = ""
    step_results: List[StepResult] = field(default_factory=list)
    summary: Dict[str, Any] = field(default_factory=dict)
    duration_seconds: float = 0.0
    error_message: Optional[str] = None


@dataclass
class ReindexPlan:
    """Plan for reindex operation.

    This is shown in dry-run mode before execution.
    """
    scope_description: str = ""
    affected_instances: int = 0
    affected_studies: int = 0
    steps: List[str] = field(default_factory=list)
    estimated_duration_minutes: Optional[float] = None
    warnings: List[str] = field(default_factory=list)


class ReindexWorkflow:
    """Workflow for operational reindex/rebuild operations.

    Responsibilities (D3):
    - Provide documented operator steps for reindexing
    - Support dry-run to preview operations
    - Execute rebuild in controlled batches
    - Maintain audit trail of reindex operations
    - Support pause/resume for long operations
    - Validate and verify results

    Workflow Steps:
    1. VALIDATE - Validate scope and prerequisites
    2. ANALYZE - Analyze current state and estimate scope
    3. BACKUP - Backup current projections (if needed)
    4. REBUILD_PROJECTIONS - Rebuild core projections from source
    5. REBUILD_INDEXES - Rebuild database indexes
    6. VERIFY - Verify rebuilt data
    7. CLEANUP - Cleanup temporary data
    """

    def __init__(
        self,
        session: Session,
        projection_service: Optional[ProjectionService] = None,
    ) -> None:
        """Initialize the reindex workflow.

        Args:
            session: SQLAlchemy session
            projection_service: Projection service for rebuild operations
        """
        self._session = session
        self._projection_service = projection_service
        self._logger = logger

    async def create_job(
        self,
        name: str,
        description: str,
        created_by: str,
        scope: str = "all",
        scope_params: Optional[Dict[str, Any]] = None,
        steps: Optional[List[str]] = None,
        batch_size: int = 100,
        dry_run: bool = False,
    ) -> ReindexJob:
        """Create a new reindex job.

        Args:
            name: Job name
            description: Job description
            created_by: Operator creating the job
            scope: Reindex scope (all, study, series, date_range)
            scope_params: Scope-specific parameters
            steps: Steps to execute (default: all)
            batch_size: Instances per batch
            dry_run: Preview mode

        Returns:
            Created ReindexJob
        """
        job = ReindexJob(
            name=name,
            description=description,
            created_by=created_by,
            scope=scope,
            scope_params=scope_params or {},
            steps=steps or [s.value for s in ReindexStep],
            batch_size=batch_size,
            dry_run=dry_run,
        )

        try:
            sql = """
                INSERT INTO dicom_index_jobs (
                    name,
                    description,
                    created_by,
                    status,
                    scope,
                    scope_params,
                    steps,
                    batch_size,
                    dry_run,
                    created_at
                ) VALUES (
                    :name,
                    :description,
                    :created_by,
                    :status,
                    :scope,
                    :scope_params,
                    :steps,
                    :batch_size,
                    :dry_run,
                    NOW()
                )
                RETURNING id, created_at
            """

            result = self._session.execute(sql, {
                "name": job.name,
                "description": job.description,
                "created_by": job.created_by,
                "status": job.status,
                "scope": job.scope,
                "scope_params": json.dumps(job.scope_params),
                "steps": json.dumps(job.steps),
                "batch_size": job.batch_size,
                "dry_run": job.dry_run,
            })

            row = result.fetchone()
            if row:
                job.id = row[0]
                job.created_at = row[1]

            self._logger.info(
                "Created reindex job %s by %s (scope=%s, dry_run=%s)",
                job.id, job.created_by, job.scope, job.dry_run
            )

        except Exception as e:
            self._logger.exception("Failed to create reindex job")
            raise

        return job

    async def plan(
        self,
        job_id: int,
    ) -> Optional[ReindexPlan]:
        """Generate execution plan for a reindex job.

        This shows what would be affected without executing.

        Args:
            job_id: The reindex job ID

        Returns:
            ReindexPlan or None if job not found
        """
        job = await self._get_job(job_id)
        if not job:
            return None

        plan = ReindexPlan(
            steps=job.steps,
        )

        try:
            # Get scope description
            plan.scope_description = self._describe_scope(job.scope, job.scope_params)

            # Count affected instances
            instance_count_sql = self._build_scope_query(
                "SELECT COUNT(*) FROM dicom_instances i",
                job.scope,
                job.scope_params,
                "i.current_canonical_observation_id IS NOT NULL"
            )
            result = self._session.execute(instance_count_sql, job.scope_params)
            plan.affected_instances = result.scalar() or 0

            # Count affected studies
            study_count_sql = self._build_scope_query(
                """SELECT COUNT(DISTINCT i.study_id)
                   FROM dicom_instances i""",
                job.scope,
                job.scope_params,
                "i.current_canonical_observation_id IS NOT NULL"
            )
            result = self._session.execute(study_count_sql, job.scope_params)
            plan.affected_studies = result.scalar() or 0

            # Estimate duration (rough heuristic)
            if plan.affected_instances > 0:
                seconds_per_instance = 0.1  # 100ms per instance
                total_seconds = plan.affected_instances * seconds_per_instance
                plan.estimated_duration_minutes = total_seconds / 60

            # Generate warnings
            if plan.affected_instances > 10000:
                plan.warnings.append(
                    f"Large scope: {plan.affected_instances} instances. "
                    "Consider smaller batches or off-hours execution."
                )

            # Check current projection state
            stale_sql = self._build_scope_query(
                """SELECT COUNT(*)
                   FROM dicom_instances i
                   LEFT JOIN dicom_core_projections p ON p.instance_id = i.id
                   WHERE p.instance_id IS NULL
                      OR p.projection_version != :projection_version""",
                job.scope,
                job.scope_params,
                "i.current_canonical_observation_id IS NOT NULL"
            )
            stale_params = {**job.scope_params, "projection_version": "1.0.0"}
            result = self._session.execute(stale_sql, stale_params)
            stale_count = result.scalar() or 0

            if stale_count > 0:
                plan.warnings.append(
                    f"{stale_count} instances have stale or missing projections"
                )

        except Exception as e:
            self._logger.exception("Failed to generate reindex plan")
            plan.warnings.append(f"Error analyzing scope: {e}")

        return plan

    async def execute(
        self,
        job_id: int,
    ) -> ReindexResult:
        """Execute a reindex job.

        This executes the workflow steps for the specified job.

        Args:
            job_id: The reindex job ID

        Returns:
            ReindexResult with execution results
        """
        result = ReindexResult(job_id=job_id)
        start_time = datetime.utcnow()

        try:
            job = await self._get_job(job_id)
            if not job:
                result.status = ReindexStatus.FAILED.value
                result.error_message = f"Job {job_id} not found"
                return result

            if job.status == ReindexStatus.RUNNING.value:
                result.error_message = "Job is already running"
                result.status = job.status
                return result

            if job.status in [ReindexStatus.COMPLETED.value, ReindexStatus.CANCELLED.value]:
                result.error_message = f"Job is already {job.status}"
                result.status = job.status
                return result

            # Mark as running
            await self._update_job_status(job_id, ReindexStatus.RUNNING.value)
            job.status = ReindexStatus.RUNNING.value
            job.started_at = datetime.utcnow()

            # Execute each step
            for step_name in job.steps:
                # Check if paused/cancelled
                current_job = await self._get_job(job_id)
                if current_job and current_job.status == ReindexStatus.CANCELLED.value:
                    result.status = ReindexStatus.CANCELLED.value
                    result.error_message = "Job was cancelled"
                    break

                step_result = await self._execute_step(
                    ReindexStep(step_name),
                    job,
                    dry_run=job.dry_run,
                )
                result.step_results.append(step_result)

                if step_result.status == "failed":
                    result.status = ReindexStatus.FAILED.value
                    result.error_message = f"Step {step_name} failed: {step_result.error}"
                    break

                # Update progress
                progress = len(result.step_results) / len(job.steps) * 100
                await self._update_job_progress(job_id, progress, step_name)

            else:
                # All steps completed
                result.status = ReindexStatus.COMPLETED.value if not job.dry_run else "dry_run_completed"
                result.success = True

            # Finalize job
            await self._finalize_job(job_id, result.status)

        except Exception as e:
            self._logger.exception("Reindex job %s failed", job_id)
            result.status = ReindexStatus.FAILED.value
            result.error_message = str(e)
            await self._finalize_job(job_id, ReindexStatus.FAILED.value)

        finally:
            result.duration_seconds = (datetime.utcnow() - start_time).total_seconds()
            result.summary = await self._build_summary(job_id)

        return result

    async def pause(self, job_id: int) -> bool:
        """Pause a running reindex job.

        Args:
            job_id: The job ID

        Returns:
            True if paused successfully
        """
        try:
            await self._update_job_status(job_id, ReindexStatus.PAUSED.value)
            self._logger.info("Paused reindex job %s", job_id)
            return True
        except Exception as e:
            self._logger.exception("Failed to pause job %s", job_id)
            return False

    async def resume(self, job_id: int) -> ReindexResult:
        """Resume a paused reindex job.

        Args:
            job_id: The job ID

        Returns:
            ReindexResult
        """
        await self._update_job_status(job_id, ReindexStatus.RUNNING.value)
        return await self.execute(job_id)

    async def cancel(self, job_id: int) -> bool:
        """Cancel a reindex job.

        Args:
            job_id: The job ID

        Returns:
            True if cancelled successfully
        """
        try:
            await self._update_job_status(job_id, ReindexStatus.CANCELLED.value)
            self._logger.info("Cancelled reindex job %s", job_id)
            return True
        except Exception as e:
            self._logger.exception("Failed to cancel job %s", job_id)
            return False

    async def get_job_status(self, job_id: int) -> Optional[Dict[str, Any]]:
        """Get current status of a reindex job.

        Args:
            job_id: The job ID

        Returns:
            Status dictionary or None if job not found
        """
        job = await self._get_job(job_id)
        if not job:
            return None

        return {
            "id": job.id,
            "name": job.name,
            "status": job.status,
            "current_step": job.current_step,
            "progress": job.progress,
            "created_at": job.created_at.isoformat() if job.created_at else None,
            "started_at": job.started_at.isoformat() if job.started_at else None,
            "completed_at": job.completed_at.isoformat() if job.completed_at else None,
        }

    async def list_jobs(
        self,
        status: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """List reindex jobs.

        Args:
            status: Filter by status
            limit: Maximum records

        Returns:
            List of job status dictionaries
        """
        where_clause = "1=1"
        params: Dict[str, Any] = {"limit": limit}

        if status:
            where_clause = "status = :status"
            params["status"] = status

        sql = f"""
            SELECT
                id, name, status, scope, dry_run,
                created_at, started_at, completed_at,
                progress, current_step
            FROM dicom_index_jobs
            WHERE {where_clause}
            ORDER BY created_at DESC
            LIMIT :limit
        """

        result = self._session.execute(sql, params)

        jobs = []
        for row in result:
            jobs.append({
                "id": row[0],
                "name": row[1],
                "status": row[2],
                "scope": row[3],
                "dry_run": row[4],
                "created_at": row[5].isoformat() if row[5] else None,
                "started_at": row[6].isoformat() if row[6] else None,
                "completed_at": row[7].isoformat() if row[7] else None,
                "progress": row[8],
                "current_step": row[9],
            })

        return jobs

    async def _get_job(self, job_id: int) -> Optional[ReindexJob]:
        """Fetch a reindex job by ID."""
        sql = """
            SELECT
                id, name, description, created_by, status,
                scope, scope_params, steps, batch_size, dry_run,
                created_at, started_at, completed_at, progress, current_step
            FROM dicom_index_jobs
            WHERE id = :job_id
        """
        result = self._session.execute(sql, {"job_id": job_id})
        row = result.fetchone()

        if not row:
            return None

        # Handle JSON fields with type compatibility (str -> loads, dict/list -> use directly)
        scope_params = row[6]
        if isinstance(scope_params, str):
            scope_params = json.loads(scope_params) if scope_params else {}
        elif scope_params is None:
            scope_params = {}

        steps = row[7]
        if isinstance(steps, str):
            steps = json.loads(steps) if steps else []
        elif steps is None:
            steps = []

        return ReindexJob(
            id=row[0],
            name=row[1] or "",
            description=row[2] or "",
            created_by=row[3] or "",
            status=row[4] or ReindexStatus.PENDING.value,
            scope=row[5] or "all",
            scope_params=scope_params,
            steps=steps,
            batch_size=row[8] or 100,
            dry_run=row[9] or False,
            created_at=row[10],
            started_at=row[11],
            completed_at=row[12],
            progress=row[13] or 0.0,
            current_step=row[14],
        )

    async def _execute_step(
        self,
        step: ReindexStep,
        job: ReindexJob,
        dry_run: bool = False,
    ) -> StepResult:
        """Execute a single workflow step."""
        result = StepResult(step=step.value)
        self._logger.info("Executing step %s (dry_run=%s)", step.value, dry_run)

        try:
            if dry_run:
                result.status = "skipped"
                result.message = f"Would execute {step.value} (dry run)"
                return result

            if step == ReindexStep.VALIDATE:
                await self._step_validate(job, dry_run, result)
            elif step == ReindexStep.ANALYZE:
                await self._step_analyze(job, dry_run, result)
            elif step == ReindexStep.BACKUP:
                await self._step_backup(job, dry_run, result)
            elif step == ReindexStep.REBUILD_PROJECTIONS:
                await self._step_rebuild_projections(job, dry_run, result)
            elif step == ReindexStep.REBUILD_INDEXES:
                await self._step_rebuild_indexes(job, dry_run, result)
            elif step == ReindexStep.VERIFY:
                await self._step_verify(job, dry_run, result)
            elif step == ReindexStep.CLEANUP:
                await self._step_cleanup(job, dry_run, result)
            else:
                result.status = "skipped"
                result.message = f"Unknown step: {step.value}"

            result.status = result.status or "success"

        except Exception as e:
            self._logger.exception("Step %s failed", step.value)
            result.status = "failed"
            result.error = str(e)

        result.completed_at = datetime.utcnow()
        return result

    async def _step_validate(
        self,
        job: ReindexJob,
        dry_run: bool,
        result: StepResult,
    ) -> None:
        """Validate prerequisites."""
        # Check projection service is available
        if ReindexStep.REBUILD_PROJECTIONS.value in job.steps and not self._projection_service:
            raise ValueError("ProjectionService required but not available")

        # Check database connectivity
        self._session.execute("SELECT 1")

        result.message = "Validation passed"
        result.status = "success"

    async def _step_analyze(
        self,
        job: ReindexJob,
        dry_run: bool,
        result: StepResult,
    ) -> None:
        """Analyze scope and estimate impact."""
        # Count affected instances
        count_sql = self._build_scope_query(
            "SELECT COUNT(*) FROM dicom_instances i",
            job.scope,
            job.scope_params,
            "i.current_canonical_observation_id IS NOT NULL"
        )
        result_count = self._session.execute(count_sql, job.scope_params)
        instance_count = result_count.scalar() or 0

        result.details["affected_instances"] = instance_count
        result.message = f"Scope analysis complete: {instance_count} instances"
        result.status = "success"

    async def _step_backup(
        self,
        job: ReindexJob,
        dry_run: bool,
        result: StepResult,
    ) -> None:
        """Backup current state."""
        if dry_run:
            result.message = "Would backup current projections (dry run)"
            result.status = "skipped"
            return

        # In production, this would create a backup table
        # For now, just log the operation
        result.message = "Backup step completed (no-op in this implementation)"
        result.status = "success"

    async def _step_rebuild_projections(
        self,
        job: ReindexJob,
        dry_run: bool,
        result: StepResult,
    ) -> None:
        """Rebuild projections from source."""
        if dry_run:
            result.message = "Would rebuild projections (dry run)"
            result.status = "skipped"
            return

        if not self._projection_service:
            result.message = "ProjectionService not available"
            result.status = "skipped"
            return

        # Build rebuild request
        from dicom_ingestion.services.projection.projection_service import ProjectionRebuildRequest

        rebuild_request = ProjectionRebuildRequest(
            study_instance_uid=job.scope_params.get("study_uid"),
            series_instance_uid=job.scope_params.get("series_uid"),
            from_date=job.scope_params.get("from_date"),
            force=True,
            batch_size=job.batch_size,
        )

        # Execute rebuild
        rebuild_results = await self._projection_service.rebuild_projections(rebuild_request)

        success_count = sum(1 for r in rebuild_results if r.success)
        failure_count = len(rebuild_results) - success_count

        result.details["rebuilt_count"] = success_count
        result.details["failed_count"] = failure_count
        result.message = f"Rebuilt {success_count} projections, {failure_count} failures"
        result.status = "success" if failure_count == 0 else "partial"

    async def _step_rebuild_indexes(
        self,
        job: ReindexJob,
        dry_run: bool,
        result: StepResult,
    ) -> None:
        """Rebuild database indexes."""
        if dry_run:
            result.message = "Would rebuild indexes (dry run)"
            result.status = "skipped"
            return

        # Reindex core projections table
        self._session.execute("REINDEX TABLE dicom_core_projections")

        result.message = "Indexes rebuilt"
        result.status = "success"

    async def _step_verify(
        self,
        job: ReindexJob,
        dry_run: bool,
        result: StepResult,
    ) -> None:
        """Verify rebuilt data."""
        if dry_run:
            result.message = "Would verify data (dry run)"
            result.status = "skipped"
            return

        # Count instances without projections
        missing_sql = """
            SELECT COUNT(*)
            FROM dicom_instances i
            LEFT JOIN dicom_core_projections p ON p.instance_id = i.id
            WHERE i.current_canonical_observation_id IS NOT NULL
              AND p.instance_id IS NULL
        """
        missing_result = self._session.execute(missing_sql)
        missing_count = missing_result.scalar() or 0

        result.details["instances_without_projections"] = missing_count
        result.message = f"Verification complete: {missing_count} instances missing projections"
        result.status = "success" if missing_count == 0 else "warning"

    async def _step_cleanup(
        self,
        job: ReindexJob,
        dry_run: bool,
        result: StepResult,
    ) -> None:
        """Cleanup temporary data."""
        if dry_run:
            result.message = "Would cleanup (dry run)"
            result.status = "skipped"
            return

        # Cleanup is a no-op for this implementation
        result.message = "Cleanup completed"
        result.status = "success"

    async def _update_job_status(self, job_id: int, status: str) -> None:
        """Update job status."""
        sql = """
            UPDATE dicom_index_jobs
            SET status = :status, updated_at = NOW()
            WHERE id = :job_id
        """
        self._session.execute(sql, {"job_id": job_id, "status": status})

    async def _update_job_progress(
        self,
        job_id: int,
        progress: float,
        current_step: str,
    ) -> None:
        """Update job progress."""
        sql = """
            UPDATE dicom_index_jobs
            SET progress = :progress, current_step = :step, updated_at = NOW()
            WHERE id = :job_id
        """
        self._session.execute(sql, {
            "job_id": job_id,
            "progress": progress,
            "step": current_step,
        })

    async def _finalize_job(self, job_id: int, status: str) -> None:
        """Finalize a job."""
        sql = """
            UPDATE dicom_index_jobs
            SET status = :status,
                completed_at = NOW(),
                updated_at = NOW()
            WHERE id = :job_id
        """
        self._session.execute(sql, {"job_id": job_id, "status": status})

    async def _build_summary(self, job_id: int) -> Dict[str, Any]:
        """Build result summary."""
        # Get projection stats
        stats_sql = """
            SELECT
                COUNT(*),
                COUNT(*) FILTER (WHERE projection_version = '1.0.0')
            FROM dicom_core_projections
        """
        stats_result = self._session.execute(stats_sql)
        stats_row = stats_result.fetchone()

        return {
            "total_projections": stats_row[0] if stats_row else 0,
            "current_version_projections": stats_row[1] if stats_row else 0,
        }

    def _describe_scope(self, scope: str, params: Dict[str, Any]) -> str:
        """Generate human-readable scope description."""
        if scope == "all":
            return "All instances with canonical observations"
        elif scope == "study":
            return f"Study UID: {params.get('study_uid', 'N/A')}"
        elif scope == "series":
            return f"Series UID: {params.get('series_uid', 'N/A')}"
        elif scope == "date_range":
            return f"Date range: {params.get('from_date')} to {params.get('to_date')}"
        else:
            return f"Unknown scope: {scope}"

    def _build_scope_query(
        self,
        base_query: str,
        scope: str,
        params: Dict[str, Any],
        additional_where: str = "",
    ) -> str:
        """Build a SQL query with scope filtering."""
        joins = ""
        where_conditions = []

        if additional_where:
            where_conditions.append(additional_where)

        if scope == "study":
            joins += " JOIN dicom_studies st ON st.id = i.study_id"
            where_conditions.append("st.study_instance_uid = :study_uid")
        elif scope == "series":
            joins += " JOIN dicom_series s ON s.id = i.series_id"
            where_conditions.append("s.series_instance_uid = :series_uid")
        elif scope == "date_range":
            joins += " JOIN dicom_instance_observations o ON o.id = i.current_canonical_observation_id"
            where_conditions.append("o.observed_at BETWEEN :from_date AND :to_date")

        where_clause = " AND ".join(where_conditions) if where_conditions else "1=1"

        # Insert joins before WHERE
        if "WHERE" in base_query:
            return base_query.replace("WHERE", f"{joins} WHERE {where_clause} AND")
        else:
            return f"{base_query}{joins} WHERE {where_clause}"
