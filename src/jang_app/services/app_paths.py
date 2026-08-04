from __future__ import annotations

import json
import os
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path


APP_DATA_DIR_NAME = "JJZero Audio"
STORAGE_LAYOUT_VERSION = 1
STORAGE_FILE_NAME = "storage.json"


@dataclass(frozen=True)
class AppPaths:
    is_frozen: bool
    source_root: Path
    install_root: Path
    package_root: Path
    data_root: Path
    settings_dir: Path
    log_dir: Path
    cache_dir: Path
    workspace_root: Path
    workspace_anchor: Path
    output_root: Path
    runtime_root: Path
    legacy_root: Path | None

    @property
    def storage_file(self) -> Path:
        return self.settings_dir / STORAGE_FILE_NAME


def discover_app_paths(
    package_root: Path,
    *,
    environ: Mapping[str, str] | None = None,
    frozen: bool | None = None,
    executable: Path | None = None,
    source_root: Path | None = None,
) -> AppPaths:
    environment = os.environ if environ is None else environ
    resolved_package = package_root.expanduser().resolve()
    is_frozen = bool(getattr(sys, "frozen", False)) if frozen is None else frozen
    development_root = source_root or resolved_package.parents[1]
    resolved_source = development_root.expanduser().resolve()
    resolved_executable = (executable or Path(sys.executable)).expanduser().resolve()
    install_root = resolved_executable.parent if is_frozen else resolved_source
    data_root = _data_root(environment)
    settings_dir = data_root / "settings"
    stored_workspace, stored_anchor = _stored_workspace(settings_dir / STORAGE_FILE_NAME)
    legacy_root = _legacy_root(environment, resolved_source, is_frozen)
    workspace_root, workspace_anchor = _workspace_layout(
        environment,
        stored_workspace,
        stored_anchor,
        legacy_root,
    )
    runtime_root = _runtime_root(environment, install_root, resolved_source, is_frozen)
    return AppPaths(
        is_frozen=is_frozen,
        source_root=resolved_source,
        install_root=install_root,
        package_root=resolved_package,
        data_root=data_root,
        settings_dir=settings_dir,
        log_dir=data_root / "logs",
        cache_dir=data_root / "cache",
        workspace_root=workspace_root,
        workspace_anchor=workspace_anchor,
        output_root=workspace_anchor / "output",
        runtime_root=runtime_root,
        legacy_root=legacy_root,
    )


def _data_root(environment: Mapping[str, str]) -> Path:
    override = _absolute_environment_path(environment, "JJZERO_DATA_ROOT")
    if override is not None:
        return override
    local_app_data = environment.get("LOCALAPPDATA") or environment.get("APPDATA")
    if local_app_data:
        return (Path(local_app_data).expanduser() / APP_DATA_DIR_NAME).resolve()
    return (Path.home() / ".local" / "share" / APP_DATA_DIR_NAME).resolve()


def _legacy_root(
    environment: Mapping[str, str],
    source_root: Path,
    is_frozen: bool,
) -> Path | None:
    override = _absolute_environment_path(environment, "JJZERO_LEGACY_ROOT")
    if override is not None:
        return override
    return None if is_frozen else source_root


def _workspace_layout(
    environment: Mapping[str, str],
    stored_workspace: Path | None,
    stored_anchor: Path | None,
    legacy_root: Path | None,
) -> tuple[Path, Path]:
    override = _absolute_environment_path(environment, "JJZERO_WORKSPACE_ROOT")
    if override is not None:
        anchor = _absolute_environment_path(environment, "JJZERO_WORKSPACE_ANCHOR")
        return override, anchor or override.parent
    if stored_workspace is not None:
        return stored_workspace, stored_anchor or stored_workspace.parent
    if legacy_root is not None and _contains_user_data(legacy_root / "workspace"):
        return (legacy_root / "workspace").resolve(), legacy_root.resolve()

    user_home = Path(environment.get("USERPROFILE") or Path.home()).expanduser().resolve()
    workspace = user_home / "Music" / APP_DATA_DIR_NAME / "workspace"
    return workspace, workspace.parent


def _runtime_root(
    environment: Mapping[str, str],
    install_root: Path,
    source_root: Path,
    is_frozen: bool,
) -> Path:
    override = _absolute_environment_path(environment, "JJZERO_RUNTIME_ROOT")
    if override is not None:
        return override
    return (install_root / "runtime") if is_frozen else (source_root / "third_party")


def _stored_workspace(path: Path) -> tuple[Path | None, Path | None]:
    if not path.is_file():
        return None, None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None, None
    if not isinstance(data, dict) or data.get("version") != STORAGE_LAYOUT_VERSION:
        return None, None
    return _absolute_data_path(data.get("workspace_root")), _absolute_data_path(
        data.get("workspace_anchor")
    )


def _absolute_environment_path(
    environment: Mapping[str, str],
    name: str,
) -> Path | None:
    return _absolute_data_path(environment.get(name))


def _absolute_data_path(value: object) -> Path | None:
    if not isinstance(value, str) or not value.strip():
        return None
    path = Path(value).expanduser()
    return path.resolve() if path.is_absolute() else None


def _contains_user_data(path: Path) -> bool:
    if not path.is_dir():
        return False
    try:
        return any(child.name != ".gitkeep" for child in path.iterdir())
    except OSError:
        return False
