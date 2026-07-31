from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path

from jang_app.config import MODEL_WORKSPACE_DIR


CATALOG_VERSION = 1
CATALOG_FILE_NAME = "catalog.json"
MANAGED_LIBRARY_DIR_NAME = "library"
_EPOCH_WEIGHT_PATTERN = re.compile(r"^(?P<name>.+)_e(?P<epoch>\d+)_s(?P<step>\d+)$", re.IGNORECASE)
_CHECKPOINT_PATTERN = re.compile(r"^[GD]_(?P<step>\d+)\.pth$", re.IGNORECASE)


class RvcModelWorkspaceError(RuntimeError):
    """Raised when an RVC model folder cannot be inspected or imported."""


@dataclass(frozen=True)
class DiscoveredRvcModel:
    name: str
    runtime_root: Path
    source_folder: Path
    inference_model: Path | None = None
    index_file: Path | None = None
    generator_checkpoint: Path | None = None
    discriminator_checkpoint: Path | None = None

    @property
    def artifacts(self) -> tuple[Path, ...]:
        return _existing_unique_paths(
            self.inference_model,
            self.index_file,
            self.generator_checkpoint,
            self.discriminator_checkpoint,
        )

    @property
    def import_size_bytes(self) -> int:
        return sum(path.stat().st_size for path in self.artifacts)


@dataclass(frozen=True)
class RvcModelRecord:
    model_id: str
    name: str
    mode: str
    runtime_root: Path
    source_folder: Path
    inference_model: Path | None
    index_file: Path | None
    generator_checkpoint: Path | None
    discriminator_checkpoint: Path | None
    created_at: str
    display_name: str = ""
    tags: tuple[str, ...] = ()
    notes: str = ""
    default_pitch: int = 0
    default_device: str = "cuda:0"

    @property
    def title(self) -> str:
        return self.display_name or self.name

    @property
    def artifacts(self) -> tuple[Path, ...]:
        return _existing_unique_paths(
            self.inference_model,
            self.index_file,
            self.generator_checkpoint,
            self.discriminator_checkpoint,
        )

    @property
    def is_managed(self) -> bool:
        return self.mode == "managed"

    @property
    def mode_label(self) -> str:
        return "Managed Copy" if self.is_managed else "Linked"

    @property
    def runtime_ready(self) -> bool:
        return (self.runtime_root / "runtime" / "python.exe").is_file() and (self.runtime_root / "infer_cli.py").is_file()

    @property
    def checkpoint_pair_ready(self) -> bool:
        generator = self.generator_checkpoint
        discriminator = self.discriminator_checkpoint
        if generator is None or discriminator is None or not generator.is_file() or not discriminator.is_file():
            return False
        return _checkpoint_step(generator) == _checkpoint_step(discriminator)

    @property
    def can_convert(self) -> bool:
        return self.runtime_ready and self.inference_model is not None and self.inference_model.is_file()

    @property
    def can_resume(self) -> bool:
        return self.runtime_ready and self.checkpoint_pair_ready

    @property
    def has_index(self) -> bool:
        return self.index_file is not None and self.index_file.is_file()

    @property
    def has_missing_files(self) -> bool:
        configured = (
            self.inference_model,
            self.index_file,
            self.generator_checkpoint,
            self.discriminator_checkpoint,
        )
        return any(path is not None and not path.is_file() for path in configured)

    @property
    def status_key(self) -> str:
        if self.has_missing_files:
            return "missing"
        if not self.runtime_ready:
            return "runtime"
        if self.can_resume:
            return "resume"
        if self.generator_checkpoint is not None or self.discriminator_checkpoint is not None:
            return "checkpoint"
        if self.can_convert and self.has_index:
            return "indexed"
        if self.can_convert:
            return "inference"
        return "incomplete"

    @property
    def status_label(self) -> str:
        return {
            "resume": "Resume Ready",
            "indexed": "Indexed",
            "inference": "Inference Only",
            "checkpoint": "Checkpoint Incomplete",
            "runtime": "Runtime Missing",
            "missing": "Missing Files",
            "incomplete": "Incomplete",
        }[self.status_key]

    @property
    def total_size_bytes(self) -> int:
        return sum(path.stat().st_size for path in self.artifacts)

    @property
    def modified_at(self) -> datetime | None:
        timestamps = [path.stat().st_mtime for path in self.artifacts]
        return datetime.fromtimestamp(max(timestamps)) if timestamps else None

    @property
    def primary_location(self) -> Path:
        if self.is_managed:
            for path in self.artifacts:
                try:
                    path.relative_to(MODEL_WORKSPACE_DIR)
                    return path
                except ValueError:
                    continue
        return self.inference_model or self.generator_checkpoint or self.source_folder


class RvcModelWorkspace:
    def __init__(self, root: Path = MODEL_WORKSPACE_DIR) -> None:
        self.root = root.expanduser().resolve()
        self.catalog_path = self.root / CATALOG_FILE_NAME
        self.library_dir = self.root / MANAGED_LIBRARY_DIR_NAME

    def records(self) -> list[RvcModelRecord]:
        if not self.catalog_path.is_file():
            return []
        try:
            data = json.loads(self.catalog_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        if data.get("version") != CATALOG_VERSION or not isinstance(data.get("models"), list):
            return []

        records: list[RvcModelRecord] = []
        for item in data["models"]:
            try:
                records.append(self._record_from_data(item))
            except (KeyError, TypeError, ValueError):
                continue
        return sorted(records, key=lambda record: record.title.casefold())

    def inspect_folder(self, folder: Path) -> list[DiscoveredRvcModel]:
        return discover_rvc_models(folder)

    def link_folder(self, folder: Path) -> list[RvcModelRecord]:
        discovered = self.inspect_folder(folder)
        existing = {record.model_id: record for record in self.records()}
        linked: list[RvcModelRecord] = []
        for model in discovered:
            model_id = _model_id("linked", model)
            record = _record_from_discovery(model_id, "linked", model, existing.get(model_id))
            existing[model_id] = record
            linked.append(record)
        self._save_records(existing.values())
        return linked

    def import_folder(
        self,
        folder: Path,
        progress: Callable[[int], None] | None = None,
    ) -> list[RvcModelRecord]:
        discovered = self.inspect_folder(folder)
        existing = {record.model_id: record for record in self.records()}
        total_bytes = sum(model.import_size_bytes for model in discovered)
        copied_bytes = 0
        imported: list[RvcModelRecord] = []

        for model in discovered:
            model_id = _model_id("managed", model)
            model_dir = self.library_dir / model_id
            baseline_dir = model_dir / "baseline"
            targets = {
                "inference_model": _artifact_target(model.inference_model, baseline_dir / "inference"),
                "index_file": _artifact_target(model.index_file, baseline_dir / "inference"),
                "generator_checkpoint": _artifact_target(model.generator_checkpoint, baseline_dir / "checkpoints"),
                "discriminator_checkpoint": _artifact_target(model.discriminator_checkpoint, baseline_dir / "checkpoints"),
            }

            for field_name, source in _discovery_artifact_items(model):
                target = targets[field_name]
                if source is None or target is None:
                    continue

                def report(file_bytes: int, base: int = copied_bytes) -> None:
                    if progress is not None:
                        progress(_percentage(base + file_bytes, total_bytes))

                _copy_file(source, target, report)
                copied_bytes += source.stat().st_size
                if progress is not None:
                    progress(_percentage(copied_bytes, total_bytes))

            managed = DiscoveredRvcModel(
                name=model.name,
                runtime_root=model.runtime_root,
                source_folder=model.source_folder,
                inference_model=targets["inference_model"],
                index_file=targets["index_file"],
                generator_checkpoint=targets["generator_checkpoint"],
                discriminator_checkpoint=targets["discriminator_checkpoint"],
            )
            record = _record_from_discovery(model_id, "managed", managed, existing.get(model_id))
            existing[model_id] = record
            imported.append(record)

        self._save_records(existing.values())
        if progress is not None:
            progress(100)
        return imported

    def update_profile(
        self,
        model_id: str,
        *,
        display_name: str,
        tags: tuple[str, ...],
        notes: str,
        default_pitch: int,
        default_device: str,
    ) -> RvcModelRecord:
        record = self._require_record(model_id)
        normalized_tags = _normalize_tags(tags)
        device = default_device if default_device in {"cuda:0", "cpu"} else "cuda:0"
        updated = replace(
            record,
            display_name=display_name.strip()[:80],
            tags=normalized_tags,
            notes=notes.strip()[:2000],
            default_pitch=int(default_pitch),
            default_device=device,
        )
        self._replace_record(updated)
        return updated

    def replace_artifact(
        self,
        model_id: str,
        artifact_name: str,
        source: Path,
        progress: Callable[[int], None] | None = None,
    ) -> RvcModelRecord:
        record = self._require_record(model_id)
        source_path = source.expanduser().resolve()
        _validate_replacement_artifact(artifact_name, source_path)
        replacement = source_path
        if record.is_managed:
            model_dir = self.library_dir / record.model_id / "baseline"
            directory = model_dir / ("inference" if artifact_name in {"inference_model", "index_file"} else "checkpoints")
            replacement = directory / source_path.name
            source_size = source_path.stat().st_size
            _copy_file(
                source_path,
                replacement,
                lambda copied: progress(_percentage(copied, source_size)) if progress is not None else None,
            )
        updated = replace(record, **{artifact_name: replacement})
        self._replace_record(updated)
        if progress is not None:
            progress(100)
        return updated

    def replace_runtime_root(self, model_id: str, runtime_root: Path) -> RvcModelRecord:
        record = self._require_record(model_id)
        root = runtime_root.expanduser().resolve()
        if not (root / "runtime" / "python.exe").is_file() or not (root / "infer_cli.py").is_file():
            raise RvcModelWorkspaceError("The selected folder is not a usable RVC runtime.")
        updated = replace(record, runtime_root=root)
        self._replace_record(updated)
        return updated

    def _require_record(self, model_id: str) -> RvcModelRecord:
        record = next((item for item in self.records() if item.model_id == model_id), None)
        if record is None:
            raise RvcModelWorkspaceError(f"Model is not registered: {model_id}")
        return record

    def _replace_record(self, updated: RvcModelRecord) -> None:
        records = {record.model_id: record for record in self.records()}
        records[updated.model_id] = updated
        self._save_records(records.values())

    def _save_records(self, records) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        sorted_records = sorted(records, key=lambda item: item.title.casefold())
        data = {
            "version": CATALOG_VERSION,
            "models": [self._record_to_data(record) for record in sorted_records],
        }
        _write_json_atomic(self.catalog_path, data)
        for record in sorted_records:
            if record.is_managed:
                _write_model_manifest(self.library_dir / record.model_id, record)

    def _record_to_data(self, record: RvcModelRecord) -> dict[str, object]:
        return {
            "id": record.model_id,
            "name": record.name,
            "mode": record.mode,
            "runtime_root": str(record.runtime_root),
            "source_folder": str(record.source_folder),
            "inference_model": self._path_to_data(record.inference_model),
            "index_file": self._path_to_data(record.index_file),
            "generator_checkpoint": self._path_to_data(record.generator_checkpoint),
            "discriminator_checkpoint": self._path_to_data(record.discriminator_checkpoint),
            "created_at": record.created_at,
            "display_name": record.display_name,
            "tags": list(record.tags),
            "notes": record.notes,
            "default_pitch": record.default_pitch,
            "default_device": record.default_device,
        }

    def _record_from_data(self, data: dict[str, object]) -> RvcModelRecord:
        mode = str(data["mode"])
        if mode not in {"linked", "managed"}:
            raise ValueError("Unsupported model mode")
        return RvcModelRecord(
            model_id=str(data["id"]),
            name=str(data["name"]),
            mode=mode,
            runtime_root=Path(str(data["runtime_root"])).expanduser(),
            source_folder=Path(str(data["source_folder"])).expanduser(),
            inference_model=self._path_from_data(data.get("inference_model")),
            index_file=self._path_from_data(data.get("index_file")),
            generator_checkpoint=self._path_from_data(data.get("generator_checkpoint")),
            discriminator_checkpoint=self._path_from_data(data.get("discriminator_checkpoint")),
            created_at=str(data["created_at"]),
            display_name=_string_value(data.get("display_name")),
            tags=_tags_from_data(data.get("tags")),
            notes=_string_value(data.get("notes")),
            default_pitch=_int_value(data.get("default_pitch"), 0),
            default_device=_device_value(data.get("default_device")),
        )

    def _path_to_data(self, path: Path | None) -> str:
        if path is None:
            return ""
        resolved = path.expanduser().resolve()
        try:
            return f"@workspace/{resolved.relative_to(self.root).as_posix()}"
        except ValueError:
            return str(resolved)

    def _path_from_data(self, value: object) -> Path | None:
        if not isinstance(value, str) or not value:
            return None
        if value.startswith("@workspace/"):
            return self.root / Path(value.removeprefix("@workspace/"))
        return Path(value).expanduser()


def discover_rvc_models(folder: Path) -> list[DiscoveredRvcModel]:
    selected = folder.expanduser().resolve()
    if not selected.is_dir():
        raise RvcModelWorkspaceError(f"Model folder does not exist: {selected}")

    runtime_root, experiment_filter = _resolve_rvc_layout(selected)
    weights_dir = runtime_root / "weights"
    logs_dir = runtime_root / "logs"
    weight_groups = _group_inference_weights(weights_dir)
    experiment_names = set(weight_groups)
    if logs_dir.is_dir():
        experiment_names.update(path.name for path in logs_dir.iterdir() if path.is_dir())
    if experiment_filter is not None:
        experiment_names = {experiment_filter}

    models: list[DiscoveredRvcModel] = []
    for name in sorted(experiment_names, key=str.casefold):
        experiment_dir = logs_dir / name
        inference_model = _preferred_inference_weight(name, weight_groups.get(name, []))
        index_file = _preferred_index(experiment_dir)
        generator, discriminator = _latest_checkpoint_pair(experiment_dir)
        if not any((inference_model, index_file, generator, discriminator)):
            continue
        source_folder = experiment_dir if experiment_dir.is_dir() else weights_dir
        models.append(
            DiscoveredRvcModel(
                name=name,
                runtime_root=runtime_root,
                source_folder=source_folder,
                inference_model=inference_model,
                index_file=index_file,
                generator_checkpoint=generator,
                discriminator_checkpoint=discriminator,
            )
        )

    if not models:
        models = _discover_flat_model_folder(selected, runtime_root)
    if not models:
        raise RvcModelWorkspaceError("No RVC model artifacts were found in the selected folder.")
    return models


def _resolve_rvc_layout(selected: Path) -> tuple[Path, str | None]:
    if (selected / "weights").is_dir() and (selected / "logs").is_dir():
        return selected, None
    if selected.parent.name.casefold() == "logs" and (selected.parent.parent / "weights").is_dir():
        return selected.parent.parent, selected.name

    current = selected
    for _ in range(5):
        if (current / "runtime" / "python.exe").is_file() and (current / "infer_cli.py").is_file():
            return current, None
        if current.parent == current:
            break
        current = current.parent
    return selected, None


def _discover_flat_model_folder(selected: Path, runtime_root: Path) -> list[DiscoveredRvcModel]:
    weights = sorted(selected.glob("*.pth"), key=lambda path: path.name.casefold())
    grouped = _group_paths_by_model_name(weights)
    indexes = [path for path in selected.glob("*.index") if "trained" not in path.name.casefold()]
    generator, discriminator = _latest_checkpoint_pair(selected)
    models: list[DiscoveredRvcModel] = []
    for name, candidates in sorted(grouped.items(), key=lambda item: item[0].casefold()):
        models.append(
            DiscoveredRvcModel(
                name=name,
                runtime_root=runtime_root,
                source_folder=selected,
                inference_model=_preferred_inference_weight(name, candidates),
                index_file=_match_flat_index(name, indexes),
                generator_checkpoint=generator,
                discriminator_checkpoint=discriminator,
            )
        )
    return models


def _group_inference_weights(weights_dir: Path) -> dict[str, list[Path]]:
    if not weights_dir.is_dir():
        return {}
    return _group_paths_by_model_name(weights_dir.glob("*.pth"))


def _group_paths_by_model_name(paths) -> dict[str, list[Path]]:
    groups: dict[str, list[Path]] = {}
    for path in paths:
        if _CHECKPOINT_PATTERN.match(path.name):
            continue
        match = _EPOCH_WEIGHT_PATTERN.match(path.stem)
        name = match.group("name") if match else path.stem
        groups.setdefault(name, []).append(path)
    return groups


def _preferred_inference_weight(name: str, candidates: list[Path]) -> Path | None:
    if not candidates:
        return None
    exact = next((path for path in candidates if path.stem.casefold() == name.casefold()), None)
    if exact is not None:
        return exact

    def rank(path: Path) -> tuple[int, int, float]:
        match = _EPOCH_WEIGHT_PATTERN.match(path.stem)
        if match is None:
            return (0, 0, path.stat().st_mtime)
        return (int(match.group("epoch")), int(match.group("step")), path.stat().st_mtime)

    return max(candidates, key=rank)


def _preferred_index(experiment_dir: Path) -> Path | None:
    if not experiment_dir.is_dir():
        return None
    candidates = [path for path in experiment_dir.glob("*.index") if "trained" not in path.name.casefold()]
    if not candidates:
        return None
    return max(candidates, key=lambda path: ("added" in path.name.casefold(), path.stat().st_mtime))


def _match_flat_index(name: str, indexes: list[Path]) -> Path | None:
    normalized_name = _normalize_name(name)
    matching = [path for path in indexes if normalized_name in _normalize_name(path.stem)]
    candidates = matching or indexes if len(indexes) == 1 else matching
    return max(candidates, key=lambda path: path.stat().st_mtime) if candidates else None


def _latest_checkpoint_pair(folder: Path) -> tuple[Path | None, Path | None]:
    if not folder.is_dir():
        return None, None
    generators = {_checkpoint_step(path): path for path in folder.glob("G_*.pth") if _checkpoint_step(path) is not None}
    discriminators = {_checkpoint_step(path): path for path in folder.glob("D_*.pth") if _checkpoint_step(path) is not None}
    matching_steps = set(generators) & set(discriminators)
    if matching_steps:
        step = max(matching_steps)
        return generators[step], discriminators[step]
    generator = generators[max(generators)] if generators else None
    discriminator = discriminators[max(discriminators)] if discriminators else None
    return generator, discriminator


def _checkpoint_step(path: Path) -> int | None:
    match = _CHECKPOINT_PATTERN.match(path.name)
    return int(match.group("step")) if match else None


def _model_id(mode: str, model: DiscoveredRvcModel) -> str:
    identity_path = model.inference_model or model.generator_checkpoint or model.source_folder
    identity = f"{mode}|{model.runtime_root.resolve()}|{model.name.casefold()}|{identity_path.resolve()}"
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:16]
    return f"{mode}-{digest}"


def _record_from_discovery(
    model_id: str,
    mode: str,
    model: DiscoveredRvcModel,
    existing: RvcModelRecord | None,
) -> RvcModelRecord:
    created_at = existing.created_at if existing is not None else datetime.now(UTC).isoformat()
    return RvcModelRecord(
        model_id=model_id,
        name=model.name,
        mode=mode,
        runtime_root=model.runtime_root,
        source_folder=model.source_folder,
        inference_model=model.inference_model,
        index_file=model.index_file,
        generator_checkpoint=model.generator_checkpoint,
        discriminator_checkpoint=model.discriminator_checkpoint,
        created_at=created_at,
        display_name=existing.display_name if existing is not None else "",
        tags=existing.tags if existing is not None else (),
        notes=existing.notes if existing is not None else "",
        default_pitch=existing.default_pitch if existing is not None else 0,
        default_device=existing.default_device if existing is not None else "cuda:0",
    )


def _artifact_target(source: Path | None, directory: Path) -> Path | None:
    return directory / source.name if source is not None else None


def _discovery_artifact_items(model: DiscoveredRvcModel):
    return (
        ("inference_model", model.inference_model),
        ("index_file", model.index_file),
        ("generator_checkpoint", model.generator_checkpoint),
        ("discriminator_checkpoint", model.discriminator_checkpoint),
    )


def _copy_file(source: Path, target: Path, progress: Callable[[int], None]) -> None:
    source_size = source.stat().st_size
    target.parent.mkdir(parents=True, exist_ok=True)
    if source.resolve() == target.resolve():
        progress(source_size)
        return
    if (
        target.is_file()
        and target.stat().st_size == source_size
        and target.stat().st_mtime_ns == source.stat().st_mtime_ns
    ):
        progress(source_size)
        return

    temporary = target.with_suffix(f"{target.suffix}.copying")
    copied = 0
    try:
        with source.open("rb") as source_file, temporary.open("wb") as target_file:
            while chunk := source_file.read(8 * 1024 * 1024):
                target_file.write(chunk)
                copied += len(chunk)
                progress(copied)
        os.replace(temporary, target)
        shutil.copystat(source, target)
    finally:
        if temporary.exists():
            temporary.unlink()


def _write_model_manifest(model_dir: Path, record: RvcModelRecord) -> None:
    def relative(path: Path | None) -> str:
        if path is None:
            return ""
        return path.relative_to(model_dir).as_posix()

    data = {
        "version": CATALOG_VERSION,
        "id": record.model_id,
        "name": record.name,
        "mode": record.mode,
        "runtime_root": str(record.runtime_root),
        "source_folder": str(record.source_folder),
        "artifacts": {
            "inference_model": relative(record.inference_model),
            "index_file": relative(record.index_file),
            "generator_checkpoint": relative(record.generator_checkpoint),
            "discriminator_checkpoint": relative(record.discriminator_checkpoint),
        },
        "created_at": record.created_at,
        "profile": {
            "display_name": record.display_name,
            "tags": list(record.tags),
            "notes": record.notes,
            "default_pitch": record.default_pitch,
            "default_device": record.default_device,
        },
    }
    _write_json_atomic(model_dir / "manifest.json", data)


def _write_json_atomic(path: Path, data: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    temporary.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(temporary, path)


def _existing_unique_paths(*paths: Path | None) -> tuple[Path, ...]:
    existing: list[Path] = []
    seen: set[Path] = set()
    for path in paths:
        if path is None or not path.is_file():
            continue
        resolved = path.expanduser().resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        existing.append(path)
    return tuple(existing)


def _normalize_name(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.casefold())


def _normalize_tags(tags: tuple[str, ...]) -> tuple[str, ...]:
    normalized: list[str] = []
    seen: set[str] = set()
    for tag in tags:
        value = tag.strip()[:24]
        key = value.casefold()
        if not value or key in seen:
            continue
        seen.add(key)
        normalized.append(value)
        if len(normalized) == 8:
            break
    return tuple(normalized)


def _validate_replacement_artifact(artifact_name: str, path: Path) -> None:
    allowed = {
        "inference_model": ".pth",
        "index_file": ".index",
        "generator_checkpoint": ".pth",
        "discriminator_checkpoint": ".pth",
    }
    expected_suffix = allowed.get(artifact_name)
    if expected_suffix is None:
        raise RvcModelWorkspaceError(f"Unsupported model artifact: {artifact_name}")
    if not path.is_file() or path.suffix.casefold() != expected_suffix:
        raise RvcModelWorkspaceError(f"Select a valid {expected_suffix} file.")
    if artifact_name == "generator_checkpoint" and not path.name.upper().startswith("G_"):
        raise RvcModelWorkspaceError("Generator checkpoint file names must start with G_.")
    if artifact_name == "discriminator_checkpoint" and not path.name.upper().startswith("D_"):
        raise RvcModelWorkspaceError("Discriminator checkpoint file names must start with D_.")


def _string_value(value: object) -> str:
    return value if isinstance(value, str) else ""


def _tags_from_data(value: object) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return _normalize_tags(tuple(item for item in value if isinstance(item, str)))


def _int_value(value: object, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _device_value(value: object) -> str:
    return value if value in {"cuda:0", "cpu"} else "cuda:0"


def _percentage(current: int, total: int) -> int:
    if total <= 0:
        return 100
    return max(0, min(100, round(current * 100 / total)))
