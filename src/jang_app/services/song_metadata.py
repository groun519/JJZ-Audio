from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from jang_app.services.audio_metadata import format_duration, read_audio_metadata
from jang_app.services.output_catalog import load_output_sound_set
from jang_app.services.song_library import SongItem


@dataclass(frozen=True)
class SongDisplayMetadata:
    source_type: str
    source_label: str
    format_label: str
    duration_label: str
    size_label: str
    waveform_path: Path | None

    @property
    def detail_label(self) -> str:
        return f"{self.format_label} | {self.duration_label} | {self.size_label}"


def build_song_display_metadata(song: SongItem, output_root: Path) -> SongDisplayMetadata:
    waveform_path = _waveform_path(song, output_root)
    duration_ms = _duration_ms(song, output_root)
    source_type = _source_type(song)
    return SongDisplayMetadata(
        source_type=source_type,
        source_label=_source_label(source_type),
        format_label=song.format_label,
        duration_label=format_duration(duration_ms) if duration_ms > 0 else "--:--",
        size_label=song.size_label,
        waveform_path=waveform_path,
    )


def _source_type(song: SongItem) -> str:
    if song.source_type in {"local", "youtube", "output"}:
        return song.source_type
    return "output" if song.kind == "output" else "local"


def _source_label(source_type: str) -> str:
    return {"local": "LOCAL", "youtube": "YT", "output": "OUT"}[source_type]


def _duration_ms(song: SongItem, output_root: Path) -> int:
    try:
        if song.kind != "output":
            return read_audio_metadata(song.path).duration_ms
        if song.output_job_dir is None:
            return 0
        sound_set = load_output_sound_set(song.output_job_dir, output_root)
        if sound_set is None:
            return 0
        return max(
            read_audio_metadata(sound_set.vocals_path).duration_ms,
            read_audio_metadata(sound_set.instrumental_path).duration_ms,
        )
    except Exception:
        return 0


def _waveform_path(song: SongItem, output_root: Path) -> Path | None:
    if song.kind != "output":
        return song.path
    if song.output_job_dir is None:
        return song.path
    sound_set = load_output_sound_set(song.output_job_dir, output_root)
    if sound_set is None:
        return song.path
    return sound_set.vocals_path
