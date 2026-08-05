from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from jang_app.services.settings import RvcSettings


def settings_for_managed_rvc_runtime(
    settings: RvcSettings,
    managed_root: Path,
) -> RvcSettings:
    """Keep external model paths while routing execution through the managed runtime."""
    source_root = settings.root.expanduser().resolve()
    return replace(
        settings,
        root=managed_root.expanduser().resolve(),
        voice_model=_absolute_setting_path(source_root, settings.voice_model),
        index_file=_absolute_setting_path(source_root, settings.index_file),
    )


def _absolute_setting_path(root: Path, value: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        return ""
    path = Path(cleaned).expanduser()
    return str((path if path.is_absolute() else root / path).resolve())
