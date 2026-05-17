import pytest
import sqlalchemy as sa
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from dicom_ingestion.repositories.item_repository import ItemRepository

DATABASE_URL = "postgresql://postgres:postgres@localhost:5432/dicom_test"


@pytest.fixture(scope="session")
def engine():
    return create_engine(DATABASE_URL)


@pytest.fixture(scope="function")
def session(engine):
    connection = engine.connect()
    transaction = connection.begin()
    Session = sessionmaker(bind=connection)
    sess = Session()
    yield sess
    sess.close()
    transaction.rollback()
    connection.close()


@pytest.fixture
def repo(session):
    return ItemRepository(session=session)


def _create_job(session):
    return session.execute(
        sa.text("INSERT INTO dicom_ingestion_jobs (actor_id, source_type) VALUES ('test', 'upload') RETURNING id")
    ).scalar()


def _create_item(session, job_id):
    return session.execute(
        sa.text(
            "INSERT INTO dicom_ingestion_items (ingestion_job_id, item_fingerprint) "
            "VALUES (:job_id, :fp) RETURNING id"
        ),
        {"job_id": job_id, "fp": f"fp_{job_id}"},
    ).scalar()


def _create_attempt(session, job_id):
    return session.execute(
        sa.text(
            "INSERT INTO dicom_series_ingestion_attempts (ingestion_job_id, study_instance_uid, series_instance_uid) "
            "VALUES (:job_id, 'st', 'se') RETURNING id"
        ),
        {"job_id": job_id},
    ).scalar()


# ─── Happy path ──────────────────────────────────────────────────────────────

def test_mark_as_accepted_same_job(session, repo):
    """Same job: item and attempt share ingestion_job_id → must succeed."""
    job_id = _create_job(session)
    item_id = _create_item(session, job_id)
    attempt_id = _create_attempt(session, job_id)

    repo.mark_as_accepted(item_id, attempt_id)
    session.flush()

    row = session.execute(
        sa.text("SELECT terminal_outcome, series_ingestion_attempt_id FROM dicom_ingestion_items WHERE id = :id"),
        {"id": item_id},
    ).fetchone()
    assert row.terminal_outcome == "accepted"
    assert row.series_ingestion_attempt_id == attempt_id


# ─── Guard tests ─────────────────────────────────────────────────────────────

def test_mark_as_accepted_raises_if_attempt_id_is_none(session, repo):
    job_id = _create_job(session)
    item_id = _create_item(session, job_id)
    with pytest.raises(ValueError, match="series_ingestion_attempt_id"):
        repo.mark_as_accepted(item_id, attempt_id=None)


def test_mark_as_accepted_rejects_cross_job_attempt(session, repo):
    """Cross-job binding must raise: item belongs to job A, attempt to job B."""
    job_a = _create_job(session)
    job_b = _create_job(session)
    item_id = _create_item(session, job_a)
    attempt_id = _create_attempt(session, job_b)   # different job!

    with pytest.raises(ValueError, match="different ingestion job"):
        repo.mark_as_accepted(item_id, attempt_id)


def test_mark_as_accepted_rejects_nonexistent_item(session, repo):
    """Nonexistent item_id must not silently no-op."""
    job_id = _create_job(session)
    attempt_id = _create_attempt(session, job_id)

    with pytest.raises(ValueError, match="does not exist"):
        repo.mark_as_accepted(item_id=999999999, attempt_id=attempt_id)


# ─── Rejection path ───────────────────────────────────────────────────────────

def test_mark_as_rejected_leaves_attempt_id_null(session, repo):
    job_id = _create_job(session)
    item_id = _create_item(session, job_id)

    repo.mark_as_rejected(item_id, reason="rejected_non_dicom")
    session.flush()

    row = session.execute(
        sa.text("SELECT terminal_outcome, series_ingestion_attempt_id FROM dicom_ingestion_items WHERE id = :id"),
        {"id": item_id},
    ).fetchone()
    assert row.terminal_outcome == "rejected"
    assert row.series_ingestion_attempt_id is None
