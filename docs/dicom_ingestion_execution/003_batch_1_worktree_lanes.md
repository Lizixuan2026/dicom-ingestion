# DICOM Ingestion — Batch 1 Worktree Lanes

## 1. Purpose

Batch 1 has real parallelism. Use it. But split by **ownership boundary**, not by whoever happens to be free.

## 2. Safe lanes

| Lane | Work | Modules touched | Depends on | Merge risk |
| --- | --- | --- | --- | --- |
| A | schema + invariants | `db/migrate/`, schema specs | internal A1 order only | high inside lane, low outside lane |
| B | fixture corpus | `spec/fixtures/dicom/` | none | low |
| C | raw storage contract | storage service + storage specs | none | low |
| D | observability vocabulary draft | `docs/observability/` | none | low |

```text
Lane A: A1-a -> ... -> A1-l -> A1-z
Lane B: A2
Lane C: A3
Lane D: vocabulary draft
```

Launch all four lanes immediately.

## 3. Why these lanes are safe

- Lane A owns schema shape. Do not split migrations across multiple worktrees unless you enjoy reconciling FK order at 11pm.
- Lane B is mostly additive files and a manifest.
- Lane C can design against the approved raw-byte semantics without waiting for controllers.
- Lane D produces words, not implementation, so the rest of the system can converge on the same words later.

## 4. Coordination points

| Moment | Required sync |
| --- | --- |
| after `A1-d` | schema owner confirms canonical observation shape for fixture and storage owners |
| after `A1-l` | schema owner confirms series-attempt linkage exists |
| before Batch 1 merge | all lanes verify their artifact names match `011` / `012` / vocabulary draft |

## 5. Merge order

```text
1. Lane A schema migrations
2. Lane B fixtures
3. Lane C raw storage contract
4. Lane D observability vocabulary draft
5. Lane A invariant suite final reconciliation
```

The first four can be developed in parallel. The invariant suite should land last because it is the contract referee for the final merged shape.

## 6. Conflict flags

- Do not let Lane C create application code that assumes final table names before Lane A lands them.
- Do not let Lane B encode fixture expectations that contradict `011` just because they are convenient to test.
- Do not let Lane D invent PHI-bearing structured fields. The vocabulary should make safe logging easier, not more decorative.

## 7. Recommended worktree labels

```text
worktree-a-schema
worktree-b-fixtures
worktree-c-storage
worktree-d-observability-vocabulary
```

The names are boring on purpose. Future you should be able to guess what is inside without opening them.
