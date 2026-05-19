"""In-process Batch 7 ingestion pipeline scheduler."""
from __future__ import annotations

import hashlib
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from dicom_ingestion.models.ingestion_item import IngestionItem, ItemStatusValue, TerminalOutcome
from dicom_ingestion.models.ingestion_job import IngestionJob, JobStatus
from dicom_ingestion.parser.factory import ConfigurableDicomParser, DicomParserFactory, ParseError
from dicom_ingestion.sources.base import IngestSourceItem, SourceEnumerationResult
from dicom_ingestion.storage.manager import StorageManager

from .report import Batch7IngestReport, Batch7ReportBuilder


@dataclass
class PipelineResult:
    """Result of one in-process ingest pipeline run."""

    job: IngestionJob
    items: list[IngestionItem]
    report: Batch7IngestReport
    source_errors: list[dict[str, str]] = field(default_factory=list)


class MaterializedSource:
    """Context manager for source item materialization.

    P1-3: Ensures temp files created from bytes-only sources are cleaned up.
    Local file sources are left untouched.
    """

    def __init__(self, source_item: IngestSourceItem, data: bytes) -> None:
        self.source_item = source_item
        self.data = data
        self.path: Optional[Path] = None
        self._is_temp = False

    def __enter__(self) -> Path:
        if self.source_item.local_path is not None:
            self.path = self.source_item.local_path
            return self.path
        suffix = Path(self.source_item.original_relative_path).suffix or ".dcm"
        temp = tempfile.NamedTemporaryFile(prefix="dicom-ingest-", suffix=suffix, delete=False)
        with temp:
            temp.write(self.data)
        self.path = Path(temp.name)
        self._is_temp = True
        return self.path

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        if self._is_temp and self.path is not None and self.path.exists():
            self.path.unlink()


class Batch7PipelineScheduler:
    """Sequential in-process pipeline for Batch 7 core ingestion.

    This deliberately avoids REST handlers and external queues. The explicit item
    axes are the async boundary that later workers can replace.
    """

    def __init__(
        self,
        *,
        storage_manager: StorageManager,
        parser: Optional[ConfigurableDicomParser] = None,
        report_builder: Optional[Batch7ReportBuilder] = None,
    ) -> None:
        self.storage_manager = storage_manager
        self.parser = parser or DicomParserFactory.create_parser("default")
        self.report_builder = report_builder or Batch7ReportBuilder()
        self._next_job_id = 1
        self._next_item_id = 1

    def run(self, *, source: Any, actor_id: str, request_idempotency_key: str = "") -> PipelineResult:
        job = IngestionJob(
            id=self._allocate_job_id(),
            actor_id=actor_id,
            request_idempotency_key=request_idempotency_key,
            source_type=getattr(source, "source_kind", "unknown"),
            metadata={"source_label": getattr(source, "source_label", "")},
        )
        items: list[IngestionItem] = []
        source_errors: list[dict[str, str]] = []

        try:
            job.transition_to(JobStatus.RECEIVING, "receiving source request")
            job.transition_to(JobStatus.SCANNING, "enumerating ingest source")
            enumeration: SourceEnumerationResult = source.enumerate()
            source_errors = enumeration.errors

            job.transition_to(JobStatus.PROCESSING, "processing source items")
            for source_item in enumeration.items:
                item = self._create_item(job.id, source_item)
                items.append(item)
                self._process_item(item, source_item)

            job.transition_to(JobStatus.FINALIZING, "generating ingest report")
            report = self.report_builder.build(
                job=job,
                items=items,
                source_summary={
                    "type": enumeration.source_kind,
                    "root_label": enumeration.source_label,
                    "total_items": enumeration.total_items,
                    "total_bytes": enumeration.total_bytes,
                },
                source_errors=source_errors,
            )
            job.transition_to(JobStatus.COMPLETED, "pipeline completed")
            # Rebuild after final transition so report shows terminal job status.
            report = self.report_builder.build(
                job=job,
                items=items,
                source_summary={
                    "type": enumeration.source_kind,
                    "root_label": enumeration.source_label,
                    "total_items": enumeration.total_items,
                    "total_bytes": enumeration.total_bytes,
                },
                source_errors=source_errors,
            )
            job.metadata["report"] = report.to_dict()
            return PipelineResult(job=job, items=items, report=report, source_errors=source_errors)
        except Exception as exc:
            job.fail(str(exc))
            report = self.report_builder.build(
                job=job,
                items=items,
                source_summary={"type": getattr(source, "source_kind", "unknown"), "root_label": getattr(source, "source_label", "")},
                source_errors=source_errors + [{"path": "", "error_code": "JobFatalError", "error_detail": str(exc)}],
            )
            job.metadata["report"] = report.to_dict()
            return PipelineResult(job=job, items=items, report=report, source_errors=source_errors)

    def _create_item(self, job_id: int, source_item: IngestSourceItem) -> IngestionItem:
        fingerprint_input = f"{job_id}:{source_item.source_kind}:{source_item.original_relative_path}:{source_item.size_bytes}"
        item = IngestionItem(
            id=self._allocate_item_id(),
            ingestion_job_id=job_id,
            source_path=source_item.original_relative_path,
            byte_size=source_item.size_bytes,
            item_fingerprint=hashlib.sha256(fingerprint_input.encode()).hexdigest(),
            metadata={"source_kind": source_item.source_kind},
        )
        item.mark_seen()
        return item

    def _process_item(self, item: IngestionItem, source_item: IngestSourceItem) -> None:
        try:
            data = source_item.open_bytes()
        except Exception as exc:
            item.mark_scanned(False, "SourceFileUnreadable")
            item.error_detail = str(exc)
            item.close_pending_axes()
            return

        if not self._looks_like_dicom(data):
            item.mark_scanned(False, IngestionItem.ERROR_NOT_DICOM)
            item.error_detail = "DICOM magic not found at byte offset 128"
            item.close_pending_axes()
            return

        item.mark_scanned(True)

        with MaterializedSource(source_item, data) as source_path:
            try:
                parse_result = self.parser.parse(str(source_path))
            except ParseError as exc:
                item.mark_parsed(False, "ParseError", str(exc))
                item.set_terminal_outcome(TerminalOutcome.REJECTED, IngestionItem.ERROR_MISSING_REQUIRED_TAG, str(exc))
                item.close_pending_axes()
                return
            except Exception as exc:
                item.mark_parsed(False, IngestionItem.ERROR_PARSE_FAILED, str(exc))
                item.set_terminal_outcome(TerminalOutcome.REJECTED, IngestionItem.ERROR_PARSE_FAILED, str(exc))
                item.close_pending_axes()
                return

            if not parse_result.success:
                error_detail = "; ".join(parse_result.errors) or "parse failed"
                item.mark_parsed(False, IngestionItem.ERROR_MISSING_REQUIRED_TAG, error_detail)
                item.set_terminal_outcome(TerminalOutcome.REJECTED, IngestionItem.ERROR_MISSING_REQUIRED_TAG, error_detail)
                item.close_pending_axes()
                return

            item.mark_parsed(True)
            item.metadata["parsed_tags"] = parse_result.tags
            item.metadata["parse_warnings"] = parse_result.warnings

            try:
                location = self.storage_manager.store_for_archive(str(source_path), {**parse_result.tags, "suggested_path": item.source_path})
                item.mark_stored(location.uri, location.checksum)
                item.metadata["storage"] = {
                    "mode": location.mode.value if hasattr(location.mode, "value") else str(location.mode),
                    "uri": location.uri,
                    "path": location.path,
                    "metadata": {key: value for key, value in location.metadata.items() if key not in {"absolute_path", "local_path"}},
                }
            except Exception as exc:
                item.mark_storage_failed(IngestionItem.ERROR_STORAGE_FAILED)
                item.error_detail = str(exc)
                item.set_terminal_outcome(TerminalOutcome.FAILED, IngestionItem.ERROR_STORAGE_FAILED, str(exc))
                return

            item.mark_metadata_persisted()
            item.mark_validated()
            item.mark_bound()
            item.mark_indexed()
            item.set_terminal_outcome(TerminalOutcome.ACCEPTED)

    def _looks_like_dicom(self, data: bytes) -> bool:
        return len(data) >= 132 and data[128:132] == b"DICM"

    def _allocate_job_id(self) -> int:
        value = self._next_job_id
        self._next_job_id += 1
        return value

    def _allocate_item_id(self) -> int:
        value = self._next_item_id
        self._next_item_id += 1
        return value
