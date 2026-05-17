"""create_dicom_duplicate_findings

Revision ID: 234a9c2da0f4
Revises: 6c6ab93e5963
Create Date: 2026-05-17 19:32:10.736273

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '234a9c2da0f4'
down_revision: Union[str, None] = '6c6ab93e5963'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'dicom_duplicate_findings',
        sa.Column('id', sa.BigInteger(), autoincrement=True, primary_key=True),
        sa.Column('observation_id', sa.BigInteger(), sa.ForeignKey('dicom_instance_observations.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('duplicate_type', sa.Text(), nullable=False),
        sa.Column('basis', sa.Text(), nullable=False),
        sa.Column('matched_instance_id', sa.BigInteger(), sa.ForeignKey('dicom_instances.id', ondelete='RESTRICT'), nullable=True),
        sa.Column('matched_observation_id', sa.BigInteger(), sa.ForeignKey('dicom_instance_observations.id', ondelete='RESTRICT'), nullable=True),
        sa.Column('resolution_status', sa.Text(), server_default='open', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.CheckConstraint('matched_instance_id IS NOT NULL OR matched_observation_id IS NOT NULL', name='chk_dicom_duplicate_findings_matched')
    )
    op.create_index('ix_dicom_duplicate_findings_obs', 'dicom_duplicate_findings', ['observation_id'])
    op.create_index('ix_dicom_duplicate_findings_match_inst', 'dicom_duplicate_findings', ['matched_instance_id'])
    op.create_index('ix_dicom_duplicate_findings_match_obs', 'dicom_duplicate_findings', ['matched_observation_id'])

    # PostgreSQL 15+ single constraint NULLS NOT DISTINCT
    op.execute('''
        CREATE UNIQUE INDEX udx_dup_findings_natural
        ON dicom_duplicate_findings(observation_id, duplicate_type, basis,
                                     matched_instance_id, matched_observation_id)
        NULLS NOT DISTINCT;
    ''')

def downgrade() -> None:
    op.execute('DROP INDEX udx_dup_findings_natural')
    op.drop_index('ix_dicom_duplicate_findings_match_obs', table_name='dicom_duplicate_findings')
    op.drop_index('ix_dicom_duplicate_findings_match_inst', table_name='dicom_duplicate_findings')
    op.drop_index('ix_dicom_duplicate_findings_obs', table_name='dicom_duplicate_findings')
    op.drop_table('dicom_duplicate_findings')
