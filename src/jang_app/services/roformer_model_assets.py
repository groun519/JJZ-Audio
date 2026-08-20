from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

from jang_app.services.app_update import ReleaseArtifact, UpdateError, download_artifact
from jang_app.services.managed_files import write_json_atomic, write_text_atomic
from jang_app.services.separation_assets import RoFormerModelAssets, roformer_model_assets


ProgressCallback = Callable[[int], None]
MODEL_REGISTRY_FILE = "download_checks.json"


class RoFormerModelAssetError(RuntimeError):
    pass


@dataclass(frozen=True)
class PreparedRoFormerAssets:
    files: tuple[Path, ...]
    registry: Path


def prepare_roformer_model_assets(
    model: str,
    model_root: Path,
    progress: ProgressCallback | None = None,
) -> PreparedRoFormerAssets:
    assets = roformer_model_assets(model)
    if assets is None:
        raise RoFormerModelAssetError(f"Unsupported precision separation model: {model}")

    root = model_root.expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    pending = tuple(
        item
        for item in assets.files
        if not _file_has_size(root / item.filename, item.size)
    )
    total = sum(item.size for item in pending)
    completed = 0
    try:
        for item in pending:

            def report_file(value: int, *, base: int = completed, size: int = item.size) -> None:
                _report(progress, round((base + size * value / 100) * 100 / total))

            download_artifact(
                ReleaseArtifact(
                    name=item.filename,
                    size=item.size,
                    sha256=item.sha256,
                    url=item.url,
                ),
                root,
                progress=report_file,
                timeout=300.0,
            )
            completed += item.size
    except UpdateError as exc:
        raise RoFormerModelAssetError(
            f"Could not prepare precision separation model {model}: {exc}"
        ) from exc

    runtime_config = _prepare_runtime_config(root, assets)
    registry = _update_model_registry(root, assets)
    _report(progress, 100)
    prepared_files = [root / item.filename for item in assets.files]
    if runtime_config is not None and runtime_config not in prepared_files:
        prepared_files.append(runtime_config)
    return PreparedRoFormerAssets(
        files=tuple(prepared_files),
        registry=registry,
    )


def _prepare_runtime_config(root: Path, assets: RoFormerModelAssets) -> Path | None:
    if not assets.config:
        return None
    source = root / (assets.config_source or assets.config)
    target = root / assets.config
    if not assets.config_replacements:
        if not source.is_file():
            raise RoFormerModelAssetError(
                f"Precision separation config is missing: {source.name}"
            )
        return source
    try:
        text = source.read_text(encoding="utf-8")
    except OSError as exc:
        raise RoFormerModelAssetError(
            f"Could not read precision separation config {source.name}: {exc}"
        ) from exc
    for original, replacement in assets.config_replacements:
        if original not in text:
            raise RoFormerModelAssetError(
                f"Precision separation config is incompatible: {source.name}"
            )
        text = text.replace(original, replacement)
    write_text_atomic(target, text)
    return target


def _update_model_registry(root: Path, assets: RoFormerModelAssets) -> Path:
    target = root / MODEL_REGISTRY_FILE
    data = _load_registry(target)
    downloads = data.setdefault(assets.registry_group, {})
    if not isinstance(downloads, dict):
        downloads = {}
        data[assets.registry_group] = downloads
    downloads[assets.registry_name] = (
        assets.model
        if assets.registry_group == "vr_download_list"
        else {assets.model: assets.config}
    )
    write_json_atomic(target, data)
    return target


def _load_registry(path: Path) -> dict[str, object]:
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        loaded = {}
    data = dict(loaded) if isinstance(loaded, Mapping) else {}
    for key in (
        "vr_download_list",
        "mdx_download_list",
        "mdx_download_vip_list",
        "demucs_download_list",
        "mdx23c_download_list",
        "mdx23c_download_vip_list",
        "roformer_download_list",
    ):
        if not isinstance(data.get(key), dict):
            data[key] = {}
    return data


def _file_has_size(path: Path, expected_size: int) -> bool:
    try:
        return path.is_file() and path.stat().st_size == expected_size
    except OSError:
        return False


def _report(progress: ProgressCallback | None, value: int) -> None:
    if progress is not None:
        progress(max(0, min(100, value)))
