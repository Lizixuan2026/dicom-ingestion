"""
Tests for IngestionJob and JobStateMachine.

Acceptance criteria:
- Job transitions: created -> receiving -> scanning -> processing -> finalizing -> completed
- Any active state can transition to failed or cancelled
- completed -> reindexing -> completed is valid
- Invalid transitions raise, not silently no-op
"""
import pytest
from datetime import datetime

from dicom_ingestion.models import (
    IngestionJob,
    JobStatus,
    JobStateMachine,
    InvalidStateTransition
)


class TestJobStateMachineValidTransitions:
    """Tests for valid state transitions."""

    def test_created_to_receiving(self):
        """CREATED -> RECEIVING is valid."""
        sm = JobStateMachine(JobStatus.CREATED)
        sm.transition_to(JobStatus.RECEIVING)
        assert sm.status == JobStatus.RECEIVING

    def test_receiving_to_scanning(self):
        """RECEIVING -> SCANNING is valid."""
        sm = JobStateMachine(JobStatus.RECEIVING)
        sm.transition_to(JobStatus.SCANNING)
        assert sm.status == JobStatus.SCANNING

    def test_scanning_to_processing(self):
        """SCANNING -> PROCESSING is valid."""
        sm = JobStateMachine(JobStatus.SCANNING)
        sm.transition_to(JobStatus.PROCESSING)
        assert sm.status == JobStatus.PROCESSING

    def test_processing_to_finalizing(self):
        """PROCESSING -> FINALIZING is valid."""
        sm = JobStateMachine(JobStatus.PROCESSING)
        sm.transition_to(JobStatus.FINALIZING)
        assert sm.status == JobStatus.FINALIZING

    def test_finalizing_to_completed(self):
        """FINALIZING -> COMPLETED is valid."""
        sm = JobStateMachine(JobStatus.FINALIZING)
        sm.transition_to(JobStatus.COMPLETED)
        assert sm.status == JobStatus.COMPLETED

    def test_completed_to_reindexing(self):
        """COMPLETED -> REINDEXING is valid."""
        sm = JobStateMachine(JobStatus.COMPLETED)
        sm.transition_to(JobStatus.REINDEXING)
        assert sm.status == JobStatus.REINDEXING

    def test_reindexing_to_completed(self):
        """REINDEXING -> COMPLETED is valid."""
        sm = JobStateMachine(JobStatus.REINDEXING)
        sm.transition_to(JobStatus.COMPLETED)
        assert sm.status == JobStatus.COMPLETED


class TestJobStateMachineInvalidTransitions:
    """Tests for invalid state transitions that should raise."""

    def test_cannot_skip_stages(self):
        """Cannot skip intermediate stages."""
        sm = JobStateMachine(JobStatus.CREATED)
        with pytest.raises(InvalidStateTransition):
            sm.transition_to(JobStatus.PROCESSING)

    def test_cannot_go_backwards(self):
        """Cannot transition backwards to previous stages."""
        sm = JobStateMachine(JobStatus.PROCESSING)
        with pytest.raises(InvalidStateTransition):
            sm.transition_to(JobStatus.SCANNING)

    def test_cannot_go_from_completed_to_processing(self):
        """COMPLETED cannot go to PROCESSING."""
        sm = JobStateMachine(JobStatus.COMPLETED)
        with pytest.raises(InvalidStateTransition):
            sm.transition_to(JobStatus.PROCESSING)

    def test_failed_cannot_transition(self):
        """FAILED is terminal and cannot transition."""
        sm = JobStateMachine(JobStatus.FAILED)
        with pytest.raises(InvalidStateTransition):
            sm.transition_to(JobStatus.COMPLETED)

    def test_cancelled_cannot_transition(self):
        """CANCELLED is terminal and cannot transition."""
        sm = JobStateMachine(JobStatus.CANCELLED)
        with pytest.raises(InvalidStateTransition):
            sm.transition_to(JobStatus.COMPLETED)


class TestJobStateMachineToFailed:
    """Tests for transitioning to FAILED state."""

    def test_any_active_can_fail(self):
        """Any active state can transition to FAILED."""
        active_states = [
            JobStatus.CREATED,
            JobStatus.RECEIVING,
            JobStatus.SCANNING,
            JobStatus.PROCESSING,
            JobStatus.FINALIZING,
            JobStatus.REINDEXING,
        ]
        for status in active_states:
            sm = JobStateMachine(status)
            sm.fail("Test failure")
            assert sm.status == JobStatus.FAILED

    def test_cannot_fail_completed(self):
        """COMPLETED cannot transition to FAILED."""
        sm = JobStateMachine(JobStatus.COMPLETED)
        with pytest.raises(InvalidStateTransition):
            sm.fail("Should not work")

    def test_cannot_fail_already_failed(self):
        """Already FAILED stays FAILED (idempotent)."""
        sm = JobStateMachine(JobStatus.FAILED)
        sm.fail("Another reason")  # Should not raise
        assert sm.status == JobStatus.FAILED

    def test_cannot_fail_cancelled(self):
        """CANCELLED cannot transition to FAILED."""
        sm = JobStateMachine(JobStatus.CANCELLED)
        with pytest.raises(InvalidStateTransition):
            sm.fail("Should not work")


class TestJobStateMachineToCancelled:
    """Tests for transitioning to CANCELLED state."""

    def test_any_active_can_cancel(self):
        """Any active state can transition to CANCELLED."""
        active_states = [
            JobStatus.CREATED,
            JobStatus.RECEIVING,
            JobStatus.SCANNING,
            JobStatus.PROCESSING,
            JobStatus.FINALIZING,
            JobStatus.REINDEXING,
        ]
        for status in active_states:
            sm = JobStateMachine(status)
            sm.cancel("User request")
            assert sm.status == JobStatus.CANCELLED

    def test_cannot_cancel_completed(self):
        """COMPLETED cannot transition to CANCELLED."""
        sm = JobStateMachine(JobStatus.COMPLETED)
        with pytest.raises(InvalidStateTransition):
            sm.cancel("Should not work")

    def test_cannot_cancel_failed(self):
        """FAILED cannot transition to CANCELLED."""
        sm = JobStateMachine(JobStatus.FAILED)
        with pytest.raises(InvalidStateTransition):
            sm.cancel("Should not work")

    def test_cancelled_is_idempotent(self):
        """Already CANCELLED stays CANCELLED."""
        sm = JobStateMachine(JobStatus.CANCELLED)
        sm.cancel("Another reason")  # Should not raise
        assert sm.status == JobStatus.CANCELLED


class TestJobStateMachineIdempotent:
    """Tests for idempotent transitions (same state)."""

    def test_same_state_no_op(self):
        """Transitioning to same state is allowed (idempotent)."""
        sm = JobStateMachine(JobStatus.PROCESSING)
        sm.transition_to(JobStatus.PROCESSING)  # Should not raise
        assert sm.status == JobStatus.PROCESSING

    def test_same_state_no_transition_record(self):
        """Idempotent transition should not create transition record."""
        sm = JobStateMachine(JobStatus.PROCESSING)
        initial_count = len(sm.transitions)
        sm.transition_to(JobStatus.PROCESSING)
        assert len(sm.transitions) == initial_count


class TestJobStateMachineProperties:
    """Tests for state machine properties."""

    def test_is_active_for_active_states(self):
        """is_active should be True for active states."""
        active_states = [
            JobStatus.CREATED,
            JobStatus.RECEIVING,
            JobStatus.SCANNING,
            JobStatus.PROCESSING,
            JobStatus.FINALIZING,
            JobStatus.REINDEXING,
        ]
        for status in active_states:
            sm = JobStateMachine(status)
            assert sm.is_active is True
            assert sm.is_terminal is False

    def test_is_terminal_for_terminal_states(self):
        """is_terminal should be True for terminal states."""
        terminal_states = [
            JobStatus.COMPLETED,
            JobStatus.FAILED,
            JobStatus.CANCELLED,
        ]
        for status in terminal_states:
            sm = JobStateMachine(status)
            assert sm.is_terminal is True
            assert sm.is_active is False

    def test_can_transition_to(self):
        """can_transition_to should return True for valid transitions."""
        sm = JobStateMachine(JobStatus.CREATED)
        assert sm.can_transition_to(JobStatus.RECEIVING) is True
        assert sm.can_transition_to(JobStatus.PROCESSING) is False

    def test_get_allowed_transitions(self):
        """get_allowed_transitions should return valid next states."""
        sm = JobStateMachine(JobStatus.RECEIVING)
        allowed = sm.get_allowed_transitions()
        assert JobStatus.SCANNING in allowed
        assert JobStatus.FAILED in allowed
        assert JobStatus.CANCELLED in allowed
        assert JobStatus.PROCESSING not in allowed


class TestJobStateMachineTransitions:
    """Tests for transition recording."""

    def test_records_successful_transitions(self):
        """Successful transitions should be recorded."""
        sm = JobStateMachine(JobStatus.CREATED)
        sm.transition_to(JobStatus.RECEIVING, "Starting upload")
        sm.transition_to(JobStatus.SCANNING)

        assert len(sm.transitions) == 2
        assert sm.transitions[0].from_status == JobStatus.CREATED
        assert sm.transitions[0].to_status == JobStatus.RECEIVING
        assert sm.transitions[0].reason == "Starting upload"

    def test_transition_has_timestamp(self):
        """Transitions should have timestamps."""
        sm = JobStateMachine(JobStatus.CREATED)
        before = datetime.utcnow()
        sm.transition_to(JobStatus.RECEIVING)
        after = datetime.utcnow()

        assert before <= sm.transitions[0].timestamp <= after


class TestIngestionJob:
    """Tests for IngestionJob model."""

    def test_job_has_correct_initial_state(self):
        """New job should start in CREATED state."""
        job = IngestionJob(actor_id="user1", source_type="upload")
        assert job.status == JobStatus.CREATED
        assert job.is_active() is True

    def test_job_transition_updates_status(self):
        """Job transition should update status."""
        job = IngestionJob()
        job.transition_to(JobStatus.RECEIVING)
        assert job.status == JobStatus.RECEIVING

    def test_job_complete_sets_completed_at(self):
        """Reaching terminal state should set completed_at."""
        job = IngestionJob()
        job.transition_to(JobStatus.RECEIVING)
        job.transition_to(JobStatus.SCANNING)
        job.transition_to(JobStatus.PROCESSING)
        job.transition_to(JobStatus.FINALIZING)

        before = datetime.utcnow()
        job.transition_to(JobStatus.COMPLETED)
        after = datetime.utcnow()

        assert job.completed_at is not None
        assert before <= job.completed_at <= after

    def test_job_fail_sets_error_message(self):
        """Failing should set error message."""
        job = IngestionJob()
        job.fail("Database connection lost")
        assert job.error_message == "Database connection lost"
        assert job.status == JobStatus.FAILED

    def test_job_get_state_history(self):
        """Should return transition history."""
        job = IngestionJob()
        job.transition_to(JobStatus.RECEIVING)
        job.transition_to(JobStatus.SCANNING)

        history = job.get_state_history()
        assert len(history) == 2

    def test_job_is_terminal(self):
        """is_terminal should reflect state."""
        job = IngestionJob()
        assert job.is_terminal() is False

        job.transition_to(JobStatus.RECEIVING)
        job.transition_to(JobStatus.SCANNING)
        job.transition_to(JobStatus.PROCESSING)
        job.transition_to(JobStatus.FINALIZING)
        job.transition_to(JobStatus.COMPLETED)
        assert job.is_terminal() is True

    def test_job_can_transition_to(self):
        """can_transition_to should delegate to state machine."""
        job = IngestionJob()
        assert job.can_transition_to(JobStatus.RECEIVING) is True
        assert job.can_transition_to(JobStatus.COMPLETED) is False


class TestIngestionJobFullLifecycle:
    """Tests for complete job lifecycle."""

    def test_successful_lifecycle(self):
        """Complete successful job lifecycle."""
        job = IngestionJob(actor_id="user1")

        # Progress through all stages
        job.transition_to(JobStatus.RECEIVING)
        job.transition_to(JobStatus.SCANNING)
        job.transition_to(JobStatus.PROCESSING)
        job.transition_to(JobStatus.FINALIZING)
        job.transition_to(JobStatus.COMPLETED)

        assert job.status == JobStatus.COMPLETED
        assert job.is_terminal() is True
        assert len(job.get_state_history()) == 5

    def test_failed_lifecycle(self):
        """Job lifecycle with failure."""
        job = IngestionJob()

        job.transition_to(JobStatus.RECEIVING)
        job.transition_to(JobStatus.SCANNING)
        job.fail("Scan error")

        assert job.status == JobStatus.FAILED
        assert job.is_terminal() is True
        assert job.completed_at is not None

    def test_cancelled_lifecycle(self):
        """Job lifecycle with cancellation."""
        job = IngestionJob()

        job.transition_to(JobStatus.RECEIVING)
        job.transition_to(JobStatus.SCANNING)
        job.cancel("User request")

        assert job.status == JobStatus.CANCELLED
        assert job.is_terminal() is True

    def test_reindex_lifecycle(self):
        """Job lifecycle with reindexing."""
        job = IngestionJob()

        # Complete first
        job.transition_to(JobStatus.RECEIVING)
        job.transition_to(JobStatus.SCANNING)
        job.transition_to(JobStatus.PROCESSING)
        job.transition_to(JobStatus.FINALIZING)
        job.transition_to(JobStatus.COMPLETED)

        # Then reindex
        job.transition_to(JobStatus.REINDEXING)
        job.transition_to(JobStatus.COMPLETED)

        assert job.status == JobStatus.COMPLETED
        assert len(job.get_state_history()) == 7
