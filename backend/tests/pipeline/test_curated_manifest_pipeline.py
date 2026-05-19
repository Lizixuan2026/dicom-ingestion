from __future__ import annotations

import json
from pathlib import Path

import pytest

try:
    import pydicom
    from pydicom.dataset import FileDataset, FileMetaDataset
    from pydicom.uid import ExplicitVRLittleEndian, generate_uid
    HAS_PYDICOM = True
except ImportError:  # pragma: no cover
    HAS_PYDICOM = False

from dicom_ingestion.models.ingestion_item import TerminalOutcome
from dicom_ingestion.path_generator.local_nas import LocalNASPathGenerator
from dicom_ingestion.pipeline import Batch7PipelineScheduler
from dicom_ingestion.sources import CuratedUploadManifestSource
from dicom_ingestion.storage.local_nas_storage import LocalNASStorageBackend
from dicom_ingestion.storage.manager import StorageManager

pytestmark = pytest.mark.skipif(not HAS_PYDICOM, reason="pydicom not installed")


def write_dicom(path: Path) -> None:
    file_meta = FileMetaDataset()
    file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
    file_meta.MediaStorageSOPClassUID = generate_uid()
    file_meta.MediaStorageSOPInstanceUID = generate_uid()
    file_meta.ImplementationClassUID = generate_uid()

    ds = FileDataset(str(path), {}, file_meta=file_meta, preamble=b"\0" * 128)
    ds.is_little_endian = True
    ds.is_implicit_VR = False
    ds.SOPClassUID = file_meta.MediaStorageSOPClassUID
    ds.SOPInstanceUID = file_meta.MediaStorageSOPInstanceUID
    ds.StudyInstanceUID = generate_uid()
    ds.SeriesInstanceUID = generate_uid()
    ds.Modality = "MR"
    ds.save_as(str(path), write_like_original=False)


def make_scheduler(storage_root: Path) -> Batch7PipelineScheduler:
    backend = LocalNASStorageBackend(
        base_path=str(storage_root),
        path_generator=LocalNASPathGenerator(max_component_length=32),
        storage_root_id="test-root",
    )
    return Batch7PipelineScheduler(storage_manager=StorageManager(local_backend=backend))


def build_curated_package(tmp_path: Path, *, required_label: bool = False, include_label: bool = True) -> Path:
    root = tmp_path / "package"
    data = root / "data"
    label1 = root / "label1"
    data.mkdir(parents=True)
    if include_label:
        label1.mkdir()
        (label1 / "sample_001.json").write_text("{}")
    write_dicom(data / "sample_001.dcm")
    manifest = root / "data_manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "data": "data",
                "annotation": [
                    {
                        "path": "label1",
                        "task_type": "segmentation",
                        "name": "label1",
                        "required": required_label,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return manifest


def test_curated_manifest_valid_dicom_with_annotation_is_accepted(tmp_path):
    manifest = build_curated_package(tmp_path)
    result = make_scheduler(tmp_path / "store").run(
        source=CuratedUploadManifestSource(manifest, allowed_roots=[tmp_path / "package"]),
        actor_id="uploader-1",
    )

    assert result.items[0].terminal_outcome == TerminalOutcome.ACCEPTED.value
    assert result.job.status.value == "completed"


def test_curated_manifest_annotation_files_are_not_parsed_as_dicom_items(tmp_path):
    manifest = build_curated_package(tmp_path)
    result = make_scheduler(tmp_path / "store").run(
        source=CuratedUploadManifestSource(manifest, allowed_roots=[tmp_path / "package"]),
        actor_id="uploader-1",
    )

    assert len(result.items) == 1
    assert all("label1" not in item.source_path for item in result.items)


def test_curated_manifest_report_includes_annotation_refs(tmp_path):
    manifest = build_curated_package(tmp_path)
    report = make_scheduler(tmp_path / "store").run(
        source=CuratedUploadManifestSource(manifest, allowed_roots=[tmp_path / "package"]),
        actor_id="uploader-1",
    ).report.to_dict()

    item = report["items"][0]
    assert item["annotation_refs"][0]["source_relative_path"] == "label1/sample_001.json"
    assert item["annotation_refs"][0]["task_type"] == "segmentation"


def test_curated_manifest_report_includes_annotation_summary(tmp_path):
    manifest = build_curated_package(tmp_path)
    report = make_scheduler(tmp_path / "store").run(
        source=CuratedUploadManifestSource(manifest, allowed_roots=[tmp_path / "package"]),
        actor_id="uploader-1",
    ).report.to_dict()

    summary = report["annotation_summary"]
    assert summary["referenced_items"] == 1
    assert summary["items_with_annotations"] == 1
    assert summary["items_missing_required_annotations"] == 0
    assert summary["task_type_counts"]["segmentation"] == 1


def test_curated_manifest_report_excludes_absolute_annotation_paths(tmp_path):
    manifest = build_curated_package(tmp_path)
    report = make_scheduler(tmp_path / "store").run(
        source=CuratedUploadManifestSource(manifest, allowed_roots=[tmp_path / "package"]),
        actor_id="uploader-1",
    ).report.to_dict()

    assert str(tmp_path) not in json.dumps(report)


def test_curated_manifest_required_annotation_missing_rejects_item(tmp_path):
    manifest = build_curated_package(tmp_path, required_label=True, include_label=False)
    result = make_scheduler(tmp_path / "store").run(
        source=CuratedUploadManifestSource(manifest, allowed_roots=[tmp_path / "package"]),
        actor_id="uploader-1",
    )

    assert result.items[0].terminal_outcome == TerminalOutcome.REJECTED.value
    assert result.items[0].error_code == "RequiredAnnotationMissing"
    report = result.report.to_dict()
    assert report["annotation_summary"]["items_missing_required_annotations"] == 1
    assert any(row["reason"] == "RequiredAnnotationMissing" for row in report["rejections"])


def test_curated_manifest_fatal_error_preserves_specific_error_code_in_report(tmp_path):
    root = tmp_path / "package"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    manifest = root / "data_manifest.json"
    manifest.write_text(json.dumps({"data": str(outside), "annotation": []}), encoding="utf-8")

    result = make_scheduler(tmp_path / "store").run(
        source=CuratedUploadManifestSource(manifest, allowed_roots=[root]),
        actor_id="uploader-1",
    )
    report = result.report.to_dict()

    assert any(row["reason"] == "CuratedManifestDataPathOutsideAllowedRoot" for row in report["rejections"])
    assert str(tmp_path) not in json.dumps(report["rejections"])


def test_curated_manifest_optional_missing_annotation_report_excludes_absolute_path(tmp_path):
    root = tmp_path / "package"
    data = root / "data"
    data.mkdir(parents=True)
    write_dicom(data / "sample_001.dcm")
    manifest = root / "data_manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "data": "data",
                "annotation": [{"path": "missing_label", "task_type": "detection", "required": False}],
            }
        ),
        encoding="utf-8",
    )

    report = make_scheduler(tmp_path / "store").run(
        source=CuratedUploadManifestSource(manifest, allowed_roots=[root]),
        actor_id="uploader-1",
    ).report.to_dict()

    assert str(tmp_path) not in json.dumps(report["rejections"])
    assert any(row["reason"] == "AnnotationPathMissing" for row in report["rejections"])


def test_curated_manifest_optional_annotation_missing_does_not_reject_item(tmp_path):
    manifest = build_curated_package(tmp_path, required_label=False, include_label=False)
    result = make_scheduler(tmp_path / "store").run(
        source=CuratedUploadManifestSource(manifest, allowed_roots=[tmp_path / "package"]),
        actor_id="uploader-1",
    )

    assert result.items[0].terminal_outcome == TerminalOutcome.ACCEPTED.value
    assert result.items[0].metadata.get("annotation_refs") == []
