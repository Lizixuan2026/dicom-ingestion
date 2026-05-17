"""create_dicom_private_tags

Revision ID: 7effc6c4842e
Revises: b43b801a7147
Create Date: 2026-05-17 19:32:10.461791

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7effc6c4842e'
down_revision: Union[str, None] = 'b43b801a7147'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'dicom_private_tags',
        sa.Column('id', sa.BigInteger(), autoincrement=True, primary_key=True),
        sa.Column('observation_id', sa.BigInteger(), sa.ForeignKey('dicom_instance_observations.id', ondelete='CASCADE'), nullable=False),
        sa.Column('private_creator', sa.Text(), nullable=False),
        sa.Column('tag', sa.Text(), nullable=False),
        sa.Column('vr', sa.Text(), nullable=True),
        sa.Column('raw_value', sa.LargeBinary(), nullable=True),
        sa.Column('interpreted_keyword', sa.Text(), nullable=True),
        sa.Column('interpreted_value', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False)
    )
    op.create_index('ix_dicom_private_tags_uniqueness', 'dicom_private_tags', ['observation_id', 'private_creator', 'tag'], unique=True)

def downgrade() -> None:
    op.drop_index('ix_dicom_private_tags_uniqueness', table_name='dicom_private_tags')
    op.drop_table('dicom_private_tags')
