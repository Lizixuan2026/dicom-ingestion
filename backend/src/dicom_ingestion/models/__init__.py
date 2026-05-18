"""Models for DICOM ingestion."""
from .ingestion_job import IngestionJob, JobStatus, JobStateMachine, InvalidStateTransition
from .ingestion_item import IngestionItem, ItemStatusAxes, TerminalOutcome, ItemStatusValue
from .duplicate_finding import (
    DicomDuplicateFinding,
    DuplicateType,
    DuplicateBasis,
    ResolutionStatus,
    DuplicateFindingSummary,
)
from .private_tag import (
    DicomPrivateTag,
    PrivateTagRedactionStatus,
    PrivateTagPolicy,
    PrivateTagSummary,
)
from .reference_edge import (
    DicomReferenceEdge,
    ParsedReference,
    ReferenceRelationshipType,
    ReferenceResolutionStatus,
    ReferenceEdgeSummary,
)
from .binding_policy import (
    DicomBindingPolicy,
    BindingContext,
    BindingResult,
    BindingStatus,
    BindingTargetType,
    BindingPolicySummary,
)
from .series_conflict import (
    SeriesIngestionAttempt,
    SeriesConflictSummary,
    SeriesConflictClassification,
    SeriesConflictStatus,
    ConflictClassificationResult,
    ConflictResolutionResult,
)

__all__ = [
    # Ingestion core
    "IngestionJob",
    "JobStatus",
    "JobStateMachine",
    "InvalidStateTransition",
    "IngestionItem",
    "ItemStatusAxes",
    "TerminalOutcome",
    "ItemStatusValue",
    # Duplicate detection (C1)
    "DicomDuplicateFinding",
    "DuplicateType",
    "DuplicateBasis",
    "ResolutionStatus",
    "DuplicateFindingSummary",
    # Private tags (C2)
    "DicomPrivateTag",
    "PrivateTagRedactionStatus",
    "PrivateTagPolicy",
    "PrivateTagSummary",
    # Reference edges (C3)
    "DicomReferenceEdge",
    "ParsedReference",
    "ReferenceRelationshipType",
    "ReferenceResolutionStatus",
    "ReferenceEdgeSummary",
    # Binding policy (C4)
    "DicomBindingPolicy",
    "BindingContext",
    "BindingResult",
    "BindingStatus",
    "BindingTargetType",
    "BindingPolicySummary",
    # Series conflict (C4)
    "SeriesIngestionAttempt",
    "SeriesConflictSummary",
    "SeriesConflictClassification",
    "SeriesConflictStatus",
    "ConflictClassificationResult",
    "ConflictResolutionResult",
]
