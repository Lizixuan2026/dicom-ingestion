"""Local folder ingest source."""
from __future__ import annotations

from pathlib import Path
from typing import Iterable, Optional

from .base import (
    IngestSourceItem,
    SourceEnumerationResult,
    SourceKind,
    is_relative_to,
    normalize_relative_path,
)


class LocalFolderSource:
    """Enumerate files under a configured local/NAS folder root."""

    def __init__(
        self,
        root_path: str | Path,
        *,
        recursive: bool = True,
        allowed_roots: Optional[Iterable[str | Path]] = None,
        max_items: Optional[int] = None,
        max_file_bytes: Optional[int] = None,
    ) -> None:
        self.root_path = Path(root_path).expanduser().resolve()
        self.recursive = recursive
        self.max_items = max_items
        self.max_file_bytes = max_file_bytes
        self.allowed_roots = [Path(root).expanduser().resolve() for root in (allowed_roots or [self.root_path])]

    @property
    def source_kind(self) -> str:
        return SourceKind.LOCAL_FOLDER.value

    @property
    def source_label(self) -> str:
        return self.root_path.name or str(self.root_path)

    def validate(self) -> None:
        if not self.root_path.exists():
            raise FileNotFoundError(f"Local folder source does not exist: {self.root_path}")
        if not self.root_path.is_dir():
            raise NotADirectoryError(f"Local folder source is not a directory: {self.root_path}")
        if not any(is_relative_to(self.root_path, root) for root in self.allowed_roots):
            raise ValueError(f"Local folder source is outside allowed roots: {self.root_path}")

    def enumerate(self) -> SourceEnumerationResult:
        self.validate()
        result = SourceEnumerationResult(source_kind=self.source_kind, source_label=self.source_label)
        iterator = self.root_path.rglob("*") if self.recursive else self.root_path.glob("*")

        for path in sorted(iterator):
            try:
                if path.is_dir():
                    continue
            except OSError as exc:
                result.errors.append({"path": str(path), "error_code": "SourceFileUnreadable", "error_detail": str(exc)})
                continue
            if self.max_items is not None and len(result.items) >= self.max_items:
                result.errors.append({"path": "", "error_code": "MaxItemsExceeded", "error_detail": str(self.max_items)})
                break

            try:
                stat = path.stat()
                if self.max_file_bytes is not None and stat.st_size > self.max_file_bytes:
                    result.errors.append({
                        "path": normalize_relative_path(path.relative_to(self.root_path)),
                        "error_code": "FileTooLarge",
                        "error_detail": str(stat.st_size),
                    })
                    continue
                rel_path = normalize_relative_path(path.relative_to(self.root_path))
                result.items.append(
                    IngestSourceItem(
                        source_kind=self.source_kind,
                        original_relative_path=rel_path,
                        size_bytes=stat.st_size,
                        open_bytes=lambda p=path: p.read_bytes(),
                        metadata={"local_path": str(path), "mtime": str(stat.st_mtime)},
                    )
                )
            except OSError as exc:
                rel_path = normalize_relative_path(path.relative_to(self.root_path)) if path.exists() else str(path)
                result.errors.append({"path": rel_path, "error_code": "SourceFileUnreadable", "error_detail": str(exc)})

        return result
