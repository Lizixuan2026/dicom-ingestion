"""create_dicom_series

Revision ID: 57ecad6e0b49
Revises: 19a095a9dfad
Create Date: 2026-05-17 19:30:41.248379

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '57ecad6e0b49'
down_revision: Union[str, None] = '19a095a9dfad'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'dicom_series',
        sa.Column('id', sa.BigInteger(), autoincrement=True, primary_key=True),
        sa.Column('study_id', sa.BigInteger(), sa.ForeignKey('dicom_studies.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('series_instance_uid', sa.Text(), nullable=False),
        sa.Column('modality', sa.Text(), nullable=True),
        sa.Column('series_number', sa.Integer(), nullable=True),
        sa.Column('series_description', sa.Text(), nullable=True),
        sa.Column('frame_of_reference_uid', sa.Text(), nullable=True),
        sa.Column('object_class_family', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.UniqueConstraint('series_instance_uid')
    )
    op.create_index('ix_dicom_series_study_id', 'dicom_series', ['study_id'])


def downgrade() -> None:
    op.drop_index('ix_dicom_series_study_id', table_name='dicom_series')
    op.drop_table('dicom_series')
