# DICOM Ingestion — Implementation Readiness Review

Documentation map: `001_dicom_ingestion_documentation_map.md`

## 1. Purpose

This review checks whether the now-consistent plan is actually ready to execute. It is narrower than the earlier architecture and engineering reviews: the question is no longer "is the design coherent?" but "will the current backlog and gates keep a team from drifting once implementation starts?"

Reviewed documents:

- `011_dicom_ingestion_schema_and_contracts.md`
- `012_migration_first_backlog.md`
- `013_dicom_ingestion_full_feature_implementation_roadmap.md`
- `014_dicom_ingestion_execution_start_checklist.md`

## 2. Result

The plan is ready to start after the small documentation fixes recorded below.

| Check | Result | Notes |
| --- | --- | --- |
| `012 -> 011` cross-references | Pass | every cited `011` section still exists and still supports the acceptance criterion that references it |
| Gate exits vs backlog acceptance | Pass after fixes | a few gate-level truths existed only in prose; they are now represented in `012` acceptance criteria |
| Early observability ownership | Pass after fixes | the plan now assigns a Batch-1 observability vocabulary draft instead of waiting until Batch 6 to think about C7 |

## 3. Findings and resolutions

### 3.1 Contract cross-references remain valid

The current references from `012` into `011` are still accurate:

- `011` §3 canonical observation policy
- `011` §4.5 projection hot paths
- `011` §6 idempotency contract
- `011` §9.1 and §9.2 ingestion API response shapes
- `011` §11.1–11.5 Series conflict rules and actions

No broken section references or semantic drift were found in this pass.

### 3.2 Gate coverage needed three small repairs

The design was internally consistent, but three execution truths were not yet represented at the same precision in `012`:

1. **G1 mixed-batch accounting** existed in roadmap prose but had no explicit backlog acceptance proving every source entry reaches a tracked state before canonical persistence. `B5` now includes an integration acceptance over `B2` through `B5`.
2. **G2 sibling isolation** was stated as a gate test but not explicitly required by the terminal-report task. `B7` now requires a mixed-batch proof that one malformed item cannot poison siblings.
3. **G5 dashboards** were required by the roadmap but absent from `C7` acceptance. `C7` now requires dashboard panels for ingest throughput, failures, duplicate pressure, Series conflict resolution, and indexing lag.

One test was also moved to the correct gate: **failed binding does not invalidate ingest** now lives under G3, because binding policy is introduced by `C4`, not by G2.

### 3.3 C7 needed an early owner, not just a late ticket

Before this review, every document said observability should "start early and close late," but none of them named the early deliverable. That leaves the likely real outcome: nobody touches vocabulary until Batch 6.

The plan now makes the early work concrete:

- `014` requires an **observability owner** before coding starts,
- Batch 1 opens an **observability vocabulary draft** alongside schema / fixtures / storage work,
- Batch 1 cannot close until the provisional stage / event vocabulary is published,
- `012` names `docs/observability/dicom_ingestion_event_vocabulary.md` as the artifact that C7 later finalizes against.

## 4. Readiness conclusion

The document set is now coherent at three levels:

1. **contracts** — `011`
2. **minimum technical dependencies and acceptance** — `012`
3. **recommended construction order and operating cadence** — `013` / `014`

The next useful review should happen against implementation artifacts, not more planning prose: once Batch 1 lands, re-check whether migrations, fixture manifests, raw-storage tests, and the observability vocabulary actually satisfy the gates they now claim to satisfy.
