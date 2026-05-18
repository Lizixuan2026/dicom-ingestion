"""
Tests for DicomReferenceEdge model (C3).

Acceptance criteria:
- Reference edges capture from/to relationship
- Resolution can be marked with target instance
- Ambiguous and external statuses supported
"""
import pytest
from datetime import datetime

from dicom_ingestion.models.reference_edge import (
    DicomReferenceEdge,
    ParsedReference,
    ReferenceRelationshipType,
    ReferenceResolutionStatus,
    ReferenceEdgeSummary,
)


class TestDicomReferenceEdge:
    """Tests for DicomReferenceEdge model."""

    def test_from_parsed_reference(self):
        """Factory should create edge from parsed reference."""
        edge = DicomReferenceEdge.from_parsed_reference(
            from_instance_id=100,
            relationship_type=ReferenceRelationshipType.REFERENCED_IMAGE.value,
            study_uid="1.2.3",
            series_uid="1.2.3.4",
            sop_uid="1.2.3.4.5",
            frame_number=1,
        )

        assert edge.from_instance_id == 100
        assert edge.relationship_type == ReferenceRelationshipType.REFERENCED_IMAGE.value
        assert edge.to_study_instance_uid == "1.2.3"
        assert edge.to_series_instance_uid == "1.2.3.4"
        assert edge.to_sop_instance_uid == "1.2.3.4.5"
        assert edge.referenced_frame_number == 1

    def test_mark_resolved(self):
        """mark_resolved should update status and target."""
        edge = DicomReferenceEdge()
        edge.mark_resolved(200, {"path": "sop_uid"})

        assert edge.resolved_target_instance_id == 200
        assert edge.resolution_status == ReferenceResolutionStatus.RESOLVED.value
        assert edge.resolution_metadata["path"] == "sop_uid"
        assert edge.is_resolved is True

    def test_mark_ambiguous(self):
        """mark_ambiguous should set status and candidates."""
        edge = DicomReferenceEdge()
        edge.mark_ambiguous([200, 201], "multiple_matches")

        assert edge.resolution_status == ReferenceResolutionStatus.AMBIGUOUS.value
        assert edge.resolution_metadata["candidate_ids"] == [200, 201]
        assert edge.resolution_metadata["ambiguity_reason"] == "multiple_matches"

    def test_mark_external(self):
        """mark_external should set external status."""
        edge = DicomReferenceEdge()
        edge.mark_external("outside_scope")

        assert edge.resolution_status == ReferenceResolutionStatus.EXTERNAL.value
        assert edge.resolution_metadata["external_reason"] == "outside_scope"

    def test_target_uid_key_unique(self):
        """target_uid_key should be unique per edge."""
        edge1 = DicomReferenceEdge(
            from_instance_id=100,
            relationship_type=ReferenceRelationshipType.REFERENCED_IMAGE.value,
            to_sop_instance_uid="1.2.3",
        )
        edge2 = DicomReferenceEdge(
            from_instance_id=100,
            relationship_type=ReferenceRelationshipType.REFERENCED_IMAGE.value,
            to_sop_instance_uid="1.2.4",
        )

        assert edge1.target_uid_key != edge2.target_uid_key


class TestParsedReference:
    """Tests for ParsedReference."""

    def test_to_edge(self):
        """to_edge should convert to DicomReferenceEdge."""
        parsed = ParsedReference(
            relationship_type=ReferenceRelationshipType.REFERENCED_IMAGE.value,
            study_uid="1.2.3",
            series_uid="1.2.3.4",
            sop_uid="1.2.3.4.5",
            frame_number=2,
        )

        edge = parsed.to_edge(from_instance_id=100)

        assert edge.from_instance_id == 100
        assert edge.to_study_instance_uid == "1.2.3"
        assert edge.referenced_frame_number == 2


class TestReferenceEdgeSummary:
    """Tests for ReferenceEdgeSummary."""

    def test_to_dict(self):
        """to_dict should include all fields."""
        summary = ReferenceEdgeSummary(
            total_edges=10,
            resolved_count=7,
            unresolved_count=3,
            by_relationship_type={"referenced_image": 5, "source_instance": 5},
            by_resolution_status={"resolved": 7, "unresolved": 3},
        )

        data = summary.to_dict()

        assert data["total_edges"] == 10
        assert data["resolved_count"] == 7
        assert data["unresolved_count"] == 3
        assert data["by_relationship_type"]["referenced_image"] == 5
