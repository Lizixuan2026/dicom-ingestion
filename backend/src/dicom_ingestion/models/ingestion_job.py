"""
Ingestion Job Model — State machine for ingestion jobs.

This module provides the IngestionJob class and JobStateMachine
for managing job state transitions through the ingestion pipeline.
"""
from enum import Enum
from dataclasses import dataclass, field
from typing import List, Optional, Set, Dict, Callable
from datetime import datetime


class JobStatus(str, Enum):
    """
    Job status values.

    States:
        CREATED: Initial state when job is created
        RECEIVING: Upload is being received
        SCANNING: Files are being scanned
        PROCESSING: Items are being processed
        FINALIZING: Finalizing results
        COMPLETED: Successfully completed
        FAILED: Processing failed
        CANCELLED: Manually cancelled
        REINDEXING: Rebuilding projections
    """
    CREATED = "created"
    RECEIVING = "receiving"
    SCANNING = "scanning"
    PROCESSING = "processing"
    FINALIZING = "finalizing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    REINDEXING = "reindexing"


class InvalidStateTransition(Exception):
    """Raised when an invalid state transition is attempted."""
    pass


@dataclass
class StateTransition:
    """Represents a state transition event."""
    from_status: JobStatus
    to_status: JobStatus
    timestamp: datetime
    reason: str = ""


class JobStateMachine:
    """
    State machine for IngestionJob lifecycle.

    Valid transitions:
        CREATED -> RECEIVING -> SCANNING -> PROCESSING -> FINALIZING -> COMPLETED
        Any active state -> FAILED
        Any active state -> CANCELLED
        COMPLETED -> REINDEXING -> COMPLETED

    Raises:
        InvalidStateTransition: For invalid transition attempts
    """

    # Define valid transitions
    VALID_TRANSITIONS: Dict[JobStatus, Set[JobStatus]] = {
        JobStatus.CREATED: {JobStatus.RECEIVING, JobStatus.FAILED, JobStatus.CANCELLED},
        JobStatus.RECEIVING: {JobStatus.SCANNING, JobStatus.FAILED, JobStatus.CANCELLED},
        JobStatus.SCANNING: {JobStatus.PROCESSING, JobStatus.FAILED, JobStatus.CANCELLED},
        JobStatus.PROCESSING: {JobStatus.FINALIZING, JobStatus.FAILED, JobStatus.CANCELLED},
        JobStatus.FINALIZING: {JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED},
        JobStatus.COMPLETED: {JobStatus.REINDEXING, JobStatus.FAILED},
        JobStatus.REINDEXING: {JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED},
        # Terminal states can only transition from themselves (idempotent)
        JobStatus.FAILED: set(),
        JobStatus.CANCELLED: set(),
    }

    # Active states (not terminal)
    ACTIVE_STATES: Set[JobStatus] = {
        JobStatus.CREATED,
        JobStatus.RECEIVING,
        JobStatus.SCANNING,
        JobStatus.PROCESSING,
        JobStatus.FINALIZING,
        JobStatus.REINDEXING,
    }

    # Terminal states
    TERMINAL_STATES: Set[JobStatus] = {
        JobStatus.COMPLETED,
        JobStatus.FAILED,
        JobStatus.CANCELLED,
    }

    def __init__(self, initial_status: JobStatus = JobStatus.CREATED):
        """
        Initialize the state machine.

        Args:
            initial_status: Starting state (default: CREATED)
        """
        self._status = initial_status
        self._transitions: List[StateTransition] = []
        self._on_transition_callbacks: List[Callable[[StateTransition], None]] = []

    @property
    def status(self) -> JobStatus:
        """Current job status."""
        return self._status

    @property
    def transitions(self) -> List[StateTransition]:
        """History of state transitions."""
        return self._transitions.copy()

    @property
    def is_active(self) -> bool:
        """True if job is in an active (non-terminal) state."""
        return self._status in self.ACTIVE_STATES

    @property
    def is_terminal(self) -> bool:
        """True if job is in a terminal state."""
        return self._status in self.TERMINAL_STATES

    def can_transition_to(self, new_status: JobStatus) -> bool:
        """
        Check if transition to new_status is valid.

        Args:
            new_status: Target status

        Returns:
            True if transition is valid
        """
        # Same state is always valid (idempotent)
        if new_status == self._status:
            return True

        return new_status in self.VALID_TRANSITIONS.get(self._status, set())

    def transition_to(self, new_status: JobStatus, reason: str = "") -> None:
        """
        Attempt to transition to a new status.

        Args:
            new_status: Target status
            reason: Optional reason for the transition

        Raises:
            InvalidStateTransition: If transition is not valid
        """
        # Idempotent: same state is always allowed
        if new_status == self._status:
            return

        if not self.can_transition_to(new_status):
            raise InvalidStateTransition(
                f"Cannot transition from {self._status.value} to {new_status.value}"
            )

        # Record the transition
        transition = StateTransition(
            from_status=self._status,
            to_status=new_status,
            timestamp=datetime.utcnow(),
            reason=reason
        )
        self._transitions.append(transition)

        # Update status
        old_status = self._status
        self._status = new_status

        # Notify callbacks
        for callback in self._on_transition_callbacks:
            callback(transition)

    def fail(self, reason: str = "") -> None:
        """
        Transition to FAILED state.

        Args:
            reason: Failure reason

        Raises:
            InvalidStateTransition: If already in a terminal state
        """
        if self._status == JobStatus.FAILED:
            return  # Idempotent
        if self._status in {JobStatus.COMPLETED, JobStatus.CANCELLED}:
            raise InvalidStateTransition(
                f"Cannot fail a job that is already {self._status.value}"
            )
        self.transition_to(JobStatus.FAILED, reason)

    def cancel(self, reason: str = "") -> None:
        """
        Transition to CANCELLED state.

        Args:
            reason: Cancellation reason

        Raises:
            InvalidStateTransition: If already in a terminal state
        """
        if self._status == JobStatus.CANCELLED:
            return  # Idempotent
        if self._status in {JobStatus.COMPLETED, JobStatus.FAILED}:
            raise InvalidStateTransition(
                f"Cannot cancel a job that is already {self._status.value}"
            )
        self.transition_to(JobStatus.CANCELLED, reason)

    def on_transition(self, callback: Callable[[StateTransition], None]) -> None:
        """
        Register a callback for state transitions.

        Args:
            callback: Function to call on each transition
        """
        self._on_transition_callbacks.append(callback)

    def get_allowed_transitions(self) -> Set[JobStatus]:
        """Get set of allowed next states."""
        return self.VALID_TRANSITIONS.get(self._status, set()).copy()


@dataclass
class IngestionJob:
    """
    Represents a DICOM ingestion job.

    Attributes:
        id: Unique job identifier
        actor_id: User/system that created the job
        request_idempotency_key: Idempotency key for request deduplication
        source_type: Source of the upload (e.g., 'upload', 'api', 'sync')
        state_machine: JobStateMachine managing job lifecycle
        created_at: Job creation timestamp
        completed_at: Job completion timestamp (if completed)
        error_message: Error message if job failed
        metadata: Additional job metadata
    """
    id: int = 0
    actor_id: str = ""
    request_idempotency_key: str = ""
    source_type: str = ""
    state_machine: JobStateMachine = field(default_factory=JobStateMachine)
    created_at: datetime = field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = None
    error_message: str = ""
    metadata: Dict = field(default_factory=dict)

    @property
    def status(self) -> JobStatus:
        """Current job status."""
        return self.state_machine.status

    def transition_to(self, new_status: JobStatus, reason: str = "") -> None:
        """Transition job to new status."""
        self.state_machine.transition_to(new_status, reason)

        # Update completed_at if reaching terminal state
        if self.state_machine.is_terminal and not self.completed_at:
            self.completed_at = datetime.utcnow()

    def fail(self, reason: str = "") -> None:
        """Fail the job."""
        self.state_machine.fail(reason)
        if not self.completed_at:
            self.completed_at = datetime.utcnow()
        if reason:
            self.error_message = reason

    def cancel(self, reason: str = "") -> None:
        """Cancel the job."""
        self.state_machine.cancel(reason)
        if not self.completed_at:
            self.completed_at = datetime.utcnow()
        if reason:
            self.error_message = reason

    def is_active(self) -> bool:
        """True if job is active (not in terminal state)."""
        return self.state_machine.is_active

    def is_terminal(self) -> bool:
        """True if job is in terminal state."""
        return self.state_machine.is_terminal

    def can_transition_to(self, status: JobStatus) -> bool:
        """Check if transition to status is allowed."""
        return self.state_machine.can_transition_to(status)

    def get_state_history(self) -> List[StateTransition]:
        """Get list of state transitions."""
        return self.state_machine.transitions
