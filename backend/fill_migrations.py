import os
import re

replacements = {
    "3757fa339113_create_dicom_instance_observations.py": """def upgrade() -> None:
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
""",
    "f6c3cdac23ae_create_dicom_ingestion_jobs.py": """def upgrade() -> None:
    op.create_table(
        'dicom_ingestion_jobs',
        sa.Column('id', sa.BigInteger(), autoincrement=True, primary_key=True),
        sa.Column('actor_id', sa.Text(), nullable=False),
        sa.Column('request_idempotency_key', sa.Text(), nullable=True),
        sa.Column('source_type', sa.Text(), nullable=False),
        sa.Column('status', sa.Text(), server_default='created', nullable=False),
        sa.Column('input_manifest_json', sa.JSON(), nullable=True),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('retry_count', sa.Integer(), server_default='0', nullable=False),
        sa.Column('report_json', sa.JSON(), nullable=True),
        sa.Column('failure_summary', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False)
    )
    op.execute("CREATE UNIQUE INDEX idx_dicom_jobs_actor_idempotency ON dicom_ingestion_jobs(actor_id, request_idempotency_key) WHERE request_idempotency_key IS NOT NULL")
    op.create_index('ix_dicom_jobs_status_created_at', 'dicom_ingestion_jobs', ['status', 'created_at'])

def downgrade() -> None:
    op.drop_index('ix_dicom_jobs_status_created_at', table_name='dicom_ingestion_jobs')
    op.execute("DROP INDEX idx_dicom_jobs_actor_idempotency")
    op.drop_table('dicom_ingestion_jobs')
""",
    "0e27324d2490_create_dicom_ingestion_items.py": """def upgrade() -> None:
    op.create_table(
        'dicom_ingestion_items',
        sa.Column('id', sa.BigInteger(), autoincrement=True, primary_key=True),
        sa.Column('ingestion_job_id', sa.BigInteger(), sa.ForeignKey('dicom_ingestion_jobs.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('source_path', sa.Text(), nullable=True),
        sa.Column('byte_size', sa.BigInteger(), nullable=True),
        sa.Column('whole_file_sha256', sa.Text(), nullable=True),
        sa.Column('item_fingerprint', sa.Text(), nullable=False),
        sa.Column('scan_status', sa.Text(), server_default='seen', nullable=False),
        sa.Column('parse_status', sa.Text(), server_default='pending', nullable=False),
        sa.Column('storage_status', sa.Text(), server_default='pending', nullable=False),
        sa.Column('metadata_persistence_status', sa.Text(), server_default='pending', nullable=False),
        sa.Column('validation_status', sa.Text(), server_default='pending', nullable=False),
        sa.Column('binding_status', sa.Text(), server_default='pending', nullable=False),
        sa.Column('index_status', sa.Text(), server_default='pending', nullable=False),
        sa.Column('terminal_outcome', sa.Text(), nullable=True),
        sa.Column('storage_uri', sa.Text(), nullable=True),
        sa.Column('raw_object_status', sa.Text(), nullable=True),
        sa.Column('raw_object_sha256', sa.Text(), nullable=True),
        sa.Column('last_retryable_stage', sa.Text(), nullable=True),
        sa.Column('error_code', sa.Text(), nullable=True),
        sa.Column('error_detail', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.UniqueConstraint('item_fingerprint')
    )
    op.create_index('ix_dicom_items_job_outcome', 'dicom_ingestion_items', ['ingestion_job_id', 'terminal_outcome'])
    op.create_index('ix_dicom_items_last_retryable', 'dicom_ingestion_items', ['last_retryable_stage'])

    op.execute('''
        ALTER TABLE dicom_instance_observations
        ADD CONSTRAINT fk_ingestion_item
        FOREIGN KEY (ingestion_item_id)
        REFERENCES dicom_ingestion_items(id)
        ON DELETE RESTRICT;
    ''')

def downgrade() -> None:
    op.execute('ALTER TABLE dicom_instance_observations DROP CONSTRAINT fk_ingestion_item')
    op.drop_index('ix_dicom_items_last_retryable', table_name='dicom_ingestion_items')
    op.drop_index('ix_dicom_items_job_outcome', table_name='dicom_ingestion_items')
    op.drop_table('dicom_ingestion_items')
""",
    "b43b801a7147_create_dicom_index_jobs.py": """def upgrade() -> None:
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
""",
    "7effc6c4842e_create_dicom_private_tags.py": """def upgrade() -> None:
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
""",
    "6c6ab93e5963_create_dicom_reference_edges.py": """def upgrade() -> None:
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
""",
    "234a9c2da0f4_create_dicom_duplicate_findings.py": """def upgrade() -> None:
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
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False)
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
""",
    "2484691efe74_create_dicom_core_projections.py": """def upgrade() -> None:
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
""",
    "660d6ad7081b_create_dicom_series_ingestion_attempts.py": """def upgrade() -> None:
    op.create_table(
        'dicom_series_ingestion_attempts',
        sa.Column('id', sa.BigInteger(), autoincrement=True, primary_key=True),
        sa.Column('ingestion_job_id', sa.BigInteger(), sa.ForeignKey('dicom_ingestion_jobs.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('study_instance_uid', sa.Text(), nullable=False),
        sa.Column('series_instance_uid', sa.Text(), nullable=False),
        sa.Column('uploaded_sop_count', sa.Integer(), server_default='0', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.UniqueConstraint('ingestion_job_id', 'series_instance_uid', name='uq_dicom_series_attempts_job_series')
    )
    op.create_index('ix_dicom_series_attempts_job', 'dicom_series_ingestion_attempts', ['ingestion_job_id'])
    op.create_index('ix_dicom_series_attempts_series', 'dicom_series_ingestion_attempts', ['series_instance_uid'])

    op.execute('''
        ALTER TABLE dicom_ingestion_items
        ADD COLUMN series_ingestion_attempt_id BIGINT REFERENCES dicom_series_ingestion_attempts(id) ON DELETE RESTRICT;
    ''')
    op.execute('CREATE INDEX ix_dicom_items_series_attempt ON dicom_ingestion_items(series_ingestion_attempt_id);')

def downgrade() -> None:
    op.execute('DROP INDEX ix_dicom_items_series_attempt;')
    op.execute('ALTER TABLE dicom_ingestion_items DROP COLUMN series_ingestion_attempt_id;')
    op.drop_index('ix_dicom_series_attempts_series', table_name='dicom_series_ingestion_attempts')
    op.drop_index('ix_dicom_series_attempts_job', table_name='dicom_series_ingestion_attempts')
    op.drop_table('dicom_series_ingestion_attempts')
"""
}

base_path = "/Users/haohuayin/Documents/dicom_injection/backend/alembic/versions"

for filename, content in replacements.items():
    filepath = os.path.join(base_path, filename)
    with open(filepath, 'r') as f:
        original = f.read()
    
    # Replace the def upgrade() to end with our new content
    new_content = re.sub(r'def upgrade\(\) -> None:.*', content, original, flags=re.DOTALL)
    
    with open(filepath, 'w') as f:
        f.write(new_content)
