"""
Tests for DicomPrivateTag model (C2).

Acceptance criteria:
- Private tags store creator, tag address, VR, and raw value
- Redaction clears raw value and updates status
- Interpretation adds keyword and value
"""
import pytest
from datetime import datetime

from dicom_ingestion.models.private_tag import (
    DicomPrivateTag,
    PrivateTagRedactionStatus,
    PrivateTagPolicy,
    PrivateTagSummary,
)


class TestDicomPrivateTag:
    """Tests for DicomPrivateTag model."""

    def test_from_parsed_factory(self):
        """Factory method should create from parsed data."""
        tag = DicomPrivateTag.from_parsed(
            observation_id=100,
            creator="SIEMENS",
            tag="0019,0010",
            vr="LO",
            raw_value=b"test value",
        )

        assert tag.observation_id == 100
        assert tag.private_creator == "SIEMENS"
        assert tag.tag == "0019,0010"
        assert tag.vr == "LO"
        assert tag.raw_value == b"test value"
        assert tag.redaction_status == PrivateTagRedactionStatus.PRESERVED.value

    def test_redact_clears_values(self):
        """redact should clear raw value and update status."""
        tag = DicomPrivateTag(
            raw_value=b"secret",
            interpreted_value="secret text",
        )
        tag.redact("phi_policy")

        assert tag.raw_value is None
        assert tag.interpreted_value is None
        assert tag.redaction_status == PrivateTagRedactionStatus.REDACTED.value
        assert tag.redaction_reason == "phi_policy"

    def test_interpret_adds_metadata(self):
        """interpret should add keyword and value."""
        tag = DicomPrivateTag()
        tag.interpret("PrivateCreator", "MyVendor")

        assert tag.interpreted_keyword == "PrivateCreator"
        assert tag.interpreted_value == "MyVendor"
        assert tag.redaction_status == PrivateTagRedactionStatus.INTERPRETED.value

    def test_to_dict_hides_raw_binary(self):
        """to_dict should not expose raw binary data."""
        tag = DicomPrivateTag(
            raw_value=b"sensitive binary data here",
        )

        data = tag.to_dict()

        # The raw_value should be shown as a placeholder, not the actual data
        raw_value_str = str(data.get("raw_value", ""))
        assert "sensitive" not in raw_value_str  # Actual content hidden
        assert "bytes" in raw_value_str  # But we know it's binary data


class TestPrivateTagPolicy:
    """Tests for PrivateTagPolicy."""

    def test_default_action_is_preserve(self):
        """Default action should be preserve."""
        policy = PrivateTagPolicy()

        assert policy.default_action == "preserve"
        assert policy.get_action_for_creator("UNKNOWN") == "preserve"

    def test_redact_list(self):
        """Creators in redact list should be redacted."""
        policy = PrivateTagPolicy(
            redact_creators=["PHI_VENDOR"],
        )

        assert policy.get_action_for_creator("PHI_VENDOR") == "redact"
        assert policy.get_action_for_creator("OTHER") == "preserve"

    def test_preserve_list(self):
        """Creators in preserve list should be preserved."""
        policy = PrivateTagPolicy(
            preserve_creators=["SAFE_VENDOR"],
            default_action="redact",
        )

        assert policy.get_action_for_creator("SAFE_VENDOR") == "preserve"
        assert policy.get_action_for_creator("OTHER") == "redact"


class TestPrivateTagSummary:
    """Tests for PrivateTagSummary."""

    def test_to_dict(self):
        """to_dict should include all fields."""
        summary = PrivateTagSummary(
            observation_id=100,
            total_tags=10,
            by_creator={"SIEMENS": 5, "GE": 5},
            redacted_count=2,
            interpreted_count=3,
        )

        data = summary.to_dict()

        assert data["observation_id"] == 100
        assert data["total_tags"] == 10
        assert data["redacted_count"] == 2
        assert data["interpreted_count"] == 3
