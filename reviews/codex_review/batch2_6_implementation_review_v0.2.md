# Batch 2-6 Implementation Review v0.2

Date: 2026-05-18
Reviewer: Codex / gstack-review
Base reviewed: `origin/main` at `6e8337f`
Scope: current local working tree after Batch 2-6 fixes.

## Verdict

Green for the previously failing Batch 5 test cluster.

The seven named failures were real, but mostly test/result-shape mismatches around SQLAlchemy result handling and one async test bug. I also found and fixed one additional real schema mismatch not covered by those seven tests: `ReviewQueryService.get_job_review_view()` queried `dicom_ingestion_jobs.completed_at`, but the migration defines `finished_at`.

## Local sync status

Local repo is up to date with remote:

```text
HEAD == origin/main == 6e8337f
```

There are local uncommitted fixes on top of that head.

## Verification

Commands run:

```bash
cd backend && venv/bin/python -m pytest -q \
  tests/services/canonical/test_batch5_integration.py::TestC5ProjectionFoundation::test_projection_query_exposes_semantic_facts \
  tests/services/canonical/test_batch5_integration.py::TestC5ProjectionFoundation::test_projection_stats_show_coverage \
  tests/services/canonical/test_batch5_integration.py::TestC6RetryReplayFoundation::test_replay_history_recorded \
  tests/services/canonical/test_batch5_integration.py::TestC6RetryReplayFoundation::test_bulk_retry_without_reupload \
  tests/services/canonical/test_batch5_integration.py::TestD1ReviewQueries::test_review_query_includes_batch4_facts \
  tests/services/canonical/test_batch5_integration.py::TestD3ReindexWorkflow::test_dry_run_shows_plan \
  tests/services/canonical/test_batch5_integration.py::TestBatch5Integration::test_end_to_end_reindex_and_query
```

Result:

```text
7 passed in 0.04s
```

Full backend suite:

```bash
cd backend && venv/bin/python -m pytest -q
```

Result:

```text
429 passed, 13 skipped, 1 warning in 0.75s
```

Alembic heads:

```bash
cd backend && venv/bin/python -m alembic heads
```

Result:

```text
a1b2c3d4e5f6 (head)
```

## Fixes applied in this pass

### 1. SQLAlchemy result row handling

Files:

- `backend/src/dicom_ingestion/services/projection/projection_service.py`
- `backend/src/dicom_ingestion/services/replay/replay_service.py`

Problem:

Some tests mocked `fetchall()`, others mocked `__iter__`. The services were inconsistent about how they consumed SQLAlchemy results.

Fix:

Added `_result_rows()` helper in projection and replay services. It supports real SQLAlchemy results, `fetchall()` mocks, and iterable mocks.

### 2. Replay history row shape

File:

- `backend/src/dicom_ingestion/services/replay/replay_service.py`

Problem:

`get_replay_history()` did not select or return `error_detail`, while the replay history table and tests include it.

Fix:

Selected `error_detail` and mapped the row indexes correctly.

### 3. Dry-run reindex step semantics

File:

- `backend/src/dicom_ingestion/services/reindex/reindex_workflow.py`

Problem:

Dry-run jobs returned `success` for validate/analyze steps, while Batch 5 integration expected dry-run steps to be marked skipped and non-mutating.

Fix:

`_execute_step()` now returns a skipped step with a dry-run message before executing any step body.

### 4. Batch 4 binding fact mock coverage

File:

- `backend/tests/services/canonical/test_batch5_integration.py`

Problem:

`test_review_query_includes_batch4_facts` did not mock `dicom_binding_policies`, so the service read a bare `MagicMock` as `binding_status`.

Fix:

Added explicit binding policy mock row: `("bound", "project-1", "user-1")`.

### 5. Async test bug

File:

- `backend/tests/services/canonical/test_batch5_integration.py`

Problem:

`test_end_to_end_reindex_and_query` was already inside an async pytest test but called `asyncio.run()`, causing nested event-loop failure.

Fix:

Changed to `await workflow.create_job(...)`.

### 6. Real schema mismatch: job `completed_at`

Files:

- `backend/src/dicom_ingestion/services/queries/review_queries.py`
- `backend/tests/services/queries/test_review_queries.py`

Problem:

`dicom_ingestion_jobs` migration defines `finished_at`, not `completed_at`. `get_job_review_view()` queried `completed_at`, which would fail against real Postgres.

Fix:

Changed the query to use `finished_at` and added a regression assertion that the query does not reference `completed_at`.

## Remaining note

The only remaining test warning is:

```text
PytestCollectionWarning: cannot collect test class 'TestStatus'
```

Source:

- `backend/src/dicom_ingestion/ops/smoke_tests.py`

This is not a functional failure. If you want zero-warning hygiene, rename `TestStatus` to something like `SmokeTestStatus`.

## Final assessment

Current state is green by tests and the previously identified migration-head blocker is fixed.

I would still recommend one last `/review` after these fixes are committed, because the current review is against an uncommitted working tree.
