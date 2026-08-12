from __future__ import annotations

import hashlib
from dataclasses import dataclass, replace
from pathlib import Path

from jang_app.services.audio_metadata import read_audio_metadata
from jang_app.services.output_catalog import converted_vocal_paths
from jang_app.services.song_package import SongOutputReference, SongPackage
from jang_app.services.studio_session import (
    TRACK_CONVERTED_VOCAL,
    TRACK_INSTRUMENTAL,
    TRACK_ORIGINAL_VOCAL,
    TRACK_VIDEO,
    StudioAssetRef,
    StudioClip,
    StudioSession,
    StudioTrack,
    StudioTrackState,
)
from jang_app.services.video_source import VideoSourceStore
from jang_app.services.vocal_project import VocalProjectValidationError, VocalTake
from jang_app.services.vocal_project_store import VocalProjectStore


@dataclass(frozen=True)
class StudioSoundAsset:
    reference: StudioAssetRef
    label: str
    path: Path
    duration_ms: int
    take: VocalTake | None = None
    media_kind: str = "audio"

    @property
    def asset_id(self) -> str:
        return self.reference.asset_id


def studio_sound_pool(package: SongPackage) -> tuple[StudioSoundAsset, ...]:
    assets: list[StudioSoundAsset] = []
    outputs = sorted(
        package.outputs,
        key=lambda output: output.output_id != package.active_output_id,
    )
    for output in outputs:
        assets.extend(_assets_for_output(output))
    assets.extend(_video_assets(package, assets))
    return tuple(assets)


def resolve_studio_asset(package: SongPackage, reference: StudioAssetRef) -> Path | None:
    if reference.role == TRACK_VIDEO:
        return _resolve_video_asset(package, reference)
    output = next(
        (candidate for candidate in package.outputs if candidate.output_id == reference.output_id),
        None,
    )
    if output is None:
        return None
    if reference.role == TRACK_ORIGINAL_VOCAL:
        candidate = output.job_dir / "vocals.wav"
    elif reference.role == TRACK_INSTRUMENTAL:
        candidate = output.job_dir / "no_vocals.wav"
    elif reference.role == TRACK_CONVERTED_VOCAL and reference.filename:
        candidate = output.job_dir / Path(reference.filename).name
    else:
        return None
    resolved = candidate.expanduser().resolve()
    return resolved if resolved.is_file() else None


def sync_studio_video_track(
    package: SongPackage,
    session: StudioSession,
    assets: tuple[StudioSoundAsset, ...],
) -> StudioSession:
    """Keep one timeline video track aligned with the song's active local video."""
    source = VideoSourceStore().resolve(package)
    active_path = (
        source.path.expanduser().resolve()
        if source.path is not None
        else None
    )
    active_asset = next(
        (
            asset
            for asset in assets
            if asset.media_kind == "video"
            and active_path is not None
            and asset.path == active_path
        ),
        None,
    )
    video_tracks = tuple(track for track in session.tracks if track.role == TRACK_VIDEO)
    audio_tracks = tuple(track for track in session.tracks if track.role != TRACK_VIDEO)
    existing = video_tracks[0] if video_tracks else None
    available_references = {
        asset.reference
        for asset in assets
        if asset.media_kind == "video" and asset.duration_ms > 0
    }
    if (
        existing is not None
        and existing.clips
        and all(clip.asset in available_references for clip in existing.clips)
    ):
        return replace(session, tracks=(existing, *audio_tracks))
    if active_asset is None or active_asset.duration_ms <= 0:
        return session if not video_tracks else replace(session, tracks=audio_tracks)

    video_track = StudioTrack(
        track_id="track-video",
        name="Video",
        role=TRACK_VIDEO,
        collapsed=existing.collapsed if existing is not None else False,
        clips=(_full_asset_clip(active_asset, TRACK_VIDEO),),
    )
    return replace(session, tracks=(video_track, *audio_tracks))


def build_default_studio_tracks(
    package: SongPackage,
    states: dict[str, StudioTrackState],
) -> tuple[StudioTrack, ...]:
    output = package.active_output
    if output is None:
        return ()
    assets = _assets_for_output(output)
    selected_converted = _selected_converted_asset(output, assets)
    assets_by_role = {
        asset.reference.role: asset
        for asset in assets
        if asset.reference.role != TRACK_CONVERTED_VOCAL
    }
    if selected_converted is not None:
        assets_by_role[TRACK_CONVERTED_VOCAL] = selected_converted

    definitions = (
        (TRACK_ORIGINAL_VOCAL, "Original Vocal"),
        (TRACK_INSTRUMENTAL, "Instrumental"),
        (TRACK_CONVERTED_VOCAL, "Converted Vocal"),
    )
    tracks: list[StudioTrack] = []
    for role, name in definitions:
        state = states.get(role, StudioTrackState())
        asset = assets_by_role.get(role)
        clips = (_full_asset_clip(asset, role),) if asset is not None and asset.duration_ms > 0 else ()
        tracks.append(
            StudioTrack(
                track_id=f"track-{role.replace('_', '-')}",
                name=name,
                role=role,
                muted=state.muted,
                volume_percent=state.volume_percent,
                pan_percent=state.pan_percent,
                clips=clips,
            )
        )
    return tuple(tracks)


def _assets_for_output(output: SongOutputReference) -> list[StudioSoundAsset]:
    result: list[StudioSoundAsset] = []
    takes_by_path = _vocal_takes_by_path(output.job_dir)
    candidates = (
        (TRACK_ORIGINAL_VOCAL, output.job_dir / "vocals.wav", "Original Vocal"),
        (TRACK_INSTRUMENTAL, output.job_dir / "no_vocals.wav", "Instrumental"),
    )
    for role, path, label in candidates:
        asset = _sound_asset(output, role, path, f"{output.label} / {label}")
        if asset is not None:
            result.append(asset)
    for path in converted_vocal_paths(output.job_dir):
        asset = _sound_asset(
            output,
            TRACK_CONVERTED_VOCAL,
            path,
            f"{output.label} / {path.stem}",
            take=takes_by_path.get(path.expanduser().resolve()),
        )
        if asset is not None:
            result.append(asset)
    return result


def _video_assets(
    package: SongPackage,
    audio_assets: list[StudioSoundAsset],
) -> list[StudioSoundAsset]:
    store = VideoSourceStore()
    active = store.resolve(package)
    sources = (
        [active] if active.path is not None and active.path.is_file() else []
    ) + list(store.managed_sources(package))
    fallback_duration = max((asset.duration_ms for asset in audio_assets), default=0)
    assets: list[StudioSoundAsset] = []
    seen: set[Path] = set()
    for source in sources:
        if source.path is None:
            continue
        resolved = source.path.expanduser().resolve()
        if resolved in seen or not resolved.is_file():
            continue
        seen.add(resolved)
        duration_ms = _media_duration_ms(resolved) or fallback_duration
        reference = StudioAssetRef(_video_output_id(resolved), TRACK_VIDEO, resolved.name)
        assets.append(
            StudioSoundAsset(
                reference,
                source.display_name or resolved.name,
                resolved,
                duration_ms,
                media_kind="video",
            )
        )
    return assets


def _resolve_video_asset(package: SongPackage, reference: StudioAssetRef) -> Path | None:
    store = VideoSourceStore()
    active = store.resolve(package)
    sources = (
        [active] if active.path is not None else []
    ) + list(store.managed_sources(package))
    for source in sources:
        if source.path is None:
            continue
        path = source.path.expanduser().resolve()
        if (
            path.is_file()
            and _video_output_id(path) == reference.output_id
            and path.name == Path(reference.filename).name
        ):
            return path
    return None


def _video_output_id(path: Path) -> str:
    digest = hashlib.sha1(
        path.name.casefold().encode("utf-8"),
        usedforsecurity=False,
    ).hexdigest()[:12]
    return f"video-{digest}"


def _media_duration_ms(path: Path) -> int:
    try:
        return max(0, read_audio_metadata(path).duration_ms)
    except Exception:
        return 0


def _sound_asset(
    output: SongOutputReference,
    role: str,
    path: Path,
    label: str,
    *,
    take: VocalTake | None = None,
) -> StudioSoundAsset | None:
    resolved = path.expanduser().resolve()
    if not resolved.is_file():
        return None
    try:
        duration_ms = max(0, read_audio_metadata(resolved).duration_ms)
    except Exception:
        duration_ms = 0
    filename = resolved.name if role == TRACK_CONVERTED_VOCAL else ""
    return StudioSoundAsset(
        StudioAssetRef(output.output_id, role, filename),
        label,
        resolved,
        duration_ms,
        take,
    )


def _vocal_takes_by_path(job_dir: Path) -> dict[Path, VocalTake]:
    try:
        project = VocalProjectStore().load(job_dir)
    except (OSError, VocalProjectValidationError):
        return {}
    if project is None:
        return {}
    return {
        take.output_path.expanduser().resolve(): take
        for take in project.takes
        if take.output_path.is_file()
    }


def _selected_converted_asset(
    output: SongOutputReference,
    assets: list[StudioSoundAsset],
) -> StudioSoundAsset | None:
    converted = [
        asset for asset in assets if asset.reference.role == TRACK_CONVERTED_VOCAL
    ]
    selected = output.active_converted_path
    if selected is not None:
        resolved = selected.expanduser().resolve()
        matched = next((asset for asset in converted if asset.path == resolved), None)
        if matched is not None:
            return matched
    return converted[0] if converted else None


def _full_asset_clip(asset: StudioSoundAsset, role: str) -> StudioClip:
    digest = hashlib.sha1(asset.asset_id.encode("utf-8"), usedforsecurity=False).hexdigest()[:12]
    return StudioClip(
        clip_id=f"clip-{role.replace('_', '-')}-{digest}",
        asset=asset.reference,
        timeline_start_ms=0,
        source_start_ms=0,
        source_end_ms=asset.duration_ms,
    )
