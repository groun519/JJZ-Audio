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
INITIAL_SETUP_VERSION = 1
INITIAL_SETUP_FILE_NAME = "initial_setup.json"


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
    workspace_source: str

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
    setup_workspace, setup_anchor = _stored_initial_setup_workspace(
        settings_dir / INITIAL_SETUP_FILE_NAME
    )
    legacy_root = _legacy_root(
        environment,
        resolved_source,
        install_root,
        is_frozen,
    )
    workspace_root, workspace_anchor, workspace_source = _workspace_layout(
        environment,
        stored_workspace,
        stored_anchor,
        setup_workspace,
        setup_anchor,
        legacy_root,
        legacy_source="legacy_install" if is_frozen else "legacy_source",
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
        workspace_source=workspace_source,
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
    install_root: Path,
    is_frozen: bool,
) -> Path | None:
    override = _absolute_environment_path(environment, "JJZERO_LEGACY_ROOT")
    if override is not None:
        return override
    if not is_frozen:
        return source_root
    if _contains_legacy_data(install_root):
        return install_root
    return None


def _workspace_layout(
    environment: Mapping[str, str],
    stored_workspace: Path | None,
    stored_anchor: Path | None,
    setup_workspace: Path | None,
    setup_anchor: Path | None,
    legacy_root: Path | None,
    legacy_source: str,
) -> tuple[Path, Path, str]:
    override = _absolute_environment_path(environment, "JJZERO_WORKSPACE_ROOT")
    if override is not None:
        anchor = _absolute_environment_path(environment, "JJZERO_WORKSPACE_ANCHOR")
        return override, anchor or override.parent, "environment"

    legacy_workspace = legacy_root / "workspace" if legacy_root is not None else None
    candidates = (
        (stored_workspace, stored_anchor, "storage"),
        (setup_workspace, setup_anchor, "initial_setup"),
        (legacy_workspace, legacy_root, legacy_source),
    )
    for workspace, anchor, source in candidates:
        if workspace is not None and _contains_workspace_files(workspace):
            return workspace.resolve(), (anchor or workspace.parent).resolve(), source

    if stored_workspace is not None:
        return stored_workspace, stored_anchor or stored_workspace.parent, "storage"
    if setup_workspace is not None:
        return setup_workspace, setup_anchor or setup_workspace.parent, "initial_setup"
    if legacy_root is not None and _contains_user_data(legacy_root / "workspace"):
        return (legacy_root / "workspace").resolve(), legacy_root.resolve(), legacy_source

    user_home = Path(environment.get("USERPROFILE") or Path.home()).expanduser().resolve()
    workspace = user_home / "Music" / APP_DATA_DIR_NAME / "workspace"
    return workspace, workspace.parent, "default"


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
    data = _read_json_object(path)
    if data is None or data.get("version") != STORAGE_LAYOUT_VERSION:
        return None, None
    return _absolute_data_path(data.get("workspace_root")), _absolute_data_path(
        data.get("workspace_anchor")
    )


def _stored_initial_setup_workspace(path: Path) -> tuple[Path | None, Path | None]:
    data = _read_json_object(path)
    if data is None or data.get("version") != INITIAL_SETUP_VERSION:
        return None, None
    anchor = _absolute_data_path(data.get("media_root"))
    if anchor is None:
        return None, None
    return anchor / "workspace", anchor


def _read_json_object(path: Path) -> dict[str, object] | None:
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


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


def _contains_workspace_files(path: Path) -> bool:
    if not path.is_dir():
        return False
    try:
        return any(
            child.is_file() and child.name != ".gitkeep"
            for child in path.rglob("*")
        )
    except OSError:
        return False


def _contains_legacy_data(root: Path) -> bool:
    return _contains_user_data(root / "workspace") or any(
        (root / "settings" / name).is_file()
        for name in ("app_settings.json", "song_library.json", "work_song.json")
    )
