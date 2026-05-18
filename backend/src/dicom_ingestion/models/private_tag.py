"""
Private Tag Model — Records of private DICOM tags.

This module provides the DicomPrivateTag class which represents
private (vendor-specific) DICOM tags extracted during parsing.
"""
from enum import Enum
from dataclasses import dataclass, field
from typing import Optional, Dict, Any
from datetime import datetime


class PrivateTagRedactionStatus(str, Enum):
    """Redaction status for private tags."""
    PRESERVED = "preserved"  # Stored as-is
    REDACTED = "redacted"    # Redacted per policy
    INTERPRETED = "interpreted"  # Interpreted and stored with metadata


@dataclass
class DicomPrivateTag:
    """
    Represents a private (vendor-specific) DICOM tag.

    Private tags have odd group numbers and are used by vendors
    for proprietary metadata. They require special handling for
    storage and potential redaction.

    Attributes:
        id: Unique tag identifier
        observation_id: The observation this tag belongs to
        private_creator: Private creator identifier (e.g., vendor name)
        tag: Tag address in format "GGGG,EEEE"
        vr: Value Representation (e.g., "LO", "OB", etc.)
        raw_value: Raw bytes of the tag value
        interpreted_keyword: Interpreted keyword name if known
        interpreted_value: Interpreted value if decodable
        redaction_status: Current redaction status
        redaction_reason: Reason for redaction if redacted
        created_at: When the tag was created
    """
    id: int = 0
    observation_id: int = 0
    private_creator: str = ""
    tag: str = ""
    vr: str = ""
    raw_value: Optional[bytes] = None
    interpreted_keyword: Optional[str] = None
    interpreted_value: Optional[str] = None
    redaction_status: str = PrivateTagRedactionStatus.PRESERVED.value
    redaction_reason: str = ""
    created_at: datetime = field(default_factory=datetime.utcnow)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            "id": self.id,
            "observation_id": self.observation_id,
            "private_creator": self.private_creator,
            "tag": self.tag,
            "vr": self.vr,
            "raw_value": (
                f"<binary:{len(self.raw_value)}bytes>"
                if self.raw_value else None
            ),
            "interpreted_keyword": self.interpreted_keyword,
            "interpreted_value": self.interpreted_value,
            "redaction_status": self.redaction_status,
            "redaction_reason": self.redaction_reason,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

    def redact(self, reason: str = "") -> None:
        """
        Redact this private tag.

        Clears raw_value and marks as redacted. Preserves metadata
        about the tag's existence but not its content.

        Args:
            reason: Reason for redaction
        """
        self.raw_value = None
        self.interpreted_value = None
        self.redaction_status = PrivateTagRedactionStatus.REDACTED.value
        self.redaction_reason = reason or "policy_redaction"

    def interpret(self, keyword: str, value: str) -> None:
        """
        Add interpreted metadata to this tag.

        Args:
            keyword: Interpreted keyword name
            value: Interpreted value
        """
        self.interpreted_keyword = keyword
        self.interpreted_value = value
        self.redaction_status = PrivateTagRedactionStatus.INTERPRETED.value

    @classmethod
    def from_parsed(
        cls,
        observation_id: int,
        creator: str,
        tag: str,
        vr: str,
        raw_value: bytes,
    ) -> "DicomPrivateTag":
        """
        Factory method to create from parsed DICOM data.

        Args:
            observation_id: The parent observation
            creator: Private creator string
            tag: Tag address
            vr: Value representation
            raw_value: Raw bytes

        Returns:
            DicomPrivateTag instance
        """
        return cls(
            observation_id=observation_id,
            private_creator=creator,
            tag=tag,
            vr=vr,
            raw_value=raw_value,
        )


@dataclass
class PrivateTagPolicy:
    """
    Policy for handling private tags.

    Defines which private creators/tags should be preserved,
    redacted, or interpreted.

    Attributes:
        preserve_creators: List of private creators to always preserve
        redact_creators: List of private creators to always redact
        interpret_creators: List of private creators to interpret
        default_action: Default action for unlisted creators
        max_raw_value_size: Maximum size for raw value storage
    """
    preserve_creators: list = field(default_factory=list)
    redact_creators: list = field(default_factory=list)
    interpret_creators: list = field(default_factory=list)
    default_action: str = "preserve"
    max_raw_value_size: int = 65536  # 64KB default

    def get_action_for_creator(self, creator: str) -> str:
        """
        Determine action for a private creator.

        Args:
            creator: The private creator identifier

        Returns:
            Action: "preserve", "redact", or "interpret"
        """
        if creator in self.redact_creators:
            return "redact"
        if creator in self.interpret_creators:
            return "interpret"
        if creator in self.preserve_creators:
            return "preserve"
        return self.default_action


@dataclass
class PrivateTagSummary:
    """
    Summary of private tags for an observation.

    Attributes:
        observation_id: The observation
        total_tags: Total number of private tags
        by_creator: Count by private creator
        redacted_count: Number of redacted tags
        interpreted_count: Number of interpreted tags
    """
    observation_id: int = 0
    total_tags: int = 0
    by_creator: Dict[str, int] = field(default_factory=dict)
    redacted_count: int = 0
    interpreted_count: int = 0

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            "observation_id": self.observation_id,
            "total_tags": self.total_tags,
            "by_creator": self.by_creator,
            "redacted_count": self.redacted_count,
            "interpreted_count": self.interpreted_count,
        }
