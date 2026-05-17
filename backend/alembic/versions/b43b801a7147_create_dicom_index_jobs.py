"""create_dicom_index_jobs

Revision ID: b43b801a7147
Revises: 0e27324d2490
Create Date: 2026-05-17 19:32:10.328327

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b43b801a7147'
down_revision: Union[str, None] = '0e27324d2490'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'dicom_index_jobs',
        sa.Column('id', sa.BigInteger(), autoincrement=True, primary_key=True),
        sa.Column('scope_type', sa.Text(), nullable=False),
        sa.Column('scope_id', sa.BigInteger(), nullable=False),
        sa.Column('status', sa.Text(), server_default='pending', nullable=False),
        sa.Column('report_json', sa.JSON(), nullable=True),
        sa.Column('failed_items_json', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False)
    )
    op.create_index('ix_dicom_index_jobs_status_created', 'dicom_index_jobs', ['status', 'created_at'])

def downgrade() -> None:
    op.drop_index('ix_dicom_index_jobs_status_created', table_name='dicom_index_jobs')
    op.drop_table('dicom_index_jobs')
