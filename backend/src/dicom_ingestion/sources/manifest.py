"""Manifest ingest source."""
from __future__ import annotations

from pathlib import Path
from typing import Iterable, Mapping, Any

from .base import IngestSourceItem, SourceEnumerationResult, SourceKind, is_relative_to


class ManifestSource:
    """Enumerate explicitly listed local files under configured roots."""

    def __init__(
        self,
        entries: Iterable[str | Path | Mapping[str, Any]],
        *,
        allowed_roots: Iterable[str | Path],
        source_label: str = "manifest",
    ) -> None:
        self.entries = list(entries)
        self.allowed_roots = [Path(root).expanduser().resolve() for root in allowed_roots]
        self._source_label = source_label

    @property
    def source_kind(self) -> str:
        return SourceKind.MANIFEST.value

    @property
    def source_label(self) -> str:
        return self._source_label

    def enumerate(self) -> SourceEnumerationResult:
        result = SourceEnumerationResult(source_kind=self.source_kind, source_label=self.source_label)
        for entry in self.entries:
            path_value = entry.get("path") if isinstance(entry, Mapping) else entry
            path = Path(path_value).expanduser().resolve()
            root = next((allowed for allowed in self.allowed_roots if is_relative_to(path, allowed)), None)
            if root is None:
                result.errors.append({"path": str(path), "error_code": "ManifestPathOutsideAllowedRoot", "error_detail": "outside allowed roots"})
                continue
            if not path.exists() or not path.is_file():
                result.errors.append({"path": str(path), "error_code": "ManifestFileNotFound", "error_detail": "not a file"})
                continue
            try:
                stat = path.stat()
                rel_path = path.relative_to(root).as_posix()
                result.items.append(
                    IngestSourceItem(
                        source_kind=self.source_kind,
                        original_relative_path=rel_path,
                        size_bytes=stat.st_size,
                        open_bytes=lambda p=path: p.read_bytes(),
                        metadata={"local_path": str(path), "manifest_path": str(path)},
                    )
                )
            except OSError as exc:
                result.errors.append({"path": str(path), "error_code": "SourceFileUnreadable", "error_detail": str(exc)})
        return result
