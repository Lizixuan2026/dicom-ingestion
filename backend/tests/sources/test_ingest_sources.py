from __future__ import annotations

import zipfile
from io import BytesIO
from pathlib import Path

import pytest

from dicom_ingestion.sources import FileListManifestSource, LocalFolderSource, ZipArchiveSourceAdapter


def dicom_magic_bytes(payload: bytes = b"payload") -> bytes:
    return b"\x00" * 128 + b"DICM" + payload


def test_local_folder_source_enumerates_nested_files_with_relative_paths(tmp_path):
    root = tmp_path / "incoming"
    nested = root / "study" / "series"
    nested.mkdir(parents=True)
    (nested / "image.dcm").write_bytes(dicom_magic_bytes())
    (root / "notes.txt").write_text("not dicom")

    result = LocalFolderSource(root, allowed_roots=[tmp_path]).enumerate()

    assert result.total_items == 2
    assert [item.original_relative_path for item in result.items] == ["notes.txt", "study/series/image.dcm"]
    assert result.errors == []


def test_local_folder_source_empty_folder_completes_with_zero_items(tmp_path):
    root = tmp_path / "empty"
    root.mkdir()

    result = LocalFolderSource(root, allowed_roots=[tmp_path]).enumerate()

    assert result.total_items == 0
    assert result.total_bytes == 0
    assert result.errors == []


def test_local_folder_source_reports_unreadable_file(monkeypatch, tmp_path):
    root = tmp_path / "incoming"
    root.mkdir()
    bad = root / "bad.dcm"
    bad.write_bytes(dicom_magic_bytes())
    original_stat = Path.stat

    def flaky_stat(self, *args, **kwargs):
        if self == bad:
            raise OSError("permission denied")
        return original_stat(self, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", flaky_stat)

    result = LocalFolderSource(root, allowed_roots=[tmp_path]).enumerate()

    assert result.items == []
    assert result.errors[0]["error_code"] == "SourceFileUnreadable"


def test_file_list_manifest_source_rejects_paths_outside_allowed_root(tmp_path):
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    outside = tmp_path / "outside.dcm"
    outside.write_bytes(dicom_magic_bytes())

    result = FileListManifestSource([outside], allowed_roots=[allowed]).enumerate()

    assert result.items == []
    assert result.errors[0]["error_code"] == "ManifestPathOutsideAllowedRoot"


def test_zip_adapter_reuses_existing_scanner_output():
    zip_buffer = BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("study/image.dcm", dicom_magic_bytes())
        zf.writestr("readme.txt", b"not dicom")

    result = ZipArchiveSourceAdapter(zip_buffer.getvalue(), filename="mixed.zip").enumerate()

    assert result.total_items == 2
    by_path = {item.original_relative_path: item for item in result.items}
    assert by_path["study/image.dcm"].metadata["is_dicom"] is True
    assert by_path["readme.txt"].metadata["is_dicom"] is False
