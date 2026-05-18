# Batch 2-6 Implementation Review v0.3

Date: 2026-05-18
Reviewer: Codex / gstack-review
Reviewed commit: `b12ee49`
Review mode: last-commit review, because `HEAD == origin/main` and the submitted commit is already on remote.

## Verdict

Clean after one mechanical auto-fix.

The submitted commit fixes the previous blockers:

- backend test suite runs on Python 3.11,
- Batch 5 integration tests pass,
- full backend suite passes,
- Alembic now reports one head,
- `status_axes` and item `completed_at` schema mismatches are removed,
- pixel digest is computed in FULL parse mode and persisted to observations.

## Scope check

Intent: Fix Batch 5 integration failures and schema mismatches from the prior review.

Delivered: The commit fixes test failures, pins Python 3.11 expectations, merges the Alembic migration graph, repairs replay/query column usage, and records the review artifacts.

Scope status: CLEAN.

## Verification

Commands run:

```bash
git status --short --branch
git log --oneline --decorate -5
git diff --stat HEAD~1..HEAD
cd backend && venv/bin/python --version
cd backend && venv/bin/python -m pytest -q
cd backend && venv/bin/python -m alembic heads
cd backend && venv/bin/python -m alembic history --verbose
rg -n "status_axes->|SELECT[\\s\\S]{0,120}status_axes|completed_at" backend/src/dicom_ingestion backend/alembic/versions
```

Results:

```text
HEAD == origin/main == b12ee49
Python 3.11.15
429 passed, 13 skipped, 1 warning in 0.70s
a1b2c3d4e5f6 (head)
```

The remaining warning is non-blocking:

```text
PytestCollectionWarning: cannot collect test class 'TestStatus'
```

Source: `backend/src/dicom_ingestion/ops/smoke_tests.py`.

## Findings

### AUTO-FIXED: P3 stale Alembic merge docstring

File:

- `backend/alembic/versions/d0e1f2a3b4c5_merge_terminal_reports_and_canonical.py`

Issue:

The actual merge revision is:

```python
down_revision = ('c2a4f9df1b10', 'f1a4c9e2b8d3')
```

but the docstring said it revised `c2a4f9df1b10` and `c2a8f1f4a9c3`. That was stale because `f1a4c9e2b8d3` is the current canonical/batch4 chain head and already includes `c2a8f1f4a9c3` through its ancestry.

Fix applied:

Updated the docstring and `Revises:` text to match the real Alembic graph:

- `c2a4f9df1b10`, terminal reports branch
- `f1a4c9e2b8d3`, canonical/batch4 chain

Verification after fix:

```text
cd backend && venv/bin/python -m alembic heads
# a1b2c3d4e5f6 (head)

cd backend && venv/bin/python -m pytest -q
# 429 passed, 13 skipped, 1 warning
```

## Review notes

No remaining P0/P1/P2 findings.

The one remaining warning can be cleaned later by renaming `TestStatus` to `SmokeTestStatus`, but it does not block this Batch 2-6 fix commit.

## Status

DONE_WITH_CONCERNS:

- Code and migrations review clean.
- Tests green.
- One mechanical docstring fix is now uncommitted and should be committed before final ship.
