"""create_dicom_series_conflict_summaries

Revision ID: e8f3a2b1c4d5
Revises: c2a8f1f4a9c3
Create Date: 2026-05-18 15:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e8f3a2b1c4d5'
down_revision: Union[str, None] = 'c2a8f1f4a9c3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'dicom_series_conflict_summaries',
        sa.Column('id', sa.BigInteger(), autoincrement=True, primary_key=True),
        sa.Column('series_ingestion_attempt_id', sa.BigInteger(), sa.ForeignKey('dicom_series_ingestion_attempts.id', ondelete='RESTRICT'), nullable=False, unique=True),
        sa.Column('existing_series_id', sa.BigInteger(), sa.ForeignKey('dicom_series.id', ondelete='RESTRICT'), nullable=True),
        sa.Column('classification', sa.Text(), nullable=False),
        sa.Column('existing_sop_count', sa.Integer(), server_default='0', nullable=False),
        sa.Column('uploaded_sop_count', sa.Integer(), server_default='0', nullable=False),
        sa.Column('overlap_sop_count', sa.Integer(), server_default='0', nullable=False),
        sa.Column('new_sop_count', sa.Integer(), server_default='0', nullable=False),
        sa.Column('missing_sop_count', sa.Integer(), server_default='0', nullable=False),
        sa.Column('conflicting_sop_count', sa.Integer(), server_default='0', nullable=False),
        sa.Column('overlap_ratio', sa.Numeric(precision=5, scale=4), server_default='0.0000', nullable=False),
        sa.Column('status', sa.Text(), server_default='open', nullable=False),
        sa.Column('resolution_action', sa.Text(), nullable=True),
        sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('resolved_by', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False)
    )
    op.create_index('ix_dicom_series_conflict_attempt', 'dicom_series_conflict_summaries', ['series_ingestion_attempt_id'])
    op.create_index('ix_dicom_series_conflict_existing', 'dicom_series_conflict_summaries', ['existing_series_id'])
    op.create_index('ix_dicom_series_conflict_status', 'dicom_series_conflict_summaries', ['status'])
    op.create_index('ix_dicom_series_conflict_classification', 'dicom_series_conflict_summaries', ['classification'])


def downgrade() -> None:
    op.drop_index('ix_dicom_series_conflict_classification', table_name='dicom_series_conflict_summaries')
    op.drop_index('ix_dicom_series_conflict_status', table_name='dicom_series_conflict_summaries')
    op.drop_index('ix_dicom_series_conflict_existing', table_name='dicom_series_conflict_summaries')
    op.drop_index('ix_dicom_series_conflict_attempt', table_name='dicom_series_conflict_summaries')
    op.drop_table('dicom_series_conflict_summaries')
