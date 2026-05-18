# DICOM Ingestion — Batch 5 Execution Plan (Query + Replay)

## 1. Goal

Make ingestion state queryable and recoverable.

## 2. Tickets and order

- `C5` projection foundation
- `C6` retry/replay foundation
- `D1` review queries (depends on Batch 4 semantic facts)
- `D3` operational reindex/rebuild

`C5/C6` may start after `B6` exists, but batch closure waits for Batch 4 dependencies needed by `D1`.

## 3. Merge gates

1. Read models/projected views rebuild from source-of-truth events/state.
2. Retry/replay does not require end-user re-upload.
3. Query interfaces expose ingest/review semantics coherently.
4. Reindex/rebuild workflow is executable via documented operator steps.

## 4. Handoff

Provide stable query/replay/rebuild interfaces and artifacts required by Batch 6 production-readiness work.
