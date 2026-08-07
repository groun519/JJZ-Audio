from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from uuid import uuid4

from jang_app.services.app_paths import (
    INITIAL_SETUP_FILE_NAME,
    INITIAL_SETUP_VERSION,
    LEGACY_INITIAL_SETUP_VERSION,
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
    return isinstance(data, dict) and data.get("version") in {
        LEGACY_INITIAL_SETUP_VERSION,
        2,
        INITIAL_SETUP_VERSION,
    }


def build_storage_layout(paths: AppPaths, media_root: Path) -> AppPaths:
    media = normalize_storage_root(media_root)
    return build_custom_storage_layout(
        paths,
        workspace_root=media / "Data",
        output_root=media / "Output",
        runtime_root=media / "Runtime",
        cache_root=media / "Cache",
        storage_root=media,
        mode="linked",
    )


def build_custom_storage_layout(
    paths: AppPaths,
    *,
    workspace_root: Path,
    output_root: Path,
    runtime_root: Path,
    cache_root: Path,
    storage_root: Path | None = None,
    mode: str = "custom",
) -> AppPaths:
    roots = tuple(
        _absolute_storage_path(path, label)
        for label, path in (
            ("Data", workspace_root),
            ("Output", output_root),
            ("Runtime", runtime_root),
            ("Cache", cache_root),
        )
    )
    _validate_storage_roots(paths, roots)
    workspace, output, runtime, cache = roots
    anchor = _absolute_storage_path(storage_root or workspace.parent, "Storage")
    normalized_mode = mode.strip().lower()
    if normalized_mode not in {"linked", "custom"}:
        raise InitialSetupError(f"Unsupported storage mode: {mode}")

    return replace(
        paths,
        storage_root=anchor,
        workspace_root=workspace,
        workspace_anchor=workspace.parent,
        output_root=output,
        runtime_root=runtime,
        cache_dir=cache,
        catalog_file=workspace / "catalog.db",
        workspace_source="storage",
        storage_version=STORAGE_LAYOUT_VERSION,
        storage_mode=normalized_mode,
    )


def normalize_storage_root(media_root: Path) -> Path:
    media = media_root.expanduser()
    if not media.is_absolute():
        raise InitialSetupError("Media storage location must be an absolute path.")
    media = media.resolve()
    if media.anchor and media == Path(media.anchor):
        return media / "JJZero Audio"
    return media


def prepare_storage_layout(paths: AppPaths, media_root: Path) -> AppPaths:
    configured = build_storage_layout(paths, media_root)
    return prepare_configured_storage_layout(configured)


def prepare_configured_storage_layout(configured: AppPaths) -> AppPaths:
    directories = (
        configured.data_root,
        configured.settings_dir,
        configured.log_dir,
        configured.cache_dir,
        configured.runtime_root,
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
            "mode": paths.storage_mode,
            "storage_root": str(paths.storage_root),
            "workspace_root": str(paths.workspace_root),
            "workspace_anchor": str(paths.workspace_anchor),
            "output_root": str(paths.output_root),
            "runtime_root": str(paths.runtime_root),
            "cache_root": str(paths.cache_dir),
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
            "storage_root": str(paths.storage_root),
            "media_root": str(paths.workspace_anchor),
            "workspace_root": str(paths.workspace_root),
            "output_root": str(paths.output_root),
            "runtime_root": str(paths.runtime_root),
            "cache_root": str(paths.cache_dir),
            "diagnostics_ready": bool(diagnostics_ready),
        },
    )
    return marker


def configure_default_storage(paths: AppPaths) -> AppPaths:
    configured = prepare_storage_layout(paths, paths.workspace_anchor)
    complete_initial_setup(configured, diagnostics_ready=False)
    return configured


def promote_storage_layout(paths: AppPaths) -> AppPaths:
    if paths.storage_version == STORAGE_LAYOUT_VERSION:
        return paths
    promoted = replace(
        paths,
        storage_version=STORAGE_LAYOUT_VERSION,
        storage_mode=_infer_storage_mode(paths),
    )
    persist_storage_layout(promoted)
    return promoted


def _absolute_storage_path(path: Path, label: str) -> Path:
    candidate = path.expanduser()
    if not candidate.is_absolute():
        raise InitialSetupError(f"{label} storage location must be an absolute path.")
    candidate = candidate.resolve()
    if candidate.anchor and candidate == Path(candidate.anchor):
        base = candidate / "JJZero Audio"
        return base if label == "Storage" else base / label
    return candidate


def _validate_storage_roots(paths: AppPaths, roots: tuple[Path, ...]) -> None:
    install = paths.install_root.resolve()
    current = (
        paths.workspace_root.resolve(),
        paths.output_root.resolve(),
        paths.runtime_root.resolve(),
        paths.cache_dir.resolve(),
    )
    for root, existing in zip(roots, current):
        if root == existing:
            continue
        if paths.is_frozen and (root == install or install in root.parents):
            raise InitialSetupError("Storage cannot be placed inside the application folder.")
    for index, root in enumerate(roots):
        for other in roots[index + 1 :]:
            if root == other or root in other.parents or other in root.parents:
                raise InitialSetupError("Data, Output, Runtime, and Cache locations cannot overlap.")


def _infer_storage_mode(paths: AppPaths) -> str:
    root = paths.storage_root.resolve()
    expected = (root / "Data", root / "Output", root / "Runtime", root / "Cache")
    actual = (paths.workspace_root, paths.output_root, paths.runtime_root, paths.cache_dir)
    return "linked" if all(left.resolve() == right.resolve() for left, right in zip(actual, expected)) else "custom"


def _verify_writable_directory(directory: Path) -> None:
    try:
        directory.mkdir(parents=True, exist_ok=True)
        probe = directory / f".jjzero-write-{uuid4().hex}.tmp"
        probe.write_bytes(b"jjzero")
        probe.unlink()
    except OSError as exc:
        raise InitialSetupError(f"Storage location is not writable: {directory}") from exc
