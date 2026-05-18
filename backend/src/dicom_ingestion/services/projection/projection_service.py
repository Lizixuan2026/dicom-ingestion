"""Projection service for DICOM ingestion.

This module provides the ProjectionService which builds and queries read models
(projections) from the source-of-truth canonical data.

C5: Projection Foundation - Read models/projections rebuild from source-of-truth events/state.
"""
from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Union

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


@dataclass
class ProjectionBuildResult:
    """Result of building a projection for a single instance.

    Attributes:
        success: Whether projection build was successful
        instance_id: The instance ID
        projection_version: Version of projection schema used
        built_at: Timestamp when projection was built
        source_checksum: Checksum of source data for verification
        error_code: Error code if build failed
        error_detail: Detailed error message if failed
    """
    success: bool = False
    instance_id: Optional[int] = None
    projection_version: str = "1.0.0"
    built_at: datetime = field(default_factory=datetime.utcnow)
    source_checksum: str = ""
    error_code: str = ""
    error_detail: str = ""


@dataclass
class ProjectionQueryResult:
    """Result of querying projections.

    Attributes:
        items: List of projection records
        total_count: Total matching records (for pagination)
        page: Current page number
        per_page: Records per page
        has_more: Whether more records exist
    """
    items: List[Dict[str, Any]] = field(default_factory=list)
    total_count: int = 0
    page: int = 1
    per_page: int = 100
    has_more: bool = False


@dataclass
class ProjectionRebuildRequest:
    """Request to rebuild projections for a set of instances.

    Attributes:
        instance_ids: Specific instance IDs to rebuild (None = all)
        study_instance_uid: Filter by study UID
        series_instance_uid: Filter by series UID
        from_date: Only rebuild instances observed after this date
        force: Rebuild even if projection is current
        batch_size: Number of instances to process per batch
    """
    instance_ids: Optional[List[int]] = None
    study_instance_uid: Optional[str] = None
    series_instance_uid: Optional[str] = None
    from_date: Optional[datetime] = None
    force: bool = False
    batch_size: int = 100


class ProjectionService:
    """Service for building and querying DICOM projections.

    Responsibilities (C5):
    - Build core projections from source-of-truth canonical data
    - Query projections with filtering and pagination
    - Rebuild projections on demand from canonical observations
    - Maintain projection versioning for schema evolution

    Projection Invariants:
    - Projections are read-only views derived from canonical data
    - Projections can always be rebuilt from source-of-truth
    - Projection version tracks schema compatibility
    """

    PROJECTION_VERSION = "1.0.0"
    METADATA_EXTRACTOR_VERSION = "dicom-ingestion-1.0.0"

    def __init__(
        self,
        session: Session,
    ) -> None:
        """Initialize the projection service.

        Args:
            session: SQLAlchemy session for database operations
        """
        self._session = session
        self._logger = logger

    async def build_projection(self, instance_id: int) -> ProjectionBuildResult:
        """Build or rebuild projection for a single instance.

        This method reads the canonical observation for an instance
        and materializes a read-optimized projection record.

        Args:
            instance_id: The instance ID to build projection for

        Returns:
            ProjectionBuildResult with build status
        """
        result = ProjectionBuildResult(instance_id=instance_id)

        try:
            # Fetch canonical data for this instance
            canonical_data = await self._fetch_canonical_data(instance_id)
            if not canonical_data:
                result.error_code = "CanonicalDataNotFound"
                result.error_detail = f"No canonical observation found for instance {instance_id}"
                return result

            # Calculate source checksum for verification
            source_checksum = self._calculate_source_checksum(canonical_data)
            result.source_checksum = source_checksum

            # Check if projection exists and is current
            if not self._should_rebuild(instance_id, source_checksum):
                result.success = True
                result.projection_version = self.PROJECTION_VERSION
                return result

            # Build projection record
            projection_data = self._build_projection_record(canonical_data)

            # Upsert projection
            await self._upsert_projection(instance_id, projection_data, source_checksum)

            result.success = True
            result.projection_version = self.PROJECTION_VERSION
            result.built_at = datetime.utcnow()

            self._logger.debug(
                "Built projection for instance %s (version %s)",
                instance_id, self.PROJECTION_VERSION
            )

        except Exception as e:
            self._logger.exception("Failed to build projection for instance %s", instance_id)
            result.error_code = "ProjectionBuildFailed"
            result.error_detail = str(e)

        return result

    async def query_projections(
        self,
        study_instance_uid: Optional[str] = None,
        series_instance_uid: Optional[str] = None,
        sop_instance_uid: Optional[str] = None,
        modality: Optional[str] = None,
        study_date_from: Optional[datetime] = None,
        study_date_to: Optional[datetime] = None,
        binding_status: Optional[str] = None,
        page: int = 1,
        per_page: int = 100,
    ) -> ProjectionQueryResult:
        """Query projections with filters.

        Args:
            study_instance_uid: Filter by study UID
            series_instance_uid: Filter by series UID
            sop_instance_uid: Filter by SOP UID
            modality: Filter by modality (CT, MR, etc.)
            study_date_from: Filter by study date range start
            study_date_to: Filter by study date range end
            binding_status: Filter by binding status
            page: Page number (1-based)
            per_page: Records per page

        Returns:
            ProjectionQueryResult with matching records
        """
        result = ProjectionQueryResult(page=page, per_page=per_page)

        try:
            # Build WHERE clause dynamically
            where_conditions = []
            params: Dict[str, Any] = {}

            if study_instance_uid:
                where_conditions.append("study_instance_uid = :study_uid")
                params["study_uid"] = study_instance_uid

            if series_instance_uid:
                where_conditions.append("series_instance_uid = :series_uid")
                params["series_uid"] = series_instance_uid

            if sop_instance_uid:
                where_conditions.append("sop_instance_uid = :sop_uid")
                params["sop_uid"] = sop_instance_uid

            if modality:
                where_conditions.append("modality = :modality")
                params["modality"] = modality

            if study_date_from:
                where_conditions.append("study_date >= :date_from")
                params["date_from"] = study_date_from

            if study_date_to:
                where_conditions.append("study_date <= :date_to")
                params["date_to"] = study_date_to

            if binding_status:
                where_conditions.append("binding_status = :binding_status")
                params["binding_status"] = binding_status

            where_clause = " AND ".join(where_conditions) if where_conditions else "1=1"

            # Count total
            count_sql = f"""
                SELECT COUNT(*) FROM dicom_core_projections
                WHERE {where_clause}
            """
            count_result = self._session.execute(count_sql, params)
            result.total_count = count_result.scalar() or 0

            # Query records
            offset = (page - 1) * per_page
            query_sql = f"""
                SELECT
                    instance_id,
                    study_instance_uid,
                    series_instance_uid,
                    sop_instance_uid,
                    modality,
                    study_date,
                    object_class_family,
                    binding_status,
                    duplicate_flags,
                    reference_resolution_status,
                    metadata_extractor_version,
                    projection_version,
                    projection_built_at,
                    projection_source_checksum
                FROM dicom_core_projections
                WHERE {where_clause}
                ORDER BY instance_id
                LIMIT :limit OFFSET :offset
            """
            query_params = {**params, "limit": per_page, "offset": offset}

            rows = self._session.execute(query_sql, query_params)

            for row in rows:
                result.items.append({
                    "instance_id": row[0],
                    "study_instance_uid": row[1],
                    "series_instance_uid": row[2],
                    "sop_instance_uid": row[3],
                    "modality": row[4],
                    "study_date": row[5],
                    "object_class_family": row[6],
                    "binding_status": row[7],
                    "duplicate_flags": row[8],
                    "reference_resolution_status": row[9],
                    "metadata_extractor_version": row[10],
                    "projection_version": row[11],
                    "projection_built_at": row[12],
                    "projection_source_checksum": row[13],
                })

            result.has_more = len(result.items) == per_page and (offset + len(result.items)) < result.total_count

        except Exception as e:
            self._logger.exception("Failed to query projections")
            result.error_code = "ProjectionQueryFailed"
            result.error_detail = str(e)

        return result

    async def rebuild_projections(
        self,
        request: ProjectionRebuildRequest,
    ) -> List[ProjectionBuildResult]:
        """Rebuild projections for multiple instances.

        This method rebuilds projections from source-of-truth data,
        ensuring read models are consistent with canonical state.

        Args:
            request: Rebuild request parameters

        Returns:
            List of ProjectionBuildResult for each instance processed
        """
        results: List[ProjectionBuildResult] = []

        try:
            # Get list of instance IDs to rebuild
            instance_ids = await self._get_instance_ids_for_rebuild(request)

            self._logger.info(
                "Rebuilding projections for %d instances (force=%s)",
                len(instance_ids), request.force
            )

            # Process in batches
            for i in range(0, len(instance_ids), request.batch_size):
                batch = instance_ids[i:i + request.batch_size]

                for instance_id in batch:
                    build_result = await self.build_projection(instance_id)
                    results.append(build_result)

                self._logger.debug(
                    "Processed batch %d-%d of %d instances",
                    i, min(i + request.batch_size, len(instance_ids)), len(instance_ids)
                )

        except Exception as e:
            self._logger.exception("Failed to rebuild projections")
            # Add error result if not already added
            if not results:
                error_result = ProjectionBuildResult()
                error_result.error_code = "RebuildFailed"
                error_result.error_detail = str(e)
                results.append(error_result)

        return results

    async def get_projection_stats(self) -> Dict[str, Any]:
        """Get statistics about projections.

        Returns:
            Dictionary with projection statistics
        """
        try:
            # Count projections by version
            version_sql = """
                SELECT projection_version, COUNT(*) as count
                FROM dicom_core_projections
                GROUP BY projection_version
            """
            version_rows = self._session.execute(version_sql)
            versions = {row[0]: row[1] for row in version_rows}

            # Count instances without projections
            missing_sql = """
                SELECT COUNT(*)
                FROM dicom_instances i
                LEFT JOIN dicom_core_projections p ON p.instance_id = i.id
                WHERE p.instance_id IS NULL
                  AND i.current_canonical_observation_id IS NOT NULL
            """
            missing_result = self._session.execute(missing_sql)
            missing_count = missing_result.scalar() or 0

            # Count total instances with canonical observations
            total_sql = """
                SELECT COUNT(*)
                FROM dicom_instances
                WHERE current_canonical_observation_id IS NOT NULL
            """
            total_result = self._session.execute(total_sql)
            total_canonical = total_result.scalar() or 0

            return {
                "total_projections": sum(versions.values()),
                "version_distribution": versions,
                "instances_without_projections": missing_count,
                "total_canonical_instances": total_canonical,
                "coverage_percentage": (
                    (total_canonical - missing_count) / total_canonical * 100
                    if total_canonical > 0 else 0
                ),
            }

        except Exception as e:
            self._logger.exception("Failed to get projection stats")
            return {
                "error": str(e),
                "total_projections": 0,
            }

    async def _fetch_canonical_data(self, instance_id: int) -> Optional[Dict[str, Any]]:
        """Fetch canonical data for an instance.

        Args:
            instance_id: The instance ID

        Returns:
            Dictionary with canonical data or None if not found
        """
        sql = """
            SELECT
                i.id as instance_id,
                i.sop_instance_uid,
                i.sop_class_uid,
                i.current_canonical_observation_id,
                s.id as series_id,
                s.series_instance_uid,
                s.modality,
                s.object_class_family,
                st.id as study_id,
                st.study_instance_uid,
                st.study_date,
                st.patient_id,
                st.patient_name,
                o.id as observation_id,
                o.whole_file_sha256,
                o.pixel_digest,
                o.raw_tag_set_json,
                o.is_canonical,
                bp.project_id,
                bp.user_id,
                bp.binding_status
            FROM dicom_instances i
            JOIN dicom_series s ON s.id = i.series_id
            JOIN dicom_studies st ON st.id = i.study_id
            LEFT JOIN dicom_instance_observations o ON o.id = i.current_canonical_observation_id
            LEFT JOIN dicom_binding_policies bp ON bp.instance_id = i.id
            WHERE i.id = :instance_id
              AND o.id IS NOT NULL
        """
        result = self._session.execute(sql, {"instance_id": instance_id})
        row = result.fetchone()

        if not row:
            return None

        return {
            "instance_id": row[0],
            "sop_instance_uid": row[1],
            "sop_class_uid": row[2],
            "canonical_observation_id": row[3],
            "series_id": row[4],
            "series_instance_uid": row[5],
            "modality": row[6],
            "object_class_family": row[7],
            "study_id": row[8],
            "study_instance_uid": row[9],
            "study_date": row[10],
            "patient_id": row[11],
            "patient_name": row[12],
            "observation_id": row[13],
            "whole_file_sha256": row[14],
            "pixel_digest": row[15],
            "raw_tag_set_json": row[16],
            "is_canonical": row[17],
            "project_id": row[18],
            "user_id": row[19],
            "binding_status": row[20] or "unbound",
        }

    def _calculate_source_checksum(self, canonical_data: Dict[str, Any]) -> str:
        """Calculate checksum of canonical source data.

        Args:
            canonical_data: Dictionary with canonical data

        Returns:
            SHA256 checksum of canonical data
        """
        # Create deterministic string representation
        checksum_input = json.dumps(canonical_data, sort_keys=True, default=str)
        return hashlib.sha256(checksum_input.encode("utf-8")).hexdigest()[:32]

    def _should_rebuild(self, instance_id: int, source_checksum: str) -> bool:
        """Check if projection needs to be rebuilt.

        Args:
            instance_id: The instance ID
            source_checksum: Current source checksum

        Returns:
            True if rebuild is needed
        """
        sql = """
            SELECT projection_source_checksum, projection_version
            FROM dicom_core_projections
            WHERE instance_id = :instance_id
        """
        result = self._session.execute(sql, {"instance_id": instance_id})
        row = result.fetchone()

        if not row or row[0] is None:
            return True  # No projection exists

        existing_checksum, existing_version = row

        # Rebuild if checksum changed or version mismatch
        return (
            existing_checksum != source_checksum
            or existing_version != self.PROJECTION_VERSION
        )

    def _build_projection_record(self, canonical_data: Dict[str, Any]) -> Dict[str, Any]:
        """Build projection record from canonical data.

        Args:
            canonical_data: Dictionary with canonical data

        Returns:
            Dictionary with projection fields
        """
        # Parse duplicate flags from raw tags if available
        duplicate_flags = None
        if canonical_data.get("raw_tag_set_json"):
            try:
                raw_tags = canonical_data["raw_tag_set_json"]
                if isinstance(raw_tags, str):
                    raw_tags = json.loads(raw_tags)
                # Duplicate flags would be populated by duplicate detection service
                duplicate_flags = raw_tags.get("_duplicate_flags")
            except (json.JSONDecodeError, TypeError):
                pass

        return {
            "study_instance_uid": canonical_data.get("study_instance_uid"),
            "series_instance_uid": canonical_data.get("series_instance_uid"),
            "sop_instance_uid": canonical_data.get("sop_instance_uid"),
            "modality": canonical_data.get("modality"),
            "study_date": canonical_data.get("study_date"),
            "object_class_family": canonical_data.get("object_class_family"),
            "binding_status": canonical_data.get("binding_status", "unbound"),
            "duplicate_flags": duplicate_flags,
            "reference_resolution_status": "pending",  # Would be populated by reference service
            "metadata_extractor_version": self.METADATA_EXTRACTOR_VERSION,
            "projection_version": self.PROJECTION_VERSION,
        }

    async def _upsert_projection(
        self,
        instance_id: int,
        projection_data: Dict[str, Any],
        source_checksum: str,
    ) -> None:
        """Upsert projection record.

        Args:
            instance_id: The instance ID
            projection_data: Projection fields
            source_checksum: Source data checksum
        """
        sql = """
            INSERT INTO dicom_core_projections (
                instance_id,
                study_instance_uid,
                series_instance_uid,
                sop_instance_uid,
                modality,
                study_date,
                object_class_family,
                binding_status,
                duplicate_flags,
                reference_resolution_status,
                metadata_extractor_version,
                projection_version,
                projection_built_at,
                projection_source_checksum
            ) VALUES (
                :instance_id,
                :study_instance_uid,
                :series_instance_uid,
                :sop_instance_uid,
                :modality,
                :study_date,
                :object_class_family,
                :binding_status,
                :duplicate_flags,
                :reference_resolution_status,
                :metadata_extractor_version,
                :projection_version,
                NOW(),
                :source_checksum
            )
            ON CONFLICT (instance_id) DO UPDATE SET
                study_instance_uid = EXCLUDED.study_instance_uid,
                series_instance_uid = EXCLUDED.series_instance_uid,
                sop_instance_uid = EXCLUDED.sop_instance_uid,
                modality = EXCLUDED.modality,
                study_date = EXCLUDED.study_date,
                object_class_family = EXCLUDED.object_class_family,
                binding_status = EXCLUDED.binding_status,
                duplicate_flags = EXCLUDED.duplicate_flags,
                reference_resolution_status = EXCLUDED.reference_resolution_status,
                metadata_extractor_version = EXCLUDED.metadata_extractor_version,
                projection_version = EXCLUDED.projection_version,
                projection_built_at = NOW(),
                projection_source_checksum = EXCLUDED.projection_source_checksum
        """

        params = {
            "instance_id": instance_id,
            "source_checksum": source_checksum,
            **projection_data,
        }

        self._session.execute(sql, params)

    async def _get_instance_ids_for_rebuild(
        self,
        request: ProjectionRebuildRequest,
    ) -> List[int]:
        """Get list of instance IDs to rebuild.

        Args:
            request: Rebuild request

        Returns:
            List of instance IDs
        """
        if request.instance_ids:
            return request.instance_ids

        where_conditions = ["i.current_canonical_observation_id IS NOT NULL"]
        params: Dict[str, Any] = {}

        if request.study_instance_uid:
            where_conditions.append("st.study_instance_uid = :study_uid")
            params["study_uid"] = request.study_instance_uid

        if request.series_instance_uid:
            where_conditions.append("s.series_instance_uid = :series_uid")
            params["series_uid"] = request.series_instance_uid

        if request.from_date:
            where_conditions.append("o.observed_at >= :from_date")
            params["from_date"] = request.from_date

        if not request.force:
            # Only instances without current projections
            where_conditions.append(
                """(
                    p.instance_id IS NULL
                    OR p.projection_version != :projection_version
                )"""
            )
            params["projection_version"] = self.PROJECTION_VERSION

        where_clause = " AND ".join(where_conditions)

        sql = f"""
            SELECT DISTINCT i.id
            FROM dicom_instances i
            JOIN dicom_series s ON s.id = i.series_id
            JOIN dicom_studies st ON st.id = i.study_id
            JOIN dicom_instance_observations o ON o.id = i.current_canonical_observation_id
            LEFT JOIN dicom_core_projections p ON p.instance_id = i.id
            WHERE {where_clause}
            ORDER BY i.id
        """

        result = self._session.execute(sql, params)
        return [row[0] for row in result]
