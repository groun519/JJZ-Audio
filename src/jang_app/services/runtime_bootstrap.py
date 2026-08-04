from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

from jang_app.services.app_paths import AppPaths
from jang_app.services.app_update import (
    DEFAULT_MANIFEST_URL,
    ReleaseArtifact,
    UpdateError,
    download_artifact,
    fetch_release_manifest,
    verify_artifact,
)
from jang_app.services.runtime_installation import (
    RuntimeInstallation,
    install_runtime_packages,
)


ProgressReporter = Callable[[int], None]


def provision_ai_runtime(
    paths: AppPaths,
    *,
    manifest_url: str = DEFAULT_MANIFEST_URL,
    progress: ProgressReporter | None = None,
) -> RuntimeInstallation:
    _report(progress, 2)
    release = fetch_release_manifest(manifest_url)
    runtime = release.ai_runtime
    if runtime is None or runtime.install_mode != "extract":
        raise UpdateError("The release does not contain an installable AI runtime.")
    cache = paths.cache_dir / "runtime" / runtime.version
    packages = _download_runtime_artifacts(runtime.artifacts, cache, progress)
    return install_runtime_packages(
        packages,
        paths.runtime_root,
        runtime.version,
        progress=lambda value: _report(progress, 70 + int(value * 0.3)),
    )


def provision_ai_runtime_offline(
    paths: AppPaths,
    package_index: Path,
    *,
    progress: ProgressReporter | None = None,
) -> RuntimeInstallation:
    return install_ai_runtime_offline(
        paths.runtime_root,
        package_index,
        progress=progress,
    )


def install_ai_runtime_offline(
    runtime_root: Path,
    package_index: Path,
    *,
    progress: ProgressReporter | None = None,
) -> RuntimeInstallation:
    index = package_index.expanduser().resolve()
    try:
        data = json.loads(index.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise UpdateError(f"Could not read the AI runtime package index: {exc}") from exc
    if not isinstance(data, dict) or data.get("schema_version") != 1:
        raise UpdateError("Unsupported AI runtime package index.")
    if data.get("component") != "ai-runtime":
        raise UpdateError("The selected package index is not an AI runtime.")
    version = data.get("version")
    raw_artifacts = data.get("artifacts")
    if not isinstance(version, str) or not version.strip():
        raise UpdateError("The AI runtime package index has no version.")
    if not isinstance(raw_artifacts, list) or not raw_artifacts:
        raise UpdateError("The AI runtime package index has no packages.")

    packages: list[Path] = []
    for position, raw in enumerate(raw_artifacts, start=1):
        artifact = _offline_artifact(raw)
        package = index.parent / artifact.name
        if not verify_artifact(package, artifact):
            raise UpdateError(f"AI runtime package verification failed: {artifact.name}")
        packages.append(package)
        _report(progress, int(position * 20 / len(raw_artifacts)))
    return install_runtime_packages(
        packages,
        runtime_root,
        version.strip(),
        progress=lambda value: _report(progress, 20 + int(value * 0.8)),
    )


def _download_runtime_artifacts(
    artifacts: tuple[ReleaseArtifact, ...],
    cache: Path,
    progress: ProgressReporter | None,
) -> tuple[Path, ...]:
    total_size = sum(artifact.size for artifact in artifacts)
    completed = 0
    packages: list[Path] = []
    for artifact in artifacts:
        base = completed
        package = download_artifact(
            artifact,
            cache,
            progress=lambda value, item=artifact, offset=base: _report(
                progress,
                5 + int((offset + item.size * value / 100) * 65 / total_size),
            ),
        )
        packages.append(package)
        completed += artifact.size
    return tuple(packages)


def _offline_artifact(data: object) -> ReleaseArtifact:
    if not isinstance(data, dict):
        raise UpdateError("An AI runtime package entry must be an object.")
    name = data.get("name")
    size = data.get("size")
    sha256 = data.get("sha256")
    if not isinstance(name, str) or Path(name).name != name:
        raise UpdateError(f"Unsafe AI runtime package name: {name!r}")
    if not isinstance(size, int) or size <= 0:
        raise UpdateError(f"Invalid AI runtime package size: {name}")
    if not isinstance(sha256, str) or len(sha256) != 64:
        raise UpdateError(f"Invalid AI runtime package checksum: {name}")
    return ReleaseArtifact(name, size, sha256.lower(), f"https://offline.invalid/{name}")


def _report(progress: ProgressReporter | None, value: int) -> None:
    if progress is not None:
        progress(max(0, min(value, 100)))
