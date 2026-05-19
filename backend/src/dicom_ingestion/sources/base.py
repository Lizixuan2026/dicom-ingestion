"""Ingest source abstractions for Batch 7 pipeline core.

These classes describe source files before they enter parser/storage work.
They intentionally avoid REST, UI, and external queue concerns.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Iterable, Optional


class SourceKind(str, Enum):
    """Supported source kinds for pipeline input."""

    LOCAL_FOLDER = "local_folder"
    MANIFEST = "manifest"
    ZIP = "zip"


@dataclass(frozen=True)
class IngestSourceItem:
    """A single file-like item discovered from an ingest source."""

    source_kind: str
    original_relative_path: str
    size_bytes: int
    open_bytes: Callable[[], bytes]
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def local_path(self) -> Optional[Path]:
        """Return the local path when the source item maps to one."""
        value = self.metadata.get("local_path")
        return Path(value) if value else None


@dataclass
class SourceEnumerationResult:
    """Result of enumerating a source."""

    source_kind: str
    source_label: str
    items: list[IngestSourceItem] = field(default_factory=list)
    errors: list[dict[str, str]] = field(default_factory=list)

    @property
    def total_items(self) -> int:
        return len(self.items)

    @property
    def total_bytes(self) -> int:
        return sum(item.size_bytes for item in self.items)


def is_relative_to(path: Path, root: Path) -> bool:
    """py3.8-compatible Path.is_relative_to."""
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def normalize_relative_path(path: Path) -> str:
    """Return a stable POSIX-style relative path."""
    return path.as_posix()
