import pytest
import sqlalchemy as sa
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

DATABASE_URL = "postgresql://postgres:postgres@localhost:5432/dicom_test"

@pytest.fixture(scope="session")
def engine():
    return create_engine(DATABASE_URL)

@pytest.fixture(scope="function")
def session(engine):
    connection = engine.connect()
    transaction = connection.begin()
    Session = sessionmaker(bind=connection)
    session = Session()
    yield session
    session.close()
    transaction.rollback()
    connection.close()

def test_unique_study_instance_uid(session):
    session.execute(sa.text("INSERT INTO dicom_studies (study_instance_uid) VALUES ('1.2.3.4')"))
    session.flush()
    with pytest.raises(IntegrityError):
        with session.begin_nested():
            session.execute(sa.text("INSERT INTO dicom_studies (study_instance_uid) VALUES ('1.2.3.4')"))

def test_fk_restrict_on_series(session):
    result = session.execute(sa.text("INSERT INTO dicom_studies (study_instance_uid) VALUES ('study1') RETURNING id"))
    study_id = result.scalar()
    session.execute(sa.text(f"INSERT INTO dicom_series (study_id, series_instance_uid) VALUES ({study_id}, 'series1')"))
    session.flush()
    with pytest.raises(IntegrityError):
        with session.begin_nested():
            session.execute(sa.text(f"DELETE FROM dicom_studies WHERE id = {study_id}"))

def test_canonical_fk_deferral(session):
    study_id = session.execute(sa.text("INSERT INTO dicom_studies (study_instance_uid) VALUES ('study2') RETURNING id")).scalar()
    series_id = session.execute(sa.text(f"INSERT INTO dicom_series (study_id, series_instance_uid) VALUES ({study_id}, 'series2') RETURNING id")).scalar()
    
    # Should succeed because constraint is deferred
    session.execute(sa.text(f"INSERT INTO dicom_instances (study_id, series_id, sop_instance_uid, current_canonical_observation_id) VALUES ({study_id}, {series_id}, 'sop2', 99999) RETURNING id"))
    
    with pytest.raises(IntegrityError):
        with session.begin_nested():
            # Force immediate check of deferred constraints
            session.execute(sa.text("SET CONSTRAINTS ALL IMMEDIATE"))

def test_ingestion_jobs_partial_unique(session):
    session.execute(sa.text("INSERT INTO dicom_ingestion_jobs (actor_id, request_idempotency_key, source_type) VALUES ('actor1', 'idem1', 'src')"))
    session.flush()
    with pytest.raises(IntegrityError):
        with session.begin_nested():
            session.execute(sa.text("INSERT INTO dicom_ingestion_jobs (actor_id, request_idempotency_key, source_type) VALUES ('actor1', 'idem1', 'src')"))

def test_duplicate_finding_idempotency_and_check(session):
    study_id = session.execute(sa.text("INSERT INTO dicom_studies (study_instance_uid) VALUES ('sd3') RETURNING id")).scalar()
    series_id = session.execute(sa.text(f"INSERT INTO dicom_series (study_id, series_instance_uid) VALUES ({study_id}, 'se3') RETURNING id")).scalar()
    instance_id = session.execute(sa.text(f"INSERT INTO dicom_instances (study_id, series_id, sop_instance_uid) VALUES ({study_id}, {series_id}, 'so3') RETURNING id")).scalar()
    job_id = session.execute(sa.text("INSERT INTO dicom_ingestion_jobs (actor_id, source_type) VALUES ('a', 's') RETURNING id")).scalar()
    item_id = session.execute(sa.text(f"INSERT INTO dicom_ingestion_items (ingestion_job_id, item_fingerprint) VALUES ({job_id}, 'fp3') RETURNING id")).scalar()
    obs_id = session.execute(sa.text(f"INSERT INTO dicom_instance_observations (instance_id, ingestion_item_id, observed_at) VALUES ({instance_id}, {item_id}, now()) RETURNING id")).scalar()
    
    with pytest.raises(IntegrityError):
        with session.begin_nested():
            session.execute(sa.text(f"INSERT INTO dicom_duplicate_findings (observation_id, duplicate_type, basis) VALUES ({obs_id}, 't', 'b')"))

    # Idempotency (NULLS NOT DISTINCT)
    session.execute(sa.text(f"INSERT INTO dicom_duplicate_findings (observation_id, duplicate_type, basis, matched_instance_id) VALUES ({obs_id}, 't', 'b', {instance_id})"))
    session.flush()
    with pytest.raises(IntegrityError):
        with session.begin_nested():
            session.execute(sa.text(f"INSERT INTO dicom_duplicate_findings (observation_id, duplicate_type, basis, matched_instance_id) VALUES ({obs_id}, 't', 'b', {instance_id})"))

def test_reference_edge_idempotency(session):
    study_id = session.execute(sa.text("INSERT INTO dicom_studies (study_instance_uid) VALUES ('sd4') RETURNING id")).scalar()
    series_id = session.execute(sa.text(f"INSERT INTO dicom_series (study_id, series_instance_uid) VALUES ({study_id}, 'se4') RETURNING id")).scalar()
    instance_id = session.execute(sa.text(f"INSERT INTO dicom_instances (study_id, series_id, sop_instance_uid) VALUES ({study_id}, {series_id}, 'so4') RETURNING id")).scalar()
    
    session.execute(sa.text(f"INSERT INTO dicom_reference_edges (from_instance_id, relationship_type, to_sop_instance_uid) VALUES ({instance_id}, 'rel', 'sop5')"))
    session.flush()
    with pytest.raises(IntegrityError):
        with session.begin_nested():
            session.execute(sa.text(f"INSERT INTO dicom_reference_edges (from_instance_id, relationship_type, to_sop_instance_uid) VALUES ({instance_id}, 'rel', 'sop5')"))

def test_series_attempt_uniqueness(session):
    job_id = session.execute(sa.text("INSERT INTO dicom_ingestion_jobs (actor_id, source_type) VALUES ('a', 's') RETURNING id")).scalar()
    session.execute(sa.text(f"INSERT INTO dicom_series_ingestion_attempts (ingestion_job_id, study_instance_uid, series_instance_uid) VALUES ({job_id}, 'sd', 'se')"))
    session.flush()
    with pytest.raises(IntegrityError):
        with session.begin_nested():
            session.execute(sa.text(f"INSERT INTO dicom_series_ingestion_attempts (ingestion_job_id, study_instance_uid, series_instance_uid) VALUES ({job_id}, 'sd', 'se')"))

def test_private_tags_cascade(session):
    study_id = session.execute(sa.text("INSERT INTO dicom_studies (study_instance_uid) VALUES ('sd6') RETURNING id")).scalar()
    series_id = session.execute(sa.text(f"INSERT INTO dicom_series (study_id, series_instance_uid) VALUES ({study_id}, 'se6') RETURNING id")).scalar()
    instance_id = session.execute(sa.text(f"INSERT INTO dicom_instances (study_id, series_id, sop_instance_uid) VALUES ({study_id}, {series_id}, 'so6') RETURNING id")).scalar()
    job_id = session.execute(sa.text("INSERT INTO dicom_ingestion_jobs (actor_id, source_type) VALUES ('a', 's') RETURNING id")).scalar()
    item_id = session.execute(sa.text(f"INSERT INTO dicom_ingestion_items (ingestion_job_id, item_fingerprint) VALUES ({job_id}, 'fp6') RETURNING id")).scalar()
    obs_id = session.execute(sa.text(f"INSERT INTO dicom_instance_observations (instance_id, ingestion_item_id, observed_at) VALUES ({instance_id}, {item_id}, now()) RETURNING id")).scalar()
    
    session.execute(sa.text(f"INSERT INTO dicom_private_tags (observation_id, private_creator, tag) VALUES ({obs_id}, 'creator', '00091001')"))
    session.flush()
    
    session.execute(sa.text(f"DELETE FROM dicom_instance_observations WHERE id = {obs_id}"))
    session.flush()
    
    res = session.execute(sa.text(f"SELECT count(*) FROM dicom_private_tags WHERE observation_id = {obs_id}")).scalar()
    assert res == 0
def test_canonical_valid_circular_insert(session):
    study_id = session.execute(sa.text("INSERT INTO dicom_studies (study_instance_uid) VALUES ('sd7') RETURNING id")).scalar()
    series_id = session.execute(sa.text(f"INSERT INTO dicom_series (study_id, series_instance_uid) VALUES ({study_id}, 'se7') RETURNING id")).scalar()
    
    # 1. Insert instance
    instance_id = session.execute(sa.text(f"INSERT INTO dicom_instances (study_id, series_id, sop_instance_uid) VALUES ({study_id}, {series_id}, 'so7') RETURNING id")).scalar()
    
    job_id = session.execute(sa.text("INSERT INTO dicom_ingestion_jobs (actor_id, source_type) VALUES ('a', 's') RETURNING id")).scalar()
    item_id = session.execute(sa.text(f"INSERT INTO dicom_ingestion_items (ingestion_job_id, item_fingerprint) VALUES ({job_id}, 'fp7') RETURNING id")).scalar()
    
    # 2. Insert observation
    obs_id = session.execute(sa.text(f"INSERT INTO dicom_instance_observations (instance_id, ingestion_item_id, observed_at) VALUES ({instance_id}, {item_id}, now()) RETURNING id")).scalar()
    
    # 3. Update canonical circular
    session.execute(sa.text(f"UPDATE dicom_instances SET current_canonical_observation_id = {obs_id} WHERE id = {instance_id}"))
    session.flush()

def test_canonical_cross_instance_rejection(session):
    study_id = session.execute(sa.text("INSERT INTO dicom_studies (study_instance_uid) VALUES ('sd8') RETURNING id")).scalar()
    series_id = session.execute(sa.text(f"INSERT INTO dicom_series (study_id, series_instance_uid) VALUES ({study_id}, 'se8') RETURNING id")).scalar()
    
    # Insert instance A and observation A
    instance_a = session.execute(sa.text(f"INSERT INTO dicom_instances (study_id, series_id, sop_instance_uid) VALUES ({study_id}, {series_id}, 'so8A') RETURNING id")).scalar()
    job_id = session.execute(sa.text("INSERT INTO dicom_ingestion_jobs (actor_id, source_type) VALUES ('a', 's') RETURNING id")).scalar()
    item_id = session.execute(sa.text(f"INSERT INTO dicom_ingestion_items (ingestion_job_id, item_fingerprint) VALUES ({job_id}, 'fp8') RETURNING id")).scalar()
    obs_a = session.execute(sa.text(f"INSERT INTO dicom_instance_observations (instance_id, ingestion_item_id, observed_at) VALUES ({instance_a}, {item_id}, now()) RETURNING id")).scalar()
    
    # Insert instance B
    instance_b = session.execute(sa.text(f"INSERT INTO dicom_instances (study_id, series_id, sop_instance_uid) VALUES ({study_id}, {series_id}, 'so8B') RETURNING id")).scalar()
    
    # Attempt to set instance B's canonical obs to obs_a (cross-instance)
    session.execute(sa.text(f"UPDATE dicom_instances SET current_canonical_observation_id = {obs_a} WHERE id = {instance_b}"))
    
    # The composite FK requires (current_canonical_observation_id, instance_id) to match
    # Since obs_a belongs to instance_a, this violates the FK.
    with pytest.raises(IntegrityError):
        with session.begin_nested():
            session.execute(sa.text("SET CONSTRAINTS ALL IMMEDIATE"))
