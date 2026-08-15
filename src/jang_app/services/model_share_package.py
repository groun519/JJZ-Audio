from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from jang_app.services.file_names import safe_display_filename_stem
from jang_app.services.rvc_model_workspace import (
    RvcModelRecord,
    RvcModelWorkspace,
    RvcModelWorkspaceError,
)


MODEL_SHARE_FORMAT = "jjzero-rvc-model"
MODEL_SHARE_VERSION = 1
MODEL_SHARE_MANIFEST = "jjzero-model.json"
MODEL_SHARE_DIRECTORY = "model"
_COPY_CHUNK_SIZE = 8 * 1024 * 1024
_MINIMUM_SPACE_BUFFER = 64 * 1024 * 1024


class ModelSharePackageError(RuntimeError):
    """Raised when a shared model package is invalid or cannot be created."""


class ModelShareStorageError(ModelSharePackageError):
    def __init__(self, required_bytes: int, available_bytes: int) -> None:
        self.required_bytes = max(0, required_bytes)
        self.available_bytes = max(0, available_bytes)
        super().__init__(
            "Not enough local space to prepare the model package "
            f"({_format_bytes(self.required_bytes)} required, "
            f"{_format_bytes(self.available_bytes)} available)."
        )


class ModelShareCancelled(ModelSharePackageError):
    """Raised when local model package creation is cancelled."""


@dataclass(frozen=True)
class ModelSharePackage:
    path: Path
    title: str
    includes_index: bool
    source_size_bytes: int


@dataclass(frozen=True)
class ImportedSharedModel:
    package_path: Path
    records: tuple[RvcModelRecord, ...]


def estimate_model_share_size_bytes(record: RvcModelRecord) -> int:
    return sum(path.stat().st_size for _, path in _model_share_artifacts(record))


def create_model_share_package(
    record: RvcModelRecord,
    output_dir: Path,
    *,
    progress: Callable[[int], None] | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> ModelSharePackage:
    artifacts = _model_share_artifacts(record)
    output_dir = output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    target = _model_share_package_path(record, output_dir)
    existing = _matching_model_share_package(record, target, artifacts)
    if existing is not None:
        if progress is not None:
            progress(100)
        return existing
    source_size = estimate_model_share_size_bytes(record)
    required = source_size + max(_MINIMUM_SPACE_BUFFER, source_size // 20)
    available = shutil.disk_usage(output_dir).free
    if available < required:
        raise ModelShareStorageError(required, available)

    temporary = target.with_suffix(f"{target.suffix}.building")
    file_entries: list[dict[str, object]] = []
    copied = 0
    try:
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_STORED) as archive:
            for artifact_name, source in artifacts:
                archive_name = f"{MODEL_SHARE_DIRECTORY}/{source.name}"
                digest = hashlib.sha256()
                with source.open("rb") as input_file, archive.open(archive_name, "w") as output_file:
                    while chunk := input_file.read(_COPY_CHUNK_SIZE):
                        if cancelled is not None and cancelled():
                            raise ModelShareCancelled("Model share packaging was cancelled.")
                        output_file.write(chunk)
                        digest.update(chunk)
                        copied += len(chunk)
                        _report(progress, copied, source_size, limit=94)
                file_entries.append(
                    {
                        "artifact": artifact_name,
                        "path": archive_name,
                        "size": source.stat().st_size,
                        "modified_ns": source.stat().st_mtime_ns,
                        "sha256": digest.hexdigest(),
                    }
                )
            manifest = {
                "format": MODEL_SHARE_FORMAT,
                "version": MODEL_SHARE_VERSION,
                "model": {
                    "name": record.name,
                    "display_name": record.display_name,
                    "tags": list(record.tags),
                    "notes": record.notes,
                    "default_pitch": record.default_pitch,
                },
                "files": file_entries,
            }
            archive.writestr(
                MODEL_SHARE_MANIFEST,
                json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8"),
            )
        os.replace(temporary, target)
    finally:
        if temporary.exists():
            temporary.unlink()
    if progress is not None:
        progress(100)
    return ModelSharePackage(
        path=target,
        title=record.title,
        includes_index=any(name == "index_file" for name, _path in artifacts),
        source_size_bytes=source_size,
    )


def find_current_model_share_package(
    record: RvcModelRecord,
    output_dir: Path,
) -> ModelSharePackage | None:
    artifacts = _model_share_artifacts(record)
    target = _model_share_package_path(record, output_dir.expanduser().resolve())
    return _matching_model_share_package(record, target, artifacts)


def _matching_model_share_package(
    record: RvcModelRecord,
    target: Path,
    artifacts: list[tuple[str, Path]],
) -> ModelSharePackage | None:
    if not _current_package_matches(target, record):
        return None
    return ModelSharePackage(
        path=target,
        title=record.title,
        includes_index=any(name == "index_file" for name, _path in artifacts),
        source_size_bytes=sum(path.stat().st_size for _, path in artifacts),
    )


def _model_share_artifacts(record: RvcModelRecord) -> list[tuple[str, Path]]:
    inference_model = record.inference_model
    if inference_model is None or not inference_model.is_file():
        raise ModelSharePackageError("This model has no inference PTH to share.")
    artifacts = [("inference_model", inference_model)]
    if record.index_file is not None and record.index_file.is_file():
        artifacts.append(("index_file", record.index_file))
    return artifacts


def _model_share_package_path(record: RvcModelRecord, output_dir: Path) -> Path:
    title = safe_display_filename_stem(record.title, "RVC Model")
    return output_dir / f"{title} - JJZero RVC.zip"


def inspect_model_share_package(package_path: Path) -> dict[str, object]:
    package_path = package_path.expanduser().resolve()
    if not package_path.is_file():
        raise ModelSharePackageError(f"Model package not found: {package_path}")
    try:
        with zipfile.ZipFile(package_path, "r") as archive:
            manifest = _read_manifest(archive)
            _validate_archive(archive, manifest)
            return manifest
    except zipfile.BadZipFile as exc:
        raise ModelSharePackageError("The shared model is not a valid ZIP package.") from exc


def _current_package_matches(package_path: Path, record: RvcModelRecord) -> bool:
    if not package_path.is_file():
        return False
    try:
        manifest = inspect_model_share_package(package_path)
    except ModelSharePackageError:
        return False
    model = manifest.get("model")
    if not isinstance(model, dict):
        return False
    expected_profile = {
        "name": record.name,
        "display_name": record.display_name,
        "tags": list(record.tags),
        "notes": record.notes,
        "default_pitch": record.default_pitch,
    }
    if model != expected_profile:
        return False
    sources = {
        "inference_model": record.inference_model,
        "index_file": record.index_file,
    }
    entries = manifest.get("files")
    if not isinstance(entries, list):
        return False
    actual_artifacts = {
        str(entry.get("artifact", "")): entry
        for entry in entries
        if isinstance(entry, dict)
    }
    expected_names = {
        name
        for name, source in sources.items()
        if source is not None and source.is_file()
    }
    if set(actual_artifacts) != expected_names:
        return False
    for artifact, source in sources.items():
        if source is None or not source.is_file():
            continue
        entry = actual_artifacts[artifact]
        try:
            if (
                int(entry.get("size", -1)) != source.stat().st_size
                or int(entry.get("modified_ns", -1)) != source.stat().st_mtime_ns
            ):
                return False
        except (TypeError, ValueError):
            return False
    return True


def import_model_share_package(
    package_path: Path,
    workspace: RvcModelWorkspace,
    *,
    progress: Callable[[int], None] | None = None,
) -> ImportedSharedModel:
    package_path = package_path.expanduser().resolve()
    workspace.root.parent.mkdir(parents=True, exist_ok=True)
    try:
        with zipfile.ZipFile(package_path, "r") as archive:
            if MODEL_SHARE_MANIFEST in archive.namelist():
                manifest = _read_manifest(archive)
                entries = _validate_archive(archive, manifest)
            else:
                manifest = {}
                entries = _legacy_archive_entries(archive)
            with tempfile.TemporaryDirectory(
                prefix="jjzero-model-import-",
                dir=workspace.root.parent,
            ) as temporary_directory:
                extraction_root = Path(temporary_directory)
                total = sum(entry["size"] for entry in entries)
                extracted = 0
                for entry in entries:
                    archive_path = str(entry["path"])
                    target_path = str(entry.get("target_path", archive_path))
                    target = extraction_root / PurePosixPath(target_path)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    digest = hashlib.sha256()
                    with archive.open(archive_path, "r") as source, target.open("wb") as output:
                        while chunk := source.read(_COPY_CHUNK_SIZE):
                            output.write(chunk)
                            digest.update(chunk)
                            extracted += len(chunk)
                            _report(progress, extracted, total, limit=48)
                    expected_digest = str(entry.get("sha256", ""))
                    if expected_digest and digest.hexdigest() != expected_digest:
                        raise ModelSharePackageError(f"Checksum mismatch: {archive_path}")
                model_folder = extraction_root / MODEL_SHARE_DIRECTORY
                records = workspace.import_folder(
                    model_folder,
                    lambda value: progress(50 + value // 2) if progress is not None else None,
                )
                if not records:
                    raise ModelSharePackageError("No RVC inference model was found in the package.")
                _apply_shared_profile(workspace, records, manifest)
                refreshed = {
                    record.model_id: record for record in workspace.records()
                }
                imported = tuple(refreshed.get(record.model_id, record) for record in records)
    except zipfile.BadZipFile as exc:
        raise ModelSharePackageError("The shared model is not a valid ZIP package.") from exc
    except RvcModelWorkspaceError as exc:
        raise ModelSharePackageError(str(exc)) from exc
    if progress is not None:
        progress(100)
    return ImportedSharedModel(package_path, imported)


def _legacy_archive_entries(archive: zipfile.ZipFile) -> list[dict[str, object]]:
    """Build a safe import plan for plain RVC ZIPs created outside JJZero Audio."""
    entries: list[dict[str, object]] = []
    target_names: set[str] = set()
    has_inference_model = False
    for info in archive.infolist():
        if info.is_dir():
            continue
        archive_path = info.filename
        if not _safe_legacy_archive_path(archive_path):
            raise ModelSharePackageError("The shared model contains an unsafe path.")
        name = PurePosixPath(archive_path).name
        suffix = Path(name).suffix.casefold()
        if suffix not in {".pth", ".index"}:
            continue
        target_key = name.casefold()
        if target_key in target_names:
            raise ModelSharePackageError(
                f"The shared model contains duplicate artifact names: {name}"
            )
        target_names.add(target_key)
        has_inference_model = has_inference_model or (
            suffix == ".pth" and not _is_training_checkpoint_name(name)
        )
        entries.append(
            {
                "artifact": "legacy_model_file",
                "path": archive_path,
                "target_path": f"{MODEL_SHARE_DIRECTORY}/{name}",
                "size": max(0, info.file_size),
                "sha256": "",
            }
        )
    if not has_inference_model:
        raise ModelSharePackageError(
            "The shared ZIP has no RVC inference PTH. Select a package containing a model .pth file."
        )
    return entries


def _read_manifest(archive: zipfile.ZipFile) -> dict[str, object]:
    try:
        raw = archive.read(MODEL_SHARE_MANIFEST)
        manifest = json.loads(raw.decode("utf-8"))
    except KeyError as exc:
        raise ModelSharePackageError("The shared model manifest is missing.") from exc
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ModelSharePackageError("The shared model manifest is invalid.") from exc
    if not isinstance(manifest, dict):
        raise ModelSharePackageError("The shared model manifest is invalid.")
    if (
        manifest.get("format") != MODEL_SHARE_FORMAT
        or manifest.get("version") != MODEL_SHARE_VERSION
    ):
        raise ModelSharePackageError("This shared model format is not supported.")
    return manifest


def _validate_archive(
    archive: zipfile.ZipFile,
    manifest: dict[str, object],
) -> list[dict[str, object]]:
    raw_files = manifest.get("files")
    if not isinstance(raw_files, list) or not raw_files:
        raise ModelSharePackageError("The shared model contains no artifacts.")
    known_names = {info.filename: info for info in archive.infolist()}
    entries: list[dict[str, object]] = []
    artifact_names: set[str] = set()
    for raw in raw_files:
        if not isinstance(raw, dict):
            raise ModelSharePackageError("The shared model file list is invalid.")
        artifact = str(raw.get("artifact", "")).strip()
        path = str(raw.get("path", "")).strip()
        sha256 = str(raw.get("sha256", "")).strip().casefold()
        try:
            size = max(0, int(raw.get("size", -1)))
        except (TypeError, ValueError) as exc:
            raise ModelSharePackageError("The shared model file size is invalid.") from exc
        if artifact not in {"inference_model", "index_file"} or artifact in artifact_names:
            raise ModelSharePackageError("The shared model artifact list is invalid.")
        if not _safe_archive_path(path):
            raise ModelSharePackageError("The shared model contains an unsafe path.")
        info = known_names.get(path)
        if info is None or info.is_dir() or info.file_size != size:
            raise ModelSharePackageError(f"The shared model artifact is missing: {path}")
        if not re_full_sha256(sha256):
            raise ModelSharePackageError("The shared model checksum is invalid.")
        artifact_names.add(artifact)
        entries.append(
            {
                "artifact": artifact,
                "path": path,
                "size": size,
                "modified_ns": raw.get("modified_ns"),
                "sha256": sha256,
            }
        )
    if "inference_model" not in artifact_names:
        raise ModelSharePackageError("The shared model has no inference PTH.")
    return entries


def _apply_shared_profile(
    workspace: RvcModelWorkspace,
    records: list[RvcModelRecord],
    manifest: dict[str, object],
) -> None:
    model = manifest.get("model")
    if not isinstance(model, dict):
        return
    display_name = str(model.get("display_name", "")).strip()
    raw_tags = model.get("tags")
    tags = (
        tuple(str(value).strip() for value in raw_tags if str(value).strip())
        if isinstance(raw_tags, list)
        else ()
    )
    notes = str(model.get("notes", "")).strip()
    try:
        pitch = int(model.get("default_pitch", 0))
    except (TypeError, ValueError):
        pitch = 0
    for record in records:
        workspace.update_profile(
            record.model_id,
            display_name=display_name,
            tags=tags,
            notes=notes,
            default_pitch=pitch,
            default_device=record.default_device,
        )


def _safe_archive_path(value: str) -> bool:
    path = PurePosixPath(value)
    return (
        bool(value)
        and not path.is_absolute()
        and ".." not in path.parts
        and path.parts[0] == MODEL_SHARE_DIRECTORY
    )


def _safe_legacy_archive_path(value: str) -> bool:
    path = PurePosixPath(value)
    return (
        bool(value)
        and "\\" not in value
        and not path.is_absolute()
        and ".." not in path.parts
        and bool(path.name)
    )


def _is_training_checkpoint_name(name: str) -> bool:
    stem = Path(name).stem
    return (
        len(stem) > 2
        and stem[0].casefold() in {"g", "d"}
        and stem[1] == "_"
        and stem[2:].isdigit()
    )


def re_full_sha256(value: str) -> bool:
    return len(value) == 64 and all(character in "0123456789abcdef" for character in value)


def _report(
    progress: Callable[[int], None] | None,
    current: int,
    total: int,
    *,
    limit: int,
) -> None:
    if progress is not None:
        progress(limit if total <= 0 else min(limit, int(current * limit / total)))


def _format_bytes(size_bytes: int) -> str:
    size = float(max(0, size_bytes))
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} {unit}"
        size /= 1024
    return ""
