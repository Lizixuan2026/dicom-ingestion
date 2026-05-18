"""
Private Tag Persistence Service — Persist private DICOM tags with policy.

This module provides the PrivateTagPersistenceService which persists
private (vendor-specific) DICOM tags to the database, applying
redaction and interpretation policies.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Optional, List, Dict

if TYPE_CHECKING:
    from sqlalchemy.orm import Session
    from dicom_ingestion.models.private_tag import (
        DicomPrivateTag,
        PrivateTagPolicy,
        PrivateTagSummary,
    )
    from dicom_ingestion.services.parser.dicom_parser import PrivateTag

logger = logging.getLogger(__name__)


@dataclass
class PrivateTagPersistenceResult:
    """
    Result of private tag persistence operation.

    Attributes:
        success: Whether persistence was successful
        persisted_count: Number of tags persisted
        redacted_count: Number of tags redacted
        interpreted_count: Number of tags interpreted
        error_code: Error code if persistence failed
        error_detail: Detailed error message
    """
    success: bool = False
    persisted_count: int = 0
    redacted_count: int = 0
    interpreted_count: int = 0
    error_code: str = ""
    error_detail: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            "success": self.success,
            "persisted_count": self.persisted_count,
            "redacted_count": self.redacted_count,
            "interpreted_count": self.interpreted_count,
            "error_code": self.error_code,
            "error_detail": self.error_detail,
        }


class PrivateTagPersistenceService:
    """
    Service for persisting private DICOM tags.

    Responsibilities:
    - Store private tags with their raw values
    - Apply redaction policies per creator/tag
    - Support interpretation of known private tags
    - Handle large values appropriately
    - Preserve tag provenance (observation-scoped)

    Private Tag Policy:
    - Tags can be preserved, redacted, or interpreted
    - Policy is creator-based for v1
    - Default action is preserve
    - Large values (>64KB) may be truncated or rejected based on policy
    """

    def __init__(
        self,
        session: Session,
        policy: Optional[Any] = None,  # PrivateTagPolicy
    ) -> None:
        """
        Initialize the private tag persistence service.

        Args:
            session: SQLAlchemy session for database operations
            policy: Private tag policy (uses default if None)
        """
        from dicom_ingestion.models.private_tag import PrivateTagPolicy

        self._session = session
        self._policy = policy or PrivateTagPolicy()
        self._logger = logger

    async def persist_private_tags(
        self,
        observation_id: int,
        private_tags: List[Any],  # List[PrivateTag]
    ) -> PrivateTagPersistenceResult:
        """
        Persist private tags for an observation.

        Args:
            observation_id: The parent observation ID
            private_tags: List of parsed private tags

        Returns:
            PrivateTagPersistenceResult with counts
        """
        result = PrivateTagPersistenceResult()

        try:
            for parsed_tag in private_tags:
                # Convert and apply policy
                db_tag = self._convert_and_apply_policy(
                    observation_id, parsed_tag
                )

                if db_tag.redaction_status == "redacted":
                    result.redacted_count += 1
                elif db_tag.redaction_status == "interpreted":
                    result.interpreted_count += 1

                # Persist to database
                await self._persist_tag(db_tag)
                result.persisted_count += 1

            result.success = True

            self._logger.info(
                "Persisted %d private tags for observation %s "
                "(redacted=%d, interpreted=%d)",
                result.persisted_count,
                observation_id,
                result.redacted_count,
                result.interpreted_count,
            )

        except Exception as e:
            self._logger.exception(
                "Failed to persist private tags for observation %s",
                observation_id
            )
            result.error_code = "PrivateTagPersistenceFailed"
            result.error_detail = str(e)

        return result

    def _convert_and_apply_policy(
        self,
        observation_id: int,
        parsed_tag: Any,  # PrivateTag
    ) -> Any:  # DicomPrivateTag
        """
        Convert parsed tag to DB model and apply policy.

        Args:
            observation_id: Parent observation
            parsed_tag: Parsed private tag

        Returns:
            DicomPrivateTag with policy applied
        """
        from dicom_ingestion.models.private_tag import (
            DicomPrivateTag,
            PrivateTagRedactionStatus,
        )

        # Create base tag
        db_tag = DicomPrivateTag.from_parsed(
            observation_id=observation_id,
            creator=parsed_tag.creator or "",
            tag=parsed_tag.tag,
            vr=parsed_tag.vr,
            raw_value=parsed_tag.raw_value,
        )

        # Apply policy
        action = self._policy.get_action_for_creator(db_tag.private_creator)

        if action == "redact":
            db_tag.redact(f"policy: {db_tag.private_creator} in redact list")
        elif action == "interpret":
            # Try to interpret - for v1 this is basic
            # In future versions, this could use catalogs
            interpreted = self._attempt_interpretation(db_tag)
            if interpreted:
                db_tag.interpreted_value = interpreted
                db_tag.redaction_status = PrivateTagRedactionStatus.INTERPRETED.value

        # Check size limits for preserved tags
        if (action == "preserve" and
            db_tag.raw_value and
            len(db_tag.raw_value) > self._policy.max_raw_value_size):
            # Truncate large values
            self._logger.warning(
                "Truncating large private tag %s (%d bytes) for observation %s",
                db_tag.tag,
                len(db_tag.raw_value),
                observation_id
            )
            db_tag.raw_value = (
                db_tag.raw_value[:self._policy.max_raw_value_size] +
                b"<truncated>"
            )

        return db_tag

    def _attempt_interpretation(
        self,
        tag: Any,  # DicomPrivateTag
    ) -> Optional[str]:
        """
        Attempt to interpret a private tag value.

        For v1, this is basic string decoding. Future versions could
        use vendor-specific catalogs.

        Args:
            tag: The private tag

        Returns:
            Interpreted value if possible, None otherwise
        """
        if not tag.raw_value:
            return None

        # Basic string interpretation for text-like VRs
        text_vrs = ["LO", "LT", "SH", "ST", "UT", "AE", "PN", "UI"]

        if tag.vr in text_vrs:
            try:
                return tag.raw_value.decode("utf-8", errors="replace").strip()
            except Exception:
                pass

        # Return None if we can't interpret
        return None

    async def _persist_tag(
        self,
        tag: Any,  # DicomPrivateTag
    ) -> int:
        """
        Persist a single private tag.

        Args:
            tag: The tag to persist

        Returns:
            The ID of the persisted tag
        """
        result = self._session.execute(
            """
            INSERT INTO dicom_private_tags (
                observation_id,
                private_creator,
                tag,
                vr,
                raw_value,
                interpreted_keyword,
                interpreted_value,
                created_at
            ) VALUES (
                :observation_id,
                :private_creator,
                :tag,
                :vr,
                :raw_value,
                :interpreted_keyword,
                :interpreted_value,
                NOW()
            )
            ON CONFLICT (observation_id, private_creator, tag) DO UPDATE SET
                vr = EXCLUDED.vr,
                raw_value = EXCLUDED.raw_value,
                interpreted_keyword = EXCLUDED.interpreted_keyword,
                interpreted_value = EXCLUDED.interpreted_value
            RETURNING id
            """,
            {
                "observation_id": tag.observation_id,
                "private_creator": tag.private_creator,
                "tag": tag.tag,
                "vr": tag.vr,
                "raw_value": tag.raw_value,
                "interpreted_keyword": tag.interpreted_keyword,
                "interpreted_value": tag.interpreted_value,
            }
        )
        return result.fetchone()[0]

    async def get_tags_for_observation(
        self,
        observation_id: int,
        include_redacted: bool = False,
    ) -> List[Any]:  # List[DicomPrivateTag]
        """
        Get private tags for an observation.

        Args:
            observation_id: The observation ID
            include_redacted: Whether to include redacted tags

        Returns:
            List of DicomPrivateTag
        """
        from dicom_ingestion.models.private_tag import DicomPrivateTag

        redact_filter = ""
        if not include_redacted:
            redact_filter = "AND redaction_status != 'redacted'"

        result = self._session.execute(
            f"""
            SELECT
                id,
                observation_id,
                private_creator,
                tag,
                vr,
                raw_value,
                interpreted_keyword,
                interpreted_value,
                redaction_status,
                redaction_reason,
                created_at
            FROM dicom_private_tags
            WHERE observation_id = :observation_id
            {redact_filter}
            ORDER BY tag
            """,
            {"observation_id": observation_id}
        )

        tags = []
        for row in result.fetchall():
            tag = DicomPrivateTag(
                id=row[0],
                observation_id=row[1],
                private_creator=row[2],
                tag=row[3],
                vr=row[4],
                raw_value=row[5],
                interpreted_keyword=row[6],
                interpreted_value=row[7],
                redaction_status=row[8],
                redaction_reason=row[9],
                created_at=row[10],
            )
            tags.append(tag)

        return tags

    async def get_summary_for_observation(
        self,
        observation_id: int,
    ) -> Any:  # PrivateTagSummary
        """
        Get summary of private tags for an observation.

        Args:
            observation_id: The observation ID

        Returns:
            PrivateTagSummary
        """
        from dicom_ingestion.models.private_tag import (
            PrivateTagSummary,
            PrivateTagRedactionStatus,
        )

        result = self._session.execute(
            """
            SELECT
                private_creator,
                redaction_status,
                COUNT(*) as cnt
            FROM dicom_private_tags
            WHERE observation_id = :observation_id
            GROUP BY private_creator, redaction_status
            """,
            {"observation_id": observation_id}
        )

        summary = PrivateTagSummary(observation_id=observation_id)
        by_creator: Dict[str, int] = {}

        for row in result.fetchall():
            creator, redaction, count = row

            summary.total_tags += count

            if creator not in by_creator:
                by_creator[creator] = 0
            by_creator[creator] += count

            if redaction == PrivateTagRedactionStatus.REDACTED.value:
                summary.redacted_count += count
            elif redaction == PrivateTagRedactionStatus.INTERPRETED.value:
                summary.interpreted_count += count

        summary.by_creator = by_creator
        return summary

    async def redact_tags_for_observation(
        self,
        observation_id: int,
        creator: Optional[str] = None,
        reason: str = "",
    ) -> int:
        """
        Redact private tags for an observation.

        Args:
            observation_id: The observation ID
            creator: If specified, only redact tags from this creator
            reason: Reason for redaction

        Returns:
            Number of tags redacted
        """
        creator_filter = ""
        params = {"observation_id": observation_id, "reason": reason or "manual_redaction"}

        if creator:
            creator_filter = "AND private_creator = :creator"
            params["creator"] = creator

        result = self._session.execute(
            f"""
            UPDATE dicom_private_tags
            SET raw_value = NULL,
                interpreted_value = NULL,
                redaction_status = 'redacted',
                redaction_reason = :reason
            WHERE observation_id = :observation_id
            {creator_filter}
            RETURNING id
            """,
            params
        )

        redacted_count = len(result.fetchall())

        self._logger.info(
            "Redacted %d private tags for observation %s (creator=%s, reason=%s)",
            redacted_count,
            observation_id,
            creator or "all",
            reason
        )

        return redacted_count
