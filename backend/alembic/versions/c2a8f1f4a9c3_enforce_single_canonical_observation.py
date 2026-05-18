"""enforce_single_canonical_observation

Revision ID: c2a8f1f4a9c3
Revises: b3954e035423
Create Date: 2026-05-18 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'c2a8f1f4a9c3'
down_revision: Union[str, None] = 'b3954e035423'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute('DROP INDEX IF EXISTS idx_dicom_obs_canonical_unique')
    op.execute(
        '''
        CREATE UNIQUE INDEX IF NOT EXISTS uq_dicom_obs_instance_is_canonical_true
        ON dicom_instance_observations (instance_id, is_canonical)
        WHERE is_canonical = true
        '''
    )


def downgrade() -> None:
    op.execute('DROP INDEX IF EXISTS uq_dicom_obs_instance_is_canonical_true')
    op.execute(
        '''
        CREATE UNIQUE INDEX IF NOT EXISTS idx_dicom_obs_canonical_unique
        ON dicom_instance_observations(instance_id)
        WHERE is_canonical = true
        '''
    )
