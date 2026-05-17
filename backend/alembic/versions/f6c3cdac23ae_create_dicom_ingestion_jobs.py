"""create_dicom_ingestion_jobs

Revision ID: f6c3cdac23ae
Revises: 3757fa339113
Create Date: 2026-05-17 19:32:10.064306

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f6c3cdac23ae'
down_revision: Union[str, None] = '3757fa339113'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'dicom_ingestion_jobs',
        sa.Column('id', sa.BigInteger(), autoincrement=True, primary_key=True),
        sa.Column('actor_id', sa.Text(), nullable=False),
        sa.Column('request_idempotency_key', sa.Text(), nullable=True),
        sa.Column('source_type', sa.Text(), nullable=False),
        sa.Column('status', sa.Text(), server_default='created', nullable=False),
        sa.Column('input_manifest_json', sa.JSON(), nullable=True),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('retry_count', sa.Integer(), server_default='0', nullable=False),
        sa.Column('report_json', sa.JSON(), nullable=True),
        sa.Column('failure_summary', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False)
    )
    op.execute("CREATE UNIQUE INDEX idx_dicom_jobs_actor_idempotency ON dicom_ingestion_jobs(actor_id, request_idempotency_key) WHERE request_idempotency_key IS NOT NULL")
    op.create_index('ix_dicom_jobs_status_created_at', 'dicom_ingestion_jobs', ['status', 'created_at'])

def downgrade() -> None:
    op.drop_index('ix_dicom_jobs_status_created_at', table_name='dicom_ingestion_jobs')
    op.execute("DROP INDEX idx_dicom_jobs_actor_idempotency")
    op.drop_table('dicom_ingestion_jobs')
