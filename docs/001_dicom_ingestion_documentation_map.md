# DICOM Ingestion Documentation Map

## 1. Purpose

This file is the map for the DICOM ingestion document set.

The module now spans research, architecture, implementation contracts, schema rules, and execution planning. Those concerns should not drift back into one giant document. This map defines:

1. what each document owns,
2. which document is authoritative for each kind of decision,
3. which files must be updated when a design changes,
4. how to add a new document without making the set harder to maintain.

If you are unsure where a new sentence belongs, start here before editing.

---

## 2. Reading order

### 2.1 If you are new to the module

1. `dicom_ingestion_research_report.md`
2. `006_dicom_ingestion_architecture.md`
3. `007_dicom_ingestion_implementation_plan.md`
4. `010_dicom_ingestion_implementation_spec.md`
5. `011_dicom_ingestion_schema_and_contracts.md`
6. `012_migration_first_backlog.md`
7. `013_dicom_ingestion_full_feature_implementation_roadmap.md`
8. `014_dicom_ingestion_execution_start_checklist.md`
9. `015_dicom_ingestion_implementation_readiness_review.md`
10. `dicom_ingestion_execution/README.md`

### 2.2 If you are about to implement

1. `010_dicom_ingestion_implementation_spec.md`
2. `011_dicom_ingestion_schema_and_contracts.md`
3. `012_migration_first_backlog.md`
4. `013_dicom_ingestion_full_feature_implementation_roadmap.md`
5. `014_dicom_ingestion_execution_start_checklist.md`
6. `015_dicom_ingestion_implementation_readiness_review.md`
7. `dicom_ingestion_execution/README.md`

### 2.3 If you are reviewing why the design exists

1. `dicom_ingestion_research_report.md`
2. `004_dicom_ingestion_deep_dive.md`
3. `005_dicom_ingestion_source_deep_dive_round2.md`
4. `006_dicom_ingestion_architecture.md`

---

## 3. Document roles

| Document | Owns | Must not become |
| --- | --- | --- |
| `dicom_ingestion_research_report.md` | Consolidated research conclusions and source-backed recommendations | A task list or implementation spec |
| `002_dicom_ingestion_source_research_matrix.md` | Compact source-evidence matrix | Narrative design doc |
| `003_dicom_ingestion_borrowing_notes.md` | Short borrowing notes from external projects | Canonical architecture |
| `004_dicom_ingestion_deep_dive.md` | Source-level follow-up evidence | Current implementation contract |
| `005_dicom_ingestion_source_deep_dive_round2.md` | Additional source-level evidence | Current implementation contract |
| `006_dicom_ingestion_architecture.md` | Product framing, system boundaries, core domain model, major flows, long-term shape | Migration checklist |
| `007_dicom_ingestion_implementation_plan.md` | Delivery plan, phased build strategy, rollout posture | Line-by-line schema contract |
| `008_dicom_ingestion_execution_breakdown.md` | Epic-level execution graph and ticket decomposition | The final authoritative backlog once `012` exists |
| `009_dicom_ingestion_eng_review.md` | Review findings and rationale for decisions that were later incorporated | A live spec |
| `010_dicom_ingestion_implementation_spec.md` | Build spec: what v1 must implement, module boundaries, required services, required tests | Historical rationale or migration-by-migration detail |
| `011_dicom_ingestion_schema_and_contracts.md` | Exact contracts: uniqueness, referential rules, API payloads, idempotency, classification, apply semantics | Broad architecture narrative |
| `012_migration_first_backlog.md` | Execution backlog: smallest shippable tasks, dependencies, acceptance criteria, critical path | The place where new product/domain design is first invented |
| `013_dicom_ingestion_full_feature_implementation_roadmap.md` | Authoritative full-feature construction order: gates, sequencing, parallel lanes, exit criteria | Another backlog or a reduced-scope MVP plan |
| `014_dicom_ingestion_execution_start_checklist.md` | Day-to-day execution checklist: batches, launch order, merge gates, worktree plan | A source of product truth or a replacement for `012` |
| `015_dicom_ingestion_implementation_readiness_review.md` | Final pre-build cross-check: contract references, gate coverage, execution-readiness gaps | A live spec or a place to invent new product behavior |
| `dicom_ingestion_execution/` | Supporting execution pack: active batch plans, worktree lanes, done criteria, and handoff checklists | A competing source of product truth |
| `drafts/001_dicom_ingestion_research_task.md` | Original research brief | A live source of truth |

---

## 4. Source of truth by topic

| Topic | Primary source of truth | Secondary references |
| --- | --- | --- |
| Product framing and v1 scope | `006` | `007`, `010` |
| Core domain model | `006` | `010`, `011` |
| Module boundaries and required services | `010` | `006` |
| Exact schema shape and uniqueness | `011` | `012` |
| Canonical observation policy | `011` | `006`, `010`, `012` |
| Idempotency semantics | `011` | `010`, `012` |
| Series-level conflict model | `011` | `006`, `010`, `012` |
| Public API contract | `011` | `010`, `012` |
| Delivery phases | `007` | `008`, `013` |
| Full-feature implementation sequencing | `013` | `007`, `008`, `012` |
| Day-to-day execution order | `014` | `013`, `012` |
| Minimum technical dependencies and acceptance criteria | `012` | `008` |
| Recommended release path | `013` | `014` |
| Historical rationale from review | `009` | `006`, `010`, `011` after incorporation |
| Pre-build readiness review | `015` | `012`, `013`, `014` after incorporation |
| Active execution control docs | `dicom_ingestion_execution/` | `012`, `013`, `014` |
| Research evidence | `dicom_ingestion_research_report.md` | `002` to `005` |

Rule of thumb:

- `006` answers **why this shape exists**.
- `010` answers **what to build**.
- `011` answers **exactly how the contracts behave**.
- `012` answers **who builds what next and what counts as done**.

---

## 5. Change routing

When one of these changes, update the listed documents in the same pass.

| Change type | Must update | Usually update too |
| --- | --- | --- |
| New domain object or relationship | `006`, `010`, `011` | `012` if implementation work changes |
| New user-facing behavior | `006`, `010`, `011` | `007`, `012` |
| New API endpoint or changed response semantics | `011` | `010`, `012` |
| New DB table, index, FK, or uniqueness rule | `011`, `012` | `010` if the data model changed materially |
| New retry / idempotency rule | `011` | `010`, `012` |
| New observability requirement | `010`, `012` | `007` if rollout posture changes |
| New execution task only, no design change | `012` | `008` if milestone graph changes |
| Design decision superseding an earlier review concern | relevant live docs (`006` / `010` / `011`) | `009` only if recording resolution status helps future readers |

Examples:

- Adding `dicom_series_ingestion_attempts` requires updates to `006`, `010`, `011`, and `012`.
- Changing `/dicom/series-conflicts/{id}/apply` idempotency requires updates to `011`, `010`, and `012`.
- Splitting one backlog ticket into two without changing behavior usually touches only `012`.

---

## 6. Rules for adding a new document

Do **not** add a new document just because a section is getting long. Add one only when all three are true:

1. the topic is durable enough to need its own lifecycle,
2. it has a clear owner not already covered by `006`, `010`, or `011`,
3. moving it out reduces duplication rather than creating another source of truth.

If a new document is added:

1. add it to the table in section 3,
2. add it to the source-of-truth table in section 4 if it owns any topic,
3. add it to the reading order if a reader should encounter it before implementation,
4. add cross-references from the documents it supersedes or complements,
5. state explicitly whether it is:
   - **authoritative**
   - **supporting**
   - **historical**
   - **draft**

Prefer updating an existing authoritative document over creating a parallel one.

---

## 7. Current boundary decisions

The current split is intentional:

- `006`, `010`, and `011` carry the stable design.
- `012` carries execution-task detail.
- `013` carries the authoritative full-feature construction order.
- `014` carries the day-to-day start checklist for actually opening workstreams.
- `015` records the final pre-build readiness review and the fixes incorporated from it.
- `dicom_ingestion_execution/` contains the supporting execution pack teams actually open while building.
- `008` remains useful for epic-level planning, but `012` is the active detailed backlog.

`Series-level conflict resolution` currently stays inside the existing hierarchy:

- architecture in `006`,
- implementation shape in `010`,
- exact classification and apply contract in `011`,
- concrete work items in `012`.

Create a separate Series-conflict design document only if that feature grows beyond these homes, for example:

- multiple user actions with distinct semantics,
- UI workflow design,
- policy variants by tenant or dataset,
- curation history and rollback rules,
- enough detail that `011` would become mostly about Series conflicts.

Until then, one extra document would create more coordination cost than clarity.

---

## 8. Maintenance checklist

Before considering a document change complete, verify:

- [ ] the source-of-truth document for the changed topic was updated,
- [ ] downstream documents were updated or intentionally left unchanged,
- [ ] no backlog task invents a contract that is absent from `010` / `011`,
- [ ] no implementation spec contradicts architecture in `006`,
- [ ] any newly added document is registered in this file,
- [ ] reading-order instructions in touched documents still point to the right next file.

This is the cheap work that prevents expensive confusion later.
