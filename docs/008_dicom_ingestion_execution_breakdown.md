# DICOM Ingestion Module — Execution Breakdown

## 1. Purpose

This document turns the v1 architecture into work that can actually be assigned, built, and verified.

For the current authoritative **full-feature construction order**, read
`013_dicom_ingestion_full_feature_implementation_roadmap.md` first. This document
remains useful for epic-level decomposition and tracker-friendly ticket framing.

It is not another strategy doc. It answers:

1. what should be built,
2. in what order,
3. what each unit of work depends on,
4. what “done” means,
5. what can be parallelized without creating fake progress.

The implementation goal is still the same:

> **ship a trustworthy intake spine first, then deepen the imaging semantics.**

---

## 2. Recommended build graph

```text
FOUNDATION
  A1 schema + enums
  A2 fixture corpus
  A3 storage contract
        │
        ▼
INTAKE SPINE
  B2 package persistence
  B1 upload API
  B3 scanner + ZIP safety
  B4 ingestion jobs/items
  B5 header parser + validation
  B6 canonical study/series/instance persistence
  B7 terminal reporting
        │
        ▼
TRUST LAYER
  C1 duplicate facts
  C1b series conflict classifier
  C2 private-tag persistence
  C3 reference edges
  C4 binding policy
  C5 index jobs + projections
  C6 retries
  C7 observability
        │
        ▼
RELEASE HARDENING
  D1 query APIs
  D2 security/threat tests
  D3 replay/reindex flow
  D4 rollout + runbooks
```

### 2.1 Execution graph

This document is a supporting epic breakdown. The authoritative dependency graph lives in `012`; the authoritative release path lives in `013`.

The current execution graph is:

```text
A1 schema + invariants
A2 fixtures
A3 raw storage contract
  -> B2
  -> B1 + B3
  -> B4 + B5
  -> B6
  -> B7

post-B6 branches:
  B6 -> C1 + C2 + C3 + C4 + C5 + C6
  C1 + A1-l -> C1b

release close:
  C1 + C1b + C3 + C5 -> D1
  B1..C6 + C1b -> C7 -> D2
  C5 + C6 -> D3
  D1 + D2 + D3 -> D4
```

Use this as an epic-level picture, not as a replacement for task-level dependencies in `012`.

### 2.2 Safe parallel work

Once the foundation is stable:

- `C1 duplicate facts`
- `C2 private tags`
- `C3 reference edges`
- `C4 binding policy`

can proceed in parallel after canonical persistence exists.

`C1b series conflict classifier` starts after `C1` and `A1-l`.

`C7 observability` should be designed early, but full implementation closes late because it depends on the final stage/event vocabulary through `C6` and `C1b`.

Do **not** parallelize `B5 parser` and `B6 persistence` before the parsed-header contract is stable. That creates two teams inventing the same data model twice. Oldest bug in software.

---

## 3. Milestones

| Milestone | User-visible outcome | Exit gate |
| --- | --- | --- |
| M0 Foundation ready | nothing visible yet | schema, fixture corpus, storage contract approved |
| M1 Intake spine works | user uploads mixed batch and gets truthful report | every file accounted for, raw bytes preserved |
| M2 Trust layer works | users/operators can inspect duplicates, refs, retries, projections | no silent failure in ingest/index path |
| M3 Limited release ready | limited users can use it safely | dashboards, threat tests, runbooks, rollback plan |

---

## 4. Epic breakdown

# Epic A — Foundation

## A1. Define v1 schema, enums, and invariants

### Goal

Freeze the relational contract before service code begins.

### Scope

- tables:
  - `dicom_ingestion_jobs`
  - `dicom_ingestion_items`
  - `dicom_index_jobs`
  - `dicom_studies`
  - `dicom_series`
  - `dicom_instances`
  - `dicom_instance_observations`
  - `dicom_private_tags`
  - `dicom_reference_edges`
  - `dicom_duplicate_findings`
  - `dicom_core_projections`
- enums:
  - job states
  - item states
  - duplicate types
  - resolution states
  - object class families
- uniqueness / identity rules:
  - canonical UID uniqueness
  - logical-instance vs observation split
  - raw/private-tag ownership is observation-scoped
  - request idempotency key
  - item fingerprint rule
  - duplicate-finding non-duplication rule

### Dependencies

- none

### Definition of done

- migrations drafted,
- unique constraints documented,
- `dicom_instance_observations` table included,
- request and item idempotency rules documented,
- state transition tables written,
- projection rebuild rule documented,
- schema reviewed against `006` and `007`.

### Main risk

Using only `sop_instance_uid` as the physical write identity. Frozen decision: `dicom_instances` is logical identity; `dicom_instance_observations` stores physical occurrences.

---

## A2. Build the golden fixture corpus

### Goal

Create the shared regression set before implementation starts.

### Fixtures

1. valid CT or MR base image,
2. malformed file,
3. DICOM-like file missing `SOPClassUID`,
4. identity duplicate pair,
5. content duplicate pair,
6. file with private tags from at least two creators,
7. one SEG or SR with references,
8. mixed ZIP payload,
9. ZIP bomb / path traversal safety fixtures.

### Dependencies

- none

### Definition of done

- fixture catalog committed,
- each fixture has an expected-result manifest,
- fixtures are usable by parser, scanner, integration, and security tests,
- fixture provenance / PHI status documented.

### Main risk

Waiting until after implementation to assemble fixtures. Then the code shape silently dictates the test corpus instead of the other way around.

---

## A3. Define raw object storage contract

### Goal

Make “canonical bytes” concrete.

### Scope

- storage URI format,
- write semantics,
- checksum semantics,
- provenance metadata,
- staged raw-object lifecycle,
- temp staging lifecycle,
- cleanup guarantees,
- retry expectations,
- whether the initial package and expanded items both persist.

### Dependencies

- none

### Definition of done

- `RawDicomObjectStore` or equivalent interface exists,
- object write is idempotent or has explicit compensation semantics,
- durable raw bytes can survive a DB failure and be retried without re-upload,
- checksum strategy documented,
- object-store failure cases named,
- temp cleanup contract written.

### Main risk

Treating object storage as a detail. It is the canonical truth. If this contract is sloppy, the rest of the module is theatre.

---

# Epic B — Intake spine

## B1. Build upload entrypoint

### Goal

Accept user input and create an ingestion job.

### Scope

- `POST /dicom-ingestions`
- accepted sources:
  - file,
  - multi-file form upload,
  - ZIP,
  - existing package manifest reference
- request validation,
- authz hook,
- initial `IngestionJob` creation.

### Dependencies

- A1-e
- A1-f
- B2

### Definition of done

- valid request returns `job_id`,
- nil / empty / oversize request paths are explicit,
- unauthorized caller is rejected,
- package-persistence failure prevents false job acceptance,
- request is traceable from first log line.

---

## B2. Persist upload package and manifest

### Goal

Preserve the original user submission before derived processing.

### Scope

- raw package storage,
- package manifest,
- provenance metadata,
- package checksum,
- package-level failure handling.

### Dependencies

- A3

### Definition of done

- original upload is durably stored,
- manifest reconstructs source structure,
- retrying package persistence is safe,
- package failure is visible in job state and API.

---

## B3. Implement recursive scanner and ZIP safety

### Goal

Enumerate input items safely without pretending file extension equals DICOM.

### Scope

- recursive folder traversal,
- ZIP expansion,
- max expanded bytes,
- max entry count,
- max nesting depth,
- path traversal prevention,
- candidate enumeration,
- non-DICOM item bookkeeping.

### Dependencies

- A2
- A3
- B2

### Definition of done

- every source entry becomes an `IngestionItem` or explicit package error,
- ZIP bomb and traversal fixtures fail safely,
- one corrupt ZIP entry does not erase sibling visibility,
- scanner output is deterministic for the same package.

---

## B4. Implement ingestion job and item state engine

### Goal

Make workflow status first-class instead of inferred from side effects.

### Scope

- job lifecycle,
- item lifecycle,
- orthogonal item status axes,
- legal transitions,
- retry counters,
- per-stage timestamps,
- terminal outcome rules.

### Dependencies

- A1-e
- A1-f

### Definition of done

- illegal transitions are rejected,
- item terminal states are exhaustive,
- storage / validation / binding / index states are modeled separately,
- batch can contain mixed outcomes,
- retry transitions are tested,
- job summary can be derived without scanning logs.

---

## B5. Implement header-only parse and usable-DICOM validation

### Goal

Extract enough information cheaply and reject unusable candidates loudly.

### Scope

- explicit `header_only` parse path,
- raw tag retention,
- normalized metadata extraction,
- required-tag validation,
- named parse errors,
- initial object-family classification.

### Dependencies

- A2

### Definition of done

- parser stops before pixel payload,
- malformed files fail without killing sibling items,
- missing `SOPClassUID` is rejected,
- raw tag retention is available for replay,
- object family assigned for supported classes.

---

## B6. Persist canonical Study / Series / Instance records

### Goal

Create neutral imaging entities without yet deciding business meaning.

### Scope

- per-item transaction boundary,
- study / series / instance upsert rules,
- provenance links,
- ingestion status fields,
- raw-byte linkage.

### Dependencies

- A1-a through A1-l
- B5

### Definition of done

- accepted DICOM creates canonical records,
- DB failure does not create phantom acceptance,
- repeated ingest is explainable,
- binding has not leaked into parser/persistence code,
- relation counts can be rebuilt.

---

## B7. Build terminal ingestion report

### Goal

Make the product tell the truth.

### Scope

- uploaded count,
- candidate count,
- accepted count,
- quarantined count,
- rejected count,
- per-item failure list,
- duplicate/ref placeholders before trust-layer completion.

### Dependencies

- B4
- B6

### Definition of done

- every item appears exactly once in the report,
- report is stable after job completion,
- mixed-batch scenario is human-readable,
- no item can disappear into “processing” forever.

---

# Epic C — Trust layer

## C1. Add duplicate-fact detection

### Goal

Separate “same identity” from “same content.”

### Scope

- SOP UID duplicate detection,
- whole-file digest duplicate detection,
- placeholder for future pixel digest,
- finding creation,
- no silent overwrite behavior.

### Dependencies

- A1-j
- B6

### Definition of done

- duplicate SOP and duplicate content are distinguishable,
- repeated uploads create findings, not mystery replacements,
- accepted vs quarantined remains separate from imported/stored,
- findings are queryable.

---

## C1b. Add Series-level conflict classifier and summary projection

### Goal

Turn SOP-level duplicate facts into the Series-level review object users can actually act on.

### Scope

- classify `exact_duplicate`, `partial_overlap`, `content_conflict`, `uid_conflict`,
- summarize per `series_ingestion_attempt_id`,
- auto-mark exact duplicates as `auto_deduped`,
- expose open conflicts for later `/resolve` actions.

### Dependencies

- C1
- B6
- A1-l

### Definition of done

- classification priority is deterministic,
- exact duplicates auto-dedupe without losing upload provenance,
- manual-reviewable Series conflicts exist as first-class rows,
- repeated rebuilds do not create duplicate summaries.

---

## C2. Persist creator-aware private tags

### Goal

Keep vendor semantics recoverable without overcommitting to early interpretation.

### Scope

- `private_creator`,
- `tag`,
- `vr`,
- raw value,
- nullable interpreted fields.

### Dependencies

- A1-h
- B5

### Definition of done

- private tags attach to observations, not logical instances,
- fixtures with same numeric private tag under different creators remain distinguishable,
- no parser path flattens private identity into tag-only storage,
- interpretation remains optional and additive.

---

## C3. Persist DICOM reference edges

### Goal

Do not lose the graph future derived objects need.

### Scope

- referenced study / series / SOP extraction,
- frame number capture,
- unresolved edge persistence,
- later resolution hook.

### Dependencies

- A1-i
- B6

### Definition of done

- SEG/SR fixture produces expected edges,
- missing target does not discard the edge,
- unresolved references are queryable,
- future resolver can update without reparsing raw bytes.

---

## C4. Introduce binding-policy interface

### Goal

Attach platform meaning without contaminating DICOM parsing.

### Scope

- `DicomBindingPolicy.bind(...)`,
- binding result model,
- failure handling,
- link creation to `Asset`, `DatasetSample`, `Annotation` as supported.

### Dependencies

- B6

### Definition of done

- parser code has zero knowledge of platform objects,
- binding can succeed, fail, or defer without corrupting ingest truth,
- valid DICOM may remain `accepted` while `binding_status = failed`,
- policy is replaceable for future product rules,
- reports expose binding status.

---

## C5. Add index jobs and fast projections

### Goal

Make accepted data queryable without turning projections into hidden canonical state.

### Scope

- `dicom_index_jobs`,
- projection build path,
- rebuild path,
- extractor / projection version fields,
- rebuild trigger rules,
- study / series / instance query backing,
- lag/error reporting.

### Dependencies

- A1-k
- B6

### Definition of done

- projection can be rebuilt from canonical state,
- stale projections can be detected by version mismatch,
- index failure does not invalidate canonical data,
- query endpoints can avoid raw tag scans,
- reindex produces equivalent query output.

---

## C6. Add retry and replay flows

### Goal

Make failures recoverable without re-uploading when possible.

### Scope

- retry failed package-level work,
- retry failed items,
- retry failed index jobs,
- replay parse / projection logic from stored raw bytes.

### Dependencies

- A3
- B4
- B6

### Definition of done

- user/operator can tell what is retryable,
- retrying does not create duplicate truth,
- replay uses preserved bytes,
- transient vs permanent failures are named separately.

---

## C7. Add observability baseline

### Goal

Make the new system operable on day one.

### Scope

- metrics,
- structured logs,
- traces,
- first dashboard,
- alert thresholds,
- runbook skeleton.

### Dependencies

- B1 through C6
- C1b

### Definition of done

- active jobs visible,
- failure reasons visible,
- duplicate rate visible,
- unresolved references visible,
- projection lag visible,
- an operator can answer “where is this batch stuck?” in under five minutes.

---

# Epic D — Release hardening

## D1. Expose query and operational APIs

### Goal

Give users and operators a clean surface over the projection layer.

### Scope

- `GET /dicom/studies`
- `GET /dicom/series`
- `GET /dicom/instances`
- `GET /dicom/duplicates`
- `GET /dicom/references/unresolved`
- `GET /dicom/series-conflicts`
- `GET /dicom/series-conflicts/{id}`
- `POST /dicom/series-conflicts/{id}/resolve`
- index job endpoints

### Dependencies

- C1
- C1b
- C3
- C5

### Definition of done

- pagination,
- authz,
- zero-result handling,
- projection-backed filters,
- no raw-tag blob scans in hot query paths.

---

## D2. Complete security and governance test pack

### Goal

Prove the module is safe enough to expose to real users.

### Scope

- ZIP bomb,
- path traversal,
- malformed parser input,
- oversize request,
- temp cleanup failure,
- PHI-safe logging/reporting,
- audit events.

### Dependencies

- A2
- B2
- B3
- C7

### Definition of done

- security fixtures pass,
- audit events visible,
- PHI does not leak into ordinary logs,
- retention hooks exist,
- threat cases are in CI.

---

## D3. Validate replay and reindex operations

### Goal

Prove the architecture claim is real, not decorative.

### Scope

- reparse from stored bytes,
- projection rebuild,
- duplicate re-evaluation,
- unresolved-reference re-resolution hook.

### Dependencies

- C5
- C6

### Definition of done

- rebuild succeeds without re-upload,
- before/after query results are equivalent where expected,
- replay is observable,
- failure paths are named and recoverable.

---

## D4. Prepare rollout, rollback, and runbooks

### Goal

Ship without pretending deploys are atomic.

### Scope

- feature flag,
- dark launch,
- limited-user rollout,
- rollback steps,
- first-five-minutes checklist,
- first-hour checklist,
- operational runbooks.

### Dependencies

- D1
- D2
- D3

### Definition of done

- rollback can be executed without schema panic,
- dark launch path tested,
- dashboards exist before widening rollout,
- support/operator handoff is written.

---

## 5. Ticketization

The table below is the version a team can actually paste into a tracker.

| ID | Ticket | Depends on | Can parallelize with | Acceptance |
| --- | --- | --- | --- | --- |
| A1 | Freeze schema + invariants | — | A2 | migrations + uniqueness/state rules approved |
| A2 | Build fixture corpus | — | A1 | fixture catalog + expected manifest |
| A3 | Raw storage contract | — | A1, A2 | idempotent write + cleanup semantics |
| B1 | Upload API | A1-e, A1-f, B2 | B3 after B2 interface stable | valid/nil/empty/oversize paths |
| B2 | Package persistence | A3 | B1, B3 once manifest stable | durable package + provenance |
| B3 | Scanner + ZIP safety | A2, A3, B2 | — | deterministic manifest + safety fixtures |
| B4 | Job/item state engine | A1-e, A1-f | B5 after candidate-item contract stable | legal transitions + exhaustive terminal states |
| B5 | Header parser + validation | A2 | B4 after candidate-item contract stable | header-only + named invalid cases |
| B6 | Canonical persistence | A1-a through A1-l, B5 | — | transactional study/series/instance writes |
| B7 | Terminal report | B4, B6 | C7 partly | every item accounted for |
| C1 | Duplicate facts | A1-j, B6 | C2, C3, C4 | identity/content split visible |
| C2 | Private tags | A1-h, B5 | C1, C3, C7 | creator-aware persistence |
| C3 | Reference edges | A1-i, B6 | C1, C2, C7 | unresolved refs retained |
| C4 | Binding policy | B6 | C1, C2, C3 | platform mapping isolated |
| C1b | Series conflict classifier | C1, B6, A1-l | C2, C3, C4 | Series-level review summary |
| C5 | Index jobs + projections | A1-k, B6 | C6 | rebuildable projection |
| C6 | Retry/replay flows | A3, B4, B6 | C7 | explicit recoverability |
| C7 | Observability baseline | B1 through C6, C1b | — | dashboard + metrics + traces |
| D1 | Query/ops APIs | C1, C1b, C3, C5 | D2 | projection-backed access |
| D2 | Security/governance pack | A2, B2, B3, C7 | D1 | threat tests + audit checks |
| D3 | Replay/reindex validation | C5, C6 | D4 | rebuild without re-upload |
| D4 | Rollout/runbooks | D1, D2, D3 | — | dark launch + rollback docs |

---

## 6. Suggested delivery slices

### Slice 1 — “Can we trust one upload?”

Ship:

- A1
- A2
- A3
- B1
- B2
- B3
- B4
- B5
- B6
- B7

Proof:

- mixed ZIP in,
- truthful report out,
- every accepted DICOM has raw bytes and canonical records.

### Slice 2 — “Can we trust it at scale?”

Ship:

- C1
- C1b
- C2
- C3
- C4
- C5
- C6
- C7

Proof:

- duplicates visible,
- unresolved refs visible,
- projections rebuild,
- failures retry cleanly,
- operators can see the system.

### Slice 3 — “Can users and operators live with it?”

Ship:

- D1
- D2
- D3
- D4

Proof:

- platform objects bind cleanly,
- users can query,
- governance controls hold,
- rollout is reversible.

---

## 7. Definition of done by release

### Internal alpha

- Slice 1 complete,
- fixture suite green,
- no silent item disappearance,
- raw bytes preserved,
- one internal mixed batch manually verified.

### Limited beta

- Slice 2 complete,
- duplicate / unresolved-ref visibility,
- reindex path proven,
- dashboard live,
- on-call runbook draft exists.

### General availability

- Slice 3 complete,
- security threat pack green,
- PHI-safe logging checked,
- dark launch and rollback rehearsed,
- acceptance criteria from `007` fully satisfied.

---

## 8. Work that should not start yet

| Not yet | Why |
| --- | --- |
| SEG/RTSTRUCT/SR deep enrichment | reference preservation first |
| vendor dictionary catalog | need actual user/dataset evidence |
| generic DAG engine | typed staged runner is enough for current problem |
| pixel analytics | not needed to prove intake trustworthiness |
| rich duplicate curation UI | facts first, workflow after usage is real |
| viewer work | separate product surface |

---

## 9. Decisions now frozen before coding

| Decision | Frozen rule |
| --- | --- |
| Duplicate SOP persistence | logical instance + physical observation model |
| Raw/private-tag ownership | observation-scoped |
| Request idempotency | caller-supplied `request_idempotency_key` |
| Item idempotency | `(ingestion_job_id, source_path, byte_size, whole_file_sha256)` |
| Raw bytes vs DB failure | retain raw bytes, mark metadata persistence failed, retry from stored object |
| Binding failure | ingest may remain accepted while binding separately fails |
| Projection rebuild | manual rebuild plus version-triggered rebuild |
| Study completeness | `unknown` by default; `complete` only with trusted manifest / explicit contract |

The remaining open items are product/workload questions, not implementation blockers.

---

## 10. Traceability to prior docs

| Prior doc | What this breakdown operationalizes |
| --- | --- |
| `006_dicom_ingestion_architecture.md` | domain model, boundaries, staged pipeline |
| `007_dicom_ingestion_implementation_plan.md` | phases, schema, APIs, observability, security |
| `004` / `005` research docs | evidence behind split jobs, projections, refs, duplicates, private tags |

---

## 11. Final call

If the team only remembers one thing, remember this:

> **Do not start with the most interesting imaging feature. Start with the invariant that no uploaded file can become mysterious.**

That is what users will actually trust.
