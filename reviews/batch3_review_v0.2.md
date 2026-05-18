# Batch 3 Review v0.2 (Re-check)

Date: 2026-05-18
Scope: `B6` (canonical parse + persistence) and `B7` (terminal reporting)
Reference: `docs/dicom_ingestion_execution/007_batch_3_execution_plan.md`

## Executive decision

**Decision: ⚠️ Yellow light (do not give full green-light for Batch 4 yet).**

Batch 3 implementation shape is directionally aligned with the plan, but the current test environment still skips most async-path tests due to missing async pytest plugin support (`pytest-asyncio` or equivalent). This leaves critical `persist()` and `generate_job_report()` execution paths under-validated in CI-like runs.

## Plan-to-implementation mapping

### 1) Canonical parse + persistence (`B6`)

Expected by plan:
- accepted candidates materialized into canonical study/series/instance records,
- deterministic failure envelopes.

Observed implementation:
- `CanonicalPersistenceService.persist()` executes study/series/instance creation flow and observation creation with canonical marker selection.
- deterministic failure envelope type exists (`CanonicalFailureEnvelope`) and serializes as machine-readable dict.

Assessment: **Implemented in code structure**, but runtime confidence is reduced by skipped async tests.

### 2) Terminal reporting (`B7`)

Expected by plan:
- candidate-level terminal outcomes,
- per-job summary for success/partial/failure,
- queryable terminal report persistence.

Observed implementation:
- `TerminalReportService.generate_job_report()` builds per-item reports and aggregate summary classification.
- report persistence hook is present through repository upsert.

Assessment: **Implemented in code structure**, but runtime confidence is reduced by skipped async tests.

## Gate check against Batch 3 merge criteria

From Batch 3 plan gate list:
1. Upload -> candidate-item -> canonical rows across success/failure fixtures.
2. Deterministic canonical persistence for repeated identical bytes.
3. Terminal ingest reporting complete/queryable.
4. Failures keep actionable reason classification.

Review status:
- Criteria intent appears to be addressed in design and tests, but **execution evidence is incomplete** because many relevant async tests are skipped in current environment.

## Evidence

Command run:

```bash
pytest -q backend/tests/services/canonical/test_canonical_persistence.py backend/tests/services/reporting/test_terminal_report.py
```

Result:
- `17 passed, 22 skipped`
- warnings include `PytestUnknownMarkWarning: Unknown pytest.mark.asyncio`
- warnings include `PytestUnhandledCoroutineWarning: async def functions are not natively supported and have been skipped`

## Required actions before Batch 4 green-light

1. Add async test runtime dependency (`pytest-asyncio` or equivalent) and ensure pytest async mode is configured.
2. Re-run Batch 3 service test set and confirm previously skipped async tests execute.
3. Treat skipped async tests as CI failure (or at least warning-to-fail policy) to avoid silent regression.

## Final recommendation

- **Not ready for unconditional green-light to start Batch 4.**
- You can proceed only if Batch 4 kickoff accepts this as an explicit risk with a near-term action to restore async test coverage first.
