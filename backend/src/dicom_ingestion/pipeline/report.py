"""Batch 7 ingest report generation."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from collections import Counter

from dicom_ingestion.models.ingestion_item import IngestionItem, TerminalOutcome
from dicom_ingestion.models.ingestion_job import IngestionJob


INTERNAL_METADATA_KEYS = {"absolute_path", "_internal_absolute_path", "local_path"}
FALLBACK_VALUES = {"UNKNOWN", "UNKNOWN_VENDOR", "UNKNOWN_DEVICE", "GENERIC", "NO_MEAS_UID"}


@dataclass
class Batch7IngestReport:
    """Stable machine-readable report for Batch 7 pipeline runs."""

    ingest_id: str
    source: dict[str, Any]
    summary: dict[str, Any]
    storage: dict[str, Any]
    fallbacks: list[dict[str, Any]] = field(default_factory=list)
    rejections: list[dict[str, Any]] = field(default_factory=list)
    failed_tasks: list[dict[str, Any]] = field(default_factory=list)
    items: list[dict[str, Any]] = field(default_factory=list)
    annotation_summary: dict[str, Any] = field(default_factory=dict)
    generated_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    def to_dict(self) -> dict[str, Any]:
        return {
            "ingest_id": self.ingest_id,
            "source": self.source,
            "summary": self.summary,
            "annotation_summary": self.annotation_summary,
            "storage": self.storage,
            "fallbacks": self.fallbacks,
            "rejections": self.rejections,
            "failed_tasks": self.failed_tasks,
            "items": self.items,
            "generated_at": self.generated_at,
        }


def sanitize_for_report(value: Any) -> Any:
    """Remove internal filesystem details from report payloads."""
    if isinstance(value, dict):
        return {key: sanitize_for_report(val) for key, val in value.items() if key not in INTERNAL_METADATA_KEYS}
    if isinstance(value, list):
        return [sanitize_for_report(item) for item in value]
    return value


def sanitize_source_error(err: dict[str, str]) -> dict[str, str]:
    """Sanitize source enumeration errors before they appear in report rejections."""
    path = err.get("path", "")
    detail = err.get("error_detail", "")
    if path:
        path_obj = Path(path)
        if path_obj.is_absolute():
            path = path_obj.name
    if ": " in detail:
        _message, _, tail = detail.partition(": ")
        if tail.startswith("/"):
            detail = _message
    return {
        "path": path,
        "error_code": err.get("error_code", "SourceError"),
        "error_detail": detail,
    }


class Batch7ReportBuilder:
    """Build Batch 7 report dictionaries from job/items."""

    def build(
        self,
        *,
        job: IngestionJob,
        items: list[IngestionItem],
        source_summary: dict[str, Any],
        source_errors: list[dict[str, str]] | None = None,
    ) -> Batch7IngestReport:
        accepted = [item for item in items if item.terminal_outcome == TerminalOutcome.ACCEPTED.value]
        rejected = [item for item in items if item.terminal_outcome == TerminalOutcome.REJECTED.value]
        failed = [item for item in items if item.terminal_outcome == TerminalOutcome.FAILED.value]
        storage_uris = [item.storage_uri for item in accepted if item.storage_uri]
        local_nas_count = sum(1 for uri in storage_uris if uri.startswith("local-nas://"))
        object_count = sum(1 for uri in storage_uris if uri.startswith("s3://"))
        fallback_counts = self._fallback_counts(items)

        annotation_summary = self._build_annotation_summary(items)
        report_items = []
        for item in items:
            full_tags = item.metadata.get("parsed_tags", {})
            # P1-1: report-safe identity projection — never expose PHI by default
            dicom_identity = {
                "study_uid": full_tags.get("study_uid", ""),
                "series_uid": full_tags.get("series_uid", ""),
                "sop_instance_uid": full_tags.get("sop_instance_uid", ""),
                "modality": full_tags.get("modality", ""),
            }
            annotation_refs = sanitize_for_report(item.metadata.get("annotation_refs", []))
            report_items.append(
                {
                    "item_id": item.id,
                    "relative_path": item.source_path,
                    "terminal_outcome": item.terminal_outcome,
                    "error_code": item.error_code,
                    "error_detail": item.error_detail,
                    "storage_uri": item.storage_uri,
                    "status_axes": item.status_axes.to_dict(),
                    "dicom_identity": sanitize_for_report(dicom_identity),
                    "annotation_refs": annotation_refs,
                }
            )

        rejection_rows = [
            {"relative_path": item.source_path, "reason": item.error_code, "detail": item.error_detail}
            for item in rejected
        ]
        rejection_rows.extend(
            {
                "relative_path": sanitized["path"],
                "reason": sanitized["error_code"],
                "detail": sanitized["error_detail"],
            }
            for sanitized in (sanitize_source_error(err) for err in (source_errors or []))
        )

        return Batch7IngestReport(
            ingest_id=str(job.id),
            source=sanitize_for_report(source_summary),
            summary={
                "total_items": len(items),
                "accepted_instances": len(accepted),
                "rejected_items": len(rejected) + len(source_errors or []),
                "failed_items": len(failed),
                "warnings": len(source_errors or []),
                "job_status": job.status.value,
            },
            storage={
                "stored_items": len(storage_uris),
                "local_nas": local_nas_count,
                "object": object_count,
                "uris": storage_uris,
            },
            fallbacks=[{"field": field, "fallback": fallback, "count": count} for (field, fallback), count in sorted(fallback_counts.items())],
            rejections=rejection_rows,
            failed_tasks=[
                {"relative_path": item.source_path, "stage": item.last_retryable_stage, "error_code": item.error_code, "error_detail": item.error_detail}
                for item in failed
            ],
            items=report_items,
            annotation_summary=annotation_summary,
        )

    def _build_annotation_summary(self, items: list[IngestionItem]) -> dict[str, Any]:
        task_type_counts: Counter[str] = Counter()
        referenced_items = 0
        items_with_annotations = 0
        items_missing_required = 0
        for item in items:
            refs = item.metadata.get("annotation_refs", [])
            if refs:
                items_with_annotations += 1
            referenced_items += len(refs)
            for ref in refs:
                task_type = ref.get("task_type")
                if task_type:
                    task_type_counts[str(task_type)] += 1
            if item.error_code == "RequiredAnnotationMissing":
                items_missing_required += 1
        return {
            "referenced_items": referenced_items,
            "items_with_annotations": items_with_annotations,
            "items_missing_required_annotations": items_missing_required,
            "task_type_counts": dict(sorted(task_type_counts.items())),
        }

    def _fallback_counts(self, items: list[IngestionItem]) -> dict[tuple[str, str], int]:
        counts: dict[tuple[str, str], int] = {}
        for item in items:
            for key, value in item.metadata.get("parsed_tags", {}).items():
                if isinstance(value, str) and value in FALLBACK_VALUES:
                    counts[(key, value)] = counts.get((key, value), 0) + 1
        return counts
