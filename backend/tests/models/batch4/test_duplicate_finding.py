"""
Tests for DicomDuplicateFinding model (C1).

Acceptance criteria:
- Duplicate findings record identity and content duplicates
- Factory methods create correct finding types
- Resolution status can be updated
"""
import pytest
from datetime import datetime

from dicom_ingestion.models.duplicate_finding import (
    DicomDuplicateFinding,
    DuplicateType,
    DuplicateBasis,
    ResolutionStatus,
    DuplicateFindingSummary,
)


class TestDicomDuplicateFinding:
    """Tests for DicomDuplicateFinding model."""

    def test_identity_duplicate_factory(self):
        """Factory method should create identity duplicate."""
        finding = DicomDuplicateFinding.identity_duplicate(
            observation_id=100,
            matched_instance_id=50,
        )

        assert finding.observation_id == 100
        assert finding.duplicate_type == DuplicateType.IDENTITY.value
        assert finding.basis == DuplicateBasis.SOP_INSTANCE_UID.value
        assert finding.matched_instance_id == 50
        assert finding.matched_observation_id is None
        assert finding.resolution_status == ResolutionStatus.OPEN.value

    def test_content_duplicate_factory(self):
        """Factory method should create content duplicate."""
        finding = DicomDuplicateFinding.content_duplicate(
            observation_id=100,
            matched_observation_id=75,
            basis=DuplicateBasis.WHOLE_FILE_SHA256.value,
        )

        assert finding.observation_id == 100
        assert finding.duplicate_type == DuplicateType.CONTENT.value
        assert finding.basis == DuplicateBasis.WHOLE_FILE_SHA256.value
        assert finding.matched_instance_id is None
        assert finding.matched_observation_id == 75
        assert finding.resolution_status == ResolutionStatus.OPEN.value

    def test_mark_resolved(self):
        """mark_resolved should update status."""
        finding = DicomDuplicateFinding()
        finding.mark_resolved("user_reviewed")

        assert finding.resolution_status == ResolutionStatus.RESOLVED.value
        assert finding.resolution_metadata["resolution_reason"] == "user_reviewed"

    def test_mark_auto_accepted(self):
        """mark_auto_accepted should update status."""
        finding = DicomDuplicateFinding()
        finding.mark_auto_accepted("policy_v1")

        assert finding.resolution_status == ResolutionStatus.AUTO_ACCEPTED.value
        assert finding.resolution_metadata["auto_accept_policy"] == "policy_v1"

    def test_to_dict(self):
        """to_dict should include all fields."""
        finding = DicomDuplicateFinding(
            id=1,
            observation_id=100,
            duplicate_type=DuplicateType.IDENTITY.value,
            basis=DuplicateBasis.SOP_INSTANCE_UID.value,
            matched_instance_id=50,
        )

        data = finding.to_dict()

        assert data["id"] == 1
        assert data["observation_id"] == 100
        assert data["duplicate_type"] == DuplicateType.IDENTITY.value
        assert data["matched_instance_id"] == 50


class TestDuplicateFindingSummary:
    """Tests for DuplicateFindingSummary."""

    def test_default_values(self):
        """Summary should have correct defaults."""
        summary = DuplicateFindingSummary()

        assert summary.total_findings == 0
        assert summary.identity_duplicates == 0
        assert summary.content_duplicates == 0
        assert summary.unresolved_count == 0
        assert summary.by_sop_instance_uid == {}

    def test_to_dict(self):
        """to_dict should include all fields."""
        summary = DuplicateFindingSummary(
            total_findings=5,
            identity_duplicates=3,
            content_duplicates=2,
            unresolved_count=1,
            by_sop_instance_uid={"1.2.3": [{"type": "identity"}]},
        )

        data = summary.to_dict()

        assert data["total_findings"] == 5
        assert data["identity_duplicates"] == 3
        assert data["by_sop_instance_uid"]["1.2.3"][0]["type"] == "identity"
