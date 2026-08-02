from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from jang_app.services.audio_export import AudioExportError, AudioMixSource, export_mix
from jang_app.services.export_catalog import ExportedFile, list_exported_files
from jang_app.services.output_catalog import load_output_sound_set
from jang_app.services.song_package import EXPORT_STAGE, VOCAL_STAGE, SongPackage
from jang_app.services.studio_session import StudioSession, StudioTrackState


SongAudioExport = ExportedFile


def export_song_mix(package: SongPackage, session: StudioSession) -> Path:
    sources = build_song_mix_sources(package, session)
    output_path = _next_mix_path(song_audio_export_dir(package))
    return export_mix(sources, output_path)


def build_song_mix_sources(package: SongPackage, session: StudioSession) -> tuple[AudioMixSource, ...]:
    output = package.active_output
    if output is None:
        raise AudioExportError("Separate the selected song before exporting.")

    sound_set = load_output_sound_set(output.job_dir, package.folder / VOCAL_STAGE)
    if sound_set is None:
        raise AudioExportError("The active vocal output is unavailable.")

    converted_path = output.active_converted_path
    if converted_path not in sound_set.converted_vocal_paths:
        converted_path = sound_set.converted_vocal_paths[0] if sound_set.converted_vocal_paths else None

    candidates = (
        ("Original Vocal", sound_set.vocals_path, session.original_vocal),
        ("Instrumental", sound_set.instrumental_path, session.instrumental),
        ("Converted Vocal", converted_path, session.converted_vocal),
    )
    sources = tuple(
        AudioMixSource(label, path, _volume_multiplier(state))
        for label, path, state in candidates
        if path is not None and not state.muted
    )
    if not sources:
        raise AudioExportError("Select at least one unmuted track before exporting a mix.")
    return sources


def list_song_audio_exports(package: SongPackage) -> tuple[SongAudioExport, ...]:
    return list_exported_files(song_audio_export_dir(package), "*.wav")


def song_audio_export_dir(package: SongPackage) -> Path:
    return package.folder / EXPORT_STAGE / "audio"


def _next_mix_path(output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    stem = f"mix-{datetime.now(UTC):%Y%m%d-%H%M%S}"
    candidate = output_dir / f"{stem}.wav"
    suffix = 2
    while candidate.exists():
        candidate = output_dir / f"{stem}-{suffix:03d}.wav"
        suffix += 1
    return candidate


def _volume_multiplier(state: StudioTrackState) -> float:
    return max(0, min(200, state.volume_percent)) / 100.0
