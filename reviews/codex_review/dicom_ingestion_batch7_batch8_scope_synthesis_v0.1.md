# DICOM Ingestion Batch 7 / Batch 8 Scope Synthesis v0.1

Date: 2026-05-18  
Reviewer: Codex synthesis after `/plan-ceo-review` + human review discussion  
Branch: `main`  
Commit reviewed: `cf2329f`  
Status: **DRAFT FOR NEXT DISCUSSION**

## Executive verdict

The earlier CEO review was directionally right but one layer too shallow.

It correctly saw that the current codebase has a real backend ingestion engine but not yet a complete user-facing product surface. What the human review exposed is more important: before we close the surface, there are still several **platform-foundation** decisions that must be made explicit, otherwise Batch 7 will accidentally polish the wrong layer.

The right product framing is:

```text
This is not a DICOM parser library.
This is not a PACS.
This is the medical-imaging intake layer of a data management platform.
```

Its job is to take messy imaging data in, preserve it, interpret it enough for the platform to use it, organize it in deployment-appropriate storage, and expose it safely to later dataset / annotation / review workflows.

That changes the sequencing:

```text
Batch 7 should close the data-platform foundation.
Batch 8 should close the product/API/review surface.
Batch 9, only if needed later, may add the smallest OHIF bridge.
```

## Hard scope guardrail

This scope line is not "temporarily lower priority." It is **not the product**.

### Explicitly out of scope

- PACS compatibility
- external hospital system integration
- generic DICOMweb conformance
- building STOW-RS / QIDO-RS / WADO-RS because "the standard says so"
- letting hospital-networking concerns steer the core product model

### Only allowed exception

A future **minimal OHIF bridge** may be added if and when OHIF integration starts and only to the extent needed for:

- opening selected managed DICOM data for viewing,
- preserving Study / Series / Instance identity across the handoff,
- linking OHIF-side annotation results back into the platform.

That is a narrow viewer handoff. It is not PACS scope wearing a fake moustache.

## Combined evidence base

This synthesis combines three inputs:

1. `/reviews/codex_review/dicom_ingestion_v1_product_surface_ceo_review_v0.1.md`
2. `/reviews/human_reviews/question_log.md`
3. `/docs/016_data_storage_structure_design.md`

The CEO review identified missing product closure:

- stable API surface,
- conflict-resolution workflow,
- platform binding contract,
- targeted operator runbooks.

The human review identified deeper foundation gaps:

- no direct folder/tree ingest yet,
- parser is still pydicom-bound and tag semantics are not configurable,
- private tags are not yet first-class semantic inputs,
- parsing is still synchronous,
- duplicate reporting is too SOP-granular for real batch UX,
- `BindingTargetType.STUDY` is semantically confusing,
- storage must support both object storage and local/NAS hierarchies.

The storage design shows why several of these are coupled. Local/NAS paths depend on DICOM semantics such as vendor, device, `StudyUID`, `SeriesUID`, and for UIH cases `MeasUID` from private tags. If parser semantics remain blind, the local storage architecture cannot become real without later rework.

## What already exists

| Capability | Existing evidence | Reuse posture |
| --- | --- | --- |
| Raw-byte preservation | `backend/src/dicom_ingestion/services/upload/upload_service.py` | Reuse. Do not rebuild upload persistence. |
| ZIP scanning and candidate classification | `services/scanner/scan_service.py`, `zip_safety.py` | Reuse, then generalize to folder/tree inputs. |
| DICOM parsing and canonical persistence | `services/parser/dicom_parser.py`, `services/persistence/canonical_persistence.py` | Reuse behavior, replace hard coupling with a cleaner parser seam. |
| Duplicate detection primitives | `services/detection/*` | Reuse detection facts, add Series-level aggregation. |
| Conflict services | `services/conflict/series_conflict.py` | Reuse in Batch 8 product workflow. |
| Query / projection / replay / reindex services | `services/queries`, `services/projection`, `services/replay`, `services/reindex` | Reuse in Batch 8 APIs and operator flows. |
| Observability / security primitives | `observability`, `security`, `ops`, `backend/dashboards` | Reuse. Batch 7/8 should extend, not fork. |

## The actual dependency graph

```text
Configurable tag semantics
        │
        ├──▶ Private-tag interpretation, including MeasUID
        │
        ├──▶ Local/NAS path generation
        │
        └──▶ Future parser replacement without rewriting callers

Folder/tree ingest ───▶ larger batch inputs ───▶ async parse pressure
                                           │
                                           └──▶ Series-level duplicate summaries

Async parse worker ───▶ truthful job state / retries / operator visibility

Clear binding vocabulary ───▶ cleaner platform object handoff
```

The important thing: these are not random feature requests. They are parts of one foundation.

## Why Batch 7 should change

The previous CEO review proposed **Batch 7: Product Surface Closure**. That is still necessary, but it should move one batch later.

If we build public APIs before fixing parser semantics, storage semantics, folder ingest, and async parse boundaries, we will freeze the wrong contracts in public. Then every later correction becomes migration work. That is exactly how a codebase starts lying about what it is.

So the better sequence is:

```text
Batch 7 = make the platform foundation true
Batch 8 = expose the now-true platform through product/API workflows
```

## Recommended batch split

### Batch 7: Data Platform Foundation Closure

**Goal:** make the ingestion layer structurally honest before exposing more product surface.

#### 7A. Parser seam + tag schema

Build a configurable parser layer while keeping current behavior available through a default implementation.

Minimum acceptance:

- parser interface exists and callers depend on the interface, not directly on pydicom,
- default pydicom-backed parser remains functional,
- tag schema can define standard and private tags, semantic names, and processors,
- private tags needed by storage design can be interpreted semantically, especially `MeasUID`,
- raw tag preservation remains intact,
- parser replacement can be tested without touching persistence code.

#### 7B. Dual storage backend + path generation

Support two deployment modes without pretending they are the same thing:

- object storage with hash-oriented flat keys,
- local/NAS storage with tag-derived human-browsable hierarchy.

Minimum acceptance:

- `StorageBackend`-style abstraction exists,
- object-storage behavior remains compatible with current raw preservation,
- local/NAS path generation uses explicit rules from `docs/016_data_storage_structure_design.md`,
- missing optional path components have defined fallback behavior rather than ad hoc strings,
- generated paths are testable and deterministic,
- annotation and multimodal path rules are acknowledged in the architecture even if not all modalities are implemented in this batch.

#### 7C. Folder/tree ingest abstraction

Support the product promise that users can give the system a folder, not only a single file or ZIP.

Minimum acceptance:

- ingest input model can represent file, ZIP, and folder/tree sources,
- directory traversal has explicit symlink, recursion, and path-safety policy,
- very large folders do not require holding the whole manifest in memory,
- existing scanner behavior is reused rather than duplicated,
- user-visible reports preserve enough source path context to explain failures.

#### 7D. Async parse worker boundary

Move parsing behind an explicit worker boundary while keeping `DicomParser` pure.

Minimum acceptance:

- `IN_PROGRESS` becomes a real state, not a decorative enum value,
- worker owns retries, state transitions, and idempotency checks,
- parser remains side-effect-free,
- retry exhaustion and dead/stuck tasks become observable,
- worker interface is abstract enough that Celery is an implementation choice, not a permanent infection of the domain layer.

#### 7E. Remove ambiguous `STUDY` binding target

Fix the vocabulary before it leaks further.

Minimum acceptance:

- remove `BindingTargetType.STUDY`,
- update all references and tests,
- if a future business-level study target is needed, reserve clearer names such as `RESEARCH_STUDY` or `PROJECT_STUDY`,
- docs explain the distinction between DICOM study records and platform business objects.

### Batch 8: Product Surface + Review Workflow Closure

**Goal:** now that the foundation is true, make it usable by users, downstream services, and operators.

#### 8A. Upload and job APIs

- public upload/job entry points,
- job status and failure reporting,
- folder/tree source support surfaced through the product contract.

#### 8B. Query APIs

- Study / Series / Instance reads,
- duplicate and unresolved-reference views,
- projection freshness clearly represented.

#### 8C. Series-level duplicate review

- aggregate duplicate findings by Series, not only SOP,
- expose concise batch-level duplicate summaries,
- avoid making users inspect hundreds of instance rows to understand one duplicate series.

#### 8D. Series conflict resolution workflow

- list conflict,
- inspect conflict,
- resolve conflict,
- audit decisions,
- guarantee repeat-action idempotency and conflicting-action rejection.

#### 8E. Platform binding response shape

- expose how ingested imaging objects relate to platform objects,
- keep failed binding visible without making valid DICOM disappear,
- make downstream consumers depend on a stable response envelope, not private internals.

#### 8F. Targeted operator handoff

- stuck batch runbook,
- replay runbook,
- projection rebuild runbook,
- commands and expected outputs tied to real operational paths.

### Batch 9: OHIF Bridge, only when needed

**Goal:** if the product actually reaches the point of viewer/annotation integration, add the smallest bridge needed.

Allowed:

- selected managed dataset/series can be opened in OHIF,
- OHIF-originated annotation can be linked back to platform entities,
- the bridge preserves only the metadata and retrieval semantics required by the chosen OHIF deployment mode.

Not allowed:

- broadening this into PACS compatibility,
- accepting external hospital protocols,
- using OHIF as the excuse to resurrect full DICOMweb scope.

## Product thesis after synthesis

The clean sentence is:

> We are building the medical-imaging intake layer for a data management platform: it must preserve raw data, understand enough semantics to organize and reuse it, and make downstream dataset / annotation workflows trustworthy.

That sentence explains why these items belong together:

- parser semantics,
- private tags,
- storage layout,
- folder ingest,
- async work,
- Series-level review.

They are not embellishments. They are the difference between "a DICOM uploader" and "a platform intake layer."

## Dream state delta

```text
CURRENT STATE
  Real ingestion engine.
  Strong services, tests, replay/projection/ops primitives.
  But several foundation contracts are still implicit or too narrow.

BATCH 7
  Make ingestion semantically honest:
  parser seam, tag schema, private-tag meaning, dual storage, folder ingest,
  async worker boundary, unambiguous binding vocabulary.

BATCH 8
  Make the honest foundation usable:
  APIs, Series duplicate summaries, conflict resolution, binding envelope,
  operator playbooks.

12-MONTH IDEAL
  Platform-native imaging intake layer.
  Cloud and on-prem deployments both fit.
  Dataset and annotation features reuse stable imaging objects.
  OHIF can be connected later by a narrow bridge without changing the core product identity.
```

## Decision log from human review

| Human review item | Product reading | Recommended placement |
| --- | --- | --- |
| Q2 folder upload | This is part of the product promise, not polish. | Batch 7 foundation |
| Q3 configurable tags / replaceable parser / async parse | This is the semantic seam everything else depends on. | Batch 7 foundation |
| Q4 Celery-style async worker | Needed for honest operational behavior at scale. | Batch 7 foundation |
| Q5 Series-level duplicate summary | User-facing review layer, downstream of correct batch ingestion. | Batch 8 product surface |
| Q6 remove `STUDY` binding target | Vocabulary cleanup before more surface leaks. | Batch 7 foundation |
| Q7 dual storage + tag-derived local paths | Deployment-defining platform capability. Depends on Q3. | Batch 7 foundation |

## What should not be smuggled into Batch 7 or Batch 8

| Item | Why not |
| --- | --- |
| PACS compatibility | Wrong product. |
| External hospital system integration | Wrong product. |
| General DICOMweb service | Wrong product unless narrowed later to OHIF bridge needs. |
| Full viewer | Separate product layer. |
| Full anonymization workflow | Important, but its own product-grade workflow. |
| Broad multimodal implementation in one jump | Storage architecture should allow it, but Batch 7 need not implement every modality before DICOM foundation is sound. |
| Advanced SEG / RTSTRUCT / SR enrichment | Preserve references now, enrich later. |

## Open decisions before implementation

These are the decisions worth settling deliberately rather than letting engineers improvise mid-flight.

1. **Exact local/NAS path fallback rules**  
   When `MeasUID`, device name, or vendor-specific fields are missing, what exact path shape do we use? This needs one canonical answer before path generation ships.

2. **Parser interface depth**  
   Do we only abstract `parse_header`, or do we also define hooks for tag processors and private-tag dictionaries in the same first cut? My recommendation: include both now, because storage design already depends on semantic private tags.

3. **Queue abstraction vs direct Celery commitment**  
   My recommendation: define a domain-level parse-task boundary and use Celery as the first adapter. That keeps infra replaceable without pretending async does not matter.

4. **Folder ingest transport shape**  
   For API clients, is a folder represented as a real directory source, a manifest, or an uploaded ZIP that preserves relative paths? The product promise is “folder works”; the implementation contract still needs one source of truth.

5. **Scope of multimodal storage in Batch 7**  
   Architecture must reserve the path grammar now. Implementation can stay DICOM-first unless there is an immediate downstream need.

6. **OHIF trigger condition**  
   Write down the trigger: the bridge begins only when a concrete viewer/annotation workflow is being built, not because generic standards feel aesthetically incomplete.

## Recommended next move

Do **not** start Batch 8 from the old CEO review directly.

First, use this synthesis as the seed for one short `/office-hours` pass focused on the actual product wedge and on the unresolved decisions above. Then turn the result into:

1. a Batch 7 execution plan,
2. a Batch 8 execution plan,
3. explicit deferred scope language that keeps PACS / external hospital / generic DICOMweb from creeping back in later.

That is the right order. It preserves speed without building on a blurry foundation.
