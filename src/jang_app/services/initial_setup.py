from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from uuid import uuid4

from jang_app.services.app_paths import (
    INITIAL_SETUP_FILE_NAME,
    INITIAL_SETUP_VERSION,
    AppPaths,
    STORAGE_LAYOUT_VERSION,
)
from jang_app.services.managed_files import write_json_atomic


class InitialSetupError(RuntimeError):
    """Raised when a storage layout cannot be prepared safely."""


def initial_setup_file(paths: AppPaths) -> Path:
    return paths.settings_dir / INITIAL_SETUP_FILE_NAME


def is_initial_setup_complete(paths: AppPaths) -> bool:
    marker = initial_setup_file(paths)
    if not marker.is_file():
        return False
    try:
        import json

        data = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return isinstance(data, dict) and data.get("version") == INITIAL_SETUP_VERSION


def prepare_storage_layout(paths: AppPaths, media_root: Path) -> AppPaths:
    media = media_root.expanduser()
    if not media.is_absolute():
        raise InitialSetupError("Media storage location must be an absolute path.")
    media = media.resolve()
    install = paths.install_root.resolve()
    if paths.is_frozen and (media == install or install in media.parents):
        raise InitialSetupError("Media storage cannot be placed inside the application folder.")

    configured = replace(
        paths,
        workspace_root=media / "workspace",
        workspace_anchor=media,
        output_root=media / "output",
    )
    directories = (
        configured.data_root,
        configured.settings_dir,
        configured.log_dir,
        configured.cache_dir,
        configured.workspace_root,
        configured.output_root / "downloads",
        configured.output_root / "separations",
    )
    for directory in directories:
        _verify_writable_directory(directory)
    return configured


def persist_storage_layout(paths: AppPaths) -> Path:
    write_json_atomic(
        paths.storage_file,
        {
            "version": STORAGE_LAYOUT_VERSION,
            "workspace_root": str(paths.workspace_root),
            "workspace_anchor": str(paths.workspace_anchor),
        },
    )
    return paths.storage_file


def complete_initial_setup(paths: AppPaths, *, diagnostics_ready: bool) -> Path:
    persist_storage_layout(paths)
    marker = initial_setup_file(paths)
    write_json_atomic(
        marker,
        {
            "version": INITIAL_SETUP_VERSION,
            "media_root": str(paths.workspace_anchor),
            "diagnostics_ready": bool(diagnostics_ready),
        },
    )
    return marker


def configure_default_storage(paths: AppPaths) -> AppPaths:
    configured = prepare_storage_layout(paths, paths.workspace_anchor)
    complete_initial_setup(configured, diagnostics_ready=False)
    return configured


def _verify_writable_directory(directory: Path) -> None:
    try:
        directory.mkdir(parents=True, exist_ok=True)
        probe = directory / f".jjzero-write-{uuid4().hex}.tmp"
        probe.write_bytes(b"jjzero")
        probe.unlink()
    except OSError as exc:
        raise InitialSetupError(f"Storage location is not writable: {directory}") from exc
