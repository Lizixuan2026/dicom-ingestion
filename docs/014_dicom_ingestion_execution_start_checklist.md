# DICOM Ingestion — Execution Start Checklist

Documentation map: `001_dicom_ingestion_documentation_map.md`

## 1. Purpose

This document is the operating checklist for actually starting the full-feature implementation.

Use `013_dicom_ingestion_full_feature_implementation_roadmap.md` to understand the construction order.
Use `012_migration_first_backlog.md` for exact task definitions.
Use `dicom_ingestion_execution/README.md` for the active execution pack teams should open while building.
Use this document when the team asks:

> **What do we open first, what can run in parallel, what must not start yet, and what has to be true before we merge forward?**

This is not a new source of product truth. It is the day-to-day execution companion for the already-approved full feature.

---

## 2. Before anyone starts coding

Complete these checks first:

| Check | Why |
| --- | --- |
| `010` and `011` agree on current contracts | implementation should not invent product semantics |
| `013` reviewed after latest contract edits | route map must match current truth |
| `012` dependency graph matches `013` | backlog and roadmap must not disagree |
| fixture corpus ownership assigned | every later stage depends on stable test inputs |
| schema owner assigned | one person must own invariant consistency across migrations |
| observability owner assigned | someone must draft the initial stage / event vocabulary before Batch 2 starts |
| review cadence agreed | the team should know when to stop and re-check the plan |

If any of these are false, fix the docs before opening workstreams. Starting with contradictory plans is not velocity. It is interest-bearing debt.

---

## 3. Batch 1 — Open immediately

### Goal

Establish the foundations that every other stream depends on.

### Open these tickets first

| Ticket | Why now | Can parallelize with |
| --- | --- | --- |
| `A1-a` through `A1-l` | all structural truth starts here | `A2`, `A3` |
| `A1-z` | prevents schema drift from becoming service-layer complexity | after migrations exist |
| `A2` fixture corpus | parser, retry, conflict, and security work all need it | `A1-*`, `A3` |
| `A3` raw storage contract | upload, retry, and replay depend on durable-byte semantics | `A1-*`, `A2` |
| Observability vocabulary draft | prevents every later lane from inventing incompatible stage/event names | `A1-*`, `A2`, `A3` |

### Merge rule for Batch 1

Do not start `B2` until all of these are true:

- schema invariants pass,
- `dicom_series_ingestion_attempts` exists,
- raw storage behavior is written down and tested,
- fixtures include duplicate, malformed, private-tag, referenced-object, and mixed-ZIP cases,
- the observability owner has published the provisional stage / event vocabulary for later C7 completion.

### What not to start yet

- no upload controller work before package/storage contracts are stable,
- no duplicate logic before observation semantics are fixed,
- no projection work before canonical data shape is real.

---

## 4. Batch 2 — Start the intake lanes

### Goal

Make every incoming file visible and durable.

### Launch order

```text
B2
  -> B1 + B3
  -> B4 + B5
```

### Parallel lanes

| Lane | Work | Why it is safe |
| --- | --- | --- |
| Lane A | `B2 -> B1` | package persistence defines the API contract |
| Lane B | `B2 -> B3` | scanner can proceed once manifest shape is fixed |
| Lane C | `B4 + B5` after candidate-item contract is fixed | state and parser can progress together if they share the same item contract |

### Merge gate before moving on

A mixed ZIP fixture must prove:

- every candidate item is represented,
- raw bytes are preserved,
- invalid and non-DICOM files are reported,
- sibling items survive one bad file,
- unsafe archives fail loudly.

### Do not advance if

- any item can disappear from the terminal report,
- a parser failure skips item accounting,
- storage failure can still produce apparent acceptance.

---

## 5. Batch 3 — Land the first real end-to-end path

### Goal

Turn durable intake into durable canonical DICOM truth.

### Open these tickets

| Ticket | Why now |
| --- | --- |
| `B6` canonical persistence | turns parsed headers into durable logical + physical state |
| `B7` terminal report | product proof is incomplete without user-visible truth |

### Merge gate

The following path must work end to end:

```text
upload -> bytes durable -> parse -> Study/Series/Instance/Observation -> terminal report
```

### Required proof

- first accepted observation becomes canonical,
- same-item retry does not duplicate observations,
- later re-upload creates a new physical occurrence,
- DB failure after durable bytes is recoverable from stored bytes,
- binding failure does not invalidate ingest.

### Team checkpoint

Stop here and re-read:

- canonical-observation policy,
- retry semantics,
- exact item terminal states.

This is the first place where a small misunderstanding becomes an expensive rewrite later.

---

## 6. Batch 4 — Open the trust-layer lanes

### Goal

Add the facts humans and downstream systems need in order to trust the ingest result.

### Parallelizable work

| Lane | Tickets | Notes |
| --- | --- | --- |
| Lane A | `C1` duplicate findings | prerequisite for `C1b` |
| Lane B | `C2` private tags | independent after `B6` |
| Lane C | `C3` reference edges | independent after `B6` |
| Lane D | `C4` binding policy | independent after `B6` |

### Then start

| Ticket | Waits for | Why |
| --- | --- | --- |
| `C1b` series conflict classifier | `C1`, `A1-l` | Series summaries are derived from SOP findings grouped by attempt |

### Merge gate

The system must now explain:

- identity duplicate,
- content duplicate,
- exact duplicate Series,
- partial overlap,
- UID conflict,
- content conflict,
- unresolved reference,
- binding failure that does not poison ingest.

### Do not advance if

- duplicate facts can mutate canonical pointers implicitly,
- `C1b` needs a field absent from `011`,
- Series classification priority is still implied rather than executable.

---

## 7. Batch 5 — Make the system queryable and recoverable

### Goal

Turn the ingestion store into something users and operators can use repeatedly.

### Start earlier, close here

`C6` retry/replay may start as soon as `B6` exists. Batch 5 is where it is proven complete against projection rebuild and replay behavior.

### Recommended order

```text
B6
  -> C6 retry/replay foundation

C5 projections
  -> D1 query APIs

C5 projections + C6 retry/replay
  -> D3 replay/reindex validation
```

### Notes

- `C6` starts earlier than this batch, but do not mark it complete until replay and projection interactions are proven.
- `D1` must read from projections. If a shortcut starts scanning raw tags, stop the line.
- `D3` is where the architecture proves it really kept raw bytes for a reason.

### Merge gate

- projection rebuild is deterministic,
- stale projections are detectable,
- retry from stored bytes works,
- query APIs satisfy `011`,
- reindex does not require re-upload.

---

## 8. Batch 6 — Close production readiness

### Goal

Make the feature safe to expose beyond the builders.

### Required work

| Ticket | Depends on | Why it closes late |
| --- | --- | --- |
| `C7` observability | `B1` through `C6`, `C1b` | final metric and trace vocabulary needs the full flow |
| `D2` security pack | `A2`, `B2`, `B3`, `C7` | threat tests need the implemented path and safe logging |
| `D4` rollout/runbooks | `D1`, `D2`, `D3` | rollout only means something once behavior, security, and recovery are real |

### Merge gate

- dashboards exist,
- PHI-safe logging is verified,
- threat pack passes,
- replay/runbook steps are executable,
- rollback has been rehearsed,
- first-hour smoke checks are written.

### No release if

- operators still need database spelunking to answer where a job is stuck,
- rollback requires deleting accepted DICOM records,
- security pack is “planned” rather than passing.

---

## 9. Practical execution board

| Batch | Tickets | Can start when | Stop when |
| --- | --- | --- | --- |
| 1 | `A1-a..A1-l`, `A1-z`, `A2`, `A3` | now | contracts + fixtures green |
| 2 | `B2`, then `B1/B3`, then `B4/B5` | Batch 1 green | durable intake proven |
| 3 | `B6`, `B7` | Batch 2 green | first end-to-end ingest proven |
| 4 | `C1/C2/C3/C4`, then `C1b` | Batch 3 green | review semantics proven |
| 5 | `C5`, `C6`, `D1`, `D3` | `C5`/`C6` may start after `B6`; batch closes once Batch 4 facts are available for `D1` | query + replay proven |
| 6 | `C7`, `D2`, `D4` | implementation vocabulary stable | production readiness proven |

---

## 10. Merge-review checklist

Before merging any batch forward, answer these:

1. Did this batch preserve every invariant from `011`?
2. Did any implementation shortcut create a second source of truth?
3. Did any new state transition become possible without an explicit test?
4. Did every failure mode become visible to the user, operator, or both?
5. Did the next batch inherit a stable contract, or are we handing it ambiguity?

If the honest answer to #5 is “ambiguity,” do not merge forward yet.

---

## 11. Worktree strategy

### Safe parallel worktrees

```text
Worktree A: schema + invariant suite
Worktree B: fixture corpus
Worktree C: raw storage contract
```

After Batch 1 merges:

```text
Worktree A: upload/package path
Worktree B: scanner safety
Worktree C: parser/validation
```

After Batch 3 merges:

```text
Worktree A: duplicate facts
Worktree B: private tags
Worktree C: reference edges
Worktree D: binding policy
```

### Work that should stay sequential

- canonical persistence after parser contract finalization,
- Series conflict classifier after duplicate semantics finalization,
- public query APIs after projection shape finalization,
- rollout/runbooks after security and replay truth exist.

### Conflict flags

- any two worktrees touching `models/` plus schema in the same window need coordination,
- projection work and API work will both lean on read-model assumptions,
- replay and canonical persistence share correctness rules and should review each other before merge.

---

## 12. First implementation week, without shrinking scope

This is not a smaller product. It is the first week of the full product.

### Expected focus

| Day range | Focus |
| --- | --- |
| Days 1-2 | Batch 1 contracts, fixtures, raw storage |
| Days 3-4 | package persistence, upload path, scanner safety |
| Day 5 | job/item state + parser contract integration |

### What success looks like at week end

- the team has not “almost built ingestion,”
- the team has built the part every later layer depends on,
- no one is guessing what an item, observation, retry, or Series attempt means.

That is a better first week than a prettier demo built on moving sand.

---

## 13. Final rule

When choosing between:

- starting one more downstream ticket early,
- or making the current gate boringly complete,

choose boringly complete.

This module is infrastructure. Its job is not to look productive halfway through. Its job is to make future product work cheap and safe.
