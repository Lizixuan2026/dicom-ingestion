"""create_dicom_studies

Revision ID: 19a095a9dfad
Revises: 
Create Date: 2026-05-17 19:30:41.117733

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '19a095a9dfad'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'dicom_studies',
        sa.Column('id', sa.BigInteger(), autoincrement=True, primary_key=True),
        sa.Column('study_instance_uid', sa.Text(), nullable=False),
        sa.Column('patient_name', sa.Text(), nullable=True),
        sa.Column('patient_id', sa.Text(), nullable=True),
        sa.Column('study_date', sa.Date(), nullable=True),
        sa.Column('study_time', sa.Text(), nullable=True),
        sa.Column('accession_number', sa.Text(), nullable=True),
        sa.Column('study_description', sa.Text(), nullable=True),
        sa.Column('series_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('instance_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('ingestion_completeness_status', sa.Text(), nullable=False, server_default='unknown'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.UniqueConstraint('study_instance_uid')
    )


def downgrade() -> None:
    op.drop_table('dicom_studies')
