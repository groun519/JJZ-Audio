from __future__ import annotations

import shutil
import uuid
from collections.abc import Iterable
from pathlib import Path


class RvcTrainingArtifactError(RuntimeError):
    """Raised when validated training outputs cannot be published safely."""


def publish_training_outputs(
    staging: Path,
    experiment_dir: Path,
    published_names: Iterable[str],
    *,
    invalidated_names: Iterable[str] = (),
    backup_label: str,
) -> None:
    experiment_dir.mkdir(parents=True, exist_ok=True)
    published = tuple(published_names)
    affected = (*published, *tuple(invalidated_names))
    backup = experiment_dir / f".jjzero-{backup_label}-backup-{uuid.uuid4().hex}"
    installed: list[Path] = []
    try:
        backup.mkdir()
        for name in affected:
            current = experiment_dir / name
            if current.exists():
                shutil.move(str(current), str(backup / name))
        for name in published:
            source = staging / name
            target = experiment_dir / name
            shutil.move(str(source), str(target))
            installed.append(target)
    except Exception as publish_error:
        for path in reversed(installed):
            _remove_path(path, experiment_dir)
        try:
            for saved in tuple(backup.iterdir()) if backup.is_dir() else ():
                shutil.move(str(saved), str(experiment_dir / saved.name))
        except Exception as restore_error:
            raise RvcTrainingArtifactError(
                f"Training output restore failed. Recovery files remain at: {backup}"
            ) from restore_error
        _remove_tree(backup, experiment_dir)
        raise publish_error
    _remove_tree(backup, experiment_dir)


def remove_training_staging(path: Path, model_dir: Path) -> None:
    _remove_tree(path, model_dir)


def _remove_path(path: Path, root: Path) -> None:
    if not path.exists() or not _is_within(path, root):
        return
    if path.is_dir():
        shutil.rmtree(path)
    else:
        path.unlink()


def _remove_tree(path: Path, root: Path) -> None:
    if path.is_dir() and _is_within(path, root):
        shutil.rmtree(path)


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False
