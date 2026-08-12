from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from jang_app.config import DEFAULT_RVC_ROOT, SEPARATION_OUTPUT_DIR, SETTINGS_FILE
from jang_app.services.i18n import LANGUAGE_KOREAN, normalize_language

RVC_DEVICE_AUTO = "auto"
RVC_DEVICE_GPU = "gpu"
RVC_DEVICE_CPU = "cpu"
RVC_DEVICE_OPTIONS = (RVC_DEVICE_AUTO, RVC_DEVICE_GPU, RVC_DEVICE_CPU)


@dataclass(frozen=True)
class RvcSettings:
    root: Path = DEFAULT_RVC_ROOT
    model_id: str = ""
    voice_model: str = ""
    index_file: str = ""
    pitch: int = 0
    device: str = RVC_DEVICE_AUTO
    f0_method: str = "rmvpe"


@dataclass(frozen=True)
class StudioLayoutSettings:
    workspace_sizes: tuple[int, int, int] = (250, 900, 320)
    center_sizes: tuple[int, int] = (340, 460)


@dataclass(frozen=True)
class AppSettings:
    output_root: Path = SEPARATION_OUTPUT_DIR
    rvc: RvcSettings = field(default_factory=RvcSettings)
    theme_mode: str = "white"
    language: str = LANGUAGE_KOREAN
    studio_layout: StudioLayoutSettings = field(default_factory=StudioLayoutSettings)


def load_app_settings() -> AppSettings:
    if not SETTINGS_FILE.exists():
        return AppSettings()

    try:
        data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return AppSettings()

    default_settings = AppSettings()
    output_root = _path_from_data(data.get("output_root"), default_settings.output_root)
    theme_mode = _theme_mode_from_data(data.get("theme_mode"), default_settings.theme_mode)
    language = normalize_language(data.get("language"))
    studio_layout_data = (
        data.get("studio_layout")
        if isinstance(data.get("studio_layout"), dict)
        else {}
    )
    studio_layout = StudioLayoutSettings(
        workspace_sizes=_size_tuple_from_data(
            studio_layout_data.get("workspace_sizes"),
            default_settings.studio_layout.workspace_sizes,
        ),
        center_sizes=_size_tuple_from_data(
            studio_layout_data.get("center_sizes"),
            default_settings.studio_layout.center_sizes,
        ),
    )
    rvc_data = data.get("rvc") if isinstance(data.get("rvc"), dict) else {}
    rvc = RvcSettings(
        root=_path_from_data(rvc_data.get("root"), default_settings.rvc.root),
        model_id=_string_from_data(rvc_data.get("model_id"), ""),
        voice_model=_string_from_data(rvc_data.get("voice_model"), default_settings.rvc.voice_model),
        index_file=_string_from_data(rvc_data.get("index_file"), default_settings.rvc.index_file),
        pitch=_int_from_data(rvc_data.get("pitch"), default_settings.rvc.pitch),
        device=normalize_rvc_device(rvc_data.get("device")),
        f0_method="rmvpe",
    )
    return AppSettings(
        output_root=output_root,
        rvc=rvc,
        theme_mode=theme_mode,
        language=language,
        studio_layout=studio_layout,
    )


def save_app_settings(settings: AppSettings) -> None:
    SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "output_root": str(settings.output_root.expanduser()),
        "theme_mode": settings.theme_mode,
        "language": normalize_language(settings.language),
        "studio_layout": {
            "workspace_sizes": list(settings.studio_layout.workspace_sizes),
            "center_sizes": list(settings.studio_layout.center_sizes),
        },
        "rvc": {
            "root": str(settings.rvc.root.expanduser()),
            "model_id": settings.rvc.model_id,
            "voice_model": settings.rvc.voice_model,
            "index_file": settings.rvc.index_file,
            "pitch": settings.rvc.pitch,
            "device": settings.rvc.device,
            "f0_method": settings.rvc.f0_method,
        },
    }
    SETTINGS_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _path_from_data(value: object, default: Path) -> Path:
    if not isinstance(value, str) or not value.strip():
        return default
    return Path(value).expanduser()


def _string_from_data(value: object, default: str) -> str:
    if not isinstance(value, str):
        return default
    return value.strip()


def _int_from_data(value: object, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _size_tuple_from_data(
    value: object,
    default: tuple[int, ...],
) -> tuple[int, ...]:
    if not isinstance(value, (list, tuple)) or len(value) != len(default):
        return default
    try:
        sizes = tuple(max(0, min(10_000, int(size))) for size in value)
    except (TypeError, ValueError):
        return default
    return sizes if sum(sizes) > 0 else default


def _theme_mode_from_data(value: object, default: str) -> str:
    if isinstance(value, str) and value in {"dark", "white"}:
        return value
    return default


def normalize_rvc_device(value: object) -> str:
    device = str(value or "").strip().lower()
    if device in RVC_DEVICE_OPTIONS:
        return device
    if device.startswith("cuda") or device in {
        "directml",
        "dml",
        "privateuseone",
        "privateuseone:0",
    }:
        return RVC_DEVICE_GPU
    return RVC_DEVICE_AUTO
