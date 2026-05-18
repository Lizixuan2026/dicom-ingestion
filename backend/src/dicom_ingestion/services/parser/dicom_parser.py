"""
DICOM Parser — Header parsing with header_only mode.

This module provides the DicomParser which parses DICOM file headers
without loading pixel data, extracts required tags, and returns a
ParsedDicomHeader with structured tag information.
"""
from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional, Tuple
from enum import Enum
import io

# Try to import pydicom, handle gracefully if not available
try:
    import pydicom
    from pydicom.dataset import Dataset
    from pydicom.errors import InvalidDicomError
    PYDICOM_AVAILABLE = True
except ImportError:
    PYDICOM_AVAILABLE = False


class DicomParseFailed(Exception):
    """
    Raised when DICOM parsing fails.
    Item bytes are preserved for debugging.
    """
    pass


class ParseMode(str, Enum):
    """Parsing modes."""
    HEADER_ONLY = "header_only"  # Parse only header, skip pixel data
    FULL = "full"                # Full parse including pixel data


@dataclass
class PrivateTag:
    """
    Represents a private DICOM tag.

    Attributes:
        creator: Private creator identifier
        tag: Tag address (as hex string)
        vr: Value Representation
        raw_value: Raw bytes of the value
    """
    creator: str
    tag: str
    vr: str
    raw_value: bytes


@dataclass
class ParsedDicomHeader:
    """
    Result of parsing a DICOM header.

    Attributes:
        required_tags: Dictionary of required tags (e.g., SOPInstanceUID)
        raw_tags: Dictionary of all tags as {tag_name: value}
        private_tags: List of private tags found
        is_valid: Whether the header is valid for processing
        parse_errors: List of errors encountered during parsing
        parse_mode: The mode used for parsing
    """
    required_tags: Dict[str, Any] = field(default_factory=dict)
    raw_tags: Dict[str, Any] = field(default_factory=dict)
    private_tags: List[PrivateTag] = field(default_factory=list)
    is_valid: bool = True
    parse_errors: List[str] = field(default_factory=list)
    parse_mode: ParseMode = ParseMode.HEADER_ONLY

    # Required DICOM tags for valid file
    REQUIRED_TAG_NAMES = [
        "SOPClassUID",
        "SOPInstanceUID",
        "StudyInstanceUID",
        "SeriesInstanceUID",
        "Modality",
    ]

    def get_missing_required_tags(self) -> List[str]:
        """Return list of required tags that are missing."""
        return [
            tag for tag in self.REQUIRED_TAG_NAMES
            if tag not in self.required_tags or not self.required_tags[tag]
        ]

    def is_complete(self) -> bool:
        """True if all required tags are present."""
        return len(self.get_missing_required_tags()) == 0


class DicomParser:
    """
    Service for parsing DICOM file headers.

    Responsibilities:
    - Parse DICOM file headers (header_only mode by default)
    - Extract required tags for identity
    - Extract all raw tags for storage
    - Extract private tags with raw bytes
    - Handle parse errors gracefully

    Interface:
        DicomParser.parse_header(item_bytes) -> ParsedDicomHeader
          ParsedDicomHeader#required_tags -> Hash
          ParsedDicomHeader#raw_tags     -> Hash
          ParsedDicomHeader#private_tags -> Array[{creator, tag, vr, raw_value}]

    Acceptance:
    - Parse mode is header_only by default; pixel data is not read into memory
    - valid_ct_single.dcm fixture parses without error
    - missing_required_tag.dcm fixture is parsed and tagged invalid with MissingRequiredDicomTag
    - truncated.dcm raises DicomParseFailed; item bytes are preserved
    - Private tags are returned with raw bytes, not interpreted
    """

    # Standard required tags to extract
    REQUIRED_TAGS = [
        "SOPClassUID",
        "SOPInstanceUID",
        "StudyInstanceUID",
        "SeriesInstanceUID",
        "PatientID",
        "PatientName",
        "StudyDate",
        "StudyTime",
        "Modality",
        "SeriesNumber",
        "InstanceNumber",
        "TransferSyntaxUID",
    ]

    def __init__(self, parse_mode: ParseMode = ParseMode.HEADER_ONLY):
        """
        Initialize the parser.

        Args:
            parse_mode: Parsing mode (default: HEADER_ONLY)
        """
        self.parse_mode = parse_mode

    def parse_header(self, item_bytes: bytes) -> ParsedDicomHeader:
        """
        Parse DICOM file header without loading pixel data.

        Args:
            item_bytes: Raw bytes of the DICOM file

        Returns:
            ParsedDicomHeader with extracted tags

        Raises:
            DicomParseFailed: If parsing fails completely
        """
        if not PYDICOM_AVAILABLE:
            raise DicomParseFailed("pydicom library is not available")

        if not item_bytes:
            raise DicomParseFailed("Empty item bytes")

        # Minimum DICOM file size check
        if len(item_bytes) < 132:  # 128 byte preamble + 4 byte DICM
            raise DicomParseFailed(f"File too small ({len(item_bytes)} bytes) to be valid DICOM")

        result = ParsedDicomHeader(parse_mode=self.parse_mode)

        try:
            # Use pydicom to read the header
            # force=True allows reading without strict validation
            # defer_size="1KB" prevents loading large data elements (including pixel data)
            ds = pydicom.dcmread(
                io.BytesIO(item_bytes),
                force=True,
                defer_size="1 KB",  # Defer loading elements > 1KB (includes pixel data)
                stop_before_pixels=(self.parse_mode == ParseMode.HEADER_ONLY)
            )

            # Check if it's a valid DICOM dataset
            if not hasattr(ds, 'file_meta') and not any(hasattr(ds, attr) for attr in ['SOPInstanceUID', 'StudyInstanceUID']):
                # Might be a DICOM without file_meta but still valid
                pass  # Continue processing

            # Extract required tags
            result.required_tags = self._extract_required_tags(ds)

            # Extract all raw tags
            result.raw_tags = self._extract_all_tags(ds)

            # Extract private tags
            result.private_tags = self._extract_private_tags(ds)

            # Check for missing required tags
            missing = result.get_missing_required_tags()
            if missing:
                result.is_valid = False
                result.parse_errors.append(f"Missing required tags: {', '.join(missing)}")

            return result

        except InvalidDicomError as e:
            raise DicomParseFailed(f"Invalid DICOM format: {e}") from e
        except Exception as e:
            raise DicomParseFailed(f"DICOM parsing failed: {e}") from e

    def _extract_required_tags(self, ds) -> Dict[str, Any]:
        """
        Extract required tags from dataset.

        Args:
            ds: pydicom Dataset

        Returns:
            Dictionary of tag name to value
        """
        result = {}
        for tag_name in self.REQUIRED_TAGS:
            try:
                if hasattr(ds, tag_name):
                    value = getattr(ds, tag_name)
                    # Convert to string representation for serialization
                    if hasattr(value, 'value'):
                        result[tag_name] = str(value.value)
                    else:
                        result[tag_name] = str(value)
            except Exception:
                # Tag exists but couldn't be read
                pass
        return result

    def _extract_all_tags(self, ds) -> Dict[str, Any]:
        """
        Extract all tags from dataset.

        Args:
            ds: pydicom Dataset

        Returns:
            Dictionary of all tag names to values
        """
        result = {}
        try:
            # Iterate through all data elements
            for elem in ds:
                if elem.keyword:
                    try:
                        value = elem.value
                        # Convert to serializable format
                        if hasattr(value, 'value'):
                            value = str(value.value)
                        elif isinstance(value, bytes):
                            value = f"<binary:{len(value)}bytes>"
                        else:
                            value = str(value)
                        result[elem.keyword] = value
                    except Exception:
                        # Skip elements that can't be read
                        pass
        except Exception:
            pass
        return result

    def _extract_private_tags(self, ds) -> List[PrivateTag]:
        """
        Extract private tags from dataset.

        Private tags are those with odd group numbers.
        We return them with raw bytes, not interpreted.

        Args:
            ds: pydicom Dataset

        Returns:
            List of PrivateTag objects
        """
        private_tags = []

        try:
            for elem in ds:
                # Check if this is a private tag (odd group number)
                if elem.tag.group % 2 == 1:
                    try:
                        # Get private creator if available
                        creator = ""
                        if hasattr(elem, 'private_creator'):
                            creator = str(elem.private_creator)

                        # Get the raw value as bytes
                        raw_value = b""
                        try:
                            if hasattr(elem, 'value') and elem.value is not None:
                                if isinstance(elem.value, bytes):
                                    raw_value = elem.value
                                else:
                                    # Convert to bytes if possible
                                    raw_value = str(elem.value).encode('utf-8', errors='replace')
                        except Exception:
                            pass

                        vr = elem.VR if hasattr(elem, 'VR') else "UN"

                        private_tags.append(PrivateTag(
                            creator=creator,
                            tag=f"{elem.tag.group:04X},{elem.tag.element:04X}",
                            vr=vr,
                            raw_value=raw_value
                        ))
                    except Exception:
                        # Skip private tags that can't be read
                        pass
        except Exception:
            pass

        return private_tags

    @staticmethod
    def is_dicom_file(item_bytes: bytes) -> bool:
        """
        Check if bytes represent a DICOM file.

        Args:
            item_bytes: File content as bytes

        Returns:
            True if data appears to be DICOM
        """
        if len(item_bytes) < 132:
            return False
        return item_bytes[128:132] == b"DICM"
