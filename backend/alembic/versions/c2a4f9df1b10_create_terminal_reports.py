"""create_terminal_reports

Revision ID: c2a4f9df1b10
Revises: b3954e035423
Create Date: 2026-05-18 00:00:00.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'c2a4f9df1b10'
down_revision: Union[str, None] = 'b3954e035423'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    op.create_table(
        'dicom_ingestion_terminal_reports',
        sa.Column('job_id', sa.BigInteger(), sa.ForeignKey('dicom_ingestion_jobs.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('total_items', sa.Integer(), nullable=False),
        sa.Column('accepted_count', sa.Integer(), nullable=False),
        sa.Column('quarantined_count', sa.Integer(), nullable=False),
        sa.Column('rejected_count', sa.Integer(), nullable=False),
        sa.Column('failed_count', sa.Integer(), nullable=False),
        sa.Column('duplicate_findings', sa.Integer(), nullable=False),
        sa.Column('unresolved_references', sa.Integer(), nullable=False),
        sa.Column('classification', sa.Text(), nullable=False),
        sa.Column('report_ready', sa.Boolean(), nullable=False),
        sa.Column('generated_at', sa.DateTime(timezone=False), nullable=False),
        sa.Column('report_metadata', sa.JSON(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    )
    op.create_table(
        'dicom_ingestion_terminal_report_items',
        sa.Column('id', sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column('job_id', sa.BigInteger(), sa.ForeignKey('dicom_ingestion_terminal_reports.job_id', ondelete='CASCADE'), nullable=False),
        sa.Column('item_id', sa.BigInteger(), nullable=False),
        sa.Column('source_path', sa.Text(), nullable=False),
        sa.Column('terminal_outcome', sa.Text(), nullable=False),
        sa.Column('error_code', sa.Text(), nullable=False, server_default=''),
        sa.Column('error_detail', sa.Text(), nullable=False, server_default=''),
        sa.Column('instance_id', sa.BigInteger(), nullable=True),
        sa.Column('observation_id', sa.BigInteger(), nullable=True),
        sa.Column('binding_status', sa.Text(), nullable=False),
        sa.Column('index_status', sa.Text(), nullable=False),
        sa.Column('processing_duration_ms', sa.Integer(), nullable=True),
    )
    op.create_index('ix_terminal_report_items_job_status', 'dicom_ingestion_terminal_report_items', ['job_id', 'terminal_outcome'])

def downgrade() -> None:
    op.drop_index('ix_terminal_report_items_job_status', table_name='dicom_ingestion_terminal_report_items')
    op.drop_table('dicom_ingestion_terminal_report_items')
    op.drop_table('dicom_ingestion_terminal_reports')
