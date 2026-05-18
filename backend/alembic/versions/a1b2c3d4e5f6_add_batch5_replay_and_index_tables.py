"""add_batch5_replay_and_index_tables

Revision ID: a1b2c3d4e5f6
Revises: f1a4c9e2b8d3
Create Date: 2026-05-18 16:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = 'f1a4c9e2b8d3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create dicom_replay_history table for C6 replay tracking
    op.create_table(
        'dicom_replay_history',
        sa.Column('id', sa.BigInteger(), autoincrement=True, primary_key=True),
        sa.Column('ingestion_item_id', sa.BigInteger(), sa.ForeignKey('dicom_ingestion_items.id', ondelete='CASCADE'), nullable=False),
        sa.Column('replay_from_stage', sa.Text(), nullable=False),
        sa.Column('success', sa.Boolean(), server_default='false', nullable=False),
        sa.Column('final_status', sa.Text(), nullable=True),
        sa.Column('error_code', sa.Text(), nullable=True),
        sa.Column('error_detail', sa.Text(), nullable=True),
        sa.Column('stage_results', sa.JSON(), nullable=True),
        sa.Column('replayed_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    )
    op.create_index('ix_dicom_replay_history_item_id', 'dicom_replay_history', ['ingestion_item_id'])
    op.create_index('ix_dicom_replay_history_replayed_at', 'dicom_replay_history', ['replayed_at'])
    op.create_index('ix_dicom_replay_history_success', 'dicom_replay_history', ['success'])

    # Update dicom_index_jobs table for D3 reindex workflow
    # First, add new columns
    op.add_column('dicom_index_jobs', sa.Column('name', sa.Text(), nullable=True))
    op.add_column('dicom_index_jobs', sa.Column('description', sa.Text(), nullable=True))
    op.add_column('dicom_index_jobs', sa.Column('created_by', sa.Text(), nullable=True))
    op.add_column('dicom_index_jobs', sa.Column('scope', sa.Text(), server_default='all', nullable=False))
    op.add_column('dicom_index_jobs', sa.Column('scope_params', sa.JSON(), nullable=True))
    op.add_column('dicom_index_jobs', sa.Column('steps', sa.JSON(), nullable=True))
    op.add_column('dicom_index_jobs', sa.Column('batch_size', sa.Integer(), server_default='100', nullable=False))
    op.add_column('dicom_index_jobs', sa.Column('dry_run', sa.Boolean(), server_default='false', nullable=False))
    op.add_column('dicom_index_jobs', sa.Column('progress', sa.Numeric(5, 2), server_default='0.0', nullable=False))
    op.add_column('dicom_index_jobs', sa.Column('current_step', sa.Text(), nullable=True))
    op.add_column('dicom_index_jobs', sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True))

    # Update existing rows with default name
    op.execute("UPDATE dicom_index_jobs SET name = 'Legacy Index Job ' || id WHERE name IS NULL")

    # Create additional indexes
    op.create_index('ix_dicom_index_jobs_name', 'dicom_index_jobs', ['name'])
    op.create_index('ix_dicom_index_jobs_created_by', 'dicom_index_jobs', ['created_by'])
    op.create_index('ix_dicom_index_jobs_scope', 'dicom_index_jobs', ['scope'])


def downgrade() -> None:
    # Drop new indexes from dicom_index_jobs
    op.drop_index('ix_dicom_index_jobs_scope', table_name='dicom_index_jobs')
    op.drop_index('ix_dicom_index_jobs_created_by', table_name='dicom_index_jobs')
    op.drop_index('ix_dicom_index_jobs_name', table_name='dicom_index_jobs')

    # Drop new columns from dicom_index_jobs
    op.drop_column('dicom_index_jobs', 'completed_at')
    op.drop_column('dicom_index_jobs', 'current_step')
    op.drop_column('dicom_index_jobs', 'progress')
    op.drop_column('dicom_index_jobs', 'dry_run')
    op.drop_column('dicom_index_jobs', 'batch_size')
    op.drop_column('dicom_index_jobs', 'steps')
    op.drop_column('dicom_index_jobs', 'scope_params')
    op.drop_column('dicom_index_jobs', 'scope')
    op.drop_column('dicom_index_jobs', 'created_by')
    op.drop_column('dicom_index_jobs', 'description')
    op.drop_column('dicom_index_jobs', 'name')

    # Drop dicom_replay_history table
    op.drop_index('ix_dicom_replay_history_success', table_name='dicom_replay_history')
    op.drop_index('ix_dicom_replay_history_replayed_at', table_name='dicom_replay_history')
    op.drop_index('ix_dicom_replay_history_item_id', table_name='dicom_replay_history')
    op.drop_table('dicom_replay_history')
