"""Batch 7 ingest report generation."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

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
    generated_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    def to_dict(self) -> dict[str, Any]:
        return {
            "ingest_id": self.ingest_id,
            "source": self.source,
            "summary": self.summary,
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
                }
            )

        rejection_rows = [
            {"relative_path": item.source_path, "reason": item.error_code, "detail": item.error_detail}
            for item in rejected
        ]
        rejection_rows.extend(
            {"relative_path": err.get("path", ""), "reason": err.get("error_code", "SourceError"), "detail": err.get("error_detail", "")}
            for err in (source_errors or [])
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
        )

    def _fallback_counts(self, items: list[IngestionItem]) -> dict[tuple[str, str], int]:
        counts: dict[tuple[str, str], int] = {}
        for item in items:
            for key, value in item.metadata.get("parsed_tags", {}).items():
                if isinstance(value, str) and value in FALLBACK_VALUES:
                    counts[(key, value)] = counts.get((key, value), 0) + 1
        return counts
