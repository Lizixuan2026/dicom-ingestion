"""
Binding Policy Service — Manage platform binding for DICOM instances.

This module provides the BindingPolicyService which manages the
binding between canonical DICOM instances and platform objects
(Assets, DatasetSamples, Annotations).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Optional, List, Dict

if TYPE_CHECKING:
    from sqlalchemy.orm import Session
    from dicom_ingestion.models.binding_policy import (
        DicomBindingPolicy,
        BindingContext,
        BindingResult,
        BindingStatus,
        BindingPolicySummary,
        BindingTargetType,
    )

logger = logging.getLogger(__name__)


class BindingPolicyService:
    """
    Service for managing platform binding of DICOM instances.

    Responsibilities:
    - Create binding policy records for new instances
    - Execute binding to platform objects (Assets, DatasetSamples)
    - Handle binding failures gracefully
    - Support binding retry and deferred binding
    - Maintain separation between ingest and binding

    Binding Policy:
    - Ingest and binding are separate concerns
    - Valid DICOM may outlive binding failure
    - Binding status is tracked independently
    - Failed bindings can be retried
    """

    def __init__(
        self,
        session: Session,
        platform_client: Optional[Any] = None,
    ) -> None:
        """
        Initialize the binding policy service.

        Args:
            session: SQLAlchemy session for database operations
            platform_client: Optional client for platform API calls
        """
        self._session = session
        self._platform = platform_client
        self._logger = logger

    async def create_binding_record(
        self,
        instance_id: int,
        observation_id: int,
        context: Any,  # BindingContext
    ) -> BindingResult:
        """
        Create a binding policy record for an instance.

        Args:
            instance_id: The DICOM instance ID
            observation_id: The observation ID
            context: Binding context with project/dataset info

        Returns:
            BindingResult with the created binding record ID
        """
        from dicom_ingestion.models.binding_policy import (
            BindingResult,
            BindingStatus,
        )

        result = BindingResult()

        try:
            # Check if binding record already exists
            existing = await self._get_binding_for_observation(observation_id)
            if existing:
                self._logger.debug(
                    "Binding record already exists for observation %s",
                    observation_id
                )
                result.success = True
                result.binding_id = existing.id
                return result

            # Create new binding record
            binding_id = await self._persist_binding(
                instance_id=instance_id,
                observation_id=observation_id,
                status=BindingStatus.PENDING.value,
            )

            result.success = True
            result.binding_id = binding_id

            self._logger.info(
                "Created binding record %s for instance %s, observation %s",
                binding_id,
                instance_id,
                observation_id
            )

        except Exception as e:
            self._logger.exception(
                "Failed to create binding record for instance %s",
                instance_id
            )
            result.error_code = "BindingRecordCreationFailed"
            result.error_detail = str(e)

        return result

    async def execute_binding(
        self,
        binding_id: int,
        context: Any,  # BindingContext
    ) -> BindingResult:
        """
        Execute binding for a binding record.

        This performs the actual platform binding operation.
        In v1, this is a stub that simulates the binding.
        Real implementation would call platform APIs.

        Args:
            binding_id: The binding record ID
            context: Binding context with project/dataset info

        Returns:
            BindingResult
        """
        from dicom_ingestion.models.binding_policy import (
            BindingResult,
            BindingStatus,
            BindingTargetType,
        )

        result = BindingResult()

        try:
            # Get the binding record
            binding = await self._get_binding_by_id(binding_id)
            if not binding:
                result.error_code = "BindingRecordNotFound"
                result.error_detail = f"Binding {binding_id} not found"
                return result

            # Check if already bound
            if binding.is_bound:
                result.success = True
                result.binding_id = binding_id
                result.target_type = binding.target_type
                result.target_id = binding.target_id
                result.target_uri = binding.target_uri
                return result

            # Mark as in progress
            binding.mark_in_progress()
            await self._update_binding_status(binding)

            # Perform the binding (stub for v1)
            bind_result = await self._perform_platform_binding(
                binding, context
            )

            if bind_result.success:
                # Update binding record
                binding.mark_bound(
                    target_type=bind_result.target_type or BindingTargetType.ASSET.value,
                    target_id=bind_result.target_id or f"asset-{binding.instance_id}",
                    target_uri=bind_result.target_uri or f"/assets/{binding.instance_id}",
                    metadata={"project_id": context.project_id},
                )
                await self._update_binding_status(binding)

                result.success = True
                result.binding_id = binding_id
                result.target_type = binding.target_type
                result.target_id = binding.target_id
                result.target_uri = binding.target_uri

                self._logger.info(
                    "Successfully bound instance %s to %s:%s",
                    binding.instance_id,
                    binding.target_type,
                    binding.target_id
                )
            else:
                # Mark as failed
                binding.mark_failed(
                    error_code=bind_result.error_code or "BindingFailed",
                    error_detail=bind_result.error_detail or "Unknown binding failure",
                )
                binding.increment_retry()
                await self._update_binding_status(binding)

                result.error_code = binding.error_code
                result.error_detail = binding.error_detail

        except Exception as e:
            self._logger.exception(
                "Failed to execute binding %s",
                binding_id
            )
            result.error_code = "BindingExecutionFailed"
            result.error_detail = str(e)

        return result

    async def _perform_platform_binding(
        self,
        binding: Any,  # DicomBindingPolicy
        context: Any,  # BindingContext
    ) -> BindingResult:
        """
        Perform the actual platform binding operation.

        In v1, this is a stub that simulates success.
        Real implementation would:
        1. Create Asset from DICOM instance
        2. Link to Project
        3. Optionally create DatasetSample
        4. Return target references

        Args:
            binding: The binding record
            context: Binding context

        Returns:
            BindingResult
        """
        from dicom_ingestion.models.binding_policy import (
            BindingResult,
            BindingTargetType,
        )

        result = BindingResult()

        # Check if platform client is available
        if self._platform:
            # Real implementation would use platform_client
            # For v1 stub, we simulate success
            pass

        # Simulate successful binding
        result.success = True
        result.target_type = BindingTargetType.ASSET.value
        result.target_id = f"asset-{binding.instance_id}"
        result.target_uri = f"/assets/{binding.instance_id}"

        return result

    async def retry_binding(
        self,
        binding_id: int,
        context: Any,  # BindingContext
    ) -> BindingResult:
        """
        Retry a failed or deferred binding.

        Args:
            binding_id: The binding record ID
            context: Binding context

        Returns:
            BindingResult
        """
        from dicom_ingestion.models.binding_policy import BindingResult

        result = BindingResult()

        binding = await self._get_binding_by_id(binding_id)
        if not binding:
            result.error_code = "BindingRecordNotFound"
            return result

        if not binding.can_retry:
            result.error_code = "BindingNotRetryable"
            result.error_detail = (
                f"Binding cannot be retried (status={binding.binding_status}, "
                f"retries={binding.retry_count})"
            )
            return result

        binding.increment_retry()
        return await self.execute_binding(binding_id, context)

    async def get_binding_for_instance(
        self,
        instance_id: int,
    ) -> Optional[Any]:  # Optional[DicomBindingPolicy]
        """
        Get binding record for an instance.

        Args:
            instance_id: The instance ID

        Returns:
            DicomBindingPolicy if found, None otherwise
        """
        from dicom_ingestion.models.binding_policy import DicomBindingPolicy

        result = self._session.execute(
            """
            SELECT
                id,
                instance_id,
                observation_id,
                binding_status,
                target_type,
                target_id,
                target_uri,
                error_code,
                error_detail,
                bound_at,
                retry_count,
                created_at,
                updated_at
            FROM dicom_binding_policies
            WHERE instance_id = :instance_id
            ORDER BY created_at DESC
            LIMIT 1
            """,
            {"instance_id": instance_id}
        )

        row = result.fetchone()
        if not row:
            return None

        return DicomBindingPolicy(
            id=row[0],
            instance_id=row[1],
            observation_id=row[2],
            binding_status=row[3],
            target_type=row[4],
            target_id=row[5],
            target_uri=row[6],
            error_code=row[7] or "",
            error_detail=row[8] or "",
            bound_at=row[9],
            retry_count=row[10] or 0,
            created_at=row[11],
            updated_at=row[12],
        )

    async def _get_binding_for_observation(
        self,
        observation_id: int,
    ) -> Optional[Any]:  # Optional[DicomBindingPolicy]
        """
        Get binding record for an observation.

        Args:
            observation_id: The observation ID

        Returns:
            DicomBindingPolicy if found, None otherwise
        """
        from dicom_ingestion.models.binding_policy import DicomBindingPolicy

        result = self._session.execute(
            """
            SELECT
                id,
                instance_id,
                observation_id,
                binding_status,
                target_type,
                target_id,
                target_uri,
                error_code,
                error_detail,
                bound_at,
                retry_count,
                created_at,
                updated_at
            FROM dicom_binding_policies
            WHERE observation_id = :observation_id
            LIMIT 1
            """,
            {"observation_id": observation_id}
        )

        row = result.fetchone()
        if not row:
            return None

        return DicomBindingPolicy(
            id=row[0],
            instance_id=row[1],
            observation_id=row[2],
            binding_status=row[3],
            target_type=row[4],
            target_id=row[5],
            target_uri=row[6],
            error_code=row[7] or "",
            error_detail=row[8] or "",
            bound_at=row[9],
            retry_count=row[10] or 0,
            created_at=row[11],
            updated_at=row[12],
        )

    async def _get_binding_by_id(
        self,
        binding_id: int,
    ) -> Optional[Any]:  # Optional[DicomBindingPolicy]
        """
        Get binding record by ID.

        Args:
            binding_id: The binding ID

        Returns:
            DicomBindingPolicy if found, None otherwise
        """
        from dicom_ingestion.models.binding_policy import DicomBindingPolicy

        result = self._session.execute(
            """
            SELECT
                id,
                instance_id,
                observation_id,
                binding_status,
                target_type,
                target_id,
                target_uri,
                error_code,
                error_detail,
                bound_at,
                retry_count,
                created_at,
                updated_at
            FROM dicom_binding_policies
            WHERE id = :binding_id
            """,
            {"binding_id": binding_id}
        )

        row = result.fetchone()
        if not row:
            return None

        return DicomBindingPolicy(
            id=row[0],
            instance_id=row[1],
            observation_id=row[2],
            binding_status=row[3],
            target_type=row[4],
            target_id=row[5],
            target_uri=row[6],
            error_code=row[7] or "",
            error_detail=row[8] or "",
            bound_at=row[9],
            retry_count=row[10] or 0,
            created_at=row[11],
            updated_at=row[12],
        )

    async def _persist_binding(
        self,
        instance_id: int,
        observation_id: int,
        status: str,
    ) -> int:
        """
        Persist a new binding record.

        Args:
            instance_id: The instance ID
            observation_id: The observation ID
            status: Initial binding status

        Returns:
            The ID of the persisted binding
        """
        result = self._session.execute(
            """
            INSERT INTO dicom_binding_policies (
                instance_id,
                observation_id,
                binding_status,
                created_at,
                updated_at
            ) VALUES (
                :instance_id,
                :observation_id,
                :status,
                NOW(),
                NOW()
            )
            ON CONFLICT (observation_id) DO UPDATE SET
                updated_at = NOW()
            RETURNING id
            """,
            {
                "instance_id": instance_id,
                "observation_id": observation_id,
                "status": status,
            }
        )
        return result.fetchone()[0]

    async def _update_binding_status(
        self,
        binding: Any,  # DicomBindingPolicy
    ) -> None:
        """
        Update binding record status.

        Args:
            binding: The binding to update
        """
        self._session.execute(
            """
            UPDATE dicom_binding_policies
            SET binding_status = :status,
                target_type = :target_type,
                target_id = :target_id,
                target_uri = :target_uri,
                error_code = :error_code,
                error_detail = :error_detail,
                bound_at = :bound_at,
                retry_count = :retry_count,
                updated_at = NOW()
            WHERE id = :binding_id
            """,
            {
                "binding_id": binding.id,
                "status": binding.binding_status,
                "target_type": binding.target_type,
                "target_id": binding.target_id,
                "target_uri": binding.target_uri,
                "error_code": binding.error_code or None,
                "error_detail": binding.error_detail or None,
                "bound_at": binding.bound_at,
                "retry_count": binding.retry_count,
            }
        )

    async def get_summary_for_job(
        self,
        job_id: int,
    ) -> Any:  # BindingPolicySummary
        """
        Get binding summary for an ingestion job.

        Args:
            job_id: The ingestion job ID

        Returns:
            BindingPolicySummary
        """
        from dicom_ingestion.models.binding_policy import (
            BindingPolicySummary,
            BindingStatus,
        )

        result = self._session.execute(
            """
            SELECT
                bp.binding_status,
                bp.target_type,
                COUNT(*) as cnt
            FROM dicom_binding_policies bp
            JOIN dicom_instance_observations o ON o.id = bp.observation_id
            WHERE o.ingestion_item_id IN (
                SELECT id FROM dicom_ingestion_items
                WHERE ingestion_job_id = :job_id
            )
            GROUP BY bp.binding_status, bp.target_type
            """,
            {"job_id": job_id}
        )

        summary = BindingPolicySummary()
        by_type: Dict[str, int] = {}

        for row in result.fetchall():
            status, target_type, count = row

            summary.total_instances += count

            if status == BindingStatus.BOUND.value:
                summary.bound_count += count
            elif status == BindingStatus.FAILED.value:
                summary.failed_count += count
            elif status == BindingStatus.PENDING.value:
                summary.pending_count += count
            elif status == BindingStatus.NOT_APPLICABLE.value:
                summary.not_applicable_count += count

            if target_type:
                if target_type not in by_type:
                    by_type[target_type] = 0
                by_type[target_type] += count

        summary.by_target_type = by_type
        return summary
