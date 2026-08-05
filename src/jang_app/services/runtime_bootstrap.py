from __future__ import annotations

import json
import logging
from collections.abc import Callable
from pathlib import Path

from jang_app.services.app_paths import AppPaths
from jang_app.services.app_update import (
    DEFAULT_MANIFEST_URL,
    ReleaseArtifact,
    ReleaseComponent,
    ReleaseManifest,
    UpdatePlan,
    UpdateError,
    create_update_plan,
    download_artifact,
    fetch_release_manifest,
    verify_artifact,
)
from jang_app.services.runtime_installation import (
    RuntimeInstallation,
    install_rvc_runtime_profile_packages,
    install_runtime_packages,
    installed_rvc_runtime_profile,
    mark_rvc_runtime_fallback,
)
from jang_app.services.rvc_runtime_profile import (
    RVC_PROFILE_CPU,
    detect_rvc_runtime_profile,
    rvc_profile_candidates,
    rvc_profile_requires_overlay,
    rvc_profile_component_id,
)
from jang_app.version import __version__


ProgressReporter = Callable[[int], None]
_LOGGER = logging.getLogger("jang_app")


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
    preferred_profile = detect_rvc_runtime_profile()
    plan = create_update_plan(
        release,
        current_version=release.version,
        runtime_version=None,
        runtime_ready=False,
        desired_rvc_profile=preferred_profile,
    )
    artifacts = plan.artifacts
    cache = paths.cache_dir / "runtime" / release.version
    packages = _download_runtime_artifacts(artifacts, cache, progress)
    installations = install_update_runtime_components(
        plan,
        packages,
        paths.runtime_root,
        progress=lambda value: _report(progress, 70 + int(value * 0.3)),
    )
    return next(
        item for item in installations if isinstance(item, RuntimeInstallation)
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
    version, packages = _offline_component_packages(index, "ai-runtime", progress)
    preferred_profile = detect_rvc_runtime_profile()
    components = [
        ReleaseComponent("application", __version__, "installer", ()),
        _offline_component("ai-runtime", version, packages),
    ]
    downloaded = list(packages)
    for profile in rvc_profile_candidates(preferred_profile):
        if not rvc_profile_requires_overlay(profile):
            continue
        component_id = rvc_profile_component_id(profile)
        profile_index = index.parent / f"{component_id}-packages.json"
        if not profile_index.is_file():
            continue
        profile_version, profile_packages = _offline_component_packages(
            profile_index,
            component_id,
            None,
        )
        components.append(_offline_component(component_id, profile_version, profile_packages))
        downloaded.extend(profile_packages)
    release = ReleaseManifest(__version__, tuple(components))
    plan = create_update_plan(
        release,
        current_version=__version__,
        runtime_version=None,
        runtime_ready=False,
        desired_rvc_profile=preferred_profile,
    )
    installations = install_update_runtime_components(
        plan,
        tuple(downloaded),
        runtime_root,
        progress=progress,
    )
    return next(item for item in installations if isinstance(item, RuntimeInstallation))


def install_update_runtime_components(
    plan: UpdatePlan,
    downloaded: tuple[Path, ...],
    runtime_root: Path,
    *,
    progress: ProgressReporter | None = None,
) -> tuple[object, ...]:
    operations = int(plan.runtime_required) + int(plan.rvc_profile_required)
    if operations == 0:
        _report(progress, 100)
        return ()
    completed = 0
    installed: list[object] = []

    def operation_progress(value: int) -> None:
        _report(progress, int((completed + value / 100) * 100 / operations))

    if plan.runtime_required:
        runtime = plan.release.ai_runtime
        if runtime is None:
            raise UpdateError("AI runtime component is unavailable.")
        packages = _component_packages(runtime, downloaded)
        installed.append(
            install_runtime_packages(
                packages,
                runtime_root,
                runtime.version,
                progress=operation_progress,
            )
        )
        completed += 1

    if plan.rvc_profile_required:
        installed.append(
            _install_profile_chain(
                plan,
                downloaded,
                runtime_root,
                progress=operation_progress,
            )
        )
    _report(progress, 100)
    return tuple(installed)


def _install_profile_chain(
    plan: UpdatePlan,
    downloaded: tuple[Path, ...],
    runtime_root: Path,
    *,
    progress: ProgressReporter | None,
) -> object:
    preferred = plan.rvc_preferred_profile or plan.rvc_profile
    preferred_version = plan.rvc_preferred_version
    failures = [plan.rvc_fallback_reason] if plan.rvc_fallback_reason else []
    failed_versions: dict[str, str] = {}
    attempts = [plan.rvc_profile]
    if plan.rvc_fallback_profile and plan.rvc_fallback_profile not in attempts:
        attempts.append(plan.rvc_fallback_profile)
    for profile in attempts:
        if not rvc_profile_requires_overlay(profile):
            break
        component = plan.release.rvc_runtime_profile(profile)
        if component is None:
            failures.append(f"RVC {profile} runtime component is unavailable.")
            continue
        try:
            return install_rvc_runtime_profile_packages(
                _component_packages(component, downloaded),
                runtime_root / "rvc",
                profile,
                component.version,
                progress=progress,
                preferred_profile=preferred,
                preferred_version=preferred_version,
                activation_status="active" if profile == preferred else "fallback",
                validation_detail="\n".join(failures),
            )
        except Exception as exc:
            detail = f"RVC {profile} activation failed: {exc}"
            failures.append(detail)
            failed_versions[profile] = component.version
            _LOGGER.warning(detail, exc_info=True)
    runtime = plan.release.ai_runtime
    previous = installed_rvc_runtime_profile(runtime_root / "rvc")
    active_version = (
        runtime.version
        if runtime is not None
        else previous.version
        if previous is not None
        else "unversioned"
    )
    return mark_rvc_runtime_fallback(
        runtime_root / "rvc",
        active_profile=RVC_PROFILE_CPU,
        active_version=active_version,
        preferred_profile=preferred,
        preferred_version=preferred_version,
        detail="\n".join(failures) or "No compatible GPU runtime profile was available.",
        failed_fallback_profile=(
            plan.rvc_fallback_profile
            if plan.rvc_fallback_profile in failed_versions
            else ""
        ),
        failed_fallback_version=failed_versions.get(plan.rvc_fallback_profile, ""),
    )


def _offline_component(
    component_id: str,
    version: str,
    packages: tuple[Path, ...],
) -> ReleaseComponent:
    return ReleaseComponent(
        component_id,
        version,
        "extract",
        tuple(
            ReleaseArtifact(
                package.name,
                package.stat().st_size,
                "0" * 64,
                f"https://offline.invalid/{package.name}",
            )
            for package in packages
        ),
    )


def _offline_component_packages(
    index: Path,
    expected_component: str,
    progress: ProgressReporter | None,
) -> tuple[str, tuple[Path, ...]]:
    try:
        data = json.loads(index.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise UpdateError(f"Could not read the AI runtime package index: {exc}") from exc
    if not isinstance(data, dict) or data.get("schema_version") != 1:
        raise UpdateError("Unsupported AI runtime package index.")
    if data.get("component") != expected_component:
        raise UpdateError(f"The selected package index is not {expected_component}.")
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
    return version.strip(), tuple(packages)


def _component_packages(
    component: ReleaseComponent,
    downloaded: tuple[Path, ...],
) -> tuple[Path, ...]:
    by_name = {path.name: path for path in downloaded}
    missing = tuple(
        artifact.name for artifact in component.artifacts if artifact.name not in by_name
    )
    if missing:
        raise UpdateError(f"Downloaded component package is unavailable: {missing[0]}")
    return tuple(by_name[artifact.name] for artifact in component.artifacts)


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
