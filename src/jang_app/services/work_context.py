from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from jang_app.services.audio_metadata import format_duration, read_audio_metadata
from jang_app.services.output_catalog import OutputSoundSet
from jang_app.services.song_library import SongItem
from jang_app.services.song_metadata import build_song_display_metadata


@dataclass(frozen=True)
class WorkContextDisplay:
    is_active: bool
    title: str = ""
    source_type: str = ""
    source_label: str = ""
    detail_label: str = ""
    state_label: str = ""
    output_label: str = ""


def build_work_context_display(
    song: SongItem | None,
    output_set: OutputSoundSet | None,
    output_root: Path,
) -> WorkContextDisplay:
    if song is not None:
        metadata = build_song_display_metadata(song, output_root)
        is_output_item = song.kind == "output"
        has_matching_output = output_set is not None and _is_output_for_song(song, output_set)
        return WorkContextDisplay(
            is_active=True,
            title=song.title,
            source_type=metadata.source_type,
            source_label=metadata.source_label,
            detail_label=metadata.detail_label,
            state_label="Output" if is_output_item else "Separated" if has_matching_output else "Source",
            output_label=output_set.label if has_matching_output and not is_output_item else "",
        )

    if output_set is not None:
        return WorkContextDisplay(
            is_active=True,
            title=output_set.label,
            source_type="output",
            source_label="OUT",
            detail_label=_output_detail_label(output_set),
            state_label="Output",
            output_label="",
        )

    return WorkContextDisplay(is_active=False)


def _output_detail_label(output_set: OutputSoundSet) -> str:
    duration_ms = _output_duration_ms(output_set)
    converted_count = len(output_set.converted_vocal_paths)
    converted_label = f"{converted_count} CV" if converted_count else "No CV"
    return f"OUTPUT | {format_duration(duration_ms) if duration_ms > 0 else '--:--'} | {converted_label}"


def _output_duration_ms(output_set: OutputSoundSet) -> int:
    durations: list[int] = []
    for path in (output_set.vocals_path, output_set.instrumental_path):
        try:
            durations.append(read_audio_metadata(path).duration_ms)
        except Exception:
            continue
    return max(durations, default=0)


def _is_output_for_song(song: SongItem, output_set: OutputSoundSet) -> bool:
    if song.kind == "output":
        return True
    return _normalize_name(song.path.stem) == _normalize_name(output_set.job_dir.name)


def _normalize_name(value: str) -> str:
    return re.sub(r"\W+", "", value, flags=re.UNICODE).casefold()
