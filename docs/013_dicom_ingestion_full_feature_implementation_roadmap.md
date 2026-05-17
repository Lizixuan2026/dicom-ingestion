# DICOM Ingestion — Full-Feature Implementation Roadmap

Documentation map: `001_dicom_ingestion_documentation_map.md`

## 1. Purpose

This document answers one question:

> **How do we build the full DICOM ingestion feature in the right order without shrinking the product or creating avoidable rework?**

It is not an MVP plan. The target remains the complete v1 capability already defined in:

1. `006_dicom_ingestion_architecture.md`
2. `010_dicom_ingestion_implementation_spec.md`
3. `011_dicom_ingestion_schema_and_contracts.md`
4. `012_migration_first_backlog.md`

This document owns **implementation sequencing**:

- which capabilities must land first,
- which work can run in parallel,
- which interfaces must be frozen before downstream work starts,
- what each stage must prove before the next stage begins,
- how to reach the complete feature without letting the architecture collapse into accidental shortcuts.

---

## 2. The implementation principle

The product is full-featured. The construction order should still be incremental.

```text
FULL PRODUCT SCOPE
  raw bytes
  canonical records
  observations
  duplicates
  series conflict review
  refs
  projections
  retry/replay
  APIs
  observability
  rollout safety

        built through

ORDERED IMPLEMENTATION SPINE
  data truth -> ingest truth -> review truth -> query truth -> operational truth
```

The wrong question is:

> what can we leave out for now?

The right question is:

> what must become true first so later pieces have something stable to stand on?

For this module, the answer is simple:

1. **Data truth first**: schema, invariants, raw storage, fixtures.
2. **Ingest truth second**: every upload becomes explainable canonical state.
3. **Review truth third**: duplicates and series conflicts become explicit facts, not side effects.
4. **Query truth fourth**: projections and APIs read from durable, rebuildable state.
5. **Operational truth last but not late**: retry, replay, metrics, runbooks, rollout controls.

---

## 3. Full-feature target at completion

The implementation is complete only when all of these are true:

| Capability | Completion condition |
| --- | --- |
| Raw-byte preservation | every accepted physical upload has durable original bytes before metadata persistence is considered complete |
| Neutral DICOM model | Study / Series / Instance / Observation are persisted with the exact identity semantics in `011` |
| Retry semantics | same-item retry reuses the observation path; a new physical upload creates a new item and observation |
| Duplicate semantics | identity duplicate and content duplicate are stored as separate facts |
| Series-level review | user-facing Series conflict summaries exist, classify deterministically, and resolve through `keep_existing` / `promote_uploaded` |
| References | unresolved and resolved reference edges are preserved without duplicate edges on rebuild |
| Projections | read APIs use rebuildable projections, not raw-tag scans |
| Replay | metadata persistence, projection rebuild, and reindex flows can run from stored bytes |
| Observability | operators can answer where a job is stuck, why it failed, and whether review queues are growing |
| Release safety | migration order, rollout order, threat pack, smoke checks, and rollback steps are documented and rehearsed |

Nothing in the roadmap below removes one of these requirements.

---

## 4. Recommended delivery structure

The implementation should be managed as **six gates**, not as a bag of tickets.

```text
G0 contracts
  -> G1 durable intake
  -> G2 canonical ingest
  -> G3 review semantics
  -> G4 query + replay
  -> G5 production readiness
```

| Gate | What becomes true | Why this gate exists |
| --- | --- | --- |
| G0 Contracts | schema, fixtures, raw-storage semantics, and invariants are frozen | downstream teams stop inventing conflicting data models |
| G1 Durable intake | bytes can enter safely and every candidate becomes a tracked item | no file can become mysterious |
| G2 Canonical ingest | valid DICOM becomes stable logical + physical state | later duplicate, ref, and projection logic has durable truth |
| G3 Review semantics | duplicate facts and Series conflict summaries are real | humans review at the right abstraction level |
| G4 Query + replay | projections, APIs, retry, and reindex are usable | the system becomes operable, not just writable |
| G5 Production readiness | dashboards, security controls, runbooks, rollout, rollback are complete | the feature can survive first contact with production |

This is stricter than the old `Slice 1 / Slice 2 / Slice 3` framing in `008`. The old slices remain useful, but these gates better match the actual dependency graph now that Series-level conflict review is part of v1.

---

## 5. End-to-end build graph

```text
G0 CONTRACTS
  A1-a..A1-l schema
  A1-z invariant suite
  A2 fixtures
  A3 raw storage contract
        │
        ▼
G1 DURABLE INTAKE
  B2 package persistence
  B1 upload API ─┐
  B3 scanner     ├─ parallel after B2
                 ▼
  B4 job/item state engine
  B5 parser + validation
        │
        ▼
G2 CANONICAL INGEST
  B6 canonical persistence
  B7 terminal report
        │
        ▼
G3 REVIEW SEMANTICS
  C1 duplicate findings ─┐
  C2 private tags        ├─ parallel after B6
  C3 reference edges     │
  C4 binding policy      ┘
        │
        ├── C1 + A1-l -> C1b series conflict classifier + summary projection
        ▼
G4 QUERY + REPLAY
  C5 index jobs + projections
  C6 retry/replay
  D1 query APIs
  D3 replay/reindex validation
        │
        ▼
G5 PRODUCTION READINESS
  C7 observability
  D2 security pack
  D4 rollout + runbooks
```

### 5.1 Recommended release path

```text
A1-a -> A1-b -> A1-c -> A1-d -> A1-f -> A1-g -> A1-z
A1-e -> A1-f
A1-e + A1-f -> A1-l
A2 + A3 + A1-z + A1-l
  -> B2
  -> B1 + B3
  -> B4 + B5
  -> B6
  -> B7

parallel post-B6 branches:
  B6 -> C1 + C2 + C3 + C4
  B6 -> C5
  B6 -> C6
  C1 + A1-l -> C1b

release close:
  C1 + C1b + C3 + C5 -> D1
  B1..C6 + C1b -> C7 -> D2
  C5 + C6 -> D3
  D1 + D2 + D3 -> D4
```

`C2`, `C6`, `C7`, and `D2` do not define the **earliest proof** that the ingestion model is real, but they do define whether the full feature is actually releasable. Schedule them aggressively in parallel. Do not let "not on the first proof spine" turn into "safe to do later."

---

## 6. Gate-by-gate implementation plan

## G0 — Contracts first

### Build now

- all migrations `A1-a` through `A1-l`
- invariant suite `A1-z`
- fixture corpus `A2`
- raw storage contract `A3`
- provisional observability vocabulary draft owned by the observability lane

### Must be frozen before leaving G0

1. logical instance vs physical observation split,
2. exact canonical-observation guarantees,
3. retry vs re-upload semantics,
4. Series conflict attempt identity,
5. duplicate-finding uniqueness shapes,
6. reference-edge natural key,
7. raw storage durability and reuse semantics.

### Exit gate

- all schema invariants are executable tests,
- fixtures cover malformed, duplicate, private-tag, referenced-object, and mixed ZIP cases,
- the provisional stage / event vocabulary exists before intake work begins,
- no downstream ticket needs to invent a missing identity rule.

### Why this must come first

If G0 is weak, every later layer compensates with application logic. That is how a six-month-old ingestion system turns into a museum of defensive hacks.

---

## G1 — Durable intake

### Build now

- `B2` package persistence
- `B1` upload API
- `B3` scanner and ZIP safety
- `B4` job/item state engine
- `B5` parser and validation

### Construction order

1. `B2` first, because the upload package and manifest shape the rest of the pipeline.
2. `B1` and `B3` next in parallel after the package contract is stable.
3. `B4` and `B5` next in parallel after the candidate-item contract is stable.

### Exit gate

A mixed ZIP can be uploaded and the system can truthfully answer, for every candidate:

- did we receive it,
- did we preserve its bytes,
- did parsing start,
- was it valid DICOM,
- if not, why not.

No canonical records are required yet to prove G1, but no file may vanish from accounting.

### Required tests in this gate

- nil upload
- empty upload
- oversize upload
- ZIP bomb
- path traversal entry
- nested ZIP depth limit
- malformed DICOM
- non-DICOM sibling survival
- object-store failure
- duplicate submission through request idempotency

---

## G2 — Canonical ingest

### Build now

- `B6` canonical persistence
- `B7` terminal report

### Why these stay together

`B6` without `B7` proves engineers can write rows. It does not prove the product can explain what happened. These two pieces should merge as one product milestone.

### Exit gate

A valid batch produces:

- durable raw bytes,
- logical Study / Series / Instance rows,
- physical Observation rows,
- exactly one current canonical observation per accepted instance after successful persistence,
- a terminal report that accounts for every item.

### Required tests in this gate

- first observation becomes canonical,
- retry of the same item reuses the observation,
- later physical upload creates a second observation,
- DB failure after raw bytes are durable preserves retryability,
- no sibling item is poisoned by one bad item.

### First real end-to-end proof

At the end of G2, one internal fixture dataset should complete this path:

```text
upload -> bytes durable -> parse -> canonical rows -> terminal report
```

If this path is not boringly reliable, do not move energy into richer imaging features yet.

---

## G3 — Review semantics

### Build now

- `C1` duplicate findings
- `C2` private tags
- `C3` reference edges
- `C4` binding policy
- `C1b` Series-level conflict classifier and summary projection

### Construction order

1. `C1`, `C2`, `C3`, and `C4` can start in parallel after `B6`.
2. `C1b` must wait for `C1` and `A1-l`, because it summarizes SOP-level findings by Series attempt.

### Exit gate

The system can now say all of the following without ambiguity:

- this is the same SOP identity,
- this is byte-identical content,
- this is a Series-level exact duplicate,
- this is partial overlap,
- this is a UID conflict,
- this is a content conflict,
- this reference points to something unseen yet,
- this valid ingest failed only at platform binding.

### Required tests in this gate

- identity duplicate vs content duplicate split,
- duplicate finding idempotency for nullable matched columns,
- exact duplicate auto-dedupes but preserves provenance,
- conflict-priority order is deterministic,
- manual `keep_existing` and `promote_uploaded` semantics,
- repeated same action returns 200,
- different post-resolution action returns 409,
- unresolved references persist through rebuild,
- private tags remain observation-scoped and creator-aware,
- failed binding does not invalidate ingest.

### User-facing milestone

This is the first point where operators and users can review the system without spelunking through low-level SOP facts. The abstraction finally matches how humans think.

---

## G4 — Query, retry, and replay

### Build now

- `C5` index jobs and projections
- `C6` retry / replay
- `D1` query APIs
- `D3` replay and reindex validation

### Construction order

1. `C5` can begin after `B6`; its minimum technical dependency is canonical persistence, not the full review layer.
2. `C6` can begin once G2 exists, but it is only complete when projection replay is supported.
3. `D1` waits for the full query facts it exposes: `C1`, `C1b`, `C3`, and `C5`.
4. `D3` waits for both `C5` and `C6`.

### Exit gate

- read APIs use projections,
- projection rebuild does not require re-upload,
- metadata persistence retry runs from stored bytes,
- replay produces consistent canonical and projected outputs,
- query contracts in `011` are satisfied.

### Required tests in this gate

- rebuild idempotency,
- no duplicate reference edges after rebuild,
- retry from stored bytes after DB failure,
- projection version bump behavior,
- API reads do not fall back to raw tag scans,
- unresolved-reference query returns only unresolved rows,
- series-conflict detail links to scoped SOP findings.

---

## G5 — Production readiness

### Build now

- `C7` observability
- `D2` security pack
- `D4` rollout and runbooks

### Construction order

`C7` design starts early, but full implementation waits until the complete stage and event vocabulary exists. `D2` waits on `C7`. `D4` waits on `D1`, `D2`, and `D3`. This gate closes only after the production flow exists end to end.

### Exit gate

- dashboard panels exist for ingest, failures, duplicate pressure, conflict resolution, and indexing,
- PHI-safe structured logs are verified,
- threat cases pass,
- dark launch checklist exists,
- rollback procedure is executable,
- smoke checks are documented for the first 5 minutes and first hour after deploy.

### Required tests in this gate

- ZIP bomb rejection,
- path traversal rejection,
- PHI-safe logging inspection,
- audit event coverage for upload and conflict resolution,
- rollout smoke tests,
- rollback rehearsal,
- alerting on job failure growth and stuck indexes.

---

## 7. What should be parallelized

| Workstream | Modules touched | Depends on | Can run with |
| --- | --- | --- | --- |
| Schema + invariants | migrations/, models/, tests/schema | — | fixtures, raw storage |
| Fixture corpus | test/fixtures/ | — | schema, raw storage |
| Raw storage contract | storage/, services/storage/ | schema concepts | fixtures |
| Upload + scanner | controllers/, services/upload/, services/scanner/ | package persistence | parser work after manifest contract |
| Parser + validation | services/parser/, validators/ | fixture corpus, item state shape | upload work |
| Duplicate/private/ref/binding | services/dicom/, repositories/, models/ | canonical persistence | each other, if contracts frozen |
| Projections + query APIs | jobs/, projections/, controllers/ | canonical + review facts | observability work |
| Retry/replay | jobs/, services/replay/ | canonical persistence, projections for full replay | observability |
| Observability + security | instrumentation/, dashboards/, tests/security/ | stage names and event schema | most other lanes |

### Parallel lanes

```text
Lane A: schema -> canonical persistence -> projections -> query APIs
Lane B: fixtures -> parser/validation -> duplicate/private/ref extraction
Lane C: raw storage -> upload/package/scanner -> retry/replay
Lane D: observability + security pack (starts early, closes late)
Lane E: series conflict classifier (waits for duplicate findings + series attempts)
```

### Merge rule

- Do not let `Lane B` invent parser output fields independently of `Lane A`'s persistence needs.
- Do not let `Lane E` start before SOP-level finding semantics are frozen.
- Merge through gates, not through random ticket completion. Parallel work is useful only if the contracts it depends on are already stable.

---

## 8. Where implementation commonly goes wrong

| Failure pattern | What it looks like | Prevent it by |
| --- | --- | --- |
| Parser-first tunnel vision | the demo works, but retries and provenance are hand-waved | finish G0 before celebrating parser throughput |
| Schema drift under pressure | services patch over missing uniqueness or FK rules | keep invariant tests ahead of service work |
| Confusing upload occurrence with logical identity | “duplicate” means four different things in four files | keep instance / observation / finding / series-summary boundaries explicit |
| Projection leakage | query APIs slowly start reading raw payloads for convenience | force projection-only read tests in G4 |
| Ops-last thinking | dashboards arrive after the first incident | start C7 early and close it in G5 |
| Review UI too early | humans are shown SOP-level noise before Series summaries exist | finish C1b before exposing manual review surfaces |

---

## 9. Test strategy by gate

```text
G0  schema invariants + fixtures
G1  unsafe-input + intake-state tests
G2  canonical transaction + report tests
G3  duplicate/conflict/reference semantics tests
G4  replay/rebuild/API contract tests
G5  threat/ops/rollout tests
```

### 9.1 Tests that must exist before implementation is considered complete

| Area | Test type | Must prove |
| --- | --- | --- |
| Schema invariants | unit / migration | FK, unique, nullable, and idempotency guarantees |
| Intake pipeline | integration | mixed batch accounting and sibling survival |
| Canonical persistence | integration | transactionality and exact canonical behavior |
| Conflict handling | unit + integration | classification priority and `/resolve` semantics |
| Replay | integration | stored bytes are sufficient to recover metadata and projections |
| APIs | request tests | contracts match `011` exactly |
| Security | integration | abusive archives and PHI leakage controls hold |
| Observability | integration / inspection | every major state transition is visible |

### 9.2 Tests worth inline ASCII diagrams in code comments

- canonical-observation state transitions in the persistence service,
- item retry vs re-upload flow in replay logic,
- Series conflict classification priority,
- replay / reindex pipeline,
- multi-stage tests whose setup is otherwise hard to read.

---

## 10. Failure-mode registry for the implementation plan

| Codepath | Realistic failure | Required handling | Must be tested before |
| --- | --- | --- | --- |
| upload intake | request retries after client timeout | request idempotency no-op | G1 exit |
| object storage write | bytes fail before durability | item not accepted, retryable failure surfaced | G1 exit |
| DB persistence after bytes | metadata write fails | retain bytes, mark failed, retry from stored bytes | G2 exit |
| canonical switch | partial Series promotion | single batched transaction, all-or-nothing | G3 exit |
| duplicate finding rebuild | duplicate rows after replay | unique indexes / idempotent writes | G3 exit |
| reference extraction | target SOP unseen | unresolved edge retained | G3 exit |
| projection rebuild | stale version or duplicate side effects | rebuild from canonical state, version aware | G4 exit |
| query path | raw-tag scan creeps into API | projection-only read rule | G4 exit |
| log emission | PHI accidentally printed | governed logging fields only | G5 exit |
| rollout | old and new code overlap during deploy | compatible migrations and dark launch | G5 exit |

No row above is optional. If a gate exits without its row passing, the gate did not actually exit.

---

## 11. Delivery controls

### 11.1 Recommended review cadence

| Moment | Required review |
| --- | --- |
| before G0 starts | confirm `010` / `011` still match implementation intent |
| after G2 | re-read end-to-end ingest invariants before building richer semantics |
| before G4 | API / projection contract review |
| before G5 exit | security, observability, and rollback review |

### 11.2 “Stop and fix” conditions

Pause the roadmap and repair the plan if any of these happen:

1. a new service needs a field absent from `010` or a contract absent from `011`,
2. an item can disappear from accounting,
3. a valid ingest becomes invalid because binding failed,
4. duplicate logic starts changing canonical pointers implicitly,
5. a projection becomes a second source of truth,
6. a manual resolution action cannot be replayed or audited.

---

## 12. NOT in scope for this roadmap

These remain outside the implementation path for the current full v1 feature:

| Not in scope | Why |
| --- | --- |
| viewer implementation | separate product surface |
| PACS networking | different integration boundary |
| generic DAG engine | current typed stages are enough |
| broad vendor dictionary catalog | needs real dataset evidence |
| rich curation UX beyond current conflict actions | facts and first actions first |
| deep SEG / RTSTRUCT / SR enrichment | references are preserved now, richer branches come later |
| pixel-derived analytics | not needed to prove ingest correctness |

---

## 13. Relationship to the other implementation docs

| Document | Use it for |
| --- | --- |
| `007_dicom_ingestion_implementation_plan.md` | product-phase strategy and rollout posture |
| `008_dicom_ingestion_execution_breakdown.md` | epic-level decomposition and older slice framing |
| `012_migration_first_backlog.md` | exact task IDs, dependencies, and acceptance checklists |
| `013_dicom_ingestion_full_feature_implementation_roadmap.md` | the authoritative construction order for the full feature |

Rule of thumb:

- start here to understand **how the build should unfold**,
- go to `012` to see **the exact next task**,
- go to `011` when there is any doubt about **the exact contract**.

---

## 14. Final recommendation

Build the whole feature. Do not build it all at once.

The winning sequence is:

```text
truthful schema
  -> truthful intake
  -> truthful canonical state
  -> truthful human review
  -> truthful query/replay
  -> truthful operations
```

That order protects the product from both classic failures:

1. the demo-first implementation that has to be rebuilt once real data arrives,
2. the cathedral-first implementation that never produces a trustworthy end-to-end path.

This roadmap gives the team a way to ship the full system without lying to itself about what is already real.
