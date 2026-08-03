from __future__ import annotations

import re
from dataclasses import dataclass

from jang_app.services.output_catalog import OutputSoundSet
from jang_app.services.song_library import SongItem


@dataclass(frozen=True)
class WorkContextDisplay:
    is_active: bool
    source_type: str = ""
    source_label: str = ""
    state_label: str = ""


def build_work_context_display(
    song: SongItem | None,
    output_set: OutputSoundSet | None,
) -> WorkContextDisplay:
    if song is not None:
        source_type = _source_type(song)
        is_output_item = song.kind == "output"
        has_matching_output = output_set is not None and _is_output_for_song(song, output_set)
        return WorkContextDisplay(
            is_active=True,
            source_type=source_type,
            source_label={"local": "LOCAL", "youtube": "YT", "output": "OUT"}[source_type],
            state_label="Output" if is_output_item else "Separated" if has_matching_output else "Source",
        )

    if output_set is not None:
        return WorkContextDisplay(
            is_active=True,
            source_type="output",
            source_label="OUT",
            state_label="Output",
        )

    return WorkContextDisplay(is_active=False)


def _source_type(song: SongItem) -> str:
    if song.source_type in {"local", "youtube", "output"}:
        return song.source_type
    return "output" if song.kind == "output" else "local"


def _is_output_for_song(song: SongItem, output_set: OutputSoundSet) -> bool:
    if song.kind == "output":
        return True
    if song.output_job_dir is not None:
        return song.output_job_dir.expanduser().resolve() == output_set.job_dir.expanduser().resolve()
    return _normalize_name(song.path.stem) == _normalize_name(output_set.job_dir.name)


def _normalize_name(value: str) -> str:
    return re.sub(r"\W+", "", value, flags=re.UNICODE).casefold()
