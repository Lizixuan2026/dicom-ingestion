"""Canonical persistence service for DICOM ingestion.

This module provides the CanonicalPersistenceService which materializes
accepted intake candidates to canonical ingest units, extracting DICOM tags
and persisting them to canonical tables with proper provenance tracking.
"""
from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import TYPE_CHECKING, Any, Optional, Dict, List

if TYPE_CHECKING:
    from sqlalchemy.orm import Session
    from dicom_ingestion.models.ingestion_item import IngestionItem
    from dicom_ingestion.services.parser.dicom_parser import ParsedDicomHeader

logger = logging.getLogger(__name__)


@dataclass
class PersistenceResult:
    """Result of canonical persistence operation.

    Attributes:
        success: Whether persistence was successful
        study_id: ID of the study record (if created/found)
        series_id: ID of the series record (if created/found)
        instance_id: ID of the instance record (if created/found)
        observation_id: ID of the observation record (if created)
        is_new_canonical: True if this observation became the canonical one
        canonical_policy_rationale: Reason for canonical pointer selection
        duplicate_check_result: Result of duplicate detection (C1)
        private_tag_result: Result of private tag persistence (C2)
        reference_extraction_result: Result of reference edge extraction (C3)
        binding_policy_result: Result of binding policy creation (C4)
        error_code: Error code if persistence failed
        error_detail: Detailed error message if failed
    """
    success: bool = False
    study_id: Optional[int] = None
    series_id: Optional[int] = None
    instance_id: Optional[int] = None
    observation_id: Optional[int] = None
    is_new_canonical: bool = False
    canonical_policy_rationale: str = ""
    duplicate_check_result: Optional[Dict[str, Any]] = None
    private_tag_result: Optional[Dict[str, Any]] = None
    reference_extraction_result: Optional[Dict[str, Any]] = None
    binding_policy_result: Optional[Dict[str, Any]] = None
    error_code: str = ""
    error_detail: str = ""


@dataclass
class CanonicalFailureEnvelope:
    """Failure envelope for deterministic persistence failures.

    Captures all information needed to understand and potentially
    retry a failed persistence operation.
    """
    item_id: int
    failure_stage: str
    error_code: str
    error_message: str
    parsed_tags: dict[str, Any] = field(default_factory=dict)
    raw_bytes_hash: str = ""
    timestamp: datetime = field(default_factory=datetime.utcnow)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for storage."""
        return {
            "item_id": self.item_id,
            "failure_stage": self.failure_stage,
            "error_code": self.error_code,
            "error_message": self.error_message,
            "parsed_tags": self.parsed_tags,
            "raw_bytes_hash": self.raw_bytes_hash,
            "timestamp": self.timestamp.isoformat(),
        }


class CanonicalPersistenceService:
    """Service for persisting canonical DICOM data.

    Responsibilities:
    - Read bytes from raw storage via immutable pointers
    - Parse DICOM envelope safely
    - Persist canonical study/series/instance-level facts
    - Create observations with proper canonical marking
    - Detect and record duplicate facts (C1)
    - Persist private tags with redaction policy (C2)
    - Extract and store reference edges (C3)
    - Create binding policy records (C4)
    - Preserve parse provenance and deterministic failure envelopes

    Canonical Observation Policy:
    - First accepted observation becomes canonical
    - Later observations do not silently replace it
    - Each instance has exactly one current canonical observation
    - Policy rationale is recorded for auditability
    """

    def __init__(
        self,
        session: Session,
        raw_object_store: Any,
        enable_duplicate_detection: bool = True,
        enable_private_tag_persistence: bool = True,
        enable_reference_extraction: bool = True,
        enable_binding_policy: bool = True,
    ) -> None:
        """Initialize the canonical persistence service.

        Args:
            session: SQLAlchemy session for database operations
            raw_object_store: RawObjectStore for retrieving raw bytes
            enable_duplicate_detection: Whether to enable C1 duplicate detection
            enable_private_tag_persistence: Whether to enable C2 private tag persistence
            enable_reference_extraction: Whether to enable C3 reference edge extraction
            enable_binding_policy: Whether to enable C4 binding policy creation
        """
        self._session = session
        self._raw_store = raw_object_store
        self._logger = logger

        # Batch 4 feature flags
        self._enable_duplicate_detection = enable_duplicate_detection
        self._enable_private_tag_persistence = enable_private_tag_persistence
        self._enable_reference_extraction = enable_reference_extraction
        self._enable_binding_policy = enable_binding_policy

        # Lazy-initialized Batch 4 services
        self._duplicate_service: Optional[Any] = None
        self._private_tag_service: Optional[Any] = None
        self._reference_service: Optional[Any] = None
        self._binding_service: Optional[Any] = None

    def _get_duplicate_service(self) -> Any:
        """Lazy initialization of duplicate detection service."""
        if self._duplicate_service is None and self._enable_duplicate_detection:
            from dicom_ingestion.services.detection.duplicate_detection import (
                DuplicateDetectionService
            )
            self._duplicate_service = DuplicateDetectionService(self._session)
        return self._duplicate_service

    def _get_private_tag_service(self) -> Any:
        """Lazy initialization of private tag persistence service."""
        if self._private_tag_service is None and self._enable_private_tag_persistence:
            from dicom_ingestion.services.persistence.private_tag_persistence import (
                PrivateTagPersistenceService
            )
            self._private_tag_service = PrivateTagPersistenceService(self._session)
        return self._private_tag_service

    def _get_reference_service(self) -> Any:
        """Lazy initialization of reference extraction service."""
        if self._reference_service is None and self._enable_reference_extraction:
            from dicom_ingestion.services.classifier.reference_extraction import (
                ReferenceExtractionService
            )
            self._reference_service = ReferenceExtractionService(self._session)
        return self._reference_service

    def _get_binding_service(self) -> Any:
        """Lazy initialization of binding policy service."""
        if self._binding_service is None and self._enable_binding_policy:
            from dicom_ingestion.services.binding.binding_policy import (
                BindingPolicyService
            )
            self._binding_service = BindingPolicyService(self._session)
        return self._binding_service

    async def persist(
        self,
        item: IngestionItem,
        parsed_header: ParsedDicomHeader,
        binding_context: Optional[Any] = None,
    ) -> PersistenceResult:
        """Persist an ingestion item to canonical storage.

        This method implements the canonical persistence pipeline:
        1. Extract UIDs from parsed header
        2. Get or create study record
        3. Get or create series record
        4. Get or create instance record
        5. Create observation record
        6. Mark as canonical if first observation for this instance
        7. C1: Detect and record duplicate facts
        8. C2: Persist private tags with redaction policy
        9. C3: Extract and store reference edges
        10. C4: Create binding policy record (with binding_context)

        Args:
            item: The ingestion item to persist
            parsed_header: The parsed DICOM header
            binding_context: Optional BindingContext with project_id/user_id for C4 binding

        Returns:
            PersistenceResult with IDs and status
        """
        result = PersistenceResult()

        try:
            # Validate required tags are present
            required_tags = self._extract_required_tags(parsed_header)
            missing = self._validate_required_tags(required_tags)
            if missing:
                result.error_code = "MissingRequiredDicomTag"
                result.error_detail = f"Missing required tags: {', '.join(missing)}"
                return result

            # Get or create study
            study_id = await self._get_or_create_study(required_tags)
            result.study_id = study_id

            # Get or create series
            series_id = await self._get_or_create_series(study_id, required_tags)
            result.series_id = series_id

            # Get or create instance
            instance_id = await self._get_or_create_instance(
                study_id, series_id, required_tags, parsed_header
            )
            result.instance_id = instance_id

            # Create observation
            observation_id = await self._create_observation(
                instance_id, item, parsed_header, required_tags
            )
            result.observation_id = observation_id

            # Try to mark as canonical if no canonical currently exists
            result.is_new_canonical = await self._mark_canonical(instance_id, observation_id)

            # Record canonical policy rationale
            if result.is_new_canonical:
                result.canonical_policy_rationale = "first_observation_becomes_canonical"
            else:
                result.canonical_policy_rationale = "canonical_already_exists"

            # C1: Duplicate detection
            if self._enable_duplicate_detection:
                await self._execute_duplicate_detection(
                    result, instance_id, observation_id, item, parsed_header
                )

            # C2: Private tag persistence
            if self._enable_private_tag_persistence:
                await self._execute_private_tag_persistence(
                    result, observation_id, parsed_header
                )

            # C3: Reference edge extraction
            if self._enable_reference_extraction:
                await self._execute_reference_extraction(
                    result, instance_id, observation_id, parsed_header
                )

            # C4: Binding policy creation
            if self._enable_binding_policy:
                await self._execute_binding_policy(
                    result, instance_id, observation_id, binding_context
                )

            result.success = True
            self._logger.info(
                "Successfully persisted item %s: study=%s, series=%s, instance=%s, observation=%s",
                item.id, study_id, series_id, instance_id, observation_id
            )

        except Exception as e:
            self._logger.exception("Failed to persist item %s", item.id)
            result.error_code = "MetadataPersistenceFailed"
            result.error_detail = str(e)

        return result

    async def _execute_duplicate_detection(
        self,
        result: PersistenceResult,
        instance_id: int,
        observation_id: int,
        item: IngestionItem,
        parsed_header: Any,
    ) -> None:
        """Execute C1 duplicate detection.

        Args:
            result: Persistence result to populate
            instance_id: The instance ID
            observation_id: The observation ID
            item: The ingestion item
            parsed_header: The parsed DICOM header
        """
        try:
            from dicom_ingestion.services.detection.duplicate_detection import (
                DuplicateDetectionContext
            )

            dup_service = self._get_duplicate_service()
            if dup_service is None:
                return

            ctx = DuplicateDetectionContext(
                observation_id=observation_id,
                instance_id=instance_id,
                sop_instance_uid=parsed_header.required_tags.get("SOPInstanceUID", ""),
                whole_file_sha256=item.raw_object_sha256,
                pixel_digest=parsed_header.pixel_digest,  # C1 fix: pixel digest for content duplicate detection
                ingestion_item_id=item.id,
            )

            dup_result = await dup_service.check_and_record_duplicates(ctx)
            result.duplicate_check_result = dup_result.to_dict()

            self._logger.debug(
                "Duplicate check for observation %s: has_duplicates=%s",
                observation_id, dup_result.has_duplicates
            )

        except Exception as e:
            self._logger.warning("Duplicate detection failed: %s", e)
            result.duplicate_check_result = {"error": str(e)}

    async def _execute_private_tag_persistence(
        self,
        result: PersistenceResult,
        observation_id: int,
        parsed_header: Any,
    ) -> None:
        """Execute C2 private tag persistence.

        Args:
            result: Persistence result to populate
            observation_id: The observation ID
            parsed_header: The parsed DICOM header
        """
        try:
            pt_service = self._get_private_tag_service()
            if pt_service is None:
                return

            pt_result = await pt_service.persist_private_tags(
                observation_id=observation_id,
                private_tags=parsed_header.private_tags,
            )
            result.private_tag_result = pt_result.to_dict()

            self._logger.debug(
                "Private tag persistence for observation %s: persisted=%d, redacted=%d",
                observation_id, pt_result.persisted_count, pt_result.redacted_count
            )

        except Exception as e:
            self._logger.warning("Private tag persistence failed: %s", e)
            result.private_tag_result = {"error": str(e)}

    async def _execute_reference_extraction(
        self,
        result: PersistenceResult,
        instance_id: int,
        observation_id: int,
        parsed_header: Any,
    ) -> None:
        """Execute C3 reference edge extraction.

        Args:
            result: Persistence result to populate
            instance_id: The instance ID
            observation_id: The observation ID (for logging)
            parsed_header: The parsed DICOM header
        """
        try:
            ref_service = self._get_reference_service()
            if ref_service is None:
                return

            ref_result = await ref_service.extract_and_persist(
                from_instance_id=instance_id,
                raw_tags=parsed_header.raw_tags,
                resolve_immediately=True,
            )
            result.reference_extraction_result = ref_result.to_dict()

            self._logger.debug(
                "Reference extraction for instance %s: extracted=%d, resolved=%d",
                instance_id, ref_result.extracted_count, ref_result.resolved_count
            )

        except Exception as e:
            self._logger.warning("Reference extraction failed: %s", e)
            result.reference_extraction_result = {"error": str(e)}

    async def _execute_binding_policy(
        self,
        result: PersistenceResult,
        instance_id: int,
        observation_id: int,
        binding_context: Optional[Any] = None,
    ) -> None:
        """Execute C4 binding policy creation.

        Args:
            result: Persistence result to populate
            instance_id: The instance ID
            observation_id: The observation ID
            binding_context: Optional BindingContext with project_id/user_id
        """
        try:
            from dicom_ingestion.models.binding_policy import BindingContext

            bind_service = self._get_binding_service()
            if bind_service is None:
                return

            # Handle missing binding context
            if binding_context is None:
                # Strategy: Use system default with explicit reason code
                self._logger.warning(
                    "Binding context missing for instance %s, using system default",
                    instance_id
                )
                binding_context = BindingContext(
                    project_id="system_default",
                    user_id="system",
                )
                # Record the fallback strategy in result
                if result.binding_policy_result is None:
                    result.binding_policy_result = {}
                result.binding_policy_result["context_fallback"] = "system_default"
                result.binding_policy_result["context_fallback_reason"] = "BINDING_CONTEXT_MISSING"

            bind_result = await bind_service.create_binding_record(
                instance_id=instance_id,
                observation_id=observation_id,
                context=binding_context,
            )

            # Merge binding result with fallback info if any
            result_dict = bind_result.to_dict()
            if isinstance(result.binding_policy_result, dict):
                result_dict.update(result.binding_policy_result)
            result.binding_policy_result = result_dict

            self._logger.debug(
                "Binding policy created for instance %s: binding_id=%s, project=%s, user=%s",
                instance_id,
                bind_result.binding_id,
                binding_context.project_id,
                binding_context.user_id
            )

        except Exception as e:
            self._logger.warning("Binding policy creation failed: %s", e)
            result.binding_policy_result = {"error": str(e)}

    def _extract_required_tags(self, parsed_header: ParsedDicomHeader) -> dict[str, Any]:
        """Extract required tags from parsed header.

        Args:
            parsed_header: The parsed DICOM header

        Returns:
            Dictionary of required tag names to values
        """
        tags = {}

        # Get from required_tags first, fallback to raw_tags
        source = parsed_header.required_tags if parsed_header.required_tags else parsed_header.raw_tags

        required_fields = [
            "SOPInstanceUID",
            "SOPClassUID",
            "StudyInstanceUID",
            "SeriesInstanceUID",
            "PatientID",
            "PatientName",
            "StudyDate",
            "StudyTime",
            "Modality",
            "SeriesNumber",
            "InstanceNumber",
            "TransferSyntaxUID",
        ]

        for field in required_fields:
            if field in source and source[field]:
                tags[field] = source[field]

        return tags

    def _validate_required_tags(self, tags: dict[str, Any]) -> list[str]:
        """Validate that all required tags are present.

        Args:
            tags: Dictionary of extracted tags

        Returns:
            List of missing required tag names
        """
        required = ["SOPInstanceUID", "SOPClassUID", "StudyInstanceUID", "SeriesInstanceUID"]
        missing = []

        for tag in required:
            if tag not in tags or not tags[tag]:
                missing.append(tag)

        return missing

    async def _get_or_create_study(self, tags: dict[str, Any]) -> int:
        """Get existing study or create new one.

        Args:
            tags: Dictionary of DICOM tags

        Returns:
            Study ID
        """
        study_uid = tags.get("StudyInstanceUID")

        # Try to find existing study
        result = self._session.execute(
            """
            SELECT id FROM dicom_studies WHERE study_instance_uid = :uid
            """,
            {"uid": study_uid}
        )
        row = result.fetchone()

        if row:
            return row[0]

        # Create new study
        result = self._session.execute(
            """
            INSERT INTO dicom_studies (
                study_instance_uid, patient_name, patient_id,
                study_date, study_time, accession_number, study_description,
                series_count, instance_count, ingestion_completeness_status,
                created_at, updated_at
            ) VALUES (
                :study_instance_uid, :patient_name, :patient_id,
                :study_date, :study_time, :accession_number, :study_description,
                0, 0, 'unknown',
                NOW(), NOW()
            )
            ON CONFLICT (study_instance_uid) DO UPDATE SET
                updated_at = NOW()
            RETURNING id
            """,
            {
                "study_instance_uid": study_uid,
                "patient_name": tags.get("PatientName"),
                "patient_id": tags.get("PatientID"),
                "study_date": tags.get("StudyDate"),
                "study_time": tags.get("StudyTime"),
                "accession_number": tags.get("AccessionNumber"),
                "study_description": tags.get("StudyDescription"),
            }
        )
        return result.fetchone()[0]

    async def _get_or_create_series(
        self, study_id: int, tags: dict[str, Any]
    ) -> int:
        """Get existing series or create new one.

        Args:
            study_id: Parent study ID
            tags: Dictionary of DICOM tags

        Returns:
            Series ID
        """
        series_uid = tags.get("SeriesInstanceUID")

        # Try to find existing series
        result = self._session.execute(
            """
            SELECT id FROM dicom_series WHERE series_instance_uid = :uid
            """,
            {"uid": series_uid}
        )
        row = result.fetchone()

        if row:
            return row[0]

        # Parse series number
        series_number = None
        if "SeriesNumber" in tags and tags["SeriesNumber"]:
            try:
                series_number = int(tags["SeriesNumber"])
            except (ValueError, TypeError):
                pass

        # Create new series
        result = self._session.execute(
            """
            INSERT INTO dicom_series (
                study_id, series_instance_uid, modality,
                series_number, series_description, frame_of_reference_uid,
                object_class_family, created_at, updated_at
            ) VALUES (
                :study_id, :series_instance_uid, :modality,
                :series_number, :series_description, :frame_of_reference_uid,
                :object_class_family, NOW(), NOW()
            )
            ON CONFLICT (series_instance_uid) DO UPDATE SET
                updated_at = NOW()
            RETURNING id
            """,
            {
                "study_id": study_id,
                "series_instance_uid": series_uid,
                "modality": tags.get("Modality"),
                "series_number": series_number,
                "series_description": tags.get("SeriesDescription"),
                "frame_of_reference_uid": tags.get("FrameOfReferenceUID"),
                "object_class_family": self._determine_object_class_family(tags.get("SOPClassUID", "")),
            }
        )
        return result.fetchone()[0]

    def _determine_object_class_family(self, sop_class_uid: str) -> Optional[str]:
        """Determine object class family from SOP Class UID.

        Args:
            sop_class_uid: SOP Class UID

        Returns:
            Object class family name or None
        """
        if not sop_class_uid:
            return None

        # Common SOP Class UID prefixes
        if "1.2.840.10008.5.1.4.1.1.2" in sop_class_uid:
            return "CT"
        elif "1.2.840.10008.5.1.4.1.1.4" in sop_class_uid:
            return "MR"
        elif "1.2.840.10008.5.1.4.1.1.1" in sop_class_uid:
            return "CR/DX"
        elif "1.2.840.10008.5.1.4.1.1.6" in sop_class_uid:
            return "US"
        elif "1.2.840.10008.5.1.4.1.1.7" in sop_class_uid:
            return "SC"
        elif "1.2.840.10008.5.1.4.1.1.128" in sop_class_uid:
            return "PET"
        elif "1.2.840.10008.5.1.4.1.1.481" in sop_class_uid:
            return "RT"
        elif "1.2.840.10008.5.1.4.1.1.88" in sop_class_uid:
            return "SR"
        else:
            return "OTHER"

    async def _get_or_create_instance(
        self, study_id: int, series_id: int, tags: dict[str, Any], parsed_header: Any
    ) -> int:
        """Get existing instance or create new one.

        Args:
            study_id: Parent study ID
            series_id: Parent series ID
            tags: Dictionary of DICOM tags
            parsed_header: Parsed DICOM header for additional metadata

        Returns:
            instance_id
        """
        sop_uid = tags.get("SOPInstanceUID")

        # Parse instance number
        instance_number = None
        if "InstanceNumber" in tags and tags["InstanceNumber"]:
            try:
                instance_number = int(tags["InstanceNumber"])
            except (ValueError, TypeError):
                pass

        # Check if pixel data is present
        pixel_data_present = False
        if hasattr(parsed_header, 'raw_tags'):
            raw_tags = parsed_header.raw_tags
            pixel_data_present = 'PixelData' in raw_tags or 'FloatPixelData' in raw_tags or 'DoubleFloatPixelData' in raw_tags

        # Create new instance
        result = self._session.execute(
            """
            INSERT INTO dicom_instances (
                study_id, series_id, sop_instance_uid, sop_class_uid,
                instance_number, transfer_syntax_uid, pixel_data_present,
                current_canonical_observation_id, ingestion_status,
                created_at, updated_at
            ) VALUES (
                :study_id, :series_id, :sop_instance_uid, :sop_class_uid,
                :instance_number, :transfer_syntax_uid, :pixel_data_present,
                NULL, 'pending',
                NOW(), NOW()
            )
            ON CONFLICT (sop_instance_uid) DO UPDATE SET
                updated_at = NOW()
            RETURNING id
            """,
            {
                "study_id": study_id,
                "series_id": series_id,
                "sop_instance_uid": sop_uid,
                "sop_class_uid": tags.get("SOPClassUID"),
                "instance_number": instance_number,
                "transfer_syntax_uid": tags.get("TransferSyntaxUID"),
                "pixel_data_present": pixel_data_present,
            }
        )
        return result.fetchone()[0]


    def _json_fallback_serializer(self, value: Any) -> str:
        """Fallback serializer for non-JSON-native tag values."""
        if isinstance(value, bytes):
            return value.decode("utf-8", errors="replace")
        if isinstance(value, (datetime, date)):
            return value.isoformat()
        return str(value)

    def _safe_json_dumps(self, raw_tag_set: Any, item_id: int) -> Optional[str]:
        """Safely serialize raw tag set to JSON.

        Tries strict JSON first, then falls back to permissive conversion.
        Returns None when serialization is impossible.
        """
        if not raw_tag_set:
            return None

        try:
            return json.dumps(raw_tag_set)
        except (TypeError, ValueError):
            pass

        try:
            return json.dumps(raw_tag_set, default=self._json_fallback_serializer)
        except (TypeError, ValueError) as exc:
            self._logger.warning(
                "Raw tag set serialization failed for item %s: %s",
                item_id,
                exc,
            )
            return None

    async def _create_observation(
        self,
        instance_id: int,
        item: IngestionItem,
        parsed_header: Any,
        tags: dict[str, Any],
    ) -> int:
        """Create observation record for this ingestion.

        Args:
            instance_id: Parent instance ID
            item: Ingestion item
            parsed_header: Parsed DICOM header
            tags: Extracted tags

        Returns:
            Observation ID
        """
        # Calculate hashes
        raw_bytes_hash = item.raw_object_sha256 if item.raw_object_sha256 else ""

        # Build raw tag set JSON
        raw_tag_set = {}
        if hasattr(parsed_header, 'raw_tags'):
            raw_tag_set = parsed_header.raw_tags

        result = self._session.execute(
            """
            INSERT INTO dicom_instance_observations (
                instance_id, ingestion_item_id, raw_object_uri,
                whole_file_sha256, pixel_digest, raw_tag_set_uri,
                raw_tag_set_json, is_canonical, observed_at,
                created_at, updated_at
            ) VALUES (
                :instance_id, :ingestion_item_id, :raw_object_uri,
                :whole_file_sha256, :pixel_digest, :raw_tag_set_uri,
                :raw_tag_set_json, FALSE, NOW(),
                NOW(), NOW()
            )
            RETURNING id
            """,
            {
                "instance_id": instance_id,
                "ingestion_item_id": item.id,
                "raw_object_uri": item.storage_uri,
                "whole_file_sha256": raw_bytes_hash,
                "pixel_digest": None,  # Would need pixel extraction for this
                "raw_tag_set_uri": None,  # Could store to object storage if needed
                "raw_tag_set_json": self._safe_json_dumps(raw_tag_set, item.id),
            }
        )
        return result.fetchone()[0]

    async def _mark_canonical(self, instance_id: int, observation_id: int) -> bool:
        """Mark an observation as canonical for an instance.

        This implements the canonical observation policy:
        - First observation becomes canonical
        - Instance's current_canonical_observation_id points to it

        Args:
            instance_id: Instance ID
            observation_id: Observation ID to mark as canonical
        """
        update_result = self._session.execute(
            """
            UPDATE dicom_instances
            SET current_canonical_observation_id = :observation_id,
                ingestion_status = 'canonical',
                updated_at = NOW()
            WHERE id = :instance_id
              AND current_canonical_observation_id IS NULL
            RETURNING id
            """,
            {
                "instance_id": instance_id,
                "observation_id": observation_id,
            }
        )
        updated_instance = update_result.fetchone()
        if not updated_instance:
            self._logger.info(
                "Canonical already exists for instance %s, observation %s remains non-canonical",
                instance_id,
                observation_id,
            )
            return False

        self._session.execute(
            """
            UPDATE dicom_instance_observations
            SET is_canonical = TRUE, updated_at = NOW()
            WHERE id = :observation_id
            """,
            {"observation_id": observation_id}
        )
        self._logger.info(
            "Marked observation %s as canonical for instance %s",
            observation_id, instance_id
        )
        return True

    async def validate_canonical(self, instance_id: int) -> bool:
        """Validate the canonical representation of an instance.

        Checks that the canonical observation invariant holds:
        - Instance has a current_canonical_observation_id set
        - The referenced observation has is_canonical = true
        - The observation belongs to this instance

        Args:
            instance_id: Instance ID to validate

        Returns:
            True if validation passed, False otherwise
        """
        result = self._session.execute(
            """
            SELECT i.current_canonical_observation_id, o.is_canonical, o.instance_id
            FROM dicom_instances i
            LEFT JOIN dicom_instance_observations o ON o.id = i.current_canonical_observation_id
            WHERE i.id = :instance_id
            """,
            {"instance_id": instance_id}
        )
        row = result.fetchone()

        if not row:
            self._logger.error("Instance %s not found", instance_id)
            return False

        canonical_obs_id, is_canonical, observation_instance_id = row

        if canonical_obs_id is None:
            self._logger.error("Instance %s has no canonical observation", instance_id)
            return False

        if not is_canonical:
            self._logger.error(
                "Instance %s canonical observation %s is not marked is_canonical",
                instance_id, canonical_obs_id
            )
            return False

        if observation_instance_id != instance_id:
            self._logger.error(
                "Instance %s canonical observation %s belongs to instance %s",
                instance_id, canonical_obs_id, observation_instance_id
            )
            return False

        return True

    def create_failure_envelope(
        self,
        item: IngestionItem,
        failure_stage: str,
        error_code: str,
        error_message: str,
        parsed_tags: Optional[dict[str, Any]] = None,
    ) -> CanonicalFailureEnvelope:
        """Create a failure envelope for a failed persistence operation.

        Args:
            item: The ingestion item
            failure_stage: Stage where failure occurred
            error_code: Error code
            error_message: Error message
            parsed_tags: Any tags that were successfully parsed

        Returns:
            CanonicalFailureEnvelope
        """
        return CanonicalFailureEnvelope(
            item_id=item.id,
            failure_stage=failure_stage,
            error_code=error_code,
            error_message=error_message,
            parsed_tags=parsed_tags or {},
            raw_bytes_hash=item.raw_object_sha256,
        )
