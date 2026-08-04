from __future__ import annotations

import hashlib
import json
import os
import shutil
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from jang_app.services.clip_edit_history import REVIEW_READY, TRAINING_MODE_CLIPS
from jang_app.services.file_names import safe_filename_stem
from jang_app.services.managed_files import file_sha256, link_or_copy_file, write_json_atomic
from jang_app.services.model_dataset import ModelDataset, ModelDatasetItem
from jang_app.services.rvc_model_package import RvcModelPackageLayout
from jang_app.services.rvc_training_state import RvcTrainingStateStore


TRAINING_SNAPSHOT_VERSION = 1
TRAINING_DIRECTORY_NAME = "training"
SNAPSHOTS_DIRECTORY_NAME = "snapshots"
SNAPSHOT_MANIFEST_NAME = "snapshot.json"
_FINGERPRINT_PREFIX = "sha256:"


class RvcTrainingDatasetError(RuntimeError):
    """Raised when reviewed training material cannot be frozen safely."""


@dataclass(frozen=True)
class RvcTrainingSnapshotInput:
    order: int
    source_item_id: str
    source_clip_id: str
    path: Path
    sha256: str
    size_bytes: int


@dataclass(frozen=True)
class RvcTrainingSnapshot:
    model_id: str
    fingerprint: str
    root: Path
    created_at: str
    inputs: tuple[RvcTrainingSnapshotInput, ...]

    @property
    def input_dir(self) -> Path:
        return self.root / "input"

    @property
    def input_paths(self) -> tuple[Path, ...]:
        return tuple(item.path for item in self.inputs)


@dataclass(frozen=True)
class _SnapshotSource:
    order: int
    source_item_id: str
    source_clip_id: str
    source_name: str
    path: Path
    sha256: str
    size_bytes: int


class RvcTrainingSnapshotStore:
    def __init__(self, model_id: str, layout: RvcModelPackageLayout) -> None:
        self.model_id = model_id
        self.layout = layout
        self.root = layout.model_dir / TRAINING_DIRECTORY_NAME
        self.snapshots_dir = self.root / SNAPSHOTS_DIRECTORY_NAME
        self.state_store = RvcTrainingStateStore(model_id, layout)

    def build(
        self,
        dataset: ModelDataset,
        progress: Callable[[int], None] | None = None,
    ) -> RvcTrainingSnapshot:
        sources = _snapshot_sources(dataset, self.model_id)
        fingerprint = _dataset_fingerprint(sources)
        target = self._snapshot_dir(fingerprint)
        if target.is_dir():
            snapshot = self.load(fingerprint)
            self.state_store.update_dataset_fingerprint(fingerprint)
            _report(progress, 100)
            return snapshot

        self.snapshots_dir.mkdir(parents=True, exist_ok=True)
        staging = self.snapshots_dir / f".building-{uuid.uuid4().hex}"
        try:
            snapshot = self._materialize(staging, fingerprint, sources, progress)
            try:
                os.replace(staging, target)
            except OSError:
                if not target.is_dir():
                    raise
                _remove_staging(staging, self.snapshots_dir)
            snapshot = self.load(fingerprint)
            self.state_store.update_dataset_fingerprint(fingerprint)
            _report(progress, 100)
            return snapshot
        except Exception:
            _remove_staging(staging, self.snapshots_dir)
            raise

    def load(self, fingerprint: str) -> RvcTrainingSnapshot:
        snapshot_dir = self._snapshot_dir(fingerprint)
        manifest = snapshot_dir / SNAPSHOT_MANIFEST_NAME
        try:
            data = json.loads(manifest.read_text(encoding="utf-8"))
            snapshot = self._snapshot_from_data(snapshot_dir, data)
            _verify_snapshot(snapshot)
            return snapshot
        except RvcTrainingDatasetError:
            raise
        except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            raise RvcTrainingDatasetError(f"Training snapshot cannot be read: {manifest}") from exc

    def current(self) -> RvcTrainingSnapshot | None:
        fingerprint = self.state_store.load().dataset_fingerprint
        return self.load(fingerprint) if fingerprint else None

    def _materialize(
        self,
        staging: Path,
        fingerprint: str,
        sources: tuple[_SnapshotSource, ...],
        progress: Callable[[int], None] | None,
    ) -> RvcTrainingSnapshot:
        input_dir = staging / "input"
        input_dir.mkdir(parents=True, exist_ok=False)
        inputs: list[RvcTrainingSnapshotInput] = []
        for index, source in enumerate(sources, start=1):
            suffix = source.path.suffix.casefold()
            safe_stem = safe_filename_stem(Path(source.source_name).stem, "audio", 52)
            target = input_dir / f"{source.order:04d}_{safe_stem}{suffix}"
            link_or_copy_file(source.path, target)
            inputs.append(
                RvcTrainingSnapshotInput(
                    order=source.order,
                    source_item_id=source.source_item_id,
                    source_clip_id=source.source_clip_id,
                    path=target,
                    sha256=source.sha256,
                    size_bytes=source.size_bytes,
                )
            )
            _report(progress, int(index * 90 / len(sources)))

        snapshot = RvcTrainingSnapshot(
            model_id=self.model_id,
            fingerprint=fingerprint,
            root=staging,
            created_at=_now(),
            inputs=tuple(inputs),
        )
        write_json_atomic(staging / SNAPSHOT_MANIFEST_NAME, _snapshot_to_data(snapshot))
        return snapshot

    def _snapshot_from_data(self, root: Path, data: object) -> RvcTrainingSnapshot:
        if not isinstance(data, dict) or data.get("version") != TRAINING_SNAPSHOT_VERSION:
            raise RvcTrainingDatasetError("Training snapshot version is not supported.")
        if data.get("model_id") != self.model_id:
            raise RvcTrainingDatasetError("Training snapshot belongs to a different model.")
        fingerprint = str(data["fingerprint"])
        if root != self._snapshot_dir(fingerprint):
            raise RvcTrainingDatasetError("Training snapshot fingerprint does not match its folder.")
        raw_inputs = data.get("inputs")
        if not isinstance(raw_inputs, list) or not raw_inputs:
            raise RvcTrainingDatasetError("Training snapshot has no input files.")
        inputs = tuple(
            RvcTrainingSnapshotInput(
                order=int(item["order"]),
                source_item_id=str(item["source_item_id"]),
                source_clip_id=str(item.get("source_clip_id", "")),
                path=_manifest_path(root, item["path"]),
                sha256=str(item["sha256"]),
                size_bytes=int(item["size_bytes"]),
            )
            for item in raw_inputs
            if isinstance(item, dict)
        )
        if len(inputs) != len(raw_inputs):
            raise RvcTrainingDatasetError("Training snapshot contains an invalid input entry.")
        return RvcTrainingSnapshot(
            model_id=self.model_id,
            fingerprint=fingerprint,
            root=root,
            created_at=str(data["created_at"]),
            inputs=inputs,
        )

    def _snapshot_dir(self, fingerprint: str) -> Path:
        digest = fingerprint.removeprefix(_FINGERPRINT_PREFIX)
        if fingerprint != f"{_FINGERPRINT_PREFIX}{digest}" or len(digest) != 64:
            raise RvcTrainingDatasetError("Training snapshot fingerprint is invalid.")
        try:
            int(digest, 16)
        except ValueError as exc:
            raise RvcTrainingDatasetError("Training snapshot fingerprint is invalid.") from exc
        return self.snapshots_dir / digest


def _snapshot_sources(dataset: ModelDataset, model_id: str) -> tuple[_SnapshotSource, ...]:
    if dataset.model_id != model_id:
        raise RvcTrainingDatasetError("Training dataset belongs to a different model.")
    if not dataset.training_items:
        raise RvcTrainingDatasetError("Select at least one reviewed training audio file.")
    unready = [item.source_name for item in dataset.training_items if item.review_state != REVIEW_READY]
    if unready:
        raise RvcTrainingDatasetError(
            "Every selected training audio file must be marked Ready: " + ", ".join(unready)
        )

    sources: list[_SnapshotSource] = []
    for item in dataset.training_items:
        paths = item.training_paths
        if not paths:
            raise RvcTrainingDatasetError(f"Training audio has no usable clips: {item.source_name}")
        clip_ids = _clip_ids(item)
        for path, clip_id in zip(paths, clip_ids, strict=True):
            resolved = path.expanduser().resolve()
            if not resolved.is_file():
                raise RvcTrainingDatasetError(f"Training audio is missing: {resolved}")
            sources.append(
                _SnapshotSource(
                    order=len(sources) + 1,
                    source_item_id=item.item_id,
                    source_clip_id=clip_id,
                    source_name=item.source_name,
                    path=resolved,
                    sha256=file_sha256(resolved),
                    size_bytes=resolved.stat().st_size,
                )
            )
    return tuple(sources)


def _clip_ids(item: ModelDatasetItem) -> tuple[str, ...]:
    if item.training_mode == TRAINING_MODE_CLIPS:
        return tuple(clip.clip_id for clip in item.clips)
    return ("",)


def _dataset_fingerprint(sources: tuple[_SnapshotSource, ...]) -> str:
    digest = hashlib.sha256()
    for source in sources:
        digest.update(source.order.to_bytes(8, "big"))
        digest.update(bytes.fromhex(source.sha256))
    return f"{_FINGERPRINT_PREFIX}{digest.hexdigest()}"


def _snapshot_to_data(snapshot: RvcTrainingSnapshot) -> dict[str, object]:
    return {
        "version": TRAINING_SNAPSHOT_VERSION,
        "model_id": snapshot.model_id,
        "fingerprint": snapshot.fingerprint,
        "created_at": snapshot.created_at,
        "inputs": [
            {
                "order": item.order,
                "source_item_id": item.source_item_id,
                "source_clip_id": item.source_clip_id,
                "path": item.path.relative_to(snapshot.root).as_posix(),
                "sha256": item.sha256,
                "size_bytes": item.size_bytes,
            }
            for item in snapshot.inputs
        ],
    }


def _manifest_path(root: Path, value: object) -> Path:
    if not isinstance(value, str) or not value:
        raise RvcTrainingDatasetError("Training snapshot path is invalid.")
    resolved = (root / Path(value)).resolve()
    if not _is_within(resolved, root):
        raise RvcTrainingDatasetError("Training snapshot path leaves its package.")
    return resolved


def _verify_snapshot(snapshot: RvcTrainingSnapshot) -> None:
    expected_orders = tuple(range(1, len(snapshot.inputs) + 1))
    if tuple(item.order for item in snapshot.inputs) != expected_orders:
        raise RvcTrainingDatasetError("Training snapshot input order is invalid.")
    for item in snapshot.inputs:
        if not item.path.is_file() or item.path.stat().st_size != item.size_bytes:
            raise RvcTrainingDatasetError(f"Training snapshot input is missing or incomplete: {item.path}")
        if file_sha256(item.path) != item.sha256:
            raise RvcTrainingDatasetError(f"Training snapshot input was modified: {item.path}")


def _remove_staging(path: Path, snapshots_dir: Path) -> None:
    if path.exists() and path.name.startswith(".building-") and _is_within(path, snapshots_dir):
        shutil.rmtree(path)


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.expanduser().resolve().relative_to(root.expanduser().resolve())
        return True
    except ValueError:
        return False


def _report(progress: Callable[[int], None] | None, value: int) -> None:
    if progress is not None:
        progress(max(0, min(100, value)))


def _now() -> str:
    return datetime.now(UTC).isoformat()
