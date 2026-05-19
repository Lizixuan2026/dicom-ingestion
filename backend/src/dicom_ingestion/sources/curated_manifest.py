"""Curated user ``data_manifest.json`` ingest source (Phase 2.5)."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from .base import (
    AnnotationRef,
    IngestSourceItem,
    SourceEnumerationResult,
    SourceKind,
    is_relative_to,
    normalize_relative_path,
)


class CuratedManifestError(Exception):
    """Fatal curated manifest error that should fail the ingest job."""

    def __init__(self, error_code: str, detail: str) -> None:
        super().__init__(detail)
        self.error_code = error_code
        self.detail = detail


@dataclass(frozen=True)
class _AnnotationSpec:
    path: Path
    source_relative_path: str
    task_type: str | None
    label_name: str | None
    required: bool


@dataclass(frozen=True)
class _DataFileEntry:
    path: Path
    relative_path: str
    sample_id: str
    size_bytes: int


class CuratedUploadManifestSource:
    """Enumerate data payloads from a user-curated ``data_manifest.json``.

    Annotation directories/files are attached as refs only — never emitted as
  standalone ingest items or parsed as DICOM.
    """

    def __init__(
        self,
        manifest_path: str | Path,
        *,
        allowed_roots: Iterable[str | Path],
        source_label: str = "curated_manifest",
    ) -> None:
        self.manifest_path = Path(manifest_path).expanduser().resolve()
        self.allowed_roots = [Path(root).expanduser().resolve() for root in allowed_roots]
        self._source_label = source_label

    @property
    def source_kind(self) -> str:
        return SourceKind.CURATED_MANIFEST.value

    @property
    def source_label(self) -> str:
        return self._source_label

    def enumerate(self) -> SourceEnumerationResult:
        result = SourceEnumerationResult(source_kind=self.source_kind, source_label=self.source_label)
        manifest_dir = self.manifest_path.parent
        payload = self._read_manifest_json()
        data_path = self._resolve_data_path(payload, manifest_dir)
        annotation_specs, pending_required_labels = self._resolve_annotation_specs(payload, manifest_dir, result)

        data_files = self._enumerate_data_files(data_path, manifest_dir)
        duplicate_sample_ids = self._duplicate_sample_ids(data_files)
        if duplicate_sample_ids:
            for entry in data_files:
                if entry.sample_id in duplicate_sample_ids:
                    result.errors.append(
                        {
                            "path": entry.relative_path,
                            "error_code": "DuplicateCuratedSampleId",
                            "error_detail": entry.sample_id,
                        }
                    )

        for entry in data_files:
            if entry.sample_id in duplicate_sample_ids:
                continue
            annotations, missing_required = self._match_annotations(entry.sample_id, annotation_specs, result)
            if pending_required_labels:
                missing_required = list(dict.fromkeys([*missing_required, *pending_required_labels]))
            metadata: dict[str, Any] = {
                "local_path": str(entry.path),
                "curated_sample_id": entry.sample_id,
                "manifest_path": str(self.manifest_path),
            }
            if missing_required:
                metadata["missing_required_annotations"] = missing_required
            result.items.append(
                IngestSourceItem(
                    source_kind=self.source_kind,
                    original_relative_path=entry.relative_path,
                    size_bytes=entry.size_bytes,
                    open_bytes=lambda p=entry.path: p.read_bytes(),
                    metadata=metadata,
                    annotations=annotations,
                )
            )
        return result

    def _read_manifest_json(self) -> dict[str, Any]:
        try:
            raw = self.manifest_path.read_text(encoding="utf-8")
        except OSError as exc:
            raise CuratedManifestError("CuratedManifestUnreadable", str(exc)) from exc
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise CuratedManifestError("CuratedManifestInvalidJson", str(exc)) from exc
        if not isinstance(payload, dict):
            raise CuratedManifestError("CuratedManifestInvalidJson", "manifest root must be an object")
        return payload

    def _resolve_data_path(self, payload: dict[str, Any], manifest_dir: Path) -> Path:
        data_value = payload.get("data")
        if data_value is None:
            raise CuratedManifestError("CuratedManifestMissingDataPath", "manifest missing data path")
        if isinstance(data_value, dict):
            data_value = data_value.get("path")
        if not isinstance(data_value, str) or not data_value.strip():
            raise CuratedManifestError("CuratedManifestMissingDataPath", "manifest data path is empty")
        return self._resolve_validated_path(
            data_value,
            manifest_dir,
            fatal_outside_code="CuratedManifestDataPathOutsideAllowedRoot",
            fatal_invalid_code="CuratedManifestDataPathInvalid",
            must_be_dir=True,
        )

    def _resolve_annotation_specs(
        self,
        payload: dict[str, Any],
        manifest_dir: Path,
        result: SourceEnumerationResult,
    ) -> tuple[list[_AnnotationSpec], list[str]]:
        raw_annotations = payload.get("annotation") or []
        if not isinstance(raw_annotations, list):
            result.errors.append(
                {
                    "path": str(self.manifest_path),
                    "error_code": "CuratedManifestInvalidJson",
                    "error_detail": "annotation must be a list",
                }
            )
            return [], []
        specs: list[_AnnotationSpec] = []
        pending_required_labels: list[str] = []
        for index, entry in enumerate(raw_annotations):
            if not isinstance(entry, dict):
                result.errors.append(
                    {
                        "path": str(self.manifest_path),
                        "error_code": "CuratedManifestInvalidJson",
                        "error_detail": f"annotation[{index}] must be an object",
                    }
                )
                continue
            path_value = entry.get("path")
            if not isinstance(path_value, str) or not path_value.strip():
                result.errors.append(
                    {
                        "path": str(self.manifest_path),
                        "error_code": "CuratedManifestInvalidJson",
                        "error_detail": f"annotation[{index}] missing path",
                    }
                )
                continue
            required = bool(entry.get("required", False))
            label_name = entry.get("name") or entry.get("label_name")
            if not isinstance(label_name, str):
                label_name = Path(path_value).name
            try:
                resolved = self._resolve_validated_path(
                    path_value,
                    manifest_dir,
                    fatal_outside_code="AnnotationPathOutsideAllowedRoot",
                    fatal_invalid_code="AnnotationPathInvalid",
                    must_be_dir=False,
                    fatal=False,
                )
            except CuratedManifestError as exc:
                if required:
                    pending_required_labels.append(label_name)
                result.errors.append(
                    {
                        "path": path_value,
                        "error_code": exc.error_code,
                        "error_detail": exc.detail,
                    }
                )
                continue
            if not resolved.exists():
                if required:
                    pending_required_labels.append(label_name)
                result.errors.append(
                    {
                        "path": normalize_relative_path(resolved.relative_to(manifest_dir))
                        if is_relative_to(resolved, manifest_dir)
                        else path_value,
                        "error_code": "AnnotationPathMissing",
                        "error_detail": "annotation path does not exist",
                    }
                )
                continue
            if not resolved.is_file() and not resolved.is_dir():
                result.errors.append(
                    {
                        "path": path_value,
                        "error_code": "AnnotationPathInvalid",
                        "error_detail": "annotation path is not a file or directory",
                    }
                )
                continue
            task_type = self._normalize_task_type(entry.get("task_type"))
            if not label_name:
                label_name = resolved.name
            rel = (
                normalize_relative_path(resolved.relative_to(manifest_dir))
                if is_relative_to(resolved, manifest_dir)
                else normalize_relative_path(resolved.name)
            )
            specs.append(
                _AnnotationSpec(
                    path=resolved,
                    source_relative_path=rel,
                    task_type=task_type,
                    label_name=label_name,
                    required=required,
                )
            )
        return specs, pending_required_labels

    def _resolve_validated_path(
        self,
        path_value: str,
        manifest_dir: Path,
        *,
        fatal_outside_code: str,
        fatal_invalid_code: str,
        must_be_dir: bool,
        fatal: bool = True,
    ) -> Path:
        candidate = Path(path_value).expanduser()
        resolved = (candidate if candidate.is_absolute() else manifest_dir / candidate).resolve()
        if not any(is_relative_to(resolved, root) for root in self.allowed_roots):
            raise CuratedManifestError(
                fatal_outside_code if fatal else "AnnotationPathOutsideAllowedRoot",
                f"path outside allowed roots: {resolved}",
            )
        if not resolved.exists():
            raise CuratedManifestError(
                fatal_invalid_code if fatal else "AnnotationPathMissing",
                f"path does not exist: {resolved}",
            )
        if must_be_dir and not resolved.is_dir():
            raise CuratedManifestError(fatal_invalid_code, f"path is not a directory: {resolved}")
        if not must_be_dir and not resolved.is_file() and not resolved.is_dir():
            raise CuratedManifestError(
                fatal_invalid_code if fatal else "AnnotationPathInvalid",
                f"path is not a file or directory: {resolved}",
            )
        return resolved

    def _enumerate_data_files(self, data_path: Path, manifest_dir: Path) -> list[_DataFileEntry]:
        entries: list[_DataFileEntry] = []
        for path in sorted(data_path.rglob("*")):
            if not path.is_file():
                continue
            try:
                stat = path.stat()
            except OSError:
                continue
            rel_to_data = path.relative_to(data_path)
            sample_id = self._sample_id_for_relative(rel_to_data)
            rel_to_manifest = normalize_relative_path(path.relative_to(manifest_dir))
            entries.append(
                _DataFileEntry(
                    path=path,
                    relative_path=rel_to_manifest,
                    sample_id=sample_id,
                    size_bytes=stat.st_size,
                )
            )
        return entries

    def _sample_id_for_relative(self, rel_to_data: Path) -> str:
        parts = rel_to_data.parts
        if len(parts) == 1:
            return rel_to_data.stem
        return parts[0]

    def _duplicate_sample_ids(self, entries: list[_DataFileEntry]) -> set[str]:
        by_id: dict[str, list[_DataFileEntry]] = {}
        for entry in entries:
            by_id.setdefault(entry.sample_id, []).append(entry)
        return {sample_id for sample_id, group in by_id.items() if len(group) > 1}

    def _match_annotations(
        self,
        sample_id: str,
        specs: list[_AnnotationSpec],
        result: SourceEnumerationResult,
    ) -> tuple[list[AnnotationRef], list[str]]:
        refs: list[AnnotationRef] = []
        missing_required: list[str] = []
        for spec in specs:
            match_path = self._find_annotation_match(sample_id, spec.path)
            if match_path is None:
                if spec.required:
                    missing_required.append(spec.label_name or spec.source_relative_path)
                continue
            rel_path = self._annotation_ref_relative_path(match_path, spec)
            refs.append(
                AnnotationRef(
                    source_relative_path=rel_path,
                    task_type=spec.task_type,
                    label_name=spec.label_name,
                    required=spec.required,
                    status="referenced",
                )
            )
        return refs, missing_required

    def _find_annotation_match(self, sample_id: str, annotation_root: Path) -> Path | None:
        file_candidate = annotation_root / f"{sample_id}.json"
        if file_candidate.is_file():
            return file_candidate
        dir_candidate = annotation_root / sample_id
        if dir_candidate.is_dir():
            return dir_candidate
        if dir_candidate.is_file():
            return dir_candidate
        return None

    def _annotation_ref_relative_path(self, match_path: Path, spec: _AnnotationSpec) -> str:
        manifest_dir = self.manifest_path.parent
        if is_relative_to(match_path, manifest_dir):
            return normalize_relative_path(match_path.relative_to(manifest_dir))
        return normalize_relative_path(f"{spec.source_relative_path.rstrip('/')}/{match_path.name}")

    def _normalize_task_type(self, value: Any) -> str | None:
        if value is None:
            return None
        if not isinstance(value, str):
            return None
        stripped = value.strip()
        return stripped or None
