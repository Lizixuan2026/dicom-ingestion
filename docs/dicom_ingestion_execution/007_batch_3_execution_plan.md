# DICOM Ingestion — Batch 3 Execution Plan (Canonical Ingest)

Parent documents:

- `001_full_execution_plan.md`
- `../011_dicom_ingestion_schema_and_contracts.md`
- `../013_dicom_ingestion_full_feature_implementation_roadmap.md`

## 1. Goal

Produce canonical DICOM truth end-to-end:

- accepted intake candidates can be materialized to canonical ingest units,
- DICOM tag extraction and normalization land in canonical tables,
- each candidate reaches a terminal ingest report state.

## 2. Tickets and order

1. `B6` canonical ingest pipeline foundation
2. `B7` ingest result reporting/terminalization

## 3. Entry conditions

Start only after Batch 2 gate is green and candidate-item contract is stable.

## 4. Implementation lanes

### Lane A — Canonical parse + persistence (`B6`)

- read bytes from raw storage via immutable pointers,
- parse DICOM envelope safely,
- persist canonical study/series/instance-level facts per `011`,
- preserve parse provenance and deterministic failure envelopes.

### Lane B — Terminal reporting (`B7`)

- convert ingest outcomes into terminal candidate-level reports,
- aggregate per-upload summaries,
- guarantee machine-readable terminal status for success/partial/failure.

## 5. Merge gates

Batch 3 is done when:

1. Upload -> candidate-item -> canonical rows path works across success and failure fixtures.
2. Canonical persistence is deterministic for repeated ingest of identical bytes.
3. Terminal ingest reporting is complete and queryable.
4. Failures retain actionable reason classification without log-only diagnostics.

## 6. Handoff to Batch 4/5

Publish:

- canonical entity mapping notes,
- terminal status taxonomy for downstream review semantics,
- fixtures capturing duplicates/references/private-tag-preservation seeds for Batch 4,
- stable canonical read interfaces needed by Batch 5 projection/replay work.
