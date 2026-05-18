# DICOM Ingestion — Batch 6 Execution Plan (Production Readiness)

## 1. Goal

Make the system safe to expose and operate in production.

## 2. Tickets

- `C7` observability implementation closure
- `D2` security + compliance pack
- `D4` rollout/rollback readiness and smoke checks

## 3. Entry conditions

Implementation vocabulary is stable and upstream batches have produced required operational interfaces.

## 4. Merge gates

1. Dashboards and alerts cover intake, canonical ingest, replay, and failure classes.
2. Security controls and compliance evidence are documented and testable.
3. Runbooks for deploy, rollback, incident triage, and replay are complete.
4. Pre-release smoke checks pass and are repeatable.

## 5. Batch closure

Batch 6 closes only when operator-facing documentation and automation are sufficient for handoff without original implementers present.
