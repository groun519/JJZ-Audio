from __future__ import annotations

import hashlib
import json
import re
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path

from jang_app.config import MODEL_WORKSPACE_DIR
from jang_app.services.managed_files import write_json_atomic
from jang_app.services.rvc_model_package import (
    RvcModelPackageLayout,
    build_rvc_package_plan,
    copy_rvc_package_files,
    create_rvc_package_directories,
    packaged_target,
    relative_package_path,
)
from jang_app.services.settings import RVC_DEVICE_AUTO, normalize_rvc_device


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
    default_device: str = RVC_DEVICE_AUTO

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
        return self.mode in {"managed", "created"}

    @property
    def mode_label(self) -> str:
        if self.mode == "created":
            return "New Model"
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
        return self.inference_model is not None and self.inference_model.is_file()

    @property
    def can_resume(self) -> bool:
        return self.checkpoint_pair_ready

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
            package_root = _managed_rvc_root(self.source_folder)
            if package_root is not None:
                return package_root
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
        did_migrate = False
        for item in data["models"]:
            try:
                record = self._record_from_data(item)
                if record.is_managed:
                    record, migrated = self._ensure_managed_package(record)
                    did_migrate = did_migrate or migrated
                records.append(record)
            except (KeyError, TypeError, ValueError):
                continue
        if did_migrate:
            self._write_catalog(records)
        return sorted(records, key=lambda record: record.title.casefold())

    def inspect_folder(self, folder: Path) -> list[DiscoveredRvcModel]:
        return discover_rvc_models(folder)

    def inspect_inference_file(self, model_file: Path) -> DiscoveredRvcModel:
        return discover_rvc_inference_file(model_file)

    def create_model(self, name: str, runtime_root: Path) -> RvcModelRecord:
        model_name = " ".join(name.split())[:80]
        if not model_name:
            raise RvcModelWorkspaceError("Model name is required.")
        existing = {record.model_id: record for record in self.records()}
        if any(record.title.casefold() == model_name.casefold() for record in existing.values()):
            raise RvcModelWorkspaceError(f'A model named "{model_name}" already exists.')

        model_id = _new_model_id(model_name)
        model_dir = self.library_dir / model_id
        model_dir.mkdir(parents=True, exist_ok=False)
        package = RvcModelPackageLayout(model_dir, model_name)
        package.create()
        record = RvcModelRecord(
            model_id=model_id,
            name=model_name,
            mode="created",
            runtime_root=runtime_root.expanduser().resolve(),
            source_folder=package.experiment_dir,
            inference_model=None,
            index_file=None,
            generator_checkpoint=None,
            discriminator_checkpoint=None,
            created_at=datetime.now(UTC).isoformat(),
        )
        existing[model_id] = record
        self._save_records(existing.values())
        return record

    def link_folder(self, folder: Path) -> list[RvcModelRecord]:
        return self._link_discovered(self.inspect_folder(folder))

    def link_inference_file(self, model_file: Path) -> RvcModelRecord:
        return self._link_discovered((self.inspect_inference_file(model_file),))[0]

    def _link_discovered(
        self,
        discovered: Sequence[DiscoveredRvcModel],
    ) -> list[RvcModelRecord]:
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
        return self._import_discovered(
            self.inspect_folder(folder),
            include_related_files=True,
            progress=progress,
        )

    def import_inference_file(
        self,
        model_file: Path,
        progress: Callable[[int], None] | None = None,
    ) -> RvcModelRecord:
        return self._import_discovered(
            (self.inspect_inference_file(model_file),),
            include_related_files=False,
            progress=progress,
        )[0]

    def _import_discovered(
        self,
        discovered: Sequence[DiscoveredRvcModel],
        *,
        include_related_files: bool,
        progress: Callable[[int], None] | None,
    ) -> list[RvcModelRecord]:
        existing = {record.model_id: record for record in self.records()}
        imported: list[RvcModelRecord] = []
        package_plans: list[tuple[DiscoveredRvcModel, str, RvcModelPackageLayout, tuple]] = []

        for model in discovered:
            model_id = _model_id("managed", model)
            model_dir = self.library_dir / model_id
            package = RvcModelPackageLayout(model_dir, model.name)
            experiment_source = (
                model.runtime_root / "logs" / model.name
                if include_related_files
                else None
            )
            if experiment_source is not None and not experiment_source.is_dir():
                experiment_source = None
            create_rvc_package_directories(package, experiment_source)
            weight_sources = (
                _group_inference_weights(model.runtime_root / "weights").get(model.name, [])
                if include_related_files
                else ()
            )
            plan = build_rvc_package_plan(
                package,
                experiment_source=experiment_source,
                weight_sources=weight_sources,
                artifacts=dict(_discovery_artifact_items(model)),
            )
            package_plans.append((model, model_id, package, plan))

        copy_rvc_package_files(
            (item for _model, _model_id_value, _package, plan in package_plans for item in plan),
            progress,
        )
        for model, model_id, package, plan in package_plans:
            managed = DiscoveredRvcModel(
                name=model.name,
                runtime_root=model.runtime_root,
                source_folder=package.experiment_dir,
                inference_model=packaged_target(plan, model.inference_model),
                index_file=packaged_target(plan, model.index_file),
                generator_checkpoint=packaged_target(plan, model.generator_checkpoint),
                discriminator_checkpoint=packaged_target(plan, model.discriminator_checkpoint),
            )
            record = _record_from_discovery(model_id, "managed", managed, existing.get(model_id))
            existing[model_id] = record
            imported.append(record)

        self._save_records(existing.values())
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
        device = normalize_rvc_device(default_device)
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
            package = RvcModelPackageLayout(self.library_dir / record.model_id, record.name)
            plan = build_rvc_package_plan(
                package,
                experiment_source=None,
                weight_sources=(),
                artifacts={artifact_name: source_path},
            )
            copy_rvc_package_files(plan, progress)
            replacement = packaged_target(plan, source_path) or source_path
        updated = replace(record, **{artifact_name: replacement})
        self._replace_record(updated)
        if progress is not None and not record.is_managed:
            progress(100)
        return updated

    def register_training_artifacts(
        self,
        model_id: str,
        *,
        inference_model: Path,
        index_file: Path,
        generator_checkpoint: Path,
        discriminator_checkpoint: Path,
    ) -> RvcModelRecord:
        record = self._require_record(model_id)
        if not record.is_managed:
            raise RvcModelWorkspaceError("Training artifacts require a managed model package.")
        package = RvcModelPackageLayout(self.library_dir / record.model_id, record.name)
        artifacts = {
            "inference_model": inference_model.expanduser().resolve(),
            "index_file": index_file.expanduser().resolve(),
            "generator_checkpoint": generator_checkpoint.expanduser().resolve(),
            "discriminator_checkpoint": discriminator_checkpoint.expanduser().resolve(),
        }
        for name, path in artifacts.items():
            _validate_replacement_artifact(name, path)
            if not package.contains(path):
                raise RvcModelWorkspaceError("Training artifacts must remain inside the model package.")
        if _checkpoint_step(artifacts["generator_checkpoint"]) != _checkpoint_step(
            artifacts["discriminator_checkpoint"]
        ):
            raise RvcModelWorkspaceError("Training checkpoint steps do not match.")
        updated = replace(record, **artifacts)
        self._replace_record(updated)
        return updated

    def portable_rvc_root(self, model_id: str) -> Path:
        record = self._require_record(model_id)
        if not record.is_managed:
            raise RvcModelWorkspaceError("Linked models do not have a managed RVC package.")
        package = RvcModelPackageLayout(self.library_dir / record.model_id, record.name)
        package.create()
        return package.root

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
        prepared: list[RvcModelRecord] = []
        for record in records:
            if record.is_managed:
                record, _migrated = self._ensure_managed_package(record)
            prepared.append(record)
        self._write_catalog(prepared)
        for record in prepared:
            if record.is_managed:
                _write_model_manifest(self.library_dir / record.model_id, record)

    def _write_catalog(self, records) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        sorted_records = sorted(records, key=lambda item: item.title.casefold())
        data = {
            "version": CATALOG_VERSION,
            "models": [self._record_to_data(record) for record in sorted_records],
        }
        write_json_atomic(self.catalog_path, data)

    def _ensure_managed_package(self, record: RvcModelRecord) -> tuple[RvcModelRecord, bool]:
        model_dir = self.library_dir / record.model_id
        package = RvcModelPackageLayout(model_dir, record.name)
        package.create()
        artifacts = dict(_record_artifact_items(record))
        external_artifacts = {
            name: path if path is not None and path.is_file() and not package.contains(path) else None
            for name, path in artifacts.items()
        }
        plan = build_rvc_package_plan(
            package,
            experiment_source=None,
            weight_sources=(),
            artifacts=external_artifacts,
        )
        if plan:
            copy_rvc_package_files(plan)

        updates = {
            name: packaged_target(plan, path) or path
            for name, path in artifacts.items()
        }
        updated = replace(record, source_folder=package.experiment_dir, **updates)
        did_migrate = updated != record
        if did_migrate or not package.manifest_path.is_file():
            _write_model_manifest(model_dir, updated)
        return updated, did_migrate

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
        if mode not in {"linked", "managed", "created"}:
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


def discover_rvc_inference_file(model_file: Path) -> DiscoveredRvcModel:
    selected = model_file.expanduser().resolve()
    if not selected.is_file() or selected.suffix.casefold() != ".pth":
        raise RvcModelWorkspaceError(f"RVC inference model does not exist: {selected}")
    if _CHECKPOINT_PATTERN.match(selected.name):
        raise RvcModelWorkspaceError("G/D training checkpoints cannot be used as inference models.")

    runtime_root, _experiment_filter = _resolve_rvc_layout(selected.parent)
    match = _EPOCH_WEIGHT_PATTERN.match(selected.stem)
    name = match.group("name") if match is not None else selected.stem
    indexes = _inference_index_candidates(selected.parent, runtime_root)
    return DiscoveredRvcModel(
        name=name,
        runtime_root=runtime_root,
        source_folder=selected.parent,
        inference_model=selected,
        index_file=_match_flat_index(name, indexes),
    )


def _resolve_rvc_layout(selected: Path) -> tuple[Path, str | None]:
    if (selected / "weights").is_dir() and (selected / "logs").is_dir():
        return selected, None
    if (selected / "rvc" / "weights").is_dir() and (selected / "rvc" / "logs").is_dir():
        return selected / "rvc", None
    if selected.name.casefold() == "weights" and (selected.parent / "logs").is_dir():
        return selected.parent, None
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


def _inference_index_candidates(model_folder: Path, runtime_root: Path) -> list[Path]:
    candidates = {
        path.resolve()
        for path in model_folder.glob("*.index")
        if "trained" not in path.name.casefold()
    }
    logs = runtime_root / "logs"
    if logs.is_dir():
        candidates.update(
            path.resolve()
            for path in logs.rglob("*.index")
            if "trained" not in path.name.casefold()
        )
    return sorted(candidates, key=lambda path: str(path).casefold())


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


def _new_model_id(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.casefold()).strip("-")[:32] or "model"
    return f"created-{slug}-{uuid.uuid4().hex[:8]}"


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
        default_device=existing.default_device if existing is not None else RVC_DEVICE_AUTO,
    )


def _discovery_artifact_items(model: DiscoveredRvcModel):
    return (
        ("inference_model", model.inference_model),
        ("index_file", model.index_file),
        ("generator_checkpoint", model.generator_checkpoint),
        ("discriminator_checkpoint", model.discriminator_checkpoint),
    )


def _record_artifact_items(record: RvcModelRecord):
    return (
        ("inference_model", record.inference_model),
        ("index_file", record.index_file),
        ("generator_checkpoint", record.generator_checkpoint),
        ("discriminator_checkpoint", record.discriminator_checkpoint),
    )


def _write_model_manifest(model_dir: Path, record: RvcModelRecord) -> None:
    package = RvcModelPackageLayout(model_dir, record.name)

    def relative(path: Path | None) -> str:
        if path is None or not package.contains(path):
            return ""
        return relative_package_path(package, path)

    data = {
        "version": 1,
        "id": record.model_id,
        "name": record.name,
        "rvc_name": record.name,
        "mode": record.mode,
        "runtime_root": str(record.runtime_root),
        "rvc": {
            "root": "rvc",
            "weights": "rvc/weights",
            "experiment": relative(package.experiment_dir),
            "artifacts": {
                "inference_model": relative(record.inference_model),
                "index_file": relative(record.index_file),
                "generator_checkpoint": relative(record.generator_checkpoint),
                "discriminator_checkpoint": relative(record.discriminator_checkpoint),
            },
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
    write_json_atomic(package.manifest_path, data)


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


def _managed_rvc_root(source_folder: Path) -> Path | None:
    experiment_dir = source_folder.expanduser().resolve()
    if experiment_dir.parent.name.casefold() != "logs":
        return None
    root = experiment_dir.parent.parent
    if (root / "weights").is_dir() and (root / "logs").is_dir():
        return root
    return None


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
    return normalize_rvc_device(value)
