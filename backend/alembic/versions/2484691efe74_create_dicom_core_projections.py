"""create_dicom_core_projections

Revision ID: 2484691efe74
Revises: 234a9c2da0f4
Create Date: 2026-05-17 19:32:10.873000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '2484691efe74'
down_revision: Union[str, None] = '234a9c2da0f4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'dicom_core_projections',
        sa.Column('instance_id', sa.BigInteger(), sa.ForeignKey('dicom_instances.id', ondelete='RESTRICT'), primary_key=True),
        sa.Column('study_instance_uid', sa.Text(), nullable=True),
        sa.Column('series_instance_uid', sa.Text(), nullable=True),
        sa.Column('sop_instance_uid', sa.Text(), nullable=True),
        sa.Column('modality', sa.Text(), nullable=True),
        sa.Column('study_date', sa.Date(), nullable=True),
        sa.Column('object_class_family', sa.Text(), nullable=True),
        sa.Column('binding_status', sa.Text(), nullable=True),
        sa.Column('duplicate_flags', sa.JSON(), nullable=True),
        sa.Column('reference_resolution_status', sa.Text(), nullable=True),
        sa.Column('metadata_extractor_version', sa.Text(), nullable=False),
        sa.Column('projection_version', sa.Text(), nullable=False),
        sa.Column('projection_built_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('projection_source_checksum', sa.Text(), nullable=False)
    )
    op.create_index('ix_dicom_core_proj_study_uid', 'dicom_core_projections', ['study_instance_uid'])
    op.create_index('ix_dicom_core_proj_series_uid', 'dicom_core_projections', ['series_instance_uid'])
    op.create_index('ix_dicom_core_proj_sop_uid', 'dicom_core_projections', ['sop_instance_uid'])
    op.create_index('ix_dicom_core_proj_modality', 'dicom_core_projections', ['modality'])
    op.create_index('ix_dicom_core_proj_study_date', 'dicom_core_projections', ['study_date'])
    op.create_index('ix_dicom_core_proj_object_class', 'dicom_core_projections', ['object_class_family'])
    op.create_index('ix_dicom_core_proj_binding_status', 'dicom_core_projections', ['binding_status'])

def downgrade() -> None:
    op.drop_index('ix_dicom_core_proj_binding_status', table_name='dicom_core_projections')
    op.drop_index('ix_dicom_core_proj_object_class', table_name='dicom_core_projections')
    op.drop_index('ix_dicom_core_proj_study_date', table_name='dicom_core_projections')
    op.drop_index('ix_dicom_core_proj_modality', table_name='dicom_core_projections')
    op.drop_index('ix_dicom_core_proj_sop_uid', table_name='dicom_core_projections')
    op.drop_index('ix_dicom_core_proj_series_uid', table_name='dicom_core_projections')
    op.drop_index('ix_dicom_core_proj_study_uid', table_name='dicom_core_projections')
    op.drop_table('dicom_core_projections')
