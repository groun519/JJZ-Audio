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

from jang_app.services.model_dataset import ModelDatasetStore
from jang_app.services.rvc_model_workspace import (
    RvcModelRecord,
    RvcModelWorkspace,
    RvcModelWorkspaceError,
)


MODEL_WORK_SHARE_FORMAT = "jjzero-rvc-model-work"
MODEL_WORK_SHARE_VERSION = 1
MODEL_WORK_SHARE_MANIFEST = "jjzero-model-work.json"
MODEL_WORK_SHARE_MODEL_DIRECTORY = "model"
MODEL_WORK_SHARE_DATASET_DIRECTORY = "dataset"
_COPY_CHUNK_SIZE = 8 * 1024 * 1024
_MINIMUM_SPACE_BUFFER = 128 * 1024 * 1024


class ModelWorkSharePackageError(RuntimeError):
    """Raised when a shared model work package is invalid or cannot be created."""


class ModelWorkShareStorageError(ModelWorkSharePackageError):
    def __init__(self, required_bytes: int, available_bytes: int) -> None:
        self.required_bytes = max(0, required_bytes)
        self.available_bytes = max(0, available_bytes)
        super().__init__(
            "Not enough local space to prepare the model work package "
            f"({_format_bytes(self.required_bytes)} required, "
            f"{_format_bytes(self.available_bytes)} available)."
        )


class ModelWorkShareCancelled(ModelWorkSharePackageError):
    """Raised when local model work package creation is cancelled."""


@dataclass(frozen=True)
class ModelWorkSharePackage:
    path: Path
    title: str
    source_size_bytes: int
    training_item_count: int
    selected_item_count: int


@dataclass(frozen=True)
class ImportedSharedModelWork:
    package_path: Path
    record: RvcModelRecord


def estimate_model_work_share_size_bytes(
    workspace: RvcModelWorkspace,
    record: RvcModelRecord,
) -> int:
    if not record.is_managed:
        raise ModelWorkSharePackageError("Only managed models can share training work.")
    package_root = workspace.library_dir / record.model_id
    dataset_root = ModelDatasetStore(workspace.root).root / record.model_id
    entries = _build_package_entries(record, package_root, dataset_root)
    return sum(source.stat().st_size for _archive_path, source in entries)


def create_model_work_share_package(
    workspace: RvcModelWorkspace,
    record: RvcModelRecord,
    output_dir: Path,
    *,
    progress: Callable[[int], None] | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> ModelWorkSharePackage:
    if not record.is_managed:
        raise ModelWorkSharePackageError("Only managed models can share training work.")
    package_root = workspace.library_dir / record.model_id
    dataset_root = ModelDatasetStore(workspace.root).root / record.model_id
    if not package_root.is_dir():
        raise ModelWorkSharePackageError("Managed model package is missing.")
    if not dataset_root.is_dir():
        raise ModelWorkSharePackageError("This model has no saved training work to share.")

    dataset = ModelDatasetStore(workspace.root).load(record.model_id)
    output_dir = output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    target = _model_work_share_package_path(record, output_dir)
    entries = _build_package_entries(record, package_root, dataset_root)
    existing = _matching_model_work_share_package(target, record, entries, dataset)
    if existing is not None:
        if progress is not None:
            progress(100)
        return existing

    source_size = estimate_model_work_share_size_bytes(workspace, record)
    required = source_size + max(_MINIMUM_SPACE_BUFFER, source_size // 20)
    available = shutil.disk_usage(output_dir).free
    if available < required:
        raise ModelWorkShareStorageError(required, available)

    temporary = target.with_suffix(f"{target.suffix}.building")
    manifest_entries: list[dict[str, object]] = []
    copied = 0
    try:
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_STORED) as archive:
            for archive_name, source in entries:
                digest = hashlib.sha256()
                with source.open("rb") as input_file, archive.open(archive_name, "w") as output_file:
                    while chunk := input_file.read(_COPY_CHUNK_SIZE):
                        if cancelled is not None and cancelled():
                            raise ModelWorkShareCancelled("Model work share packaging was cancelled.")
                        output_file.write(chunk)
                        digest.update(chunk)
                        copied += len(chunk)
                        _report(progress, copied, source_size, limit=94)
                stat = source.stat()
                manifest_entries.append(
                    {
                        "path": archive_name,
                        "size": stat.st_size,
                        "modified_ns": stat.st_mtime_ns,
                        "sha256": digest.hexdigest(),
                    }
                )
            manifest = {
                "format": MODEL_WORK_SHARE_FORMAT,
                "version": MODEL_WORK_SHARE_VERSION,
                "model": _profile_payload(record),
                "runtime_root": str(record.runtime_root),
                "package_root": MODEL_WORK_SHARE_MODEL_DIRECTORY,
                "dataset_root": MODEL_WORK_SHARE_DATASET_DIRECTORY,
                "files": manifest_entries,
                "summary": {
                    "training_items": len(dataset.training_items),
                    "selected_items": len(dataset.training_items),
                    "source_items": len(dataset.source_items),
                },
            }
            archive.writestr(
                MODEL_WORK_SHARE_MANIFEST,
                json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8"),
            )
        os.replace(temporary, target)
    finally:
        if temporary.exists():
            temporary.unlink()
    if progress is not None:
        progress(100)
    return ModelWorkSharePackage(
        path=target,
        title=record.title,
        source_size_bytes=source_size,
        training_item_count=len(dataset.items),
        selected_item_count=len(dataset.training_items),
    )


def find_current_model_work_share_package(
    workspace: RvcModelWorkspace,
    record: RvcModelRecord,
    output_dir: Path,
) -> ModelWorkSharePackage | None:
    if not record.is_managed:
        return None
    package_root = workspace.library_dir / record.model_id
    dataset_root = ModelDatasetStore(workspace.root).root / record.model_id
    if not package_root.is_dir() or not dataset_root.is_dir():
        return None
    dataset = ModelDatasetStore(workspace.root).load(record.model_id)
    entries = _build_package_entries(record, package_root, dataset_root)
    output_dir = output_dir.expanduser().resolve()
    target = _model_work_share_package_path(record, output_dir)
    return _matching_model_work_share_package(target, record, entries, dataset)


def inspect_model_work_share_package(package_path: Path) -> dict[str, object]:
    package_path = package_path.expanduser().resolve()
    if not package_path.is_file():
        raise ModelWorkSharePackageError(f"Model work package not found: {package_path}")
    try:
        with zipfile.ZipFile(package_path, "r") as archive:
            manifest = _read_manifest(archive)
            _validate_archive(archive, manifest)
            return manifest
    except zipfile.BadZipFile as exc:
        raise ModelWorkSharePackageError(
            "The shared model work is not a valid ZIP package."
        ) from exc


def import_model_work_share_package(
    package_path: Path,
    workspace: RvcModelWorkspace,
    *,
    progress: Callable[[int], None] | None = None,
) -> ImportedSharedModelWork:
    package_path = package_path.expanduser().resolve()
    workspace.root.parent.mkdir(parents=True, exist_ok=True)
    try:
        with zipfile.ZipFile(package_path, "r") as archive:
            manifest = _read_manifest(archive)
            entries = _validate_archive(archive, manifest)
            model_payload = manifest.get("model")
            if not isinstance(model_payload, dict):
                raise ModelWorkSharePackageError("The shared model work manifest is invalid.")
            model_id = str(model_payload.get("id", "")).strip()
            model_name = str(model_payload.get("name", "")).strip()
            if not model_id or not model_name:
                raise ModelWorkSharePackageError("The shared model work manifest is missing model identity.")
            with tempfile.TemporaryDirectory(
                prefix="jjzero-model-work-import-",
                dir=workspace.root.parent,
            ) as temporary_directory:
                extraction_root = Path(temporary_directory)
                total = sum(entry["size"] for entry in entries)
                extracted = 0
                for entry in entries:
                    archive_path = str(entry["path"])
                    target = extraction_root / PurePosixPath(archive_path)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    digest = hashlib.sha256()
                    with archive.open(archive_path, "r") as source, target.open("wb") as output:
                        while chunk := source.read(_COPY_CHUNK_SIZE):
                            output.write(chunk)
                            digest.update(chunk)
                            extracted += len(chunk)
                            _report(progress, extracted, total, limit=45)
                    if digest.hexdigest() != entry["sha256"]:
                        raise ModelWorkSharePackageError(f"Checksum mismatch: {archive_path}")

                imported_record = _install_imported_package(
                    workspace,
                    extraction_root / MODEL_WORK_SHARE_MODEL_DIRECTORY,
                    extraction_root / MODEL_WORK_SHARE_DATASET_DIRECTORY,
                    model_payload,
                    runtime_root=str(manifest.get("runtime_root", "")),
                )
    except zipfile.BadZipFile as exc:
        raise ModelWorkSharePackageError(
            "The shared model work is not a valid ZIP package."
        ) from exc
    except RvcModelWorkspaceError as exc:
        raise ModelWorkSharePackageError(str(exc)) from exc
    if progress is not None:
        progress(100)
    return ImportedSharedModelWork(package_path, imported_record)


def _build_package_entries(
    record: RvcModelRecord,
    package_root: Path,
    dataset_root: Path,
) -> tuple[tuple[str, Path], ...]:
    entries: list[tuple[str, Path]] = []
    for source in sorted(package_root.rglob("*")):
        if source.is_file():
            entries.append(
                (
                    f"{MODEL_WORK_SHARE_MODEL_DIRECTORY}/{source.relative_to(package_root).as_posix()}",
                    source.resolve(),
                )
            )
    for source in sorted(dataset_root.rglob("*")):
        if source.is_file():
            entries.append(
                (
                    f"{MODEL_WORK_SHARE_DATASET_DIRECTORY}/{source.relative_to(dataset_root).as_posix()}",
                    source.resolve(),
                )
            )
    if not entries:
        raise ModelWorkSharePackageError("There are no files to include in the model work package.")
    return tuple(entries)


def _matching_model_work_share_package(
    package_path: Path,
    record: RvcModelRecord,
    entries: tuple[tuple[str, Path], ...],
    dataset,
) -> ModelWorkSharePackage | None:
    if not _current_package_matches(package_path, record, entries):
        return None
    return ModelWorkSharePackage(
        path=package_path,
        title=record.title,
        source_size_bytes=sum(path.stat().st_size for _archive_name, path in entries),
        training_item_count=len(dataset.items),
        selected_item_count=len(dataset.training_items),
    )


def _current_package_matches(
    package_path: Path,
    record: RvcModelRecord,
    entries: tuple[tuple[str, Path], ...],
) -> bool:
    if not package_path.is_file():
        return False
    try:
        manifest = inspect_model_work_share_package(package_path)
    except ModelWorkSharePackageError:
        return False
    model = manifest.get("model")
    if model != _profile_payload(record):
        return False
    raw_files = manifest.get("files")
    if not isinstance(raw_files, list):
        return False
    by_path = {
        str(item.get("path", "")): item
        for item in raw_files
        if isinstance(item, dict)
    }
    expected_names = {archive_path for archive_path, _source in entries}
    if set(by_path) != expected_names:
        return False
    for archive_path, source in entries:
        entry = by_path[archive_path]
        try:
            stat = source.stat()
            if (
                int(entry.get("size", -1)) != stat.st_size
                or int(entry.get("modified_ns", -1)) != stat.st_mtime_ns
            ):
                return False
        except (OSError, TypeError, ValueError):
            return False
    return True


def _model_work_share_package_path(record: RvcModelRecord, output_dir: Path) -> Path:
    from jang_app.services.file_names import safe_display_filename_stem

    title = safe_display_filename_stem(record.title, "RVC Model Work")
    return output_dir / f"{title} - JJZero Model Work.zip"


def _read_manifest(archive: zipfile.ZipFile) -> dict[str, object]:
    try:
        raw = archive.read(MODEL_WORK_SHARE_MANIFEST)
        manifest = json.loads(raw.decode("utf-8"))
    except KeyError as exc:
        raise ModelWorkSharePackageError("The shared model work manifest is missing.") from exc
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ModelWorkSharePackageError("The shared model work manifest is invalid.") from exc
    if not isinstance(manifest, dict):
        raise ModelWorkSharePackageError("The shared model work manifest is invalid.")
    if (
        manifest.get("format") != MODEL_WORK_SHARE_FORMAT
        or manifest.get("version") != MODEL_WORK_SHARE_VERSION
    ):
        raise ModelWorkSharePackageError("This shared model work format is not supported.")
    return manifest


def _validate_archive(
    archive: zipfile.ZipFile,
    manifest: dict[str, object],
) -> list[dict[str, object]]:
    raw_files = manifest.get("files")
    if not isinstance(raw_files, list) or not raw_files:
        raise ModelWorkSharePackageError("The shared model work contains no files.")
    archive_names = set(archive.namelist())
    validated: list[dict[str, object]] = []
    for raw_entry in raw_files:
        if not isinstance(raw_entry, dict):
            raise ModelWorkSharePackageError("The shared model work manifest is invalid.")
        archive_path = str(raw_entry.get("path", ""))
        if not archive_path:
            raise ModelWorkSharePackageError("The shared model work manifest is invalid.")
        normalized = PurePosixPath(archive_path)
        if normalized.is_absolute() or ".." in normalized.parts:
            raise ModelWorkSharePackageError("The shared model work contains an unsafe path.")
        if archive_path not in archive_names:
            raise ModelWorkSharePackageError(
                f"The shared model work is missing '{archive_path}'."
            )
        validated.append(
            {
                "path": archive_path,
                "size": int(raw_entry.get("size", 0)),
                "modified_ns": int(raw_entry.get("modified_ns", 0)),
                "sha256": str(raw_entry.get("sha256", "")),
            }
        )
    return validated


def _install_imported_package(
    workspace: RvcModelWorkspace,
    package_root: Path,
    dataset_root: Path,
    model_payload: dict[str, object],
    *,
    runtime_root: str,
) -> RvcModelRecord:
    model_id = str(model_payload["id"]).strip()
    model_name = str(model_payload["name"]).strip()
    target_model_dir = workspace.library_dir / model_id
    if target_model_dir.exists():
        raise ModelWorkSharePackageError(
            f"A model with this work package already exists: {model_name}"
        )
    target_dataset_dir = ModelDatasetStore(workspace.root).root / model_id
    target_model_dir.parent.mkdir(parents=True, exist_ok=True)
    target_dataset_dir.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(package_root, target_model_dir)
    try:
        shutil.copytree(dataset_root, target_dataset_dir)
    except Exception:
        shutil.rmtree(target_model_dir, ignore_errors=True)
        raise
    try:
        record = _register_imported_record(
            workspace,
            target_model_dir,
            model_payload,
            runtime_root=runtime_root,
        )
        ModelDatasetStore(workspace.root).load(model_id)
        return record
    except Exception:
        shutil.rmtree(target_model_dir, ignore_errors=True)
        shutil.rmtree(target_dataset_dir, ignore_errors=True)
        raise


def _register_imported_record(
    workspace: RvcModelWorkspace,
    model_dir: Path,
    model_payload: dict[str, object],
    *,
    runtime_root: str,
) -> RvcModelRecord:
    model_id = str(model_payload["id"]).strip()
    model_name = str(model_payload["name"]).strip()
    created_at = str(model_payload.get("created_at", "")).strip()
    display_name = str(model_payload.get("display_name", "")).strip()
    tags = tuple(str(value) for value in model_payload.get("tags", ()) if str(value).strip())
    notes = str(model_payload.get("notes", ""))
    default_pitch = int(model_payload.get("default_pitch", 0))
    default_device = str(model_payload.get("default_device", "auto"))
    mode = str(model_payload.get("mode", "managed"))
    runtime = Path(runtime_root).expanduser() if runtime_root else model_dir / "rvc"
    manifest_path = model_dir / "model.json"
    inferred_name = _infer_rvc_name(manifest_path, model_name)
    package_root = model_dir / "rvc"
    experiment_dir = package_root / "logs" / inferred_name
    weights_dir = package_root / "weights"
    inference_model = _first_existing_file(weights_dir, "*.pth")
    index_file = _first_existing_file(experiment_dir, "*.index")
    generator_checkpoint = _first_existing_file(experiment_dir, "G_*.pth")
    discriminator_checkpoint = _first_existing_file(experiment_dir, "D_*.pth")
    return workspace.register_imported_managed_record(
        model_id=model_id,
        name=model_name,
        runtime_root=runtime,
        created_at=created_at,
        display_name=display_name,
        tags=tags,
        notes=notes,
        default_pitch=default_pitch,
        default_device=default_device,
        mode=mode if mode in {"managed", "created"} else "managed",
        inference_model=inference_model,
        index_file=index_file,
        generator_checkpoint=generator_checkpoint,
        discriminator_checkpoint=discriminator_checkpoint,
    )


def _infer_rvc_name(manifest_path: Path, fallback: str) -> str:
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return fallback
    return str(data.get("rvc_name") or data.get("name") or fallback).strip() or fallback


def _first_existing_file(root: Path, pattern: str) -> Path | None:
    if not root.is_dir():
        return None
    return next((path.resolve() for path in sorted(root.glob(pattern)) if path.is_file()), None)


def _profile_payload(record: RvcModelRecord) -> dict[str, object]:
    return {
        "id": record.model_id,
        "name": record.name,
        "display_name": record.display_name,
        "tags": list(record.tags),
        "notes": record.notes,
        "default_pitch": record.default_pitch,
        "default_device": record.default_device,
        "mode": record.mode,
        "created_at": record.created_at,
    }


def _report(
    progress: Callable[[int], None] | None,
    copied: int,
    total: int,
    *,
    limit: int = 100,
) -> None:
    if progress is None:
        return
    if total <= 0:
        progress(limit)
        return
    progress(max(0, min(limit, int(copied * limit / total))))


def _format_bytes(value: int) -> str:
    if value >= 1024**3:
        return f"{value / 1024**3:.1f} GB"
    if value >= 1024**2:
        return f"{value / 1024**2:.0f} MB"
    if value >= 1024:
        return f"{value / 1024:.0f} KB"
    return f"{value} B"
