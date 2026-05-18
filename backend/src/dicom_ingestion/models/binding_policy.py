"""
Binding Policy Model — Platform binding state for DICOM instances.

This module provides the DicomBindingPolicy class which represents
the binding state between canonical DICOM instances and platform
objects (Assets, DatasetSamples, Annotations).
"""
from enum import Enum
from dataclasses import dataclass, field
from typing import Optional, Dict, Any, List
from datetime import datetime


class BindingStatus(str, Enum):
    """Binding status values."""
    PENDING = "pending"           # Waiting to bind
    IN_PROGRESS = "in_progress"     # Binding in progress
    BOUND = "bound"               # Successfully bound
    FAILED = "failed"             # Binding failed
    NOT_APPLICABLE = "not_applicable"  # No binding required
    DEFERRED = "deferred"         # Binding deferred


class BindingTargetType(str, Enum):
    """Types of platform binding targets."""
    ASSET = "asset"               # Platform Asset
    DATASET_SAMPLE = "dataset_sample"  # DatasetSample
    ANNOTATION = "annotation"     # Annotation
    PROJECT = "project"           # Project-level binding
    STUDY = "study"               # Study-level binding


@dataclass
class DicomBindingPolicy:
    """
    Represents binding policy state for a DICOM instance.

    Binding connects canonical DICOM instances to platform-specific
    objects like Assets and DatasetSamples. The binding status is
    tracked separately from ingestion status because:
    - Valid DICOM may outlive binding failure
    - Binding may be deferred or retried
    - Platform objects may change independently

    Attributes:
        id: Unique binding record identifier
        instance_id: The DICOM instance being bound
        observation_id: The specific observation (for versioning)
        binding_status: Current binding status
        target_type: Type of platform target
        target_id: ID of the platform target
        target_uri: URI to the platform target
        binding_metadata: Additional binding metadata
        error_code: Error code if binding failed
        error_detail: Detailed error message
        bound_at: When binding was completed
        retry_count: Number of binding retries
        created_at: When the record was created
        updated_at: When the record was last updated
    """
    id: int = 0
    instance_id: int = 0
    observation_id: int = 0
    binding_status: str = BindingStatus.PENDING.value
    target_type: Optional[str] = None
    target_id: Optional[str] = None
    target_uri: Optional[str] = None
    binding_metadata: Dict[str, Any] = field(default_factory=dict)
    error_code: str = ""
    error_detail: str = ""
    bound_at: Optional[datetime] = None
    retry_count: int = 0
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            "id": self.id,
            "instance_id": self.instance_id,
            "observation_id": self.observation_id,
            "binding_status": self.binding_status,
            "target_type": self.target_type,
            "target_id": self.target_id,
            "target_uri": self.target_uri,
            "binding_metadata": self.binding_metadata,
            "error_code": self.error_code,
            "error_detail": self.error_detail,
            "bound_at": self.bound_at.isoformat() if self.bound_at else None,
            "retry_count": self.retry_count,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

    def mark_bound(
        self,
        target_type: str,
        target_id: str,
        target_uri: str = "",
        metadata: Optional[Dict] = None,
    ) -> None:
        """
        Mark this binding as successfully completed.

        Args:
            target_type: Type of platform target
            target_id: ID of the platform target
            target_uri: URI to the target
            metadata: Additional binding metadata
        """
        self.binding_status = BindingStatus.BOUND.value
        self.target_type = target_type
        self.target_id = target_id
        if target_uri:
            self.target_uri = target_uri
        if metadata:
            self.binding_metadata.update(metadata)
        self.bound_at = datetime.utcnow()
        self.error_code = ""
        self.error_detail = ""
        self.updated_at = datetime.utcnow()

    def mark_failed(
        self,
        error_code: str,
        error_detail: str = "",
    ) -> None:
        """
        Mark this binding as failed.

        Args:
            error_code: Error code
            error_detail: Detailed error message
        """
        self.binding_status = BindingStatus.FAILED.value
        self.error_code = error_code
        self.error_detail = error_detail
        self.updated_at = datetime.utcnow()

    def mark_in_progress(self) -> None:
        """Mark binding as in progress."""
        self.binding_status = BindingStatus.IN_PROGRESS.value
        self.updated_at = datetime.utcnow()

    def mark_deferred(self, reason: str = "") -> None:
        """
        Mark binding as deferred.

        Args:
            reason: Reason for deferral
        """
        self.binding_status = BindingStatus.DEFERRED.value
        if reason:
            self.binding_metadata["deferral_reason"] = reason
        self.updated_at = datetime.utcnow()

    def increment_retry(self) -> None:
        """Increment the retry count."""
        self.retry_count += 1
        self.updated_at = datetime.utcnow()

    @property
    def is_bound(self) -> bool:
        """True if successfully bound."""
        return self.binding_status == BindingStatus.BOUND.value

    @property
    def can_retry(self) -> bool:
        """True if binding can be retried."""
        return (
            self.binding_status in {
                BindingStatus.FAILED.value,
                BindingStatus.DEFERRED.value,
                BindingStatus.PENDING.value,
            } and self.retry_count < 5  # Max 5 retries
        )


@dataclass
class BindingContext:
    """
    Context for binding operations.

    Attributes:
        project_id: Project to bind to
        dataset_id: Optional dataset to bind to
        user_id: User performing the binding
        binding_preferences: Additional preferences
    """
    project_id: str = ""
    dataset_id: Optional[str] = None
    user_id: str = ""
    binding_preferences: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            "project_id": self.project_id,
            "dataset_id": self.dataset_id,
            "user_id": self.user_id,
            "binding_preferences": self.binding_preferences,
        }


@dataclass
class BindingResult:
    """
    Result of a binding operation.

    Attributes:
        success: Whether binding succeeded
        binding_id: ID of the binding record
        target_type: Type of target bound
        target_id: ID of the target
        target_uri: URI to the target
        error_code: Error code if failed
        error_detail: Error detail if failed
    """
    success: bool = False
    binding_id: int = 0
    target_type: Optional[str] = None
    target_id: Optional[str] = None
    target_uri: Optional[str] = None
    error_code: str = ""
    error_detail: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            "success": self.success,
            "binding_id": self.binding_id,
            "target_type": self.target_type,
            "target_id": self.target_id,
            "target_uri": self.target_uri,
            "error_code": self.error_code,
            "error_detail": self.error_detail,
        }


@dataclass
class BindingPolicySummary:
    """
    Summary of binding states for a job or set of instances.

    Attributes:
        total_instances: Total number of instances
        bound_count: Number successfully bound
        failed_count: Number failed
        pending_count: Number pending
        not_applicable_count: Number not applicable
        by_target_type: Count by target type
    """
    total_instances: int = 0
    bound_count: int = 0
    failed_count: int = 0
    pending_count: int = 0
    not_applicable_count: int = 0
    by_target_type: Dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            "total_instances": self.total_instances,
            "bound_count": self.bound_count,
            "failed_count": self.failed_count,
            "pending_count": self.pending_count,
            "not_applicable_count": self.not_applicable_count,
            "by_target_type": self.by_target_type,
        }
