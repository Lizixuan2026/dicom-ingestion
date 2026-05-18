import pytest
import sqlalchemy as sa
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import sessionmaker
from dicom_ingestion.repositories.item_repository import ItemRepository
import os

DATABASE_URL = os.environ.get(
    "DICOM_TEST_DATABASE_URL",
    "postgresql://postgres:postgres@localhost:5532/dicom_test"
)

def is_postgres_available():
    try:
        engine = create_engine(DATABASE_URL)
        connection = engine.connect()
        connection.close()
        return True
    except OperationalError:
        return False

POSTGRES_AVAILABLE = is_postgres_available()
pytestmark = pytest.mark.skipif(not POSTGRES_AVAILABLE, reason="PostgreSQL not available")

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

@pytest.fixture
def repo(session):
    return ItemRepository(session=session)

def test_mark_as_accepted_same_job(repo, session):
    job_id = session.execute(sa.text("INSERT INTO dicom_ingestion_jobs (actor_id, source_type) VALUES ('test', 'upload') RETURNING id")).scalar()
    attempt_id = session.execute(sa.text(f"INSERT INTO dicom_series_ingestion_attempts (ingestion_job_id, study_instance_uid, series_instance_uid) VALUES ({job_id}, '1.2.3', '1.2.4') RETURNING id")).scalar()
    item_id = session.execute(sa.text(f"INSERT INTO dicom_ingestion_items (ingestion_job_id, item_fingerprint) VALUES ({job_id}, 'fp') RETURNING id")).scalar()
    repo.mark_as_accepted(item_id, attempt_id)
    result = session.execute(sa.text(f"SELECT terminal_outcome FROM dicom_ingestion_items WHERE id = {item_id}")).fetchone()
    assert result.terminal_outcome == 'accepted'

def test_mark_as_rejected_leaves_attempt_id_null(repo, session):
    job_id = session.execute(sa.text("INSERT INTO dicom_ingestion_jobs (actor_id, source_type) VALUES ('test', 'upload') RETURNING id")).scalar()
    item_id = session.execute(sa.text(f"INSERT INTO dicom_ingestion_items (ingestion_job_id, item_fingerprint) VALUES ({job_id}, 'fp2') RETURNING id")).scalar()
    repo.mark_as_rejected(item_id, "Not DICOM")
    result = session.execute(sa.text(f"SELECT terminal_outcome, series_ingestion_attempt_id FROM dicom_ingestion_items WHERE id = {item_id}")).fetchone()
    assert result.terminal_outcome == 'rejected'
    assert result.series_ingestion_attempt_id is None
