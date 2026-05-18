"""create_dicom_binding_policies

Revision ID: f1a4c9e2b8d3
Revises: e8f3a2b1c4d5
Create Date: 2026-05-18 15:35:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f1a4c9e2b8d3'
down_revision: Union[str, None] = 'e8f3a2b1c4d5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'dicom_binding_policies',
        sa.Column('id', sa.BigInteger(), autoincrement=True, primary_key=True),
        sa.Column('instance_id', sa.BigInteger(), sa.ForeignKey('dicom_instances.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('observation_id', sa.BigInteger(), sa.ForeignKey('dicom_instance_observations.id', ondelete='RESTRICT'), nullable=False, unique=True),
        sa.Column('binding_status', sa.Text(), server_default='pending', nullable=False),
        sa.Column('target_type', sa.Text(), nullable=True),
        sa.Column('target_id', sa.Text(), nullable=True),
        sa.Column('target_uri', sa.Text(), nullable=True),
        sa.Column('error_code', sa.Text(), nullable=True),
        sa.Column('error_detail', sa.Text(), nullable=True),
        sa.Column('bound_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('retry_count', sa.Integer(), server_default='0', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False)
    )
    op.create_index('ix_dicom_binding_instance', 'dicom_binding_policies', ['instance_id'])
    op.create_index('ix_dicom_binding_observation', 'dicom_binding_policies', ['observation_id'])
    op.create_index('ix_dicom_binding_status', 'dicom_binding_policies', ['binding_status'])
    op.create_index('ix_dicom_binding_target', 'dicom_binding_policies', ['target_type', 'target_id'])


def downgrade() -> None:
    op.drop_index('ix_dicom_binding_target', table_name='dicom_binding_policies')
    op.drop_index('ix_dicom_binding_status', table_name='dicom_binding_policies')
    op.drop_index('ix_dicom_binding_observation', table_name='dicom_binding_policies')
    op.drop_index('ix_dicom_binding_instance', table_name='dicom_binding_policies')
    op.drop_table('dicom_binding_policies')
