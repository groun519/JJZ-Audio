from __future__ import annotations

from datetime import datetime
from pathlib import Path

from jang_app.services.i18n import tr
from jang_app.services.vocal_project import VocalTake


def display_result_timestamp(value: str) -> str:
    try:
        return datetime.fromisoformat(value).astimezone().strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return value


def display_compact_result_timestamp(value: str) -> str:
    try:
        return datetime.fromisoformat(value).astimezone().strftime("%m/%d %H:%M")
    except ValueError:
        return value


def vocal_take_metadata(take: VocalTake | None) -> str:
    if take is None:
        return ""
    if take.conversion is None:
        return tr("Legacy result / Conversion settings unavailable")
    conversion = take.conversion
    model = Path(conversion.voice_model).stem or conversion.voice_model
    index = Path(conversion.index_file).stem if conversion.index_file else tr("No index")
    return (
        f"{model}  /  {tr('Pitch')} {conversion.pitch:+d}  /  {index}  /  "
        f"{conversion.effective_device.upper()}  /  {display_result_timestamp(take.created_at)}"
    )


def vocal_take_tooltip(take: VocalTake | None, path: Path) -> str:
    metadata = vocal_take_metadata(take)
    return f"{metadata}\n{path}" if metadata else str(path)


def vocal_take_label(take: VocalTake | None, path: Path) -> str:
    if take is not None:
        if take.conversion is not None:
            model = Path(take.conversion.voice_model).stem or take.conversion.voice_model
            default_label = f"{model} / Pitch {take.conversion.pitch:+d}"
            if take.label == default_label:
                return f"{model} / {tr('Pitch')} {take.conversion.pitch:+d}"
        if take.label != path.stem:
            return take.label
    return _legacy_take_label(path)


def vocal_take_card_detail(take: VocalTake | None, source_label: str) -> str:
    source = tr(source_label)
    if take is None:
        return source
    timestamp = display_compact_result_timestamp(take.created_at)
    return f"{source} / {timestamp}" if timestamp else source


def vocal_take_summary(take: VocalTake | None) -> str:
    if take is None:
        return tr("Legacy result")
    timestamp = display_result_timestamp(take.created_at)
    if take.conversion is None:
        return f"{tr('Legacy result')}  /  {timestamp}"
    model = Path(take.conversion.voice_model).stem or take.conversion.voice_model
    return f"{model}  /  {tr('Pitch')} {take.conversion.pitch:+d}  /  {timestamp}"


def separation_postprocess_label(status: str) -> str:
    if status == "applied":
        return tr("Mix consistency applied")
    if status == "skipped":
        return tr("Mix consistency skipped")
    return ""


def _legacy_take_label(path: Path) -> str:
    stem = path.stem
    prefix = "vocals_rvc_"
    if not stem.casefold().startswith(prefix):
        return stem
    descriptor = stem[len(prefix):]
    marker = "_pitch_"
    model, separator, settings = descriptor.partition(marker)
    if not separator:
        return descriptor
    pitch_token = settings.split("_", 1)[0].casefold()
    if len(pitch_token) < 2 or pitch_token[0] not in {"m", "p"}:
        return descriptor
    try:
        magnitude = int(pitch_token[1:])
    except ValueError:
        return descriptor
    pitch = -magnitude if pitch_token[0] == "m" else magnitude
    return f"{model} / {tr('Pitch')} {pitch:+d}"
