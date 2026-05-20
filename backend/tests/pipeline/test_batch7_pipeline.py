from __future__ import annotations

import os
import tempfile
from pathlib import Path
from unittest.mock import Mock

import pytest

try:
    import pydicom
    from pydicom.dataset import FileDataset, FileMetaDataset
    from pydicom.uid import ExplicitVRLittleEndian, generate_uid
    HAS_PYDICOM = True
except ImportError:  # pragma: no cover
    HAS_PYDICOM = False

from dicom_ingestion.models.ingestion_item import ItemStatusValue, TerminalOutcome
from dicom_ingestion.path_generator.local_nas import LocalNASPathGenerator
from dicom_ingestion.pipeline import Batch7PipelineScheduler
from dicom_ingestion.sources import LocalFolderSource
from dicom_ingestion.storage.local_nas_storage import LocalNASStorageBackend
from dicom_ingestion.storage.manager import StorageManager

pytestmark = pytest.mark.skipif(not HAS_PYDICOM, reason="pydicom not installed")


def write_dicom(path: Path, *, missing_study_uid: bool = False, modality: str = "MR") -> None:
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
    if not missing_study_uid:
        ds.StudyInstanceUID = generate_uid()
    ds.SeriesInstanceUID = generate_uid()
    ds.Modality = modality
    ds.Manufacturer = "SIEMENS"
    ds.StationName = "Prisma"
    ds.save_as(str(path), write_like_original=False)


def make_scheduler(storage_root: Path) -> Batch7PipelineScheduler:
    backend = LocalNASStorageBackend(
        base_path=str(storage_root),
        path_generator=LocalNASPathGenerator(max_component_length=32),
        storage_root_id="test-root",
    )
    return Batch7PipelineScheduler(storage_manager=StorageManager(local_backend=backend))


def test_mixed_folder_pipeline_generates_partial_report_without_absolute_paths(tmp_path):
    incoming = tmp_path / "incoming"
    incoming.mkdir()
    write_dicom(incoming / "valid.dcm")
    write_dicom(incoming / "missing_study.dcm", missing_study_uid=True)
    (incoming / "notes.txt").write_text("not dicom")

    scheduler = make_scheduler(tmp_path / "store")
    result = scheduler.run(source=LocalFolderSource(incoming, allowed_roots=[tmp_path]), actor_id="uploader-1")
    report = result.report.to_dict()

    assert result.job.status.value == "completed"
    assert report["summary"]["total_items"] == 3
    assert report["summary"]["accepted_instances"] == 1
    assert report["summary"]["rejected_items"] == 2
    assert report["storage"]["local_nas"] == 1
    assert report["storage"]["uris"][0].startswith("local-nas://test-root/")
    assert "absolute_path" not in str(report)
    assert any(row["relative_path"] == "notes.txt" and row["reason"] == "NotDicomFile" for row in report["rejections"])
    assert any(row["relative_path"] == "missing_study.dcm" and row["reason"] == "MissingRequiredDicomTag" for row in report["rejections"])


def test_accepted_dicom_reaches_parse_storage_and_terminal_accepted(tmp_path):
    incoming = tmp_path / "incoming"
    incoming.mkdir()
    write_dicom(incoming / "valid.dcm")

    result = make_scheduler(tmp_path / "store").run(
        source=LocalFolderSource(incoming, allowed_roots=[tmp_path]),
        actor_id="uploader-1",
    )

    item = result.items[0]
    assert item.terminal_outcome == TerminalOutcome.ACCEPTED.value
    assert item.status_axes.scan_status == ItemStatusValue.COMPLETED.value
    assert item.status_axes.parse_status == ItemStatusValue.COMPLETED.value
    assert item.status_axes.storage_status == ItemStatusValue.COMPLETED.value
    assert item.storage_uri.startswith("local-nas://")


def test_storage_failure_marks_item_failed_and_report_includes_failure(tmp_path):
    incoming = tmp_path / "incoming"
    incoming.mkdir()
    write_dicom(incoming / "valid.dcm")

    failing_manager = Mock()
    failing_manager.store_for_archive.side_effect = RuntimeError("disk full")
    result = Batch7PipelineScheduler(storage_manager=failing_manager).run(
        source=LocalFolderSource(incoming, allowed_roots=[tmp_path]),
        actor_id="uploader-1",
    )

    item = result.items[0]
    assert item.terminal_outcome == TerminalOutcome.FAILED.value
    assert item.error_code == "UploadPackageStoreFailed"
    assert result.report.to_dict()["failed_tasks"][0]["error_detail"] == "disk full"
    assert result.job.status.value == "completed"


def test_rerunning_same_input_is_deterministic_and_does_not_version_same_bytes(tmp_path):
    incoming = tmp_path / "incoming"
    incoming.mkdir()
    write_dicom(incoming / "valid.dcm")

    scheduler = make_scheduler(tmp_path / "store")
    source = LocalFolderSource(incoming, allowed_roots=[tmp_path])

    first = scheduler.run(source=source, actor_id="uploader-1")
    second = scheduler.run(source=source, actor_id="uploader-1")

    assert first.items[0].storage_uri == second.items[0].storage_uri
    assert "_v001" not in second.items[0].storage_uri


def test_empty_folder_completes_with_zero_item_report(tmp_path):
    incoming = tmp_path / "incoming"
    incoming.mkdir()

    result = make_scheduler(tmp_path / "store").run(
        source=LocalFolderSource(incoming, allowed_roots=[tmp_path]),
        actor_id="uploader-1",
    )

    assert result.job.status.value == "completed"
    assert result.report.to_dict()["summary"]["total_items"] == 0
    assert result.report.to_dict()["summary"]["accepted_instances"] == 0


def test_report_does_not_expose_phi_fields(tmp_path):
    """P1-1: report item must not contain patient_name / patient_id."""
    incoming = tmp_path / "incoming"
    incoming.mkdir()
    write_dicom(incoming / "valid.dcm")

    result = make_scheduler(tmp_path / "store").run(
        source=LocalFolderSource(incoming, allowed_roots=[tmp_path]),
        actor_id="uploader-1",
    )

    report = result.report.to_dict()
    report_str = str(report)
    assert "patient_name" not in report_str.lower()
    assert "patient_id" not in report_str.lower()

    # dicom_identity should still be present for accepted items
    accepted_items = [it for it in report["items"] if it["terminal_outcome"] == TerminalOutcome.ACCEPTED.value]
    assert len(accepted_items) == 1
    identity = accepted_items[0]["dicom_identity"]
    assert "MR" in identity["modality"]
    assert identity["study_uid"]
    assert identity["series_uid"]
    assert identity["sop_instance_uid"]


def test_rejected_items_do_not_leave_pending_axes(tmp_path):
    """P1-2: non-DICOM and missing-required items must not show pending downstream axes."""
    incoming = tmp_path / "incoming"
    incoming.mkdir()
    write_dicom(incoming / "valid.dcm")
    write_dicom(incoming / "missing_study.dcm", missing_study_uid=True)
    (incoming / "notes.txt").write_text("not dicom")

    result = make_scheduler(tmp_path / "store").run(
        source=LocalFolderSource(incoming, allowed_roots=[tmp_path]),
        actor_id="uploader-1",
    )

    for item in result.items:
        axes = item.status_axes
        if item.terminal_outcome == TerminalOutcome.REJECTED.value:
            # downstream axes should be closed, not left pending
            assert axes.parse_status != ItemStatusValue.PENDING.value
            assert axes.storage_status != ItemStatusValue.PENDING.value
            assert axes.metadata_persistence_status != ItemStatusValue.PENDING.value
            assert axes.validation_status != ItemStatusValue.PENDING.value
            assert axes.binding_status != ItemStatusValue.PENDING.value
            assert axes.index_status != ItemStatusValue.PENDING.value


def test_bytes_only_source_cleans_temp_files(tmp_path):
    """P1-3: bytes-only source items must not leave temp files behind."""
    from unittest.mock import Mock
    from dicom_ingestion.sources.base import IngestSourceItem, SourceEnumerationResult

    dicom_path = tmp_path / "single.dcm"
    write_dicom(dicom_path)
    dicom_bytes = dicom_path.read_bytes()

    source = Mock()
    source.source_kind = "test"
    source.source_label = "bytes-test"
    source.enumerate.return_value = SourceEnumerationResult(
        source_kind="test",
        source_label="bytes-test",
        items=[
            IngestSourceItem(
                source_kind="test",
                original_relative_path="single.dcm",
                size_bytes=len(dicom_bytes),
                open_bytes=lambda: dicom_bytes,
                metadata={},  # no local_path => bytes-only
            )
        ],
    )

    scheduler = make_scheduler(tmp_path / "store")
    result = scheduler.run(source=source, actor_id="uploader-1")

    assert result.job.status.value == "completed"
    assert result.report.to_dict()["summary"]["accepted_instances"] == 1

    # Ensure no dicom-ingest-* temp files remain
    temp_files = [f for f in os.listdir(tempfile.gettempdir()) if f.startswith("dicom-ingest-")]
    assert len(temp_files) == 0, f"Leaked temp files: {temp_files}"
