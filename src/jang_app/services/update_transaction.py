from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from jang_app.services.app_paths import AppPaths
from jang_app.services.app_update import (
    ReleaseArtifact,
    ReleaseComponent,
    ReleaseManifest,
    UpdateError,
    UpdatePlan,
    parse_release_manifest,
    require_trusted_application_artifacts,
    verify_artifact,
)
from jang_app.services.managed_files import write_json_atomic
from jang_app.services.runtime_bootstrap import provision_update_runtime_components
from jang_app.services.update_cache import mark_update_cleanup_ready
from jang_app.version import __version__


PENDING_UPDATE_NAME = ".pending-components.json"
_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class PendingComponentUpdate:
    path: Path
    update_dir: Path
    plan: UpdatePlan
    packages: tuple[Path, ...]


def stage_pending_component_update(
    cache_root: Path,
    plan: UpdatePlan,
    downloaded: tuple[Path, ...],
) -> Path:
    if not plan.application_required or not (
        plan.runtime_required or plan.rvc_profile_required
    ):
        raise UpdateError("A pending component update requires app and runtime changes.")
    require_trusted_application_artifacts(plan.release.application)
    update_dir = _managed_update_dir(cache_root, plan.release.version)
    downloaded_by_name = {
        path.name.casefold(): path.expanduser().resolve() for path in downloaded
    }
    required = plan.artifacts
    for artifact in required:
        path = downloaded_by_name.get(artifact.name.casefold())
        if path is None or path.parent != update_dir or not verify_artifact(path, artifact):
            raise UpdateError(f"Update artifact is missing or invalid: {artifact.name}")
    journal = update_dir / PENDING_UPDATE_NAME
    write_json_atomic(
        journal,
        {
            "schema_version": _SCHEMA_VERSION,
            "created_at": datetime.now(UTC).isoformat(),
            "target_version": plan.release.version,
            "manifest": _serialize_manifest(plan.release),
            "plan": {
                "application_required": plan.application_required,
                "runtime_required": plan.runtime_required,
                "rvc_profile_required": plan.rvc_profile_required,
                "rvc_profile": plan.rvc_profile,
                "rvc_preferred_profile": plan.rvc_preferred_profile,
                "rvc_preferred_version": plan.rvc_preferred_version,
                "rvc_fallback_profile": plan.rvc_fallback_profile,
                "rvc_fallback_reason": plan.rvc_fallback_reason,
            },
        },
    )
    return journal


def apply_pending_component_updates(
    paths: AppPaths,
    *,
    current_version: str = __version__,
) -> tuple[PendingComponentUpdate, ...]:
    updates_root = (paths.cache_dir / "updates").resolve()
    if not updates_root.is_dir():
        return ()
    applied: list[PendingComponentUpdate] = []
    for journal in sorted(updates_root.glob(f"*/{PENDING_UPDATE_NAME}")):
        pending = load_pending_component_update(paths.cache_dir, journal)
        if pending.plan.release.version != current_version:
            continue
        provision_update_runtime_components(
            pending.plan,
            pending.packages,
            paths.runtime_root,
            cache_dir=pending.update_dir,
        )
        if not mark_update_cleanup_ready(
            paths.cache_dir,
            pending.update_dir,
            pending.plan.release.version,
        ):
            raise UpdateError("Could not acknowledge the completed component update.")
        applied.append(pending)
    return tuple(applied)


def load_pending_component_update(
    cache_root: Path,
    journal: Path,
) -> PendingComponentUpdate:
    source = journal.expanduser().resolve()
    updates_root = (cache_root.expanduser().resolve() / "updates").resolve()
    if source.name != PENDING_UPDATE_NAME or source.parent.parent != updates_root:
        raise UpdateError("Pending update journal is outside the update cache.")
    try:
        data = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise UpdateError(f"Could not read the pending update journal: {exc}") from exc
    if not isinstance(data, dict) or data.get("schema_version") != _SCHEMA_VERSION:
        raise UpdateError("Unsupported pending update journal.")
    manifest = parse_release_manifest(
        data.get("manifest"),
        "https://pending-update.invalid/latest.json",
    )
    target_version = str(data.get("target_version", ""))
    if manifest.version != target_version or source.parent.name != target_version:
        raise UpdateError("Pending update version does not match its cache directory.")
    raw_plan = data.get("plan")
    if not isinstance(raw_plan, dict):
        raise UpdateError("Pending update plan is missing.")
    plan = UpdatePlan(
        release=manifest,
        application_required=raw_plan.get("application_required") is True,
        runtime_required=raw_plan.get("runtime_required") is True,
        rvc_profile_required=raw_plan.get("rvc_profile_required") is True,
        rvc_profile=_text(raw_plan, "rvc_profile"),
        rvc_preferred_profile=_text(raw_plan, "rvc_preferred_profile"),
        rvc_preferred_version=_text(raw_plan, "rvc_preferred_version"),
        rvc_fallback_profile=_text(raw_plan, "rvc_fallback_profile"),
        rvc_fallback_reason=_text(raw_plan, "rvc_fallback_reason"),
    )
    if not plan.application_required or not (
        plan.runtime_required or plan.rvc_profile_required
    ):
        raise UpdateError("Pending update plan is not a combined component update.")
    packages: list[Path] = []
    for artifact in plan.runtime_artifacts:
        package = source.parent / artifact.name
        if not package.is_file() or not verify_artifact(package, artifact):
            raise UpdateError(f"Pending runtime artifact is invalid: {artifact.name}")
        packages.append(package)
    return PendingComponentUpdate(source, source.parent, plan, tuple(packages))


def _managed_update_dir(cache_root: Path, version: str) -> Path:
    root = (cache_root.expanduser().resolve() / "updates").resolve()
    candidate = (root / version).resolve()
    if candidate.parent != root or candidate.name != version:
        raise UpdateError("Unsafe pending update directory.")
    candidate.mkdir(parents=True, exist_ok=True)
    return candidate


def _serialize_manifest(release: ReleaseManifest) -> dict[str, object]:
    data: dict[str, object] = {
        "schema_version": 2,
        "product": "JJZero Audio",
        "version": release.version,
        "disabled_features": sorted(release.disabled_features),
        "components": [_serialize_component(component) for component in release.components],
    }
    if release.source_revision:
        data["source_revision"] = release.source_revision
    return data


def _serialize_component(component: ReleaseComponent) -> dict[str, object]:
    return {
        "id": component.component_id,
        "version": component.version,
        "install_mode": component.install_mode,
        "artifacts": [_serialize_artifact(artifact) for artifact in component.artifacts],
    }


def _serialize_artifact(artifact: ReleaseArtifact) -> dict[str, object]:
    data: dict[str, object] = {
        "name": artifact.name,
        "size": artifact.size,
        "sha256": artifact.sha256,
        "url": artifact.url,
    }
    if artifact.signature_required:
        data["authenticode"] = {
            "required": True,
            "publisher": artifact.publisher,
            "certificate_sha256": artifact.certificate_sha256,
        }
    if artifact.unpacked_size:
        data["unpacked_size"] = artifact.unpacked_size
    if artifact.file_count:
        data["file_count"] = artifact.file_count
    return data


def _text(data: dict[object, object], key: str) -> str:
    value = data.get(key, "")
    if not isinstance(value, str):
        raise UpdateError(f"Invalid pending update field: {key}")
    return value
