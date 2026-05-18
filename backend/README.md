# DICOM Ingestion Backend

## Environment Contract

> [!WARNING]
> **Python Requirement**: This project requires **Python 3.11+**.
> The codebase uses `X | Y` union type syntax (PEP 604) which is only valid at runtime on Python 3.10+.
> The checked-in `backend/venv` was built against Python 3.9.6 and **cannot run the test suite**.
> Rebuild the venv with Python 3.11 before running tests:
> ```bash
> python3.11 -m venv backend/venv
> backend/venv/bin/pip install -r backend/requirements.txt
> ```

> [!WARNING]
> **Database Requirement**: This project requires **PostgreSQL 15+**.
> The database migrations strictly rely on the `NULLS NOT DISTINCT` modifier for unique indexes (e.g., in `dicom_duplicate_findings` and `dicom_reference_edges`). If you attempt to deploy this against an older version of PostgreSQL, the migrations will fail.
