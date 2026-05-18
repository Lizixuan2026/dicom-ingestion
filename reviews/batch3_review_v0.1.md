# Batch3 Review Notes

## Key Finding

- The newly added async tests in `backend/tests/services/canonical/test_canonical_persistence.py` and `backend/tests/services/reporting/test_terminal_report.py` are currently being skipped in this environment because `pytest-asyncio` (or equivalent plugin) is not installed.
- This means most of the behavior in `CanonicalPersistenceService.persist()` and `TerminalReportService.generate_job_report()` is not actually executed by CI if CI has the same dependency gap.

## Evidence

Running:

```bash
pytest -q backend/tests/services/canonical/test_canonical_persistence.py backend/tests/services/reporting/test_terminal_report.py
```

Result summary:

- `16 passed, 15 skipped`
- Repeated `PytestUnknownMarkWarning: Unknown pytest.mark.asyncio`
- Repeated `PytestUnhandledCoroutineWarning: async def functions are not natively supported and have been skipped.`

## Recommendation

- Add `pytest-asyncio` to test dependencies and configure pytest async mode (if needed).
- Alternatively, convert these tests to synchronous tests that explicitly run the coroutines.
- Consider adding a CI guard that fails when `PytestUnknownMarkWarning` or skipped async tests are detected.
