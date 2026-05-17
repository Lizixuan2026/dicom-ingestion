# DICOM Ingestion Execution Pack

This folder contains the documents the team should open while **actually building** the DICOM ingestion feature.

It is intentionally separate from the root-level architecture, contract, and review documents. Those files define the durable truth of the system. This folder turns that truth into day-to-day execution.

## Use these files in order

1. `001_full_execution_plan.md` — the implementation control document for all batches.
2. `002_batch_1_execution_plan.md` — exactly what to open first, who owns it, and what must be true before Batch 2.
3. `003_batch_1_worktree_lanes.md` — how to split the first batch across parallel worktrees without creating merge soup.
4. `004_batch_1_definition_of_done.md` — the checklist that decides whether Batch 1 is really done.
5. `005_batch_1_handoff_checklist.md` — what must be handed to the next batch so downstream work does not inherit ambiguity.

## Source-of-truth hierarchy

```text
011 schema + contracts
        │
        ▼
012 minimum dependencies + task acceptance
        │
        ▼
013 full-feature construction order
        │
        ▼
014 operating checklist
        │
        ▼
this folder: execution control documents
```

This folder is **supporting**, not canonical. If a statement here conflicts with `011`, `012`, or `013`, the root-level documents win and this folder must be updated.

## When to update this folder

Update the execution pack when:

- batch order changes,
- worktree lanes change,
- merge gates change,
- owner assignments change,
- a Batch 1 artifact changes shape.

Do **not** use this folder to invent new product semantics, schema rules, or API contracts. That belongs upstream.
