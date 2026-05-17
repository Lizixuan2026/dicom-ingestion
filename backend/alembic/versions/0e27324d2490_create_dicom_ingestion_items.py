"""create_dicom_ingestion_items

Revision ID: 0e27324d2490
Revises: f6c3cdac23ae
Create Date: 2026-05-17 19:32:10.196295

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0e27324d2490'
down_revision: Union[str, None] = 'f6c3cdac23ae'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'dicom_ingestion_items',
        sa.Column('id', sa.BigInteger(), autoincrement=True, primary_key=True),
        sa.Column('ingestion_job_id', sa.BigInteger(), sa.ForeignKey('dicom_ingestion_jobs.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('source_path', sa.Text(), nullable=True),
        sa.Column('byte_size', sa.BigInteger(), nullable=True),
        sa.Column('whole_file_sha256', sa.Text(), nullable=True),
        sa.Column('item_fingerprint', sa.Text(), nullable=False),
        sa.Column('scan_status', sa.Text(), server_default='seen', nullable=False),
        sa.Column('parse_status', sa.Text(), server_default='pending', nullable=False),
        sa.Column('storage_status', sa.Text(), server_default='pending', nullable=False),
        sa.Column('metadata_persistence_status', sa.Text(), server_default='pending', nullable=False),
        sa.Column('validation_status', sa.Text(), server_default='pending', nullable=False),
        sa.Column('binding_status', sa.Text(), server_default='pending', nullable=False),
        sa.Column('index_status', sa.Text(), server_default='pending', nullable=False),
        sa.Column('terminal_outcome', sa.Text(), nullable=True),
        sa.Column('storage_uri', sa.Text(), nullable=True),
        sa.Column('raw_object_status', sa.Text(), nullable=True),
        sa.Column('raw_object_sha256', sa.Text(), nullable=True),
        sa.Column('last_retryable_stage', sa.Text(), nullable=True),
        sa.Column('error_code', sa.Text(), nullable=True),
        sa.Column('error_detail', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.UniqueConstraint('item_fingerprint')
    )
    op.create_index('ix_dicom_items_job_outcome', 'dicom_ingestion_items', ['ingestion_job_id', 'terminal_outcome'])
    op.create_index('ix_dicom_items_last_retryable', 'dicom_ingestion_items', ['last_retryable_stage'])

    op.execute('''
        ALTER TABLE dicom_instance_observations
        ADD CONSTRAINT fk_ingestion_item
        FOREIGN KEY (ingestion_item_id)
        REFERENCES dicom_ingestion_items(id)
        ON DELETE RESTRICT;
    ''')

def downgrade() -> None:
    op.execute('ALTER TABLE dicom_instance_observations DROP CONSTRAINT fk_ingestion_item')
    op.drop_index('ix_dicom_items_last_retryable', table_name='dicom_ingestion_items')
    op.drop_index('ix_dicom_items_job_outcome', table_name='dicom_ingestion_items')
    op.drop_table('dicom_ingestion_items')
