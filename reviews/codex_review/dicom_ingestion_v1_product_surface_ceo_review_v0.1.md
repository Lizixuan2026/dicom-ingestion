# DICOM Ingestion V1 Product Surface — CEO Review v0.1

Date: 2026-05-18
Reviewer: Codex via `/plan-ceo-review`
Branch: `main`
Commit reviewed: `cf2329f`
Mode recommendation: **SELECTIVE EXPANSION**
Status: **DONE_WITH_CONCERNS**

## Executive verdict

The first version is real. It runs, the tests are green, and the backend ingestion engine has a serious spine.

But it is not yet the full V1 product surface described in the planning docs.

The right framing is:

```text
Current state:
  backend ingestion engine v1
  schema + services + tests + replay/projection/ops primitives

Still missing:
  product/API v1
  user entry points + query entry points + conflict resolution + operator handoff
```

This is a good place to be. The hard inner loop exists. Now the work is turning the engine into something a user, another service, and an operator can actually use without reading the code.

## What already exists

| Area | Current evidence | CEO read |
| --- | --- | --- |
| Core schema + migrations | Alembic head is single: `a1b2c3d4e5f6`; tests pass | Solid enough to continue. The multi-head/schema mismatch issues have been cleaned up. |
| Upload package persistence | `backend/src/dicom_ingestion/services/upload/upload_service.py` | Core raw-byte preservation path exists as service code. |
| Scanner + ZIP safety | `backend/src/dicom_ingestion/services/scanner/scan_service.py`, `zip_safety.py` | Candidate discovery and safety model exist. |
| Parser + canonical persistence | `backend/src/dicom_ingestion/services/parser/dicom_parser.py`, `canonical_persistence.py` | The neutral DICOM model is no longer just a doc. Good. |
| Duplicate/private tag/reference/binding services | `services/detection`, `services/persistence`, `services/classifier`, `services/binding` | Review semantics exist at service level. |
| Series conflict service | `backend/src/dicom_ingestion/services/conflict/series_conflict.py` | Classifier/resolution machinery exists, but product/API closure is not done. |
| Projection/query/replay/reindex | `services/projection`, `services/queries`, `services/replay`, `services/reindex` | Query and recovery primitives exist. They need public contracts. |
| Batch 6 primitives | `observability`, `security`, `ops`, `backend/dashboards`, `backend/docs` | Useful primitives exist. Runbook coverage is not yet the exact operator handoff promised by the roadmap. |
| Test health | `429 passed, 13 skipped, 1 warning` on Python 3.11.15 | Good implementation signal. One warning remains from `TestStatus` naming. |

## Source-of-truth comparison

The architecture doc defines V1 as more than a parser. The must-have list in `/Users/haohuayin/Documents/dicom_injection/docs/006_dicom_ingestion_architecture.md:27-48` includes:

- accepting single files, multi-file batches, folders, and ZIP uploads,
- durable raw-byte preservation,
- canonical Study / Series / Instance records,
- explicit ingestion and indexing jobs,
- duplicate and content duplicate classification,
- Series-level conflict summaries users can review and resolve,
- clean handoff into platform objects such as `Asset`, `DatasetSample`, and `Annotation`.

The current implementation is strongest through the backend service layer. The parts still thin are the product boundaries: HTTP/API contracts, resolution workflow, platform binding, and operator playbooks.

## Product completeness gaps

### 1. API layer is not closed

**Severity:** P1

The backlog explicitly requires these endpoints in `/Users/haohuayin/Documents/dicom_injection/docs/012_migration_first_backlog.md:1225-1236`:

```text
GET  /dicom/studies
GET  /dicom/studies/{studyId}
GET  /dicom/series
GET  /dicom/series/{seriesId}
GET  /dicom/instances
GET  /dicom/instances/{instanceId}
GET  /dicom/duplicates
GET  /dicom/references/unresolved
GET  /dicom/series-conflicts
GET  /dicom/series-conflicts/{id}
POST /dicom/series-conflicts/{id}/resolve
```

Current repo scan did not show an API/controller layer for these routes. The review/query services exist, but users and downstream services do not yet have stable entry points.

**Why it matters:** without this, the system is a library. Useful, but not yet a product surface.

**Recommendation:** create a Batch 7 focused on product surface closure, starting with API routes that wrap existing service objects rather than inventing new business logic.

### 2. Series conflict resolution is not product-complete

**Severity:** P1

The architecture requires Series-level conflict summaries users can review and resolve without inspecting individual DICOM files, see `/Users/haohuayin/Documents/dicom_injection/docs/006_dicom_ingestion_architecture.md:47`.

The backlog requires `keep_existing` and `promote_uploaded` behavior, idempotent repeat actions, and 409 on conflicting actions, see `/Users/haohuayin/Documents/dicom_injection/docs/012_migration_first_backlog.md:1267-1274`.

`backend/src/dicom_ingestion/services/conflict/series_conflict.py` has the service spine. What is still missing is the full user-visible contract:

- list conflicts,
- inspect one conflict,
- resolve one conflict,
- return clear statuses,
- audit the decision,
- prove idempotency and conflict behavior with API/integration tests.

**Why it matters:** duplicate/conflict semantics are the trust center of this product. If users cannot act on conflicts, we only detect problems. We do not resolve them.

**Recommendation:** implement the conflict API and tests as a first-class closure item, not as an afterthought.

### 3. Platform object binding is still not a real handoff

**Severity:** P1/P2 depending on current product milestone

The V1 scope says ingestion must expose a clean handoff into platform objects such as `Asset`, `DatasetSample`, and `Annotation`, see `/Users/haohuayin/Documents/dicom_injection/docs/006_dicom_ingestion_architecture.md:48`.

Current binding code appears to be a policy/service layer, not a real integration with host platform domain objects.

**Why it matters:** ingestion is not valuable because bytes moved from A to B. It is valuable because downstream platform features can find and use imaging objects safely.

**Recommendation:** define the adapter contract now, even if the first implementation is intentionally thin. Minimum viable closure:

```text
Canonical DICOM instance/series
  -> Binding adapter
  -> platform object reference envelope
  -> queryable link in review/API response
```

### 4. Operator runbooks do not yet match the original operational promises

**Severity:** P2

Batch 6 produced useful artifacts:

- `/Users/haohuayin/Documents/dicom_injection/backend/dashboards/ingestion_dashboard.json`
- `/Users/haohuayin/Documents/dicom_injection/backend/docs/runbooks/deployment.md`
- `/Users/haohuayin/Documents/dicom_injection/backend/docs/runbooks/incident_response.md`
- `/Users/haohuayin/Documents/dicom_injection/backend/docs/security/compliance.md`

But the backlog specifically asks for:

- `docs/runbooks/dicom_ingestion_stuck_batch.md`,
- `docs/runbooks/dicom_ingestion_replay.md`,
- `docs/runbooks/dicom_projection_rebuild.md`,

with acceptance criteria at `/Users/haohuayin/Documents/dicom_injection/docs/012_migration_first_backlog.md:1339-1356`.

**Why it matters:** generic deployment and incident docs are good. But when ingestion fails at 2am, the operator needs the exact query, exact command, and exact expected output for stuck batch, replay, and projection rebuild.

**Recommendation:** add the three targeted runbooks and wire their commands to actual CLI/API paths.

### 5. DICOMweb/PACS-style scope must stay out unless OHIF requires a narrow bridge

**Severity:** Scope guardrail, not a product gap

This project is a **data management platform**, not a PACS, not a hospital integration product, and not a general DICOMweb server. Do not let those scopes raise their head in planning.

The only valid reason to touch DICOMweb-like behavior is a concrete OHIF integration need, and even then the target is the **minimum bridge OHIF needs**, not standards completeness.

Allowed future scope:

- expose or export selected managed DICOM data so OHIF can view/annotate it,
- preserve Study / Series / Instance identity so OHIF can open the right data,
- provide the smallest metadata/retrieve path needed by the chosen OHIF deployment mode,
- support annotation return-linking back into the data management platform.

Explicitly out of scope:

- PACS compatibility,
- external hospital system integration,
- general-purpose DICOMweb conformance,
- implementing STOW-RS/QIDO-RS/WADO-RS as product goals,
- accepting scope because “the standard says so.”

**Why it matters:** if this scope is described as “not high priority,” it will keep coming back. The correct product decision is stronger: it is **not a product goal**. Only OHIF-driven minimal bridge work can enter scope.

**Recommendation:** rewrite future planning language to say `NOT IN SCOPE: PACS/external-hospital/general-DICOMweb compatibility. Exception: minimal OHIF bridge only when OHIF integration starts.`

## Dream state delta

```text
CURRENT STATE
  Services and schema are real.
  Tests are green.
  Ingestion engine can preserve, parse, persist, project, replay, and observe.

THIS NEXT PLAN
  Add product/API surface closure.
  Make users and operators able to drive the system without direct service calls.

12-MONTH IDEAL
  Imaging intake layer for the platform.
  Byte-preserving, queryable, replayable, conflict-aware.
  Platform object binding is stable.
  Derived objects like SEG / RTSTRUCT / SR can ride on the same model.
  OHIF bridge can be added later only for viewing/annotation handoff.
```

## Recommended next batch

Create **Batch 7: Product Surface Closure**.

This should not be a random grab bag. Four workstreams only:

### Batch 7A — API closure

Implement stable route layer over existing services:

```text
Upload/API entry
  -> existing UploadService / ScanService / CanonicalPersistenceService

Query/API entry
  -> ReviewQueryService / ProjectionService

Conflict/API entry
  -> SeriesConflictService
```

Acceptance:

- all D1 endpoints exist,
- all read paths use projections or summary tables,
- stale projections are labeled,
- no endpoint scans raw tag payloads for hot queries,
- API tests cover empty, missing, not found, stale, and invalid input cases.

### Batch 7B — Conflict resolution closure

Implement the user-visible `series-conflicts` workflow.

Acceptance:

- list conflicts,
- get one conflict,
- resolve with `keep_existing`,
- resolve with `promote_uploaded`,
- same action repeated returns 200,
- conflicting action after resolution returns 409,
- `auto_deduped` resolution attempt returns 409,
- audit event emitted for every resolution attempt.

### Batch 7C — Platform binding contract

Define and test the handoff shape to platform objects.

Acceptance:

- adapter interface exists,
- binding result is visible in review/query response,
- binding failure does not make valid DICOM disappear,
- accepted DICOM with failed binding remains queryable,
- failure logs include `job_id`, `item_id`, `error_code`, and binding target context.

### Batch 7D — Operator handoff closure

Add targeted operational docs and commands.

Acceptance:

- stuck batch runbook exists,
- replay runbook exists,
- projection rebuild runbook exists,
- each runbook has copy-paste commands,
- each command maps to implemented CLI/API behavior,
- smoke/deployment checks verify the commands or the paths they depend on.

## Implementation alternatives

### Approach A: Minimal product closure

**Summary:** Add the smallest API and runbook layer over existing services. Do not change internals unless a service boundary blocks the API.

**Effort:** M human, S with CC+gstack
**Risk:** Low/Medium

Pros:

- fastest route from engine to usable product,
- minimal disruption to code that just stabilized,
- reuses current service layer.

Cons:

- may preserve some internal awkwardness,
- no PACS/DICOMweb/general external compatibility scope,
- platform binding may still be thin.

### Approach B: Product surface plus adapter contracts

**Summary:** Add API layer, conflict workflow, operator runbooks, and a formal platform binding adapter. Keep DICOMweb out of scope.

**Effort:** L human, M with CC+gstack
**Risk:** Medium

Pros:

- best match for current roadmap,
- closes real V1 gaps without boiling the ocean,
- creates stable seams for platform and future UI.

Cons:

- touches more files,
- requires sharper integration tests,
- forces decisions on API response shapes now.

### Approach C: OHIF-only bridge when annotation integration starts

**Summary:** Do not build general compatibility. When OHIF integration starts, expose only the minimum data handoff path OHIF needs to view and annotate selected platform-managed studies/series.

**Effort:** M/L human, M with CC+gstack
**Risk:** Medium

Pros:

- directly serves the product goal, viewing and annotation,
- avoids PACS/DICOMweb scope creep,
- keeps the data management platform as the source of truth.

Cons:

- should not be built before OHIF work actually starts,
- requires a concrete OHIF deployment mode decision,
- annotation return-linking must be designed carefully.

**Recommendation:** choose Approach B. It is complete enough to become a real V1 and keeps OHIF/PACS-style integration out of scope until there is a concrete OHIF annotation bridge to build.

## Error and rescue registry for the missing product surface

| Codepath | What can go wrong | Exception/status | Rescued? | User sees |
| --- | --- | --- | --- | --- |
| Upload API | empty upload | `UploadTooLarge` / `InvalidUpload` equivalent needed | Partial | 4xx with named reason |
| Upload API | object store write fails | `UploadPackageStoreFailed` | Service has exception, API mapping missing | Should see failed job/report, not 500 blob |
| Query API | projection stale | stale projection state | Service supports concept, API missing | Should see `stale: true` |
| Query API | item not found | not found | API missing | 404 with stable envelope |
| Conflict resolve | same action repeated | already resolved same action | Contract requires 200 | Should see current summary |
| Conflict resolve | different action repeated | already resolved different action | Contract requires 409 | Should see conflict message |
| Conflict resolve | promote transaction fails midway | DB/transaction error | Needs all-or-nothing proof | Should remain `open` |
| Replay API/CLI | stored bytes missing | storage miss | Service returns failure | Operator sees exact item and URI context |
| Reindex API/CLI | projection rebuild fails | DB/storage/parse error | Needs runbook path | Operator sees failed scope and retry command |

## Failure modes registry

| Codepath | Failure mode | Rescued? | Test? | User sees? | Logged? | Gap |
| --- | --- | --- | --- | --- | --- | --- |
| D1 route layer | Route does not exist | N/A | No API test found | 404 / no product | N/A | **CRITICAL GAP** |
| Series conflict resolve | User cannot resolve conflict through API | Partial service only | Service tests likely, API tests missing | No action path | Partial | **CRITICAL GAP** |
| Platform binding | Accepted DICOM has no platform object handoff | Partial | Service-level only | Downstream cannot use object | Partial | **WARNING** |
| Stuck batch ops | Operator cannot locate stuck job in under 5 minutes from docs | Partial generic incident doc | No targeted runbook test | Operator reads code/logs | Partial | **WARNING** |
| Replay ops | Operator cannot replay from documented command | Partial service/CLI primitives | Targeted runbook missing | Manual intervention | Partial | **WARNING** |
| Projection rebuild ops | Operator cannot rebuild projection from documented command | Partial service primitive | Targeted runbook missing | Manual intervention | Partial | **WARNING** |

## NOT in scope for the next closure batch

| Item | Rationale |
| --- | --- |
| Full DICOMweb/PACS/external-hospital compatibility | Not a product goal. Only a minimal OHIF bridge is allowed when OHIF integration actually starts. |
| Full viewer | Explicitly excluded in the architecture. Different product surface. |
| Full anonymization workflow | Security docs matter now, full de-identification is its own product-grade workflow. |
| SEG / RTSTRUCT / SR enrichment | The current model should preserve references; branch-specific enrichment can follow. |
| Advanced pixel analytics | Not required to make ingestion trustworthy. |
| Rich curation UI | API first. UI should not invent semantics before conflict APIs are stable. |

## Stale diagram audit

The high-level architecture diagram in `/Users/haohuayin/Documents/dicom_injection/docs/006_dicom_ingestion_architecture.md` still describes the desired system, but it now overstates product closure in two places:

1. It shows `Upload API` as a system component, while current implementation appears service-first rather than route/API-first.
2. It shows `Mapping / Binding` to platform objects, while current binding appears policy-level rather than platform-integrated.

Recommendation: after Batch 7 planning, add a current-state vs target-state diagram so future reviewers do not confuse service existence with product closure.

## CEO read

Do not rewrite the engine.

Do not chase DICOMweb/PACS/external-hospital compatibility. It is out of scope. Only build the minimum OHIF bridge when that work starts.

Do close the product surface. The next highest-leverage move is to let someone use this without being the person who wrote it.

That means API closure, conflict resolution, platform handoff, and operator runbooks.

This is the whole game for the next pass.

## Completion summary

```text
+====================================================================+
|            CEO REVIEW — PRODUCT SURFACE SUMMARY                    |
+====================================================================+
| Current status        | Backend engine v1 runs and tests are green   |
| Main concern          | Product/API/operator surface not closed       |
| Recommended mode      | SELECTIVE_EXPANSION                           |
| Recommended approach  | Approach B: product surface + adapter contracts|
| Critical gaps         | 2                                             |
| Warnings              | 4                                             |
| Proposed next batch   | Batch 7: Product Surface Closure              |
| DICOMweb/PACS         | Out of scope; OHIF minimal bridge only         |
+====================================================================+
```
