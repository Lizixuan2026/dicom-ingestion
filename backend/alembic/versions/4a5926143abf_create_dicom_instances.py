"""create_dicom_instances

Revision ID: 4a5926143abf
Revises: 57ecad6e0b49
Create Date: 2026-05-17 19:30:41.386335

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '4a5926143abf'
down_revision: Union[str, None] = '57ecad6e0b49'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'dicom_instances',
        sa.Column('id', sa.BigInteger(), autoincrement=True, primary_key=True),
        sa.Column('study_id', sa.BigInteger(), sa.ForeignKey('dicom_studies.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('series_id', sa.BigInteger(), sa.ForeignKey('dicom_series.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('sop_instance_uid', sa.Text(), nullable=False),
        sa.Column('sop_class_uid', sa.Text(), nullable=True),
        sa.Column('instance_number', sa.Integer(), nullable=True),
        sa.Column('transfer_syntax_uid', sa.Text(), nullable=True),
        sa.Column('pixel_data_present', sa.Boolean(), server_default='false', nullable=False),
        sa.Column('current_canonical_observation_id', sa.BigInteger(), nullable=True),
        sa.Column('ingestion_status', sa.Text(), server_default='pending', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.UniqueConstraint('sop_instance_uid')
    )
    op.create_index('ix_dicom_instances_study_id', 'dicom_instances', ['study_id'])
    op.create_index('ix_dicom_instances_series_id', 'dicom_instances', ['series_id'])


def downgrade() -> None:
    op.drop_index('ix_dicom_instances_series_id', table_name='dicom_instances')
    op.drop_index('ix_dicom_instances_study_id', table_name='dicom_instances')
    op.drop_table('dicom_instances')
