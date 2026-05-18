# DICOM Ingestion — Batch 4 Execution Plan (Review Semantics)

## 1. Goal

Make duplicates, references, private tags, and binding policy executable semantics.

## 2. Tickets and order

1. `C1/C2/C3/C4` in parallel lanes where possible
2. `C1b` closes after `C1` duplicate facts are available

## 3. Entry conditions

Batch 3 canonical ingest must be green and stable.

## 4. Lanes

- Duplicate facts and canonical pointer policy (`C1`, then `C1b`)
- Private tag persistence + redaction policy boundaries (`C2`)
- Reference edge extraction/storage (`C3`)
- Binding policy between intake/canonical/review artifacts (`C4`)

## 5. Merge gates

Batch 4 is done when review semantics are executable:

1. Duplicate detection outputs deterministic fact records and pointer selection rationale.
2. Reference edges are queryable and preserved across replay.
3. Private tags follow explicit storage/redaction policy.
4. Binding policy can be validated by tests, not tribal knowledge.

## 6. Handoff

Deliver the semantic facts and APIs consumed by Batch 5 query/replay and `D1` duplicate-review UX behavior.
