from __future__ import annotations

"""Repository for persisting terminal ingestion reports."""

import json
from datetime import datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Session


class TerminalReportRepository:
    def __init__(self, session: Session):
        self._session = session

    def upsert_report(self, report: dict[str, Any]) -> None:
        summary = report["summary"]
        metadata = report.get("metadata", {})
        self._session.execute(
            sa.text(
                """
                INSERT INTO dicom_ingestion_terminal_reports (
                    job_id, total_items, accepted_count, quarantined_count,
                    rejected_count, failed_count, duplicate_findings,
                    unresolved_references, classification, report_ready,
                    generated_at, report_metadata
                ) VALUES (
                    :job_id, :total_items, :accepted_count, :quarantined_count,
                    :rejected_count, :failed_count, :duplicate_findings,
                    :unresolved_references, :classification, :report_ready,
                    :generated_at, CAST(:report_metadata AS JSONB)
                )
                ON CONFLICT (job_id) DO UPDATE SET
                    total_items = EXCLUDED.total_items,
                    accepted_count = EXCLUDED.accepted_count,
                    quarantined_count = EXCLUDED.quarantined_count,
                    rejected_count = EXCLUDED.rejected_count,
                    failed_count = EXCLUDED.failed_count,
                    duplicate_findings = EXCLUDED.duplicate_findings,
                    unresolved_references = EXCLUDED.unresolved_references,
                    classification = EXCLUDED.classification,
                    report_ready = EXCLUDED.report_ready,
                    generated_at = EXCLUDED.generated_at,
                    report_metadata = EXCLUDED.report_metadata,
                    updated_at = now()
                """
            ),
            {
                **summary,
                "generated_at": datetime.fromisoformat(summary["generated_at"]),
                "report_metadata": json.dumps(metadata),
            },
        )
        self._session.execute(sa.text("DELETE FROM dicom_ingestion_terminal_report_items WHERE job_id=:job_id"), {"job_id": summary["job_id"]})
        for item in report.get("items", []):
            self._session.execute(
                sa.text(
                    """
                    INSERT INTO dicom_ingestion_terminal_report_items (
                      job_id, item_id, source_path, terminal_outcome, error_code,
                      error_detail, instance_id, observation_id, binding_status,
                      index_status, processing_duration_ms
                    ) VALUES (
                      :job_id, :item_id, :source_path, :terminal_outcome, :error_code,
                      :error_detail, :instance_id, :observation_id, :binding_status,
                      :index_status, :processing_duration_ms
                    )
                    """
                ),
                {"job_id": summary["job_id"], **item},
            )

    def get_report(self, job_id: int) -> dict[str, Any] | None:
        s = self._session.execute(sa.text("SELECT * FROM dicom_ingestion_terminal_reports WHERE job_id=:job_id"), {"job_id": job_id}).mappings().first()
        if not s:
            return None
        items = self._session.execute(sa.text("SELECT * FROM dicom_ingestion_terminal_report_items WHERE job_id=:job_id ORDER BY item_id"), {"job_id": job_id}).mappings().all()
        return {"summary": dict(s), "items": [dict(i) for i in items], "metadata": s.get("report_metadata") or {}}
