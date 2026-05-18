# Batch 2-6 Implementation Review v0.1

Date: 2026-05-18
Reviewer: Codex / gstack-review
Base reviewed: `748dc53`
Head reviewed: `6e8337f`
Scope: remote `main` implementation for Batch 2 through Batch 6 after fast-forward pull.

## Verdict

Not green.

The implementation is broad and covers a lot of the intended surface area, but it has several release-blocking correctness issues:

1. Alembic has two heads, so migration state is split.
2. Batch 5 replay/review SQL references columns that do not exist in `dicom_ingestion_items`.
3. Content-duplicate detection cannot work for pixel-level duplicates because `pixel_digest` is never computed/persisted.
4. The checked-in local backend venv cannot run the test suite as-is, and the repo does not pin the Python runtime clearly enough for that not to matter.

## Verification run

Commands run:

```bash
git pull --ff-only origin main
cd backend && venv/bin/python -m pytest -q
cd backend && venv/bin/python -m alembic heads
```

Results:

- Pull succeeded, `main` fast-forwarded from `748dc53` to `6e8337f`.
- Full test suite did not collect:
  - `TypeError: unsupported operand type(s) for |: 'type' and 'type'`
  - triggered by `backend/src/dicom_ingestion/services/upload/upload_service.py:64` under checked-in `backend/venv` Python 3.9.6.
- `pytest-asyncio` is listed in `backend/requirements.txt`, but not installed in the checked-in `backend/venv`; async marks are reported as unknown in this environment.
- Alembic reports two heads:
  - `a1b2c3d4e5f6`
  - `c2a4f9df1b10`

## Scope completion check

| Batch | Status | Notes |
| --- | --- | --- |
| Batch 2 Durable Intake | Mostly done | Upload, scanner, ZIP safety, item model, parser, and tests exist. Full verification blocked by test environment. |
| Batch 3 Canonical Ingest | Mostly done | Canonical persistence and terminal reporting exist. Migration split and test collection failure prevent green status. |
| Batch 4 Review Semantics | Partial | Duplicate/private/reference/binding services exist. Pixel digest content duplicate path is incomplete. |
| Batch 5 Query + Replay | Partial / blocked | Projection, replay, reindex, and review query services exist, but replay/review SQL references nonexistent `status_axes` and `completed_at` columns. |
| Batch 6 Production Readiness | Partial | Metrics, health checks, logging, security helpers, runbooks, dashboard, and smoke/deploy CLI exist. Gates are not reliable while migrations/tests are red. |

## Findings

### [P1] (confidence: 10/10) Alembic migration graph has two heads

Files:

- `backend/alembic/versions/c2a4f9df1b10_create_terminal_reports.py`
- `backend/alembic/versions/c2a8f1f4a9c3_enforce_single_canonical_observation.py`
- `backend/alembic/versions/a1b2c3d4e5f6_add_batch5_replay_and_index_tables.py`

Evidence:

```bash
cd backend && venv/bin/python -m alembic heads
# a1b2c3d4e5f6 (head)
# c2a4f9df1b10 (head)
```

`c2a4f9df1b10` and `c2a8f1f4a9c3` both revise `b3954e035423`. The Batch 4/5 chain continues from `c2a8f1f4a9c3`, while terminal reports stay on a separate head.

Impact:

Production/schema setup is ambiguous. A deploy or fresh database can miss terminal report tables or require an explicit multi-head upgrade path. This breaks the migration-first contract.

Recommended fix:

Create an Alembic merge revision, or linearize the revisions so there is exactly one head. Then add a test/CI check:

```bash
cd backend && python -m alembic heads | wc -l
```

Expected result: `1`.

### [P1] (confidence: 10/10) Batch 5 replay/review queries reference nonexistent `dicom_ingestion_items.status_axes`

Files:

- `backend/src/dicom_ingestion/services/replay/replay_service.py:415`
- `backend/src/dicom_ingestion/services/replay/replay_service.py:645`
- `backend/src/dicom_ingestion/services/replay/replay_service.py:749`
- `backend/src/dicom_ingestion/services/queries/review_queries.py:386`
- `backend/src/dicom_ingestion/services/queries/review_queries.py:486`
- `backend/alembic/versions/0e27324d2490_create_dicom_ingestion_items.py:30-36`

Evidence:

The migration creates separate orthogonal status columns:

```text
scan_status
parse_status
storage_status
metadata_persistence_status
validation_status
binding_status
index_status
```

There is no `status_axes` column.

But replay/review SQL reads and filters `status_axes` directly:

```sql
SELECT ..., status_axes, ... FROM dicom_ingestion_items
```

and:

```sql
status_axes->>'parse_status' = 'failed'
```

Impact:

Batch 5 replay and review flows will fail at runtime with SQL errors once they touch real Postgres. This directly violates Batch 5 gates: query interfaces and replay must be executable.

Recommended fix:

Rewrite these queries to use the real columns. If the service wants a dict-shaped `status_axes`, construct it in Python from the seven columns after select.

### [P1] (confidence: 10/10) Batch 5 review item query references nonexistent `completed_at`

Files:

- `backend/src/dicom_ingestion/services/queries/review_queries.py:392`
- `backend/alembic/versions/0e27324d2490_create_dicom_ingestion_items.py:23-45`

Evidence:

`review_queries.py` selects:

```sql
i.completed_at
```

`dicom_ingestion_items` has `created_at` and `updated_at`, but no `completed_at`.

Impact:

`ReviewQueryService.get_item_review_view()` fails for real rows. This is the user-facing review/debug path, exactly the thing Batch 5 is meant to provide.

Recommended fix:

Either add `completed_at` to the schema and update terminalization code to set it, or remove it from the query and derive completion from terminal outcome plus `updated_at`.

### [P1] (confidence: 9/10) Pixel-level content duplicate detection is incomplete

Files:

- `backend/src/dicom_ingestion/services/parser/dicom_parser.py:147-203`
- `backend/src/dicom_ingestion/services/canonical/canonical_persistence.py:823`
- `backend/src/dicom_ingestion/services/detection/duplicate_detection.py:281-287`

Evidence:

The parser dataclass has `pixel_digest`, and duplicate detection checks it. But `parse_header()` never computes it. Canonical persistence also inserts observations with:

```python
"pixel_digest": None,  # Would need pixel extraction for this
```

So `_find_content_duplicates_by_hash(..., basis='pixel_digest')` cannot match prior observations by pixel digest.

Impact:

C1 content duplicate semantics only work for whole-file hash matches. DICOM files with different metadata but identical pixel data will not be detected as content duplicates. That is a core DICOM duplicate case.

Recommended fix:

Either implement pixel digest in FULL parse mode and persist it to `dicom_instance_observations.pixel_digest`, or explicitly narrow C1 acceptance/docs to whole-file duplicate detection only. The current code claims pixel digest support but does not deliver it.

### [P1/P2] (confidence: 8/10) Test environment is not reproducible from the checked-in backend venv

Files:

- `backend/src/dicom_ingestion/services/upload/upload_service.py:64`
- `backend/requirements.txt`
- `docs/superpowers/plans/2026-05-18-batch6-production-readiness.md`

Evidence:

Checked-in `backend/venv` is Python 3.9.6. The code uses `bytes | BinaryIO`, which raises during import on Python 3.9:

```text
TypeError: unsupported operand type(s) for |: 'type' and 'type'
```

The production readiness plan says Python 3.11, but `backend/README.md` does not state this runtime contract, and the local venv does not match it. `pytest-asyncio` is also listed in requirements but missing from the venv.

Impact:

A developer pulling this branch cannot run the tests from the repo state as-is. If Python 3.11 is the intended runtime, that needs to be explicit and enforced. Otherwise, code needs Python 3.9-compatible annotations.

Recommended fix:

Pick one:

1. Preferred: add an explicit Python 3.11 runtime contract, rebuild the venv, and add `.python-version` or equivalent.
2. Compatibility path: add `from __future__ import annotations` or use `Union[...]` / `Optional[...]` in the files that use `|` annotations.

## Noted but not counted as blockers

- Batch 6 smoke CLI currently proves the CLI wrapper works, not that DB/object storage/replay paths are healthy by default. This may be acceptable if external checks are intentionally opt-in, but it should not be treated as full production smoke coverage.
- `CanonicalPersistenceService` catches duplicate/private-tag/reference/binding failures and still marks persistence success. Binding failure tolerance is intentional per plan. For duplicate/reference/private-tag failures, decide whether these are hard or soft dependencies, then encode that contract in tests.

## Recommended next action

Do not treat Batch 2-6 as green yet.

Fix in this order:

1. Merge/linearize Alembic heads.
2. Replace `status_axes` and `completed_at` SQL references with actual schema columns, or add the missing columns intentionally.
3. Implement or de-scope pixel digest duplicate detection.
4. Rebuild the backend test environment around the intended Python runtime and rerun the full suite.

