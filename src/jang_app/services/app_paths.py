from __future__ import annotations

import json
import os
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path


APP_DATA_DIR_NAME = "JJZero Audio"
LEGACY_STORAGE_LAYOUT_VERSION = 1
MANAGED_STORAGE_LAYOUT_VERSION = 2
STORAGE_LAYOUT_VERSION = 3
STORAGE_FILE_NAME = "storage.json"
LEGACY_INITIAL_SETUP_VERSION = 1
MANAGED_INITIAL_SETUP_VERSION = 2
INITIAL_SETUP_VERSION = 3
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
    storage_root: Path
    workspace_root: Path
    workspace_anchor: Path
    output_root: Path
    runtime_root: Path
    catalog_file: Path
    legacy_root: Path | None
    workspace_source: str
    storage_version: int
    storage_mode: str = "linked"

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
    stored = _stored_storage_layout(settings_dir / STORAGE_FILE_NAME)
    stored_workspace = stored.workspace_root if stored is not None else None
    stored_anchor = stored.workspace_anchor if stored is not None else None
    setup_workspace, setup_anchor, setup_output, setup_runtime, setup_cache = _stored_initial_setup_layout(
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
    storage_override = _absolute_environment_path(environment, "JJZERO_STORAGE_ROOT")
    uses_managed_storage = storage_override is not None or (
        stored is not None
        and stored.version in {MANAGED_STORAGE_LAYOUT_VERSION, STORAGE_LAYOUT_VERSION}
    ) or (
        workspace_source == "initial_setup"
        and setup_workspace is not None
        and (
            setup_workspace.name == "Data"
            or any(path is not None for path in (setup_output, setup_runtime, setup_cache))
        )
    )
    storage_root = (
        storage_override
        or (stored.storage_root if uses_managed_storage and stored is not None else None)
        or workspace_anchor
    ).resolve()
    if storage_override is not None:
        workspace_root = storage_root / "Data"
        workspace_anchor = storage_root
        workspace_source = "environment"
    if storage_override is not None:
        output_root = (
            _absolute_environment_path(environment, "JJZERO_OUTPUT_ROOT")
            or storage_root / "Output"
        )
        cache_dir = (
            _absolute_environment_path(environment, "JJZERO_CACHE_ROOT")
            or storage_root / "Cache"
        )
        runtime_default = storage_root / "Runtime"
        storage_version = STORAGE_LAYOUT_VERSION
    elif uses_managed_storage:
        output_root = _absolute_environment_path(environment, "JJZERO_OUTPUT_ROOT") or (
            setup_output
            if workspace_source == "initial_setup" and setup_output is not None
            else stored.output_root
            if stored is not None and stored.output_root is not None
            else storage_root / "Output"
        )
        cache_dir = _absolute_environment_path(environment, "JJZERO_CACHE_ROOT") or (
            setup_cache
            if workspace_source == "initial_setup" and setup_cache is not None
            else stored.cache_root
            if stored is not None and stored.cache_root is not None
            else storage_root / "Cache"
        )
        runtime_default = (
            setup_runtime
            if workspace_source == "initial_setup" and setup_runtime is not None
            else stored.runtime_root
            if stored is not None and stored.runtime_root is not None
            else storage_root / "Runtime"
        )
        storage_version = (
            stored.version
            if stored is not None
            else STORAGE_LAYOUT_VERSION if storage_override is not None else MANAGED_STORAGE_LAYOUT_VERSION
        )
    else:
        output_root = _absolute_environment_path(environment, "JJZERO_OUTPUT_ROOT") or workspace_anchor / "output"
        cache_dir = _absolute_environment_path(environment, "JJZERO_CACHE_ROOT") or data_root / "cache"
        runtime_default = None
        storage_version = (
            STORAGE_LAYOUT_VERSION
            if any(
                _absolute_environment_path(environment, name) is not None
                for name in ("JJZERO_WORKSPACE_ROOT", "JJZERO_OUTPUT_ROOT", "JJZERO_RUNTIME_ROOT", "JJZERO_CACHE_ROOT")
            )
            else LEGACY_STORAGE_LAYOUT_VERSION
        )
    runtime_root = _runtime_root(
        environment,
        install_root,
        resolved_source,
        is_frozen,
        default=runtime_default,
    )
    has_component_override = any(
        _absolute_environment_path(environment, name) is not None
        for name in (
            "JJZERO_WORKSPACE_ROOT",
            "JJZERO_OUTPUT_ROOT",
            "JJZERO_RUNTIME_ROOT",
            "JJZERO_CACHE_ROOT",
        )
    )
    return AppPaths(
        is_frozen=is_frozen,
        source_root=resolved_source,
        install_root=install_root,
        package_root=resolved_package,
        data_root=data_root,
        settings_dir=settings_dir,
        log_dir=data_root / "logs",
        cache_dir=cache_dir.resolve(),
        storage_root=storage_root,
        workspace_root=workspace_root,
        workspace_anchor=workspace_anchor,
        output_root=output_root.resolve(),
        runtime_root=runtime_root,
        catalog_file=(workspace_root / "catalog.db").resolve(),
        legacy_root=legacy_root,
        workspace_source=workspace_source,
        storage_version=storage_version,
        storage_mode=_resolved_storage_mode(
            (
                ""
                if storage_override is not None or has_component_override
                else stored.mode if stored is not None else ""
            ),
            storage_root,
            workspace_root,
            output_root,
            runtime_root,
            cache_dir,
        ),
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
    *,
    default: Path | None = None,
) -> Path:
    override = _absolute_environment_path(environment, "JJZERO_RUNTIME_ROOT")
    if override is not None:
        return override
    if default is not None:
        return default.resolve()
    return (install_root / "runtime") if is_frozen else (source_root / "third_party")


@dataclass(frozen=True)
class _StoredStorageLayout:
    version: int
    storage_root: Path | None
    workspace_root: Path
    workspace_anchor: Path
    output_root: Path | None = None
    runtime_root: Path | None = None
    cache_root: Path | None = None
    mode: str = ""


def _stored_storage_layout(path: Path) -> _StoredStorageLayout | None:
    data = _read_json_object(path)
    if data is None:
        return None
    version = data.get("version")
    if version not in {
        LEGACY_STORAGE_LAYOUT_VERSION,
        MANAGED_STORAGE_LAYOUT_VERSION,
        STORAGE_LAYOUT_VERSION,
    }:
        return None
    workspace = _absolute_data_path(data.get("workspace_root"))
    anchor = _absolute_data_path(data.get("workspace_anchor"))
    if workspace is None:
        return None
    anchor = anchor or workspace.parent
    return _StoredStorageLayout(
        version=int(version),
        storage_root=(
            _absolute_data_path(data.get("storage_root"))
            if version in {MANAGED_STORAGE_LAYOUT_VERSION, STORAGE_LAYOUT_VERSION}
            else anchor
        ),
        workspace_root=workspace,
        workspace_anchor=anchor,
        output_root=_absolute_data_path(data.get("output_root")),
        runtime_root=_absolute_data_path(data.get("runtime_root")),
        cache_root=_absolute_data_path(data.get("cache_root")),
        mode=str(data.get("mode", "")).strip().lower(),
    )


def _stored_initial_setup_layout(
    path: Path,
) -> tuple[Path | None, Path | None, Path | None, Path | None, Path | None]:
    data = _read_json_object(path)
    if data is None or data.get("version") not in {
        LEGACY_INITIAL_SETUP_VERSION,
        MANAGED_INITIAL_SETUP_VERSION,
        INITIAL_SETUP_VERSION,
    }:
        return None, None, None, None, None
    anchor = _absolute_data_path(data.get("storage_root")) or _absolute_data_path(
        data.get("media_root")
    )
    if anchor is None:
        return None, None, None, None, None
    directory_name = (
        "Data"
        if data.get("version") in {MANAGED_INITIAL_SETUP_VERSION, INITIAL_SETUP_VERSION}
        else "workspace"
    )
    workspace = _absolute_data_path(data.get("workspace_root")) or anchor / directory_name
    return (
        workspace,
        anchor,
        _absolute_data_path(data.get("output_root")),
        _absolute_data_path(data.get("runtime_root")),
        _absolute_data_path(data.get("cache_root")),
    )


def _resolved_storage_mode(
    stored_mode: str,
    storage_root: Path,
    workspace_root: Path,
    output_root: Path,
    runtime_root: Path,
    cache_root: Path,
) -> str:
    expected = (
        storage_root / "Data",
        storage_root / "Output",
        storage_root / "Runtime",
        storage_root / "Cache",
    )
    actual = (workspace_root, output_root, runtime_root, cache_root)
    matches_linked = all(
        left.resolve() == right.resolve() for left, right in zip(actual, expected)
    )
    if stored_mode == "custom":
        return "custom"
    return "linked" if matches_linked else "custom"


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
