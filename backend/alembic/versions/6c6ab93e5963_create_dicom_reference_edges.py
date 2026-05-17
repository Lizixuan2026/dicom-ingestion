"""create_dicom_reference_edges

Revision ID: 6c6ab93e5963
Revises: 7effc6c4842e
Create Date: 2026-05-17 19:32:10.598454

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '6c6ab93e5963'
down_revision: Union[str, None] = '7effc6c4842e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'dicom_reference_edges',
        sa.Column('id', sa.BigInteger(), autoincrement=True, primary_key=True),
        sa.Column('from_instance_id', sa.BigInteger(), sa.ForeignKey('dicom_instances.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('relationship_type', sa.Text(), nullable=False),
        sa.Column('to_study_instance_uid', sa.Text(), nullable=True),
        sa.Column('to_series_instance_uid', sa.Text(), nullable=True),
        sa.Column('to_sop_instance_uid', sa.Text(), nullable=True),
        sa.Column('referenced_frame_number', sa.Integer(), nullable=True),
        sa.Column('resolved_target_instance_id', sa.BigInteger(), sa.ForeignKey('dicom_instances.id', ondelete='RESTRICT'), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False)
    )
    op.create_index('ix_dicom_reference_edges_to_sop', 'dicom_reference_edges', ['to_sop_instance_uid'])
    op.create_index('ix_dicom_reference_edges_to_series', 'dicom_reference_edges', ['to_series_instance_uid'])
    op.create_index('ix_dicom_reference_edges_resolved_target', 'dicom_reference_edges', ['resolved_target_instance_id'])

    # PostgreSQL 15+ single constraint NULLS NOT DISTINCT
    op.execute('''
        CREATE UNIQUE INDEX udx_reference_edges_natural
        ON dicom_reference_edges(from_instance_id, relationship_type,
                                  to_study_instance_uid, to_series_instance_uid,
                                  to_sop_instance_uid, referenced_frame_number)
        NULLS NOT DISTINCT;
    ''')

def downgrade() -> None:
    op.execute('DROP INDEX udx_reference_edges_natural')
    op.drop_index('ix_dicom_reference_edges_resolved_target', table_name='dicom_reference_edges')
    op.drop_index('ix_dicom_reference_edges_to_series', table_name='dicom_reference_edges')
    op.drop_index('ix_dicom_reference_edges_to_sop', table_name='dicom_reference_edges')
    op.drop_table('dicom_reference_edges')
