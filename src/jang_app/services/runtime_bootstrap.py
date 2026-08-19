from __future__ import annotations

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
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
    discard_cached_artifacts,
    download_artifact,
    fetch_release_manifest,
    verify_artifact,
)
from jang_app.services.runtime_installation import (
    RuntimeInstallation,
    RuntimeInstallationError,
    install_rvc_runtime_profile_packages,
    install_runtime_packages,
    installed_rvc_runtime_profile,
    mark_rvc_runtime_fallback,
    runtime_packages_unpacked_size,
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
ComponentPackageResolver = Callable[
    [ReleaseComponent, ProgressReporter | None],
    tuple[Path, ...],
]


class RuntimeProvisionStage(StrEnum):
    PREPARING = "preparing"
    DOWNLOADING = "downloading"
    INSTALLING = "installing"
    CONFIGURING = "configuring"
    VERIFYING = "verifying"


@dataclass(frozen=True)
class RuntimeProvisionActivity:
    stage: RuntimeProvisionStage
    completed_bytes: int = 0
    total_bytes: int = 0
    detail: str = ""


ActivityReporter = Callable[[RuntimeProvisionActivity], None]
_LOGGER = logging.getLogger("jang_app")


def provision_ai_runtime(
    paths: AppPaths,
    *,
    manifest_url: str = DEFAULT_MANIFEST_URL,
    progress: ProgressReporter | None = None,
    activity: ActivityReporter | None = None,
) -> RuntimeInstallation:
    _report(progress, 2)
    _report_activity(activity, RuntimeProvisionStage.PREPARING, detail="Checking available components")
    release = fetch_release_manifest(manifest_url)
    runtime = release.ai_runtime
    if runtime is None or runtime.install_mode != "extract":
        raise UpdateError("The release does not contain an installable audio engine.")
    preferred_profile = detect_rvc_runtime_profile()
    plan = create_update_plan(
        release,
        current_version=release.version,
        runtime_version=None,
        runtime_ready=False,
        desired_rvc_profile=preferred_profile,
    )
    artifacts = plan.runtime_artifacts
    cache = paths.cache_dir / "runtime" / release.version
    packages = _download_runtime_artifacts(artifacts, cache, progress, activity)
    installations = provision_update_runtime_components(
        plan,
        packages,
        paths.runtime_root,
        cache_dir=cache,
        progress=lambda value: _report(progress, 70 + int(value * 0.3)),
        activity=activity,
    )
    _report_activity(activity, RuntimeProvisionStage.VERIFYING, detail="Verifying installed components")
    result = next(
        item for item in installations if isinstance(item, RuntimeInstallation)
    )
    discard_cached_artifacts(packages, paths.cache_dir)
    return result


def provision_ai_runtime_offline(
    paths: AppPaths,
    package_index: Path,
    *,
    progress: ProgressReporter | None = None,
    activity: ActivityReporter | None = None,
) -> RuntimeInstallation:
    return install_ai_runtime_offline(
        paths.runtime_root,
        package_index,
        progress=progress,
        activity=activity,
    )


def install_ai_runtime_offline(
    runtime_root: Path,
    package_index: Path,
    *,
    progress: ProgressReporter | None = None,
    activity: ActivityReporter | None = None,
) -> RuntimeInstallation:
    _report_activity(activity, RuntimeProvisionStage.PREPARING, detail="Checking local packages")
    index = package_index.expanduser().resolve()
    version, packages = _offline_component_packages(index, "ai-runtime", progress)
    preferred_profile = detect_rvc_runtime_profile()
    components = [
        ReleaseComponent("application", __version__, "installer", ()),
        _offline_component("ai-runtime", version, packages),
    ]
    downloaded = list(packages)
    for profile in rvc_profile_candidates(preferred_profile):
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
        activity=activity,
    )
    _report_activity(activity, RuntimeProvisionStage.VERIFYING, detail="Verifying installed components")
    return next(item for item in installations if isinstance(item, RuntimeInstallation))


def install_update_runtime_components(
    plan: UpdatePlan,
    downloaded: tuple[Path, ...],
    runtime_root: Path,
    *,
    progress: ProgressReporter | None = None,
    activity: ActivityReporter | None = None,
) -> tuple[object, ...]:
    def resolve_local(
        component: ReleaseComponent,
        component_progress: ProgressReporter | None,
    ) -> tuple[Path, ...]:
        packages = _component_packages(component, downloaded)
        _report(component_progress, 100)
        return packages

    return _install_update_runtime_components(
        plan,
        runtime_root,
        resolve_local,
        progress=progress,
        activity=activity,
    )


def provision_update_runtime_components(
    plan: UpdatePlan,
    downloaded: tuple[Path, ...],
    runtime_root: Path,
    *,
    cache_dir: Path,
    progress: ProgressReporter | None = None,
    activity: ActivityReporter | None = None,
) -> tuple[object, ...]:
    available = list(downloaded)
    fetched: list[Path] = []

    def resolve_online(
        component: ReleaseComponent,
        component_progress: ProgressReporter | None,
    ) -> tuple[Path, ...]:
        try:
            packages = _component_packages(component, tuple(available))
        except UpdateError:
            packages = _download_component_artifacts(
                component.artifacts,
                cache_dir,
                component_progress,
                activity,
            )
            available.extend(packages)
            fetched.extend(packages)
        else:
            _report(component_progress, 100)
        return packages

    installed = _install_update_runtime_components(
        plan,
        runtime_root,
        resolve_online,
        progress=progress,
        activity=activity,
    )
    if fetched:
        discard_cached_artifacts(tuple(fetched), cache_dir)
    return installed


def _install_update_runtime_components(
    plan: UpdatePlan,
    runtime_root: Path,
    resolve_packages: ComponentPackageResolver,
    *,
    progress: ProgressReporter | None = None,
    activity: ActivityReporter | None = None,
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
            raise UpdateError("The audio engine component is unavailable.")
        packages = resolve_packages(
            runtime,
            lambda value: operation_progress(int(value * 0.2)),
        )
        unpacked_size = _runtime_unpacked_size(packages)
        detail = "Installing audio tools and model components"

        def runtime_progress(value: int) -> None:
            operation_progress(20 + int(value * 0.8))
            _report_activity(
                activity,
                RuntimeProvisionStage.INSTALLING,
                int(unpacked_size * value / 100),
                unpacked_size,
                detail,
            )

        installed.append(
            install_runtime_packages(
                packages,
                runtime_root,
                runtime.version,
                progress=runtime_progress,
            )
        )
        completed += 1

    if plan.rvc_profile_required:
        installed.append(
            _install_profile_chain(
                plan,
                runtime_root,
                resolve_packages,
                progress=operation_progress,
                activity=activity,
            )
        )
    _report(progress, 100)
    return tuple(installed)


def _install_profile_chain(
    plan: UpdatePlan,
    runtime_root: Path,
    resolve_packages: ComponentPackageResolver,
    *,
    progress: ProgressReporter | None,
    activity: ActivityReporter | None = None,
) -> object:
    preferred = plan.rvc_preferred_profile or plan.rvc_profile
    preferred_version = plan.rvc_preferred_version
    failures = [plan.rvc_fallback_reason] if plan.rvc_fallback_reason else []
    failed_versions: dict[str, str] = {}
    attempts = [plan.rvc_profile]
    if plan.rvc_fallback_profile and plan.rvc_fallback_profile not in attempts:
        attempts.append(plan.rvc_fallback_profile)
    attempt_count = max(1, len(attempts))
    for attempt_index, profile in enumerate(attempts):
        attempt_start = int(attempt_index * 100 / attempt_count)
        attempt_end = int((attempt_index + 1) * 100 / attempt_count)
        attempt_span = attempt_end - attempt_start

        def attempt_progress(value: int) -> None:
            _report(progress, attempt_start + int(attempt_span * value / 100))

        component = plan.release.rvc_runtime_profile(profile)
        if component is None:
            if not rvc_profile_requires_overlay(profile):
                break
            failures.append(f"RVC {profile} runtime component is unavailable.")
            continue
        try:
            packages = resolve_packages(
                component,
                lambda value: attempt_progress(int(value * 0.35)),
            )
            unpacked_size = _runtime_unpacked_size(packages)
            detail = f"Configuring the {profile} accelerator"

            def profile_progress(value: int) -> None:
                attempt_progress(35 + int(value * 0.65))
                _report_activity(
                    activity,
                    RuntimeProvisionStage.CONFIGURING,
                    int(unpacked_size * value / 100),
                    unpacked_size,
                    detail,
                )

            return install_rvc_runtime_profile_packages(
                packages,
                runtime_root / "rvc",
                profile,
                component.version,
                progress=profile_progress,
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
        raise UpdateError(f"Could not read the audio engine package index: {exc}") from exc
    if not isinstance(data, dict) or data.get("schema_version") != 1:
        raise UpdateError("Unsupported audio engine package index.")
    if data.get("component") != expected_component:
        raise UpdateError(f"The selected package index is not {expected_component}.")
    version = data.get("version")
    raw_artifacts = data.get("artifacts")
    if not isinstance(version, str) or not version.strip():
        raise UpdateError("The audio engine package index has no version.")
    if not isinstance(raw_artifacts, list) or not raw_artifacts:
        raise UpdateError("The audio engine package index has no packages.")

    packages: list[Path] = []
    for position, raw in enumerate(raw_artifacts, start=1):
        artifact = _offline_artifact(raw)
        package = index.parent / artifact.name
        if not verify_artifact(package, artifact):
            raise UpdateError(f"Audio engine package verification failed: {artifact.name}")
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
    activity: ActivityReporter | None = None,
) -> tuple[Path, ...]:
    return _download_component_artifacts(
        artifacts,
        cache,
        lambda value: _report(progress, 5 + int(value * 0.65)),
        activity,
    )


def _download_component_artifacts(
    artifacts: tuple[ReleaseArtifact, ...],
    cache: Path,
    progress: ProgressReporter | None,
    activity: ActivityReporter | None = None,
) -> tuple[Path, ...]:
    if not artifacts:
        _report(progress, 100)
        return ()
    total_size = sum(artifact.size for artifact in artifacts)
    completed = 0
    packages: list[Path] = []
    for artifact in artifacts:
        base = completed

        def download_progress(
            value: int,
            *,
            item: ReleaseArtifact = artifact,
            offset: int = base,
        ) -> None:
            current = offset + int(item.size * value / 100)
            _report(progress, int(current * 100 / total_size))
            _report_activity(
                activity,
                RuntimeProvisionStage.DOWNLOADING,
                current,
                total_size,
                item.name,
            )

        package = download_artifact(
            artifact,
            cache,
            progress=download_progress,
        )
        packages.append(package)
        completed += artifact.size
    _report(progress, 100)
    return tuple(packages)


def _offline_artifact(data: object) -> ReleaseArtifact:
    if not isinstance(data, dict):
        raise UpdateError("An audio engine package entry must be an object.")
    name = data.get("name")
    size = data.get("size")
    sha256 = data.get("sha256")
    if not isinstance(name, str) or Path(name).name != name:
        raise UpdateError(f"Unsafe audio engine package name: {name!r}")
    if not isinstance(size, int) or size <= 0:
        raise UpdateError(f"Invalid audio engine package size: {name}")
    if not isinstance(sha256, str) or len(sha256) != 64:
        raise UpdateError(f"Invalid audio engine package checksum: {name}")
    return ReleaseArtifact(name, size, sha256.lower(), f"https://offline.invalid/{name}")


def _report(progress: ProgressReporter | None, value: int) -> None:
    if progress is not None:
        progress(max(0, min(value, 100)))


def _report_activity(
    reporter: ActivityReporter | None,
    stage: RuntimeProvisionStage,
    completed_bytes: int = 0,
    total_bytes: int = 0,
    detail: str = "",
) -> None:
    if reporter is not None:
        reporter(
            RuntimeProvisionActivity(
                stage,
                max(0, completed_bytes),
                max(0, total_bytes),
                detail,
            )
        )


def _runtime_unpacked_size(packages: tuple[Path, ...]) -> int:
    try:
        return runtime_packages_unpacked_size(packages)
    except (OSError, RuntimeInstallationError):
        # Size reporting is telemetry; package validation still happens in the installer.
        return 0
