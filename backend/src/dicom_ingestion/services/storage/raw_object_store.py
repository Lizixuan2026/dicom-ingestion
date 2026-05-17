import os
import hashlib
import tempfile
from typing import Optional

class RawObjectStore:
    """
    Foundational interface for persisting raw bytes.
    Currently uses a local temp-dir adapter as the backend.
    """
    def __init__(self, base_dir: str):
        self.base_dir = base_dir
        os.makedirs(self.base_dir, exist_ok=True)

    def put(self, data: bytes, content_hash: str) -> dict:
        """
        Idempotent put operation.
        Returns the URI pointing to the stored bytes.
        """
        # Security: Prevent path traversal
        if not content_hash or not content_hash.isalnum():
            raise ValueError(f"Invalid content_hash format: {content_hash}")

        # Security: Verify hash
        actual_hash = hashlib.sha256(data).hexdigest()
        if actual_hash != content_hash:
            raise ValueError(f"Hash mismatch. Expected {content_hash}, got {actual_hash}")

        uri = os.path.join(self.base_dir, content_hash)
        if not os.path.exists(uri):
            # Atomic write to prevent partial reads
            fd, temp_path = tempfile.mkstemp(dir=self.base_dir)
            with os.fdopen(fd, 'wb') as f:
                f.write(data)
            os.rename(temp_path, uri)

        return {"uri": uri}

    def get(self, uri: str) -> Optional[bytes]:
        """
        Retrieves the exact bytes stored at the URI.
        """
        # Security: Ensure uri doesn't traverse out of base_dir
        if not os.path.normpath(uri).startswith(os.path.normpath(self.base_dir)):
            raise ValueError(f"URI is outside the bounds of base_dir: {uri}")

        if not os.path.exists(uri):
            return None
        with open(uri, "rb") as f:
            return f.read()

    def exists(self, uri: str) -> bool:
        """
        Checks if the given URI exists in the store.
        """
        return os.path.exists(uri)

    def delete(self, uri: str) -> None:
        """
        Deletes the file at the given URI. 
        Only intended for test cleanup and temp GC.
        """
        if os.path.exists(uri):
            os.remove(uri)
