from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from jang_app.services.audio_export import AudioExportError, AudioMixSource, export_mix
from jang_app.services.audio_export_settings import AudioExportSettings
from jang_app.services.export_names import (
    migrate_legacy_song_exports,
    next_song_export_path,
    timestamp_export_pattern,
)
from jang_app.services.export_catalog import ExportedFile, list_exported_files
from jang_app.services.output_catalog import load_output_sound_set
from jang_app.services.final_audio_export import export_final_audio_mix
from jang_app.services.song_package import EXPORT_STAGE, VOCAL_STAGE, SongPackage
from jang_app.services.studio_session import (
    STUDIO_EFFECT_LEVEL_MATCH,
    TRACK_CONVERTED_VOCAL,
    TRACK_ORIGINAL_VOCAL,
    TRACK_VIDEO,
    StudioAssetRef,
    StudioSession,
    StudioTrackState,
)
from jang_app.services.studio_assets import StudioSoundAsset, resolve_studio_asset
from jang_app.services.studio_audio_levels import studio_source_gain


SongAudioExport = ExportedFile
_LEGACY_MIX_PATTERN = timestamp_export_pattern("mix", ".wav")


def export_song_mix(
    package: SongPackage,
    session: StudioSession,
    settings: AudioExportSettings | None = None,
    progress: Callable[[int], None] | None = None,
) -> Path:
    export_settings = settings or AudioExportSettings()
    sources = build_song_mix_sources(package, session)
    output_path = next_song_export_path(
        song_audio_export_dir(package),
        package.title,
        export_settings.output_label,
        export_settings.extension,
    )
    return export_final_audio_mix(
        sources,
        output_path,
        export_settings,
        progress,
    )


def build_song_mix_sources(
    package: SongPackage,
    session: StudioSession,
    assets: tuple[StudioSoundAsset, ...] | None = None,
) -> tuple[AudioMixSource, ...]:
    if session.tracks:
        sources = _timeline_mix_sources(package, session, assets)
        if not sources:
            raise AudioExportError("Add at least one audible clip to the Studio timeline.")
        return sources

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


def studio_preview_path(package: SongPackage) -> Path:
    return package.folder / "03_studio" / "preview" / "studio-preview.wav"


def render_studio_preview(package: SongPackage, session: StudioSession) -> Path:
    return export_mix(build_song_mix_sources(package, session), studio_preview_path(package))


def list_song_audio_exports(package: SongPackage) -> tuple[SongAudioExport, ...]:
    output_dir = song_audio_export_dir(package)
    migrate_legacy_song_exports(
        output_dir,
        package.title,
        "Audio Mix",
        ".wav",
        _LEGACY_MIX_PATTERN,
    )
    return list_exported_files(output_dir, ("*.wav", "*.flac", "*.mp3", "*.ogg"))


def song_audio_export_dir(package: SongPackage) -> Path:
    return package.folder / EXPORT_STAGE / "audio"


def _volume_multiplier(state: StudioTrackState) -> float:
    return max(0, min(200, state.volume_percent)) / 100.0


def _timeline_mix_sources(
    package: SongPackage,
    session: StudioSession,
    assets: tuple[StudioSoundAsset, ...] | None,
) -> tuple[AudioMixSource, ...]:
    audio_tracks = tuple(track for track in session.tracks if track.role != TRACK_VIDEO)
    has_solo = any(track.solo and not track.muted for track in audio_tracks)
    asset_paths = (
        None
        if assets is None
        else {asset.reference: asset.path for asset in assets}
    )
    sources: list[AudioMixSource] = []
    for track in audio_tracks:
        if track.muted or (has_solo and not track.solo):
            continue
        for clip in track.clips:
            if clip.muted:
                continue
            path = _mix_asset_path(package, clip.asset, asset_paths)
            if path is None:
                continue
            reference_path = None
            if (
                clip.asset.role == TRACK_CONVERTED_VOCAL
                and any(
                    effect.enabled and effect.kind == STUDIO_EFFECT_LEVEL_MATCH
                    for effect in clip.effects
                )
            ):
                reference_path = _mix_asset_path(
                    package,
                    StudioAssetRef(clip.asset.output_id, TRACK_ORIGINAL_VOCAL),
                    asset_paths,
                )
            sources.append(
                AudioMixSource(
                    label=f"{track.name} / {clip.clip_id}",
                    path=path,
                    volume=studio_source_gain(track.volume_percent, clip.gain_db),
                    timeline_start_ms=clip.timeline_start_ms,
                    source_start_ms=clip.source_start_ms,
                    source_end_ms=clip.source_end_ms,
                    fade_in_ms=clip.fade_in_ms,
                    fade_out_ms=clip.fade_out_ms,
                    pan_percent=track.pan_percent,
                    effects=clip.effects,
                    reference_path=reference_path,
                    pitch_semitones=clip.pitch_semitones,
                )
            )
    return tuple(sources)


def _mix_asset_path(
    package: SongPackage,
    reference: StudioAssetRef,
    asset_paths: dict[StudioAssetRef, Path] | None,
) -> Path | None:
    if asset_paths is not None:
        return asset_paths.get(reference)
    return resolve_studio_asset(package, reference)
