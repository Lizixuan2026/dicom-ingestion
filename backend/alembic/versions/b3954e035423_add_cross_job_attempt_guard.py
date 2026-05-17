"""add_cross_job_attempt_guard

Revision ID: b3954e035423
Revises: 660d6ad7081b
Create Date: 2026-05-17

Guard against cross-job attempt binding:
  1. Add UNIQUE(id, ingestion_job_id) to dicom_series_ingestion_attempts
     so the pair can be used as a composite FK target.
  2. Add composite FK from dicom_ingestion_items(series_ingestion_attempt_id, ingestion_job_id)
     to dicom_series_ingestion_attempts(id, ingestion_job_id).
     This makes it physically impossible at the DB layer to bind an item to
     an attempt from a different ingestion job.
"""
from typing import Sequence, Union
from alembic import op

revision: str = 'b3954e035423'
down_revision: Union[str, None] = '660d6ad7081b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Step 1: unique index to back the composite FK
    op.execute("""
        CREATE UNIQUE INDEX udx_attempts_id_job
        ON dicom_series_ingestion_attempts(id, ingestion_job_id);
    """)
    # Step 2: composite FK from items -> attempts enforcing same-job constraint
    op.execute("""
        ALTER TABLE dicom_ingestion_items
        ADD CONSTRAINT fk_items_attempt_same_job
        FOREIGN KEY (series_ingestion_attempt_id, ingestion_job_id)
        REFERENCES dicom_series_ingestion_attempts(id, ingestion_job_id)
        ON DELETE RESTRICT;
    """)


def downgrade() -> None:
    op.execute("ALTER TABLE dicom_ingestion_items DROP CONSTRAINT IF EXISTS fk_items_attempt_same_job;")
    op.execute("DROP INDEX IF EXISTS udx_attempts_id_job;")
