from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path

from jang_app.services.managed_files import copy_file_atomic


RVC_PACKAGE_DIR_NAME = "rvc"
MODEL_MANIFEST_NAME = "model.json"
ARTIFACT_NAMES = (
    "inference_model",
    "index_file",
    "generator_checkpoint",
    "discriminator_checkpoint",
)


@dataclass(frozen=True)
class RvcModelPackageLayout:
    model_dir: Path
    rvc_name: str

    @property
    def root(self) -> Path:
        return self.model_dir / RVC_PACKAGE_DIR_NAME

    @property
    def weights_dir(self) -> Path:
        return self.root / "weights"

    @property
    def experiment_dir(self) -> Path:
        return self.root / "logs" / self.rvc_name

    @property
    def manifest_path(self) -> Path:
        return self.model_dir / MODEL_MANIFEST_NAME

    def create(self) -> None:
        self.weights_dir.mkdir(parents=True, exist_ok=True)
        self.experiment_dir.mkdir(parents=True, exist_ok=True)

    def artifact_target(self, artifact_name: str, source: Path) -> Path:
        if artifact_name == "inference_model":
            return self.weights_dir / source.name
        if artifact_name in ARTIFACT_NAMES:
            return self.experiment_dir / source.name
        raise ValueError(f"Unsupported RVC artifact: {artifact_name}")

    def contains(self, path: Path) -> bool:
        return _is_within(path, self.root)


@dataclass(frozen=True)
class RvcPackageFile:
    source: Path
    target: Path


def build_rvc_package_plan(
    layout: RvcModelPackageLayout,
    *,
    experiment_source: Path | None,
    weight_sources: Iterable[Path],
    artifacts: Mapping[str, Path | None],
) -> tuple[RvcPackageFile, ...]:
    targets: dict[Path, Path] = {}

    if experiment_source is not None and experiment_source.is_dir():
        for source in experiment_source.rglob("*"):
            if source.is_file():
                target = layout.experiment_dir / source.relative_to(experiment_source)
                targets[target.resolve()] = source.resolve()

    for source in weight_sources:
        if source.is_file():
            target = layout.weights_dir / source.name
            targets[target.resolve()] = source.resolve()

    for artifact_name, source in artifacts.items():
        if source is None or not source.is_file():
            continue
        target = layout.artifact_target(artifact_name, source)
        targets[target.resolve()] = source.resolve()

    return tuple(
        RvcPackageFile(source=source, target=target)
        for target, source in sorted(targets.items(), key=lambda item: str(item[0]).casefold())
    )


def create_rvc_package_directories(
    layout: RvcModelPackageLayout,
    experiment_source: Path | None = None,
) -> None:
    layout.create()
    if experiment_source is None or not experiment_source.is_dir():
        return
    for source in experiment_source.rglob("*"):
        if source.is_dir():
            (layout.experiment_dir / source.relative_to(experiment_source)).mkdir(parents=True, exist_ok=True)


def copy_rvc_package_files(
    files: Iterable[RvcPackageFile],
    progress: Callable[[int], None] | None = None,
) -> None:
    plan = tuple(files)
    total_bytes = sum(item.source.stat().st_size for item in plan)
    copied_bytes = 0

    for item in plan:
        base_bytes = copied_bytes
        copy_file_atomic(
            item.source,
            item.target,
            lambda current, base=base_bytes: _report_progress(progress, base + current, total_bytes),
        )
        copied_bytes += item.source.stat().st_size
        _report_progress(progress, copied_bytes, total_bytes)

    if progress is not None:
        progress(100)


def packaged_target(files: Iterable[RvcPackageFile], source: Path | None) -> Path | None:
    if source is None:
        return None
    resolved = source.resolve()
    return next((item.target for item in files if item.source == resolved), None)


def relative_package_path(layout: RvcModelPackageLayout, path: Path | None) -> str:
    if path is None:
        return ""
    resolved = path.resolve()
    if not _is_within(resolved, layout.model_dir):
        raise ValueError(f"Model artifact is outside its managed package: {path}")
    return resolved.relative_to(layout.model_dir.resolve()).as_posix()


def resolve_package_path(model_dir: Path, value: object) -> Path | None:
    if not isinstance(value, str) or not value:
        return None
    resolved = (model_dir / Path(value)).resolve()
    if not _is_within(resolved, model_dir):
        raise ValueError("Model manifest path leaves its package")
    return resolved


def _report_progress(progress: Callable[[int], None] | None, copied: int, total: int) -> None:
    if progress is None:
        return
    progress(100 if total <= 0 else max(0, min(100, int(copied * 100 / total))))


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False
