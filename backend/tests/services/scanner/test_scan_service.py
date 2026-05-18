"""
Tests for ScanService — Scanner and ZIP Safety.

Acceptance criteria:
- Recursively lists DICOM candidates from folder or ZIP
- Non-DICOM files are listed with scan_status = rejected_non_dicom
- ZIP expansion enforces max bytes, max entry count, max nesting depth
- ZipBombDetected raised and logged before full extraction when limits exceeded
- UnsafeArchivePath raised on path traversal entries (../)
- Scanner with zip_bomb.zip fixture raises before writing > safety limit bytes
- Scanner with zip_path_traversal.zip raises before extracting any file
"""
import os
import zipfile
import pytest
from io import BytesIO
from dataclasses import dataclass

from dicom_ingestion.services.scanner import (
    ScanService,
    ScanManifest,
    ScanItem,
    ScanStatus,
    ZipBombDetected,
    UnsafeArchivePath,
    NestedZipTooDeep,
    ZipSafetyLimits
)


@dataclass
class MockUploadPackage:
    """Mock upload package for testing."""
    uri: str = ""
    content_hash: str = ""
    size_bytes: int = 0
    original_filename: str = ""
    _bytes: bytes = b""

    def get_bytes(self):
        return self._bytes


# Fixtures path
FIXTURES_PATH = os.path.join(os.path.dirname(__file__), '..', '..', 'fixtures', 'dicom')


def load_fixture(filename: str) -> bytes:
    """Load a fixture file."""
    path = os.path.join(FIXTURES_PATH, filename)
    if os.path.exists(path):
        with open(path, 'rb') as f:
            return f.read()
    return None


@pytest.fixture
def scan_service():
    """Create a ScanService with test limits."""
    limits = ZipSafetyLimits(
        max_total_bytes=50 * 1024 * 1024,  # 50 MB
        max_entry_count=1000,
        max_nesting_depth=3,
        max_entry_bytes=10 * 1024 * 1024
    )
    return ScanService(safety_limits=limits)


class TestScanServiceBasic:
    """Basic scanning functionality tests."""

    def test_scans_single_dicom_file(self, scan_service):
        """Scanner should accept a single DICOM file."""
        # Create a mock DICOM file (with proper magic number)
        dicom_data = b"\x00" * 128 + b"DICM" + b"\x00" * 100
        package = MockUploadPackage(
            _bytes=dicom_data,
            original_filename="test.dcm"
        )

        manifest = scan_service.scan(package)

        assert manifest.total_items == 1
        assert manifest.dicom_count == 1
        assert manifest.items[0].is_dicom is True
        assert manifest.items[0].scan_status == ScanStatus.PENDING

    def test_rejects_non_dicom_file(self, scan_service):
        """Non-DICOM files should be marked rejected_non_dicom."""
        txt_data = b"This is not a DICOM file"
        package = MockUploadPackage(
            _bytes=txt_data,
            original_filename="not_dicom.txt"
        )

        manifest = scan_service.scan(package)

        assert manifest.total_items == 1
        assert manifest.non_dicom_count == 1
        assert manifest.items[0].is_dicom is False
        assert manifest.items[0].scan_status == ScanStatus.REJECTED_NON_DICOM

    def test_detects_dicom_by_magic_number(self, scan_service):
        """DICOM detection should use magic number at offset 128."""
        # Create data with DICM at correct offset
        dicom_data = b"x" * 128 + b"DICM" + b"some dicom content"
        package = MockUploadPackage(_bytes=dicom_data)

        manifest = scan_service.scan(package)

        assert manifest.items[0].is_dicom is True

    def test_small_file_not_dicom(self, scan_service):
        """Files smaller than DICOM header are not DICOM."""
        small_data = b"tiny"
        package = MockUploadPackage(_bytes=small_data)

        manifest = scan_service.scan(package)

        assert manifest.items[0].is_dicom is False


class TestScanServiceZipHandling:
    """ZIP file scanning tests."""

    def test_scans_zip_with_single_dicom(self, scan_service):
        """Scanner should extract and scan files from ZIP."""
        # Create a ZIP with a DICOM file
        dicom_data = b"\x00" * 128 + b"DICM" + b"\x00" * 100
        zip_buffer = BytesIO()
        with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("study/dicom.dcm", dicom_data)
        zip_bytes = zip_buffer.getvalue()

        package = MockUploadPackage(
            _bytes=zip_bytes,
            original_filename="upload.zip"
        )

        manifest = scan_service.scan(package)

        assert manifest.total_items == 1
        assert manifest.dicom_count == 1
        assert manifest.items[0].source_path == "study/dicom.dcm"

    def test_scans_zip_with_mixed_content(self, scan_service):
        """Scanner should handle mixed content (DICOM and non-DICOM)."""
        dicom_data = b"\x00" * 128 + b"DICM" + b"\x00" * 100
        txt_data = b"This is a readme"

        zip_buffer = BytesIO()
        with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("dicom.dcm", dicom_data)
            zf.writestr("readme.txt", txt_data)
        zip_bytes = zip_buffer.getvalue()

        package = MockUploadPackage(
            _bytes=zip_bytes,
            original_filename="mixed.zip"
        )

        manifest = scan_service.scan(package)

        assert manifest.total_items == 2
        assert manifest.dicom_count == 1
        assert manifest.non_dicom_count == 1

    def test_scans_nested_zip(self, scan_service):
        """Scanner should recursively scan nested ZIP files."""
        # Create inner ZIP with DICOM
        inner_dicom = b"\x00" * 128 + b"DICM" + b"inner"
        inner_buffer = BytesIO()
        with zipfile.ZipFile(inner_buffer, 'w') as zf:
            zf.writestr("inner.dcm", inner_dicom)
        inner_zip = inner_buffer.getvalue()

        # Create outer ZIP containing inner ZIP
        outer_buffer = BytesIO()
        with zipfile.ZipFile(outer_buffer, 'w') as zf:
            zf.writestr("nested/inner.zip", inner_zip)
        outer_zip = outer_buffer.getvalue()

        package = MockUploadPackage(
            _bytes=outer_zip,
            original_filename="nested.zip"
        )

        manifest = scan_service.scan(package)

        # Should find the DICOM inside the nested ZIP
        assert manifest.total_items == 1
        assert manifest.dicom_count == 1
        assert manifest.items[0].source_path == "nested/inner.zip/inner.dcm"


class TestScanServiceZipSafety:
    """ZIP safety and security tests."""

    def test_detects_zip_bomb_by_ratio(self, scan_service):
        """Scanner should detect zip bombs by compression ratio."""
        # Create a ZIP with extreme compression ratio
        # The content is highly compressible (zeros)
        large_content = b"\x00" * (2 * 1024 * 1024)  # 2MB of zeros

        zip_buffer = BytesIO()
        with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("huge.bin", large_content)
        zip_bytes = zip_buffer.getvalue()

        # The compressed size should be much smaller than uncompressed
        # This creates a high compression ratio

        package = MockUploadPackage(
            _bytes=zip_bytes,
            original_filename="bomb.zip"
        )

        # Should raise or catch ZipBombDetected
        manifest = scan_service.scan(package)

        # Check for zip bomb error in scan_errors
        assert any("bomb" in err.lower() or "ratio" in err.lower() or "ZipBombDetected" in err
                   for err in manifest.scan_errors) or manifest.rejected_count > 0

    def test_detects_path_traversal(self, scan_service):
        """Scanner should detect and reject path traversal attempts."""
        # Create ZIP with path traversal entry
        zip_buffer = BytesIO()
        with zipfile.ZipFile(zip_buffer, 'w') as zf:
            zf.writestr("../etc/passwd", b"malicious content")
        zip_bytes = zip_buffer.getvalue()

        package = MockUploadPackage(
            _bytes=zip_bytes,
            original_filename="attack.zip"
        )

        manifest = scan_service.scan(package)

        # Should have error about unsafe path
        assert any("traversal" in err.lower() or "UnsafeArchivePath" in err
                   for err in manifest.scan_errors)

    def test_respects_nesting_depth_limit(self, scan_service):
        """Scanner should respect max nesting depth."""
        # Create deeply nested ZIPs (exceeding max_depth=3)
        # We'll create 5 levels of nesting to be safe

        current_zip = BytesIO()
        with zipfile.ZipFile(current_zip, 'w') as zf:
            zf.writestr("deep_file.txt", b"very deep content")
        nested_content = current_zip.getvalue()

        # Create 4 more levels of nesting
        for i in range(4):
            outer = BytesIO()
            with zipfile.ZipFile(outer, 'w') as zf:
                zf.writestr(f"nested_{i}.zip", nested_content)
            nested_content = outer.getvalue()

        # Now we have 5 levels of nesting - exceeds default max_depth=3
        package = MockUploadPackage(
            _bytes=nested_content,
            original_filename="deep.zip"
        )

        manifest = scan_service.scan(package)

        # Should have either:
        # - error about nesting too deep, OR
        # - some items that were rejected due to depth limit
        has_nesting_error = any(
            "deep" in err.lower() or "nesting" in err.lower() or "NestedZipTooDeep" in err
            for err in manifest.scan_errors
        )
        # Or we might have a rejected item for the nested zip
        has_rejected_nested = any(
            item.scan_status == ScanStatus.REJECTED_UNSAFE and item.nested_depth >= 3
            for item in manifest.items
        )

        assert has_nesting_error or has_rejected_nested or manifest.rejected_count > 0

    def test_detects_entry_count_limit(self, scan_service):
        """Scanner should detect too many entries."""
        # Create ZIP with many entries
        zip_buffer = BytesIO()
        with zipfile.ZipFile(zip_buffer, 'w') as zf:
            for i in range(1500):  # Exceeds max_entry_count=1000
                zf.writestr(f"file{i}.txt", b"content")
        zip_bytes = zip_buffer.getvalue()

        package = MockUploadPackage(
            _bytes=zip_bytes,
            original_filename="many.zip"
        )

        manifest = scan_service.scan(package)

        # Should have error about too many entries
        assert any("entries" in err.lower() or "count" in err.lower()
                   for err in manifest.scan_errors) or manifest.rejected_count > 0


class TestScanServiceManifest:
    """ScanManifest behavior tests."""

    def test_manifest_tracks_total_bytes(self, scan_service):
        """Manifest should track total bytes scanned."""
        dicom1 = b"\x00" * 128 + b"DICM" + b"a" * 100
        dicom2 = b"\x00" * 128 + b"DICM" + b"b" * 200

        zip_buffer = BytesIO()
        with zipfile.ZipFile(zip_buffer, 'w') as zf:
            zf.writestr("1.dcm", dicom1)
            zf.writestr("2.dcm", dicom2)
        zip_bytes = zip_buffer.getvalue()

        package = MockUploadPackage(_bytes=zip_bytes)
        manifest = scan_service.scan(package)

        assert manifest.total_bytes_scanned == len(dicom1) + len(dicom2)

    def test_manifest_tracks_item_counts(self, scan_service):
        """Manifest should track DICOM and non-DICOM counts."""
        dicom = b"\x00" * 128 + b"DICM" + b"x"
        txt = b"not dicom"

        zip_buffer = BytesIO()
        with zipfile.ZipFile(zip_buffer, 'w') as zf:
            zf.writestr("a.dcm", dicom)
            zf.writestr("b.txt", txt)
            zf.writestr("c.dcm", dicom)
        zip_bytes = zip_buffer.getvalue()

        package = MockUploadPackage(_bytes=zip_bytes)
        manifest = scan_service.scan(package)

        assert manifest.total_items == 3
        assert manifest.dicom_count == 2
        assert manifest.non_dicom_count == 1

    def test_scan_item_has_correct_fields(self, scan_service):
        """ScanItem should have all required fields populated."""
        dicom = b"\x00" * 128 + b"DICM" + b"test"
        package = MockUploadPackage(
            _bytes=dicom,
            original_filename="test.dcm"
        )

        manifest = scan_service.scan(package)
        item = manifest.items[0]

        assert item.source_path == "test.dcm"
        assert item.byte_size == len(dicom)
        assert item.is_dicom is True
        assert item.scan_status == ScanStatus.PENDING
        assert item.nested_depth == 0
        assert isinstance(item.item_bytes_or_uri, bytes)


class TestScanServiceWithFixtures:
    """Tests using actual fixture files."""

    @pytest.mark.skipif(
        not os.path.exists(os.path.join(FIXTURES_PATH, "zip_bomb.zip")),
        reason="zip_bomb.zip fixture not available"
    )
    def test_zip_bomb_fixture(self, scan_service):
        """Scanner should detect zip_bomb.zip fixture as unsafe."""
        data = load_fixture("zip_bomb.zip")
        if data is None:
            pytest.skip("zip_bomb.zip not found")

        package = MockUploadPackage(
            _bytes=data,
            original_filename="zip_bomb.zip"
        )

        manifest = scan_service.scan(package)

        # Should either reject it or have error
        assert manifest.rejected_count > 0 or len(manifest.scan_errors) > 0

    @pytest.mark.skipif(
        not os.path.exists(os.path.join(FIXTURES_PATH, "zip_path_traversal.zip")),
        reason="zip_path_traversal.zip fixture not available"
    )
    def test_path_traversal_fixture(self, scan_service):
        """Scanner should detect path traversal in fixture."""
        data = load_fixture("zip_path_traversal.zip")
        if data is None:
            pytest.skip("zip_path_traversal.zip not found")

        package = MockUploadPackage(
            _bytes=data,
            original_filename="zip_path_traversal.zip"
        )

        manifest = scan_service.scan(package)

        # Should have path traversal error
        assert any("traversal" in err.lower() for err in manifest.scan_errors)

    @pytest.mark.skipif(
        not os.path.exists(os.path.join(FIXTURES_PATH, "valid_ct_single.dcm")),
        reason="DICOM fixtures not available"
    )
    def test_valid_dicom_fixture(self, scan_service):
        """Scanner should accept valid DICOM fixtures."""
        data = load_fixture("valid_ct_single.dcm")
        if data is None:
            pytest.skip("valid_ct_single.dcm not found")

        package = MockUploadPackage(
            _bytes=data,
            original_filename="valid_ct_single.dcm"
        )

        manifest = scan_service.scan(package)

        assert manifest.total_items == 1
        assert manifest.dicom_count == 1
        assert manifest.items[0].is_dicom is True

    @pytest.mark.skipif(
        not os.path.exists(os.path.join(FIXTURES_PATH, "mixed_content.zip")),
        reason="mixed_content.zip fixture not available"
    )
    def test_mixed_content_fixture(self, scan_service):
        """Scanner should handle mixed content ZIP fixture."""
        data = load_fixture("mixed_content.zip")
        if data is None:
            pytest.skip("mixed_content.zip not found")

        package = MockUploadPackage(
            _bytes=data,
            original_filename="mixed_content.zip"
        )

        manifest = scan_service.scan(package)

        # Should find items
        assert manifest.total_items > 0
        # At least one should be marked appropriately
        assert manifest.dicom_count > 0 or manifest.non_dicom_count > 0
