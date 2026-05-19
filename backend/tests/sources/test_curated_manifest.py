from __future__ import annotations

import json
from pathlib import Path

import pytest

from dicom_ingestion.sources import CuratedUploadManifestSource
from dicom_ingestion.sources.curated_manifest import CuratedManifestError


def write_manifest(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_curated_manifest_file_samples_attach_annotation_refs(tmp_path):
    root = tmp_path / "package"
    data = root / "data"
    label1 = root / "label1"
    data.mkdir(parents=True)
    label1.mkdir()
    (data / "sample_001.dcm").write_bytes(b"\x00" * 128 + b"DICM" + b"payload")
    (label1 / "sample_001.json").write_text("{}")

    manifest = root / "data_manifest.json"
    write_manifest(
        manifest,
        {
            "data": "data",
            "annotation": [{"path": "label1", "task_type": "segmentation", "name": "label1"}],
        },
    )

    result = CuratedUploadManifestSource(manifest, allowed_roots=[root]).enumerate()

    assert len(result.items) == 1
    item = result.items[0]
    assert item.original_relative_path == "data/sample_001.dcm"
    assert len(item.annotations) == 1
    assert item.annotations[0].source_relative_path == "label1/sample_001.json"
    assert item.annotations[0].task_type == "segmentation"
    assert item.annotations[0].label_name == "label1"


def test_curated_manifest_folder_samples_attach_annotation_refs(tmp_path):
    root = tmp_path / "package"
    data = root / "data" / "sample_001"
    label1 = root / "label1" / "sample_001"
    data.mkdir(parents=True)
    label1.mkdir(parents=True)
    (data / "image_1.dcm").write_bytes(b"\x00" * 128 + b"DICM" + b"payload")
    (label1 / "mask.nii.gz").write_bytes(b"mask")

    manifest = root / "data_manifest.json"
    write_manifest(
        manifest,
        {
            "data": "data",
            "annotation": [{"path": "label1", "task_type": "segmentation"}],
        },
    )

    result = CuratedUploadManifestSource(manifest, allowed_roots=[root]).enumerate()

    assert len(result.items) == 1
    assert result.items[0].annotations[0].source_relative_path == "label1/sample_001"


def test_curated_manifest_relative_paths_resolve_from_manifest_dir(tmp_path):
    root = tmp_path / "package"
    data = root / "data"
    label1 = root / "label1"
    data.mkdir(parents=True)
    label1.mkdir(parents=True)
    (data / "sample_001.dcm").write_bytes(b"\x00" * 128 + b"DICM")
    (label1 / "sample_001.json").write_text("{}")

    manifest = root / "data_manifest.json"
    write_manifest(
        manifest,
        {
            "version": 1,
            "type": "curated_upload_manifest",
            "data": {"path": "data"},
            "annotation": [{"path": "label1", "task_type": "localization"}],
        },
    )

    result = CuratedUploadManifestSource(manifest, allowed_roots=[root]).enumerate()

    assert result.items[0].original_relative_path == "data/sample_001.dcm"


def test_curated_manifest_rejects_data_path_outside_allowed_roots(tmp_path):
    root = tmp_path / "package"
    outside = tmp_path / "outside"
    outside.mkdir()
    manifest = root / "data_manifest.json"
    write_manifest(manifest, {"data": str(outside), "annotation": []})

    with pytest.raises(CuratedManifestError) as exc:
        CuratedUploadManifestSource(manifest, allowed_roots=[root]).enumerate()

    assert exc.value.error_code == "CuratedManifestDataPathOutsideAllowedRoot"


def test_curated_manifest_reports_annotation_path_outside_allowed_root(tmp_path):
    root = tmp_path / "package"
    data = root / "data"
    data.mkdir(parents=True)
    (data / "sample_001.dcm").write_bytes(b"\x00" * 128 + b"DICM")
    outside = tmp_path / "outside_label"
    outside.mkdir()
    (outside / "sample_001.json").write_text("{}")

    manifest = root / "data_manifest.json"
    write_manifest(
        manifest,
        {"data": "data", "annotation": [{"path": str(outside), "task_type": "segmentation"}]},
    )

    result = CuratedUploadManifestSource(manifest, allowed_roots=[root]).enumerate()

    assert result.items[0].annotations == []
    assert any(err["error_code"] == "AnnotationPathOutsideAllowedRoot" for err in result.errors)


def test_curated_manifest_missing_optional_annotation_is_warning_not_fatal(tmp_path):
    root = tmp_path / "package"
    data = root / "data"
    data.mkdir(parents=True)
    (data / "sample_001.dcm").write_bytes(b"\x00" * 128 + b"DICM")

    manifest = root / "data_manifest.json"
    write_manifest(
        manifest,
        {
            "data": "data",
            "annotation": [{"path": "missing_label", "task_type": "detection", "required": False}],
        },
    )

    result = CuratedUploadManifestSource(manifest, allowed_roots=[root]).enumerate()

    assert len(result.items) == 1
    assert result.items[0].annotations == []
    assert any(err["error_code"] == "AnnotationPathMissing" for err in result.errors)


def test_curated_manifest_duplicate_sample_id_is_visible(tmp_path):
    root = tmp_path / "package"
    data = root / "data"
    data.mkdir(parents=True)
    nested = data / "sample_001"
    nested.mkdir()
    (data / "sample_001.dcm").write_bytes(b"\x00" * 128 + b"DICM")
    (nested / "image_1.dcm").write_bytes(b"\x00" * 128 + b"DICM")

    manifest = root / "data_manifest.json"
    write_manifest(manifest, {"data": "data", "annotation": []})

    result = CuratedUploadManifestSource(manifest, allowed_roots=[root]).enumerate()

    assert result.items == []
    assert any(err["error_code"] == "DuplicateCuratedSampleId" for err in result.errors)


def test_curated_manifest_folder_sample_allows_multiple_data_files(tmp_path):
    root = tmp_path / "package"
    data = root / "data" / "sample_001"
    label1 = root / "label1"
    data.mkdir(parents=True)
    label1.mkdir()
    (data / "image_1.dcm").write_bytes(b"\x00" * 128 + b"DICM")
    (data / "image_2.dcm").write_bytes(b"\x00" * 128 + b"DICM")
    (label1 / "sample_001").mkdir()

    manifest = root / "data_manifest.json"
    write_manifest(
        manifest,
        {"data": "data", "annotation": [{"path": "label1", "task_type": "segmentation"}]},
    )

    result = CuratedUploadManifestSource(manifest, allowed_roots=[root]).enumerate()

    assert len(result.items) == 2
    paths = {item.original_relative_path for item in result.items}
    assert paths == {"data/sample_001/image_1.dcm", "data/sample_001/image_2.dcm"}
    assert all(item.annotations[0].source_relative_path == "label1/sample_001" for item in result.items)
    assert not any(err["error_code"] == "DuplicateCuratedSampleId" for err in result.errors)


def test_curated_manifest_source_errors_do_not_leak_absolute_paths(tmp_path):
    root = tmp_path / "package"
    data = root / "data"
    data.mkdir(parents=True)
    (data / "sample_001.dcm").write_bytes(b"\x00" * 128 + b"DICM")

    manifest = root / "data_manifest.json"
    write_manifest(
        manifest,
        {"data": "data", "annotation": [{"path": "missing_label", "required": False}]},
    )

    result = CuratedUploadManifestSource(manifest, allowed_roots=[root]).enumerate()
    blob = json.dumps(result.errors)

    assert str(tmp_path) not in blob
    assert "/private/" not in blob


def test_curated_manifest_preserves_task_type_as_tag(tmp_path):
    root = tmp_path / "package"
    data = root / "data"
    label1 = root / "label1"
    data.mkdir(parents=True)
    label1.mkdir(parents=True)
    (data / "sample_001.dcm").write_bytes(b"\x00" * 128 + b"DICM")
    (label1 / "sample_001.json").write_text("{}")

    manifest = root / "data_manifest.json"
    write_manifest(
        manifest,
        {
            "data": "data",
            "annotation": [{"path": "label1", "task_type": "custom_future_task"}],
        },
    )

    result = CuratedUploadManifestSource(manifest, allowed_roots=[root]).enumerate()

    assert result.items[0].annotations[0].task_type == "custom_future_task"
