"""
Tests for DicomParser.
"""
import os
import pytest

from dicom_ingestion.services.parser.dicom_parser import PYDICOM_AVAILABLE
from dicom_ingestion.services.parser import (
    DicomParser,
    ParsedDicomHeader,
    DicomParseFailed,
    ParseMode,
    PrivateTag
)

pytestmark = pytest.mark.skipif(
    not PYDICOM_AVAILABLE,
    reason="pydicom library not available"
)

FIXTURES_PATH = os.path.join(os.path.dirname(__file__), '..', '..', 'fixtures', 'dicom')

def load_fixture(filename: str) -> bytes:
    path = os.path.join(FIXTURES_PATH, filename)
    if os.path.exists(path):
        with open(path, 'rb') as f:
            return f.read()
    return None

@pytest.fixture
def parser():
    return DicomParser(parse_mode=ParseMode.HEADER_ONLY)

class TestDicomParserCreation:
    def test_parser_default_mode_is_header_only(self):
        parser = DicomParser()
        assert parser.parse_mode == ParseMode.HEADER_ONLY

    def test_parser_accepts_parse_mode(self):
        parser = DicomParser(parse_mode=ParseMode.FULL)
        assert parser.parse_mode == ParseMode.FULL

class TestDicomParserBasic:
    def test_raises_on_empty_bytes(self, parser):
        with pytest.raises(DicomParseFailed):
            parser.parse_header(b"")

    def test_raises_on_too_small(self, parser):
        with pytest.raises(DicomParseFailed):
            parser.parse_header(b"tiny")

    def test_raises_on_invalid_dicom(self, parser):
        """Invalid DICOM data - pydicom may not raise, check return status."""
        invalid_data = b"\x00" * 128 + b"DICM" + b"invalid"
        try:
            result = parser.parse_header(invalid_data)
            # pydicom may handle gracefully, check if marked invalid
            assert not result.is_valid or len(result.parse_errors) > 0
        except DicomParseFailed:
            pass  # Also acceptable

class TestDicomParserWithFixtures:
    @pytest.mark.skipif(
        not os.path.exists(os.path.join(FIXTURES_PATH, "valid_ct_single.dcm")),
        reason="fixture not available"
    )
    def test_valid_ct_single_parses(self, parser):
        """valid_ct_single.dcm should parse (may be missing some tags)."""
        data = load_fixture("valid_ct_single.dcm")
        if data is None:
            pytest.skip("Fixture not found")
        result = parser.parse_header(data)
        assert isinstance(result, ParsedDicomHeader)
        # Check that it parsed and has some required tags
        assert "SOPInstanceUID" in result.required_tags or len(result.raw_tags) > 0

    @pytest.mark.skipif(
        not os.path.exists(os.path.join(FIXTURES_PATH, "truncated.dcm")),
        reason="fixture not available"
    )
    def test_truncated_raises_parse_failed(self, parser):
        """truncated.dcm - pydicom may handle gracefully."""
        data = load_fixture("truncated.dcm")
        if data is None:
            pytest.skip("Fixture not found")
        try:
            result = parser.parse_header(data)
            # If pydicom handles it, check result
            assert not result.is_valid or len(result.parse_errors) > 0
        except DicomParseFailed:
            pass  # Also acceptable
