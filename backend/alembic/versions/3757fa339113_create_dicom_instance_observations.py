"""create_dicom_instance_observations

Revision ID: 3757fa339113
Revises: 4a5926143abf
Create Date: 2026-05-17 19:32:09.913605

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '3757fa339113'
down_revision: Union[str, None] = '4a5926143abf'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'dicom_instance_observations',
        sa.Column('id', sa.BigInteger(), autoincrement=True, primary_key=True),
        sa.Column('instance_id', sa.BigInteger(), sa.ForeignKey('dicom_instances.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('ingestion_item_id', sa.BigInteger(), nullable=False),
        sa.Column('raw_object_uri', sa.Text(), nullable=True),
        sa.Column('whole_file_sha256', sa.Text(), nullable=True),
        sa.Column('pixel_digest', sa.Text(), nullable=True),
        sa.Column('raw_tag_set_uri', sa.Text(), nullable=True),
        sa.Column('raw_tag_set_json', sa.JSON(), nullable=True),
        sa.Column('is_canonical', sa.Boolean(), server_default='false', nullable=False),
        sa.Column('observed_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False)
    )
    op.create_index('ix_dicom_observations_instance_and_item', 'dicom_instance_observations', ['instance_id', 'ingestion_item_id'], unique=True)
    op.create_index('ix_dicom_observations_id_and_instance', 'dicom_instance_observations', ['id', 'instance_id'], unique=True)
    # Partial unique index for is_canonical
    op.execute("CREATE UNIQUE INDEX idx_dicom_obs_canonical_unique ON dicom_instance_observations(instance_id) WHERE is_canonical = true")
    op.create_index('ix_dicom_observations_ingestion_item', 'dicom_instance_observations', ['ingestion_item_id'])
    op.create_index('ix_dicom_observations_whole_file_sha256', 'dicom_instance_observations', ['whole_file_sha256'])
    op.create_index('ix_dicom_observations_pixel_digest', 'dicom_instance_observations', ['pixel_digest'])

    # Circular/Deferred FK constraints for dicom_instances
    op.execute('''
        ALTER TABLE dicom_instances
        ADD CONSTRAINT fk_canonical_observation
        FOREIGN KEY (current_canonical_observation_id)
        REFERENCES dicom_instance_observations(id)
        ON DELETE RESTRICT DEFERRABLE INITIALLY DEFERRED;
    ''')
    op.execute('''
        ALTER TABLE dicom_instances
        ADD CONSTRAINT fk_canonical_observation_owns_instance
        FOREIGN KEY (current_canonical_observation_id, id)
        REFERENCES dicom_instance_observations(id, instance_id)
        DEFERRABLE INITIALLY DEFERRED;
    ''')

def downgrade() -> None:
    op.execute('ALTER TABLE dicom_instances DROP CONSTRAINT fk_canonical_observation_owns_instance')
    op.execute('ALTER TABLE dicom_instances DROP CONSTRAINT fk_canonical_observation')
    op.drop_index('ix_dicom_observations_pixel_digest', table_name='dicom_instance_observations')
    op.drop_index('ix_dicom_observations_whole_file_sha256', table_name='dicom_instance_observations')
    op.drop_index('ix_dicom_observations_ingestion_item', table_name='dicom_instance_observations')
    op.execute('DROP INDEX idx_dicom_obs_canonical_unique')
    op.drop_index('ix_dicom_observations_id_and_instance', table_name='dicom_instance_observations')
    op.drop_index('ix_dicom_observations_instance_and_item', table_name='dicom_instance_observations')
    op.drop_table('dicom_instance_observations')
