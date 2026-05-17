"""create_dicom_series_ingestion_attempts

Revision ID: 660d6ad7081b
Revises: 2484691efe74
Create Date: 2026-05-17 19:32:11.009192

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '660d6ad7081b'
down_revision: Union[str, None] = '2484691efe74'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'dicom_series_ingestion_attempts',
        sa.Column('id', sa.BigInteger(), autoincrement=True, primary_key=True),
        sa.Column('ingestion_job_id', sa.BigInteger(), sa.ForeignKey('dicom_ingestion_jobs.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('study_instance_uid', sa.Text(), nullable=False),
        sa.Column('series_instance_uid', sa.Text(), nullable=False),
        sa.Column('uploaded_sop_count', sa.Integer(), server_default='0', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.UniqueConstraint('ingestion_job_id', 'series_instance_uid', name='uq_dicom_series_attempts_job_series')
    )
    op.create_index('ix_dicom_series_attempts_job', 'dicom_series_ingestion_attempts', ['ingestion_job_id'])
    op.create_index('ix_dicom_series_attempts_series', 'dicom_series_ingestion_attempts', ['series_instance_uid'])

    op.execute('''
        ALTER TABLE dicom_ingestion_items
        ADD COLUMN series_ingestion_attempt_id BIGINT REFERENCES dicom_series_ingestion_attempts(id) ON DELETE RESTRICT;
    ''')
    op.execute('CREATE INDEX ix_dicom_items_series_attempt ON dicom_ingestion_items(series_ingestion_attempt_id);')

def downgrade() -> None:
    op.execute('DROP INDEX ix_dicom_items_series_attempt;')
    op.execute('ALTER TABLE dicom_ingestion_items DROP COLUMN series_ingestion_attempt_id;')
    op.drop_index('ix_dicom_series_attempts_series', table_name='dicom_series_ingestion_attempts')
    op.drop_index('ix_dicom_series_attempts_job', table_name='dicom_series_ingestion_attempts')
    op.drop_table('dicom_series_ingestion_attempts')
