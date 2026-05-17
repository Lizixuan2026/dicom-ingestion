import pytest
import tempfile
import hashlib
from dicom_ingestion.services.storage.raw_object_store import RawObjectStore

@pytest.fixture
def store():
    # Use a local temp-dir adapter for tests
    with tempfile.TemporaryDirectory() as temp_dir:
        yield RawObjectStore(base_dir=temp_dir)

def test_put_is_idempotent(store):
    data = b"test_data"
    content_hash = hashlib.sha256(data).hexdigest()
    
    result1 = store.put(data, content_hash=content_hash)
    result2 = store.put(data, content_hash=content_hash)
    
    assert result1["uri"] == result2["uri"]
    assert store.exists(result1["uri"])

def test_put_fails_on_hash_mismatch(store):
    data = b"test_data"
    bad_hash = hashlib.sha256(b"wrong").hexdigest()
    with pytest.raises(ValueError, match="Hash mismatch"):
        store.put(data, content_hash=bad_hash)

def test_put_fails_on_path_traversal(store):
    data = b"test_data"
    with pytest.raises(ValueError, match="Invalid content_hash format"):
        store.put(data, content_hash="../badhash")

def test_put_then_get_returns_identical_bytes(store):
    data = b"hello_dicom"
    content_hash = hashlib.sha256(data).hexdigest()
    
    result = store.put(data, content_hash=content_hash)
    retrieved = store.get(result["uri"])
    
    assert retrieved == data

def test_get_fails_on_path_traversal(store):
    with pytest.raises(ValueError, match="outside the bounds"):
        store.get("/etc/passwd")

def test_exists_returns_false_for_unknown_uri(store):
    assert not store.exists(store.base_dir + "/nonexistent")

def test_delete_removes_file(store):
    data = b"to_delete"
    content_hash = hashlib.sha256(data).hexdigest()
    
    result = store.put(data, content_hash=content_hash)
    assert store.exists(result["uri"])
    
    store.delete(result["uri"])
    assert not store.exists(result["uri"])
