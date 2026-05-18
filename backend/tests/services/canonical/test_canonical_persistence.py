"""Tests for canonical persistence service.

This module tests the CanonicalPersistenceService which is responsible for:
- Persisting canonical study/series/instance-level facts
- Creating observations with proper canonical marking
- Preserving parse provenance and failure envelopes
"""

from typing import Dict, List, Any
import pytest
from unittest.mock import MagicMock, AsyncMock
from datetime import datetime

from dicom_ingestion.services.canonical.canonical_persistence import (
    CanonicalPersistenceService,
    PersistenceResult,
    CanonicalFailureEnvelope,
)
from dicom_ingestion.services.parser.dicom_parser import ParsedDicomHeader, ParseMode
from dicom_ingestion.models.ingestion_item import IngestionItem, ItemStatusAxes, TerminalOutcome


class MockRawObjectStore:
    """Mock raw object store for testing."""

    def __init__(self, data: Dict[str, bytes] = None):
        self._data = data or {}

    def get(self, uri: str) -> bytes:
        return self._data.get(uri)

    def exists(self, uri: str) -> bool:
        return uri in self._data


@pytest.fixture
def mock_session():
    """Create a mock database session."""
    session = MagicMock()

    # Mock execute to return fetchable results
    def mock_execute(query, params=None):
        result = MagicMock()
        # Default: return no existing rows (creates new)
        result.fetchone = MagicMock(return_value=None)
        result.rowcount = 1
        return result

    session.execute = mock_execute
    return session


@pytest.fixture
def mock_raw_store():
    """Create a mock raw object store."""
    return MockRawObjectStore()


@pytest.fixture
def persistence_service(mock_session, mock_raw_store):
    """Create a canonical persistence service fixture."""
    return CanonicalPersistenceService(session=mock_session, raw_object_store=mock_raw_store)


@pytest.fixture
def sample_parsed_header():
    """Create a sample parsed DICOM header."""
    header = ParsedDicomHeader(parse_mode=ParseMode.HEADER_ONLY)
    header.required_tags = {
        "SOPInstanceUID": "1.2.840.10008.1.2.3.4.5.6.7.8.9",
        "SOPClassUID": "1.2.840.10008.5.1.4.1.1.2",
        "StudyInstanceUID": "1.2.840.10008.1.2.3.4.5.6.7.8.10",
        "SeriesInstanceUID": "1.2.840.10008.1.2.3.4.5.6.7.8.11",
        "PatientID": "P12345",
        "PatientName": "Test^Patient",
        "StudyDate": "20240101",
        "Modality": "CT",
        "SeriesNumber": "1",
        "InstanceNumber": "1",
        "TransferSyntaxUID": "1.2.840.10008.1.2.1",
    }
    header.raw_tags = header.required_tags.copy()
    return header


@pytest.fixture
def sample_ingestion_item():
    """Create a sample ingestion item."""
    item = IngestionItem(
        id=123,
        ingestion_job_id=456,
        source_path="/upload/test.dcm",
        byte_size=1024,
        item_fingerprint="abc123",
        status_axes=ItemStatusAxes(),
        terminal_outcome=TerminalOutcome.NONE.value,
        storage_uri="/storage/abc123",
        raw_object_sha256="def456",
    )
    return item


class TestCanonicalPersistenceService:
    """Test suite for CanonicalPersistenceService."""

    @pytest.mark.asyncio
    async def test_persist_success_creates_all_records(
        self,
        persistence_service: CanonicalPersistenceService,
        sample_ingestion_item: IngestionItem,
        sample_parsed_header: ParsedDicomHeader,
        mock_session: MagicMock,
    ):
        """Test successful persistence creates all canonical records."""
        # Setup mock: SELECT queries return None (not exists), INSERTs return IDs
        call_count = [0]
        def mock_execute(query, params=None):
            result = MagicMock()
            query_str = str(query) if isinstance(query, str) else str(query.text if hasattr(query, 'text') else query)

            # SELECT queries check for existing records - return None (not found)
            if "SELECT" in query_str.upper() and "FROM" in query_str.upper():
                result.fetchone = MagicMock(return_value=None)
            else:
                # INSERT/UPDATE queries - return new ID
                call_count[0] += 1
                result.fetchone = MagicMock(return_value=(call_count[0],))

            return result

        mock_session.execute = mock_execute

        result = await persistence_service.persist(sample_ingestion_item, sample_parsed_header)

        assert result.success is True
        assert result.study_id is not None
        assert result.series_id is not None
        assert result.instance_id is not None
        assert result.observation_id is not None
        assert result.is_new_canonical is True

    @pytest.mark.asyncio
    async def test_persist_missing_required_tags_returns_failure(
        self,
        persistence_service: CanonicalPersistenceService,
        sample_ingestion_item: IngestionItem,
    ):
        """Test that missing required tags returns failure result."""
        # Create header with missing required tags
        header = ParsedDicomHeader()
        header.required_tags = {}  # Empty - missing all required tags

        result = await persistence_service.persist(sample_ingestion_item, header)

        assert result.success is False
        assert result.error_code == "MissingRequiredDicomTag"
        assert "SOPInstanceUID" in result.error_detail

    @pytest.mark.asyncio
    async def test_validate_required_tags_detects_missing(
        self,
        persistence_service: CanonicalPersistenceService,
    ):
        """Test that missing required tags are detected."""
        tags = {
            "StudyInstanceUID": "1.2.3",
            "SeriesInstanceUID": "1.2.4",
            # Missing SOPInstanceUID and SOPClassUID
        }

        missing = persistence_service._validate_required_tags(tags)

        assert "SOPInstanceUID" in missing
        assert "SOPClassUID" in missing

    @pytest.mark.asyncio
    async def test_validate_required_tags_passes_with_all_present(
        self,
        persistence_service: CanonicalPersistenceService,
    ):
        """Test validation passes when all required tags present."""
        tags = {
            "SOPInstanceUID": "1.2.3",
            "SOPClassUID": "1.2.4",
            "StudyInstanceUID": "1.2.5",
            "SeriesInstanceUID": "1.2.6",
        }

        missing = persistence_service._validate_required_tags(tags)

        assert len(missing) == 0

    def test_extract_required_tags_from_header(
        self,
        persistence_service: CanonicalPersistenceService,
        sample_parsed_header: ParsedDicomHeader,
    ):
        """Test extraction of required tags from parsed header."""
        tags = persistence_service._extract_required_tags(sample_parsed_header)

        assert tags["SOPInstanceUID"] == "1.2.840.10008.1.2.3.4.5.6.7.8.9"
        assert tags["StudyInstanceUID"] == "1.2.840.10008.1.2.3.4.5.6.7.8.10"
        assert tags["Modality"] == "CT"

    def test_determine_object_class_family_ct(
        self,
        persistence_service: CanonicalPersistenceService,
    ):
        """Test CT SOP class detection."""
        family = persistence_service._determine_object_class_family(
            "1.2.840.10008.5.1.4.1.1.2"
        )
        assert family == "CT"

    def test_determine_object_class_family_mr(
        self,
        persistence_service: CanonicalPersistenceService,
    ):
        """Test MR SOP class detection."""
        family = persistence_service._determine_object_class_family(
            "1.2.840.10008.5.1.4.1.1.4"
        )
        assert family == "MR"

    def test_determine_object_class_family_other(
        self,
        persistence_service: CanonicalPersistenceService,
    ):
        """Test unknown SOP class falls back to OTHER."""
        family = persistence_service._determine_object_class_family(
            "1.2.840.10008.5.1.4.1.9.9.9"
        )
        assert family == "OTHER"

    def test_create_failure_envelope(
        self,
        persistence_service: CanonicalPersistenceService,
        sample_ingestion_item: IngestionItem,
    ):
        """Test creation of failure envelope."""
        envelope = persistence_service.create_failure_envelope(
            item=sample_ingestion_item,
            failure_stage="metadata_persistence",
            error_code="MetadataPersistenceFailed",
            error_message="Database connection failed",
            parsed_tags={"StudyInstanceUID": "1.2.3"},
        )

        assert envelope.item_id == sample_ingestion_item.id
        assert envelope.failure_stage == "metadata_persistence"
        assert envelope.error_code == "MetadataPersistenceFailed"
        assert envelope.raw_bytes_hash == sample_ingestion_item.raw_object_sha256
        assert "StudyInstanceUID" in envelope.parsed_tags

    def test_failure_envelope_to_dict(
        self,
        persistence_service: CanonicalPersistenceService,
        sample_ingestion_item: IngestionItem,
    ):
        """Test conversion of failure envelope to dictionary."""
        envelope = persistence_service.create_failure_envelope(
            item=sample_ingestion_item,
            failure_stage="parse",
            error_code="DicomParseFailed",
            error_message="Invalid DICOM format",
        )

        data = envelope.to_dict()

        assert data["item_id"] == sample_ingestion_item.id
        assert data["failure_stage"] == "parse"
        assert data["error_code"] == "DicomParseFailed"
        assert "timestamp" in data

    @pytest.mark.asyncio
    async def test_persist_exception_handling(
        self,
        persistence_service: CanonicalPersistenceService,
        sample_ingestion_item: IngestionItem,
        sample_parsed_header: ParsedDicomHeader,
        mock_session: MagicMock,
    ):
        """Test that exceptions during persistence are handled gracefully."""
        # Make session.execute raise an exception on first call
        original_execute = mock_session.execute
        call_count = [0]

        def mock_execute_with_error(query, params=None):
            call_count[0] += 1
            if call_count[0] == 1:
                raise Exception("Database connection failed")
            return original_execute(query, params)

        mock_session.execute = mock_execute_with_error

        result = await persistence_service.persist(sample_ingestion_item, sample_parsed_header)

        assert result.success is False
        assert result.error_code == "MetadataPersistenceFailed"
        assert "Database connection failed" in result.error_detail

    @pytest.mark.asyncio
    async def test_validate_canonical_fails_when_canonical_missing(
        self,
        persistence_service: CanonicalPersistenceService,
        mock_session: MagicMock,
    ):
        """Canonical invariant: current canonical observation must exist."""
        result = MagicMock()
        result.fetchone = MagicMock(return_value=(None, None, None))
        mock_session.execute = MagicMock(return_value=result)

        is_valid = await persistence_service.validate_canonical(instance_id=10)

        assert is_valid is False

    @pytest.mark.asyncio
    async def test_validate_canonical_fails_when_canonical_not_marked(
        self,
        persistence_service: CanonicalPersistenceService,
        mock_session: MagicMock,
    ):
        """Canonical invariant: current canonical observation must be marked."""
        result = MagicMock()
        result.fetchone = MagicMock(return_value=(99, False, 10))
        mock_session.execute = MagicMock(return_value=result)

        is_valid = await persistence_service.validate_canonical(instance_id=10)

        assert is_valid is False

    @pytest.mark.asyncio
    async def test_validate_canonical_fails_when_canonical_belongs_to_other_instance(
        self,
        persistence_service: CanonicalPersistenceService,
        mock_session: MagicMock,
    ):
        """Canonical invariant: current canonical observation must belong to instance."""
        result = MagicMock()
        result.fetchone = MagicMock(return_value=(99, True, 77))
        mock_session.execute = MagicMock(return_value=result)

        is_valid = await persistence_service.validate_canonical(instance_id=10)

        assert is_valid is False


class TestPersistenceResult:
    """Test suite for PersistenceResult dataclass."""

    def test_default_values(self):
        """Test default values of PersistenceResult."""
        result = PersistenceResult()

        assert result.success is False
        assert result.study_id is None
        assert result.series_id is None
        assert result.instance_id is None
        assert result.observation_id is None
        assert result.is_new_canonical is False
        assert result.error_code == ""
        assert result.error_detail == ""

    def test_custom_values(self):
        """Test custom values of PersistenceResult."""
        result = PersistenceResult(
            success=True,
            study_id=1,
            series_id=2,
            instance_id=3,
            observation_id=4,
            is_new_canonical=True,
        )

        assert result.success is True
        assert result.study_id == 1
        assert result.series_id == 2
        assert result.instance_id == 3
        assert result.observation_id == 4
        assert result.is_new_canonical is True


class TestCanonicalFailureEnvelope:
    """Test suite for CanonicalFailureEnvelope."""

    def test_failure_envelope_creation(self):
        """Test creation of failure envelope."""
        envelope = CanonicalFailureEnvelope(
            item_id=123,
            failure_stage="parse",
            error_code="DicomParseFailed",
            error_message="Invalid format",
            parsed_tags={"StudyInstanceUID": "1.2.3"},
            raw_bytes_hash="abc123",
        )

        assert envelope.item_id == 123
        assert envelope.failure_stage == "parse"
        assert envelope.error_code == "DicomParseFailed"
        assert envelope.parsed_tags["StudyInstanceUID"] == "1.2.3"
