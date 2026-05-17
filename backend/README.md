# DICOM Ingestion Backend

## Environment Contract

> [!WARNING]
> **Database Requirement**: This project requires **PostgreSQL 15+**.
> The database migrations strictly rely on the `NULLS NOT DISTINCT` modifier for unique indexes (e.g., in `dicom_duplicate_findings` and `dicom_reference_edges`). If you attempt to deploy this against an older version of PostgreSQL, the migrations will fail.
