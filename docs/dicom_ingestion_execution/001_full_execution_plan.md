# DICOM Ingestion — Full Execution Plan

Parent documents:

- `../012_migration_first_backlog.md`
- `../013_dicom_ingestion_full_feature_implementation_roadmap.md`
- `../014_dicom_ingestion_execution_start_checklist.md`

## 1. Purpose

This is the document to run the implementation from.

The product scope is already fixed. The question here is not "what are we building?" It is:

> what do we open now, what can run in parallel, what must merge before the next batch, and where do we stop if reality disagrees with the plan?

## 2. Execution model

```text
Batch 1  contracts + fixtures + storage + observability vocabulary
   │
   ▼
Batch 2  durable intake
   │
   ▼
Batch 3  canonical ingest
   │
   ▼
Batch 4  review semantics
   │
   ▼
Batch 5  query + replay
   │
   ▼
Batch 6  production readiness
```

The graph is deliberately boring. Good. New ingestion systems already contain enough ways to surprise you.

## 3. Batch board

| Batch | Goal | Tickets | Entry condition | Exit condition |
| --- | --- | --- | --- | --- |
| 1 | Freeze the truths everything else depends on | `A1-a..A1-l`, `A1-z`, `A2`, `A3`, observability vocabulary draft | now | schema invariants, fixtures, storage contract, and provisional event vocabulary are green |
| 2 | Make every incoming file visible and durable | `B2`, then `B1/B3`, then `B4/B5` | Batch 1 green | mixed ZIP proves every candidate is tracked and unsafe input fails loudly |
| 3 | Produce canonical DICOM truth end to end | `B6`, `B7` | Batch 2 green | upload -> raw bytes -> canonical rows -> terminal report works |
| 4 | Make duplicates, refs, and binding explainable | `C1/C2/C3/C4`, then `C1b` | Batch 3 green | review semantics are executable, not implied |
| 5 | Make the system queryable and recoverable | `C5`, `C6`, `D1`, `D3` | `C5/C6` may start after `B6`; batch closes after Batch 4 facts exist for `D1` | projection rebuild, retry, query, and reindex all work |
| 6 | Make it safe to expose | `C7`, `D2`, `D4` | implementation vocabulary stable | dashboards, security pack, runbooks, rollback, smoke checks all exist |

## 4. Launch sequence

```text
NOW
  ├── Lane A: A1 schema + invariants
  ├── Lane B: A2 fixtures
  ├── Lane C: A3 raw storage contract
  └── Lane D: observability vocabulary draft

AFTER BATCH 1 GREEN
  B2
    ├── B1 upload API
    └── B3 scanner + ZIP safety
          └── B4 + B5 after candidate-item contract is stable

AFTER BATCH 2 GREEN
  B6 + B7

AFTER BATCH 3 GREEN
  ├── C1 duplicate facts -> C1b
  ├── C2 private tags
  ├── C3 reference edges
  └── C4 binding policy

AFTER B6 EXISTS
  ├── C5 projection foundation
  └── C6 retry/replay foundation

RELEASE CLOSE
  C1 + C1b + C3 + C5 -> D1
  B1..C6 + C1b -> C7 -> D2
  C5 + C6 -> D3
  D1 + D2 + D3 -> D4
```

## 5. Operating rules

1. **No batch advances on partial truth.** If the merge gate is not met, the next batch does not start because someone is "almost done." Almost done is how you manufacture two versions of the same contract.
2. **Downstream work may start early only when the minimum dependency is explicit in `012`.** Example: `C5` and `C6` can begin after `B6`, even though they close later.
3. **Every batch ends with a reality check.** Read the gate, run the tests, inspect the artifacts. No ceremony, just proof.
4. **If implementation reveals a missing contract, stop and route the change upstream.** Update `011` or `012` first. Do not let the execution docs become a shadow spec.
5. **Observability is not cleanup work.** The vocabulary starts in Batch 1; the final implementation closes in Batch 6.

## 6. Stop-the-line conditions

Stop the current batch if any of these happen:

- a ticket needs to invent a field absent from `011`,
- two lanes name the same state or event differently,
- raw bytes can be lost while the system reports apparent acceptance,
- a retry path requires re-upload from the user,
- canonical pointer changes become implicit side effects of duplicate detection,
- a gate can only be "proven" by reading logs manually.

## 7. Review cadence

| Moment | Review |
| --- | --- |
| before Batch 1 starts | plan complete, now done |
| after Batch 1 merges | reality check against `A1-z`, fixture manifest, raw storage tests, observability vocabulary |
| after Batch 3 merges | first end-to-end ingest review |
| after Batch 4 merges | semantics review before user-facing query work closes |
| before rollout | production-readiness review against Batch 6 artifacts |

## 8. What is intentionally not in this plan

- UI design for rich curation workflows, because v1 exposes review semantics before inventing a bigger product surface.
- Deep SEG / RTSTRUCT / SR enrichment, because reference preservation comes first.
- Vendor-specific private-tag interpretation catalogs, because the storage model should exist before policy accretes.
- Viewer work, because it is a separate product surface.

## 9. Immediate next action

Open Batch 1 now using:

1. `002_batch_1_execution_plan.md`
2. `003_batch_1_worktree_lanes.md`
3. `004_batch_1_definition_of_done.md`
4. `005_batch_1_handoff_checklist.md`

After Batch 1, continue in order with:

5. `006_batch_2_execution_plan.md`
6. `007_batch_3_execution_plan.md`
7. `008_batch_4_execution_plan.md`
8. `009_batch_5_execution_plan.md`
9. `010_batch_6_execution_plan.md`
