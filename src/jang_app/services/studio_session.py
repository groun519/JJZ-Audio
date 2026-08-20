from __future__ import annotations

import hashlib
import json
import logging
import math
from dataclasses import dataclass, field, fields, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from jang_app.services.managed_files import write_json_atomic
from jang_app.services.song_package import STUDIO_STAGE, SongPackage
from jang_app.services.studio_audio_levels import clamp_studio_clip_gain_db
from jang_app.services.studio_pitch import clamp_studio_clip_pitch

if TYPE_CHECKING:
    from jang_app.services.studio_assets import StudioSoundAsset


STUDIO_SESSION_VERSION = 11
STUDIO_SESSION_PREVIOUS_VERSIONS = {2, 3, 4, 5, 6, 7, 8, 9, 10}
STUDIO_SESSION_LEGACY_VERSION = 1
STUDIO_SESSION_NAME = "session.json"
STUDIO_SESSION_HISTORY_DIR = ".history"
STUDIO_SESSION_HISTORY_LIMIT = 50
TRACK_ORIGINAL_VOCAL = "original_vocal"
TRACK_INSTRUMENTAL = "instrumental"
TRACK_CONVERTED_VOCAL = "converted_vocal"
TRACK_AUDIO = "audio"
TRACK_VIDEO = "video"
STUDIO_EFFECT_REVERB = "reverb"
STUDIO_EFFECT_DELAY = "delay"
STUDIO_EFFECT_DOUBLER = "doubler"
STUDIO_EFFECT_RADIO_FILTER = "radio_filter"
STUDIO_EFFECT_RING_MODULATOR = "ring_modulator"
STUDIO_EFFECT_BITCRUSHER = "bitcrusher"
STUDIO_EFFECT_DISTORTION = "distortion"
STUDIO_EFFECT_LEVEL_MATCH = "level_match"
STUDIO_EFFECT_HARD_TUNE = "hard_tune"
SUPPORTED_STUDIO_EFFECTS = {
    STUDIO_EFFECT_REVERB,
    STUDIO_EFFECT_DELAY,
    STUDIO_EFFECT_DOUBLER,
    STUDIO_EFFECT_RADIO_FILTER,
    STUDIO_EFFECT_RING_MODULATOR,
    STUDIO_EFFECT_BITCRUSHER,
    STUDIO_EFFECT_DISTORTION,
    STUDIO_EFFECT_LEVEL_MATCH,
    STUDIO_EFFECT_HARD_TUNE,
}
MEDIA_FIT = "fit"
MEDIA_FILL = "fill"
SUPPORTED_MEDIA_FIT_MODES = {MEDIA_FIT, MEDIA_FILL}
SUPPORTED_TRACK_ROLES = {
    TRACK_ORIGINAL_VOCAL,
    TRACK_INSTRUMENTAL,
    TRACK_CONVERTED_VOCAL,
    TRACK_AUDIO,
    TRACK_VIDEO,
}


@dataclass(frozen=True)
class StudioTrackState:
    muted: bool = False
    volume_percent: int = 100
    pan_percent: int = 0


@dataclass(frozen=True)
class StudioAssetRef:
    output_id: str
    role: str
    filename: str = ""

    @property
    def asset_id(self) -> str:
        return ":".join((self.output_id, self.role, self.filename))


@dataclass(frozen=True)
class StudioReverbSettings:
    room_height_m: float = 2.5
    room_length_m: float = 4.0
    room_width_m: float = 5.0
    pre_delay_ms: int = 0
    decay_ms: int = 950
    distance_m: float = 1.75
    brightness_percent: int = 50
    modulation_percent: int = 2
    early_low_hz: int = 300
    early_high_hz: int = 10_000
    early_low_gain_db: float = 0.0
    early_high_gain_db: float = 0.0
    reverb_low_hz: int = 300
    reverb_high_hz: int = 10_000
    reverb_low_gain_db: float = 0.0
    reverb_high_gain_db: float = 0.0
    dry_wet_percent: int = 30
    direct_gain_db: float = 0.0
    early_gain_db: float = 0.0
    reverb_gain_db: float = 0.0


@dataclass(frozen=True)
class StudioDelaySettings:
    delay_ms: int = 320
    feedback_percent: int = 32
    dry_wet_percent: int = 24
    stereo_width_percent: int = 35


@dataclass(frozen=True)
class StudioDoublerSettings:
    voice_spacing_ms: int = 18
    pitch_spread_cents: int = 6
    stereo_width_percent: int = 55
    dry_wet_percent: int = 22


@dataclass(frozen=True)
class StudioRadioFilterSettings:
    low_cut_hz: int = 280
    high_cut_hz: int = 4_800
    mix_percent: int = 100


@dataclass(frozen=True)
class StudioRingModulatorSettings:
    frequency_hz: int = 72
    mix_percent: int = 28


@dataclass(frozen=True)
class StudioBitcrusherSettings:
    bit_depth: int = 10
    sample_rate_hz: int = 16_000
    mix_percent: int = 35


@dataclass(frozen=True)
class StudioDistortionSettings:
    drive_percent: int = 35
    mix_percent: int = 28


@dataclass(frozen=True)
class StudioLevelMatchSettings:
    strength_percent: int = 75
    response_ms: int = 180
    max_correction_db: int = 6
    silence_threshold_db: int = -50


@dataclass(frozen=True)
class StudioHardTuneSettings:
    key_note: int = 0
    scale: str = "chromatic"
    strength_percent: int = 90
    response_ms: int = 45
    vibrato_preserve_percent: int = 20


@dataclass(frozen=True)
class StudioEffect:
    effect_id: str
    kind: str
    enabled: bool = True
    reverb: StudioReverbSettings = field(default_factory=StudioReverbSettings)
    delay: StudioDelaySettings = field(default_factory=StudioDelaySettings)
    doubler: StudioDoublerSettings = field(default_factory=StudioDoublerSettings)
    radio_filter: StudioRadioFilterSettings = field(default_factory=StudioRadioFilterSettings)
    ring_modulator: StudioRingModulatorSettings = field(
        default_factory=StudioRingModulatorSettings
    )
    bitcrusher: StudioBitcrusherSettings = field(default_factory=StudioBitcrusherSettings)
    distortion: StudioDistortionSettings = field(default_factory=StudioDistortionSettings)
    level_match: StudioLevelMatchSettings = field(default_factory=StudioLevelMatchSettings)
    hard_tune: StudioHardTuneSettings = field(default_factory=StudioHardTuneSettings)


@dataclass(frozen=True)
class StudioMediaSettings:
    fit_mode: str = MEDIA_FIT
    scale_percent: int = 100
    offset_x_percent: int = 0
    offset_y_percent: int = 0
    source_audio_enabled: bool = False


@dataclass(frozen=True)
class StudioClip:
    clip_id: str
    asset: StudioAssetRef
    timeline_start_ms: int
    source_start_ms: int
    source_end_ms: int
    gain_db: float = 0.0
    pitch_semitones: int = 0
    muted: bool = False
    fade_in_ms: int = 0
    fade_out_ms: int = 0
    effects: tuple[StudioEffect, ...] = ()
    media: StudioMediaSettings = field(default_factory=StudioMediaSettings)

    @property
    def duration_ms(self) -> int:
        return max(0, self.source_end_ms - self.source_start_ms)

    @property
    def timeline_end_ms(self) -> int:
        return self.timeline_start_ms + self.duration_ms


@dataclass(frozen=True)
class StudioTrack:
    track_id: str
    name: str
    role: str = TRACK_AUDIO
    muted: bool = False
    solo: bool = False
    volume_percent: int = 100
    pan_percent: int = 0
    collapsed: bool = False
    clips: tuple[StudioClip, ...] = ()

    @property
    def state(self) -> StudioTrackState:
        return StudioTrackState(self.muted, self.volume_percent, self.pan_percent)


@dataclass(frozen=True)
class StudioSession:
    # Legacy fields remain as a compatibility bridge while the fixed-track UI is removed.
    original_vocal: StudioTrackState = field(default_factory=StudioTrackState)
    instrumental: StudioTrackState = field(default_factory=StudioTrackState)
    converted_vocal: StudioTrackState = field(default_factory=StudioTrackState)
    tracks: tuple[StudioTrack, ...] = ()
    updated_at: str = ""

    def state_for(self, track_key: str) -> StudioTrackState:
        timeline_track = next((track for track in self.tracks if track.role == track_key), None)
        if timeline_track is not None:
            return timeline_track.state
        if track_key == TRACK_ORIGINAL_VOCAL:
            return self.original_vocal
        if track_key == TRACK_INSTRUMENTAL:
            return self.instrumental
        if track_key == TRACK_CONVERTED_VOCAL:
            return self.converted_vocal
        raise KeyError(f"Unknown studio track: {track_key}")


def load_studio_session(
    package: SongPackage,
    *,
    assets: tuple[StudioSoundAsset, ...] | None = None,
) -> StudioSession:
    assets = _studio_assets(package, assets)
    path = studio_session_path(package)
    if not path.is_file():
        return _session_with_default_tracks(package, StudioSession(), assets)
    data = _read_session_data(path, package.song_id)
    if data is None:
        data = _latest_valid_history_data(package)
        if data is not None:
            logging.getLogger("jang_app").warning(
                "Recovered invalid Studio session from history | song=%s",
                package.song_id,
            )
    if data is None:
        return _session_with_default_tracks(package, StudioSession(), assets)

    version = data.get("version")
    if version == STUDIO_SESSION_LEGACY_VERSION:
        legacy = _legacy_session_from_data(data)
        return _session_with_default_tracks(package, legacy, assets)
    if version not in (*STUDIO_SESSION_PREVIOUS_VERSIONS, STUDIO_SESSION_VERSION):
        return _session_with_default_tracks(package, StudioSession(), assets)

    tracks = _tracks_from_data(data.get("tracks"))
    if not tracks:
        return _session_with_default_tracks(
            package,
            StudioSession(updated_at=str(data.get("updated_at", ""))),
            assets,
        )
    return _session_with_required_tracks(
        package,
        _session_from_tracks(tracks, updated_at=str(data.get("updated_at", ""))),
        assets,
    )


def save_studio_session(
    package: SongPackage,
    session: StudioSession,
    *,
    assets: tuple[StudioSoundAsset, ...] | None = None,
) -> Path:
    path = studio_session_path(package)
    normalized = _normalized_session(package, session, _studio_assets(package, assets))
    payload = {
        "version": STUDIO_SESSION_VERSION,
        "song_id": package.song_id,
        "updated_at": normalized.updated_at,
        "tracks": [_track_to_data(track) for track in normalized.tracks],
    }
    previous = _read_session_data(path, package.song_id) if path.is_file() else None
    if previous is not None and previous.get("tracks") == payload["tracks"]:
        return path
    if previous is not None:
        _archive_session_data(package, previous)
    write_json_atomic(path, payload)
    return path


def studio_session_path(package: SongPackage) -> Path:
    return package.folder / STUDIO_STAGE / STUDIO_SESSION_NAME


def studio_session_history_paths(package: SongPackage) -> tuple[Path, ...]:
    root = studio_session_path(package).parent / STUDIO_SESSION_HISTORY_DIR
    if not root.is_dir():
        return ()
    return tuple(sorted(root.glob("session-*.json"), reverse=True))


def remove_studio_session_history(package: SongPackage) -> None:
    root = studio_session_path(package).parent / STUDIO_SESSION_HISTORY_DIR
    if not root.is_dir():
        return
    for path in root.glob("session-*.json"):
        path.unlink(missing_ok=True)
    try:
        root.rmdir()
    except OSError:
        pass


def _read_session_data(path: Path, song_id: str) -> dict[str, object] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None
    if not isinstance(data, dict) or data.get("song_id") not in (None, "", song_id):
        return None
    version = data.get("version")
    if version not in (
        STUDIO_SESSION_LEGACY_VERSION,
        *STUDIO_SESSION_PREVIOUS_VERSIONS,
        STUDIO_SESSION_VERSION,
    ):
        return None
    return data


def _latest_valid_history_data(package: SongPackage) -> dict[str, object] | None:
    for path in studio_session_history_paths(package):
        data = _read_session_data(path, package.song_id)
        if data is not None:
            return data
    return None


def _archive_session_data(package: SongPackage, data: dict[str, object]) -> None:
    encoded = json.dumps(data, sort_keys=True, ensure_ascii=False).encode("utf-8")
    digest = hashlib.sha256(encoded).hexdigest()[:12]
    root = studio_session_path(package).parent / STUDIO_SESSION_HISTORY_DIR
    if any(root.glob(f"session-*-{digest}.json")):
        return
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S-%f")
    write_json_atomic(root / f"session-{stamp}-{digest}.json", data)
    history = studio_session_history_paths(package)
    for stale in history[STUDIO_SESSION_HISTORY_LIMIT:]:
        stale.unlink(missing_ok=True)


def _legacy_session_from_data(data: dict[str, object]) -> StudioSession:
    tracks = data.get("tracks") if isinstance(data.get("tracks"), dict) else {}
    return StudioSession(
        original_vocal=_track_state_from_data(tracks.get(TRACK_ORIGINAL_VOCAL)),
        instrumental=_track_state_from_data(tracks.get(TRACK_INSTRUMENTAL)),
        converted_vocal=_track_state_from_data(tracks.get(TRACK_CONVERTED_VOCAL)),
        updated_at=str(data.get("updated_at", "")),
    )


def _session_with_default_tracks(
    package: SongPackage,
    session: StudioSession,
    assets: tuple[StudioSoundAsset, ...],
) -> StudioSession:
    return _session_with_required_tracks(package, session, assets)


def _session_with_required_tracks(
    package: SongPackage,
    session: StudioSession,
    assets: tuple[StudioSoundAsset, ...],
) -> StudioSession:
    from jang_app.services.studio_assets import build_default_studio_tracks

    default_tracks = build_default_studio_tracks(
        package,
        {
            TRACK_ORIGINAL_VOCAL: session.state_for(TRACK_ORIGINAL_VOCAL),
            TRACK_INSTRUMENTAL: session.state_for(TRACK_INSTRUMENTAL),
            TRACK_CONVERTED_VOCAL: session.state_for(TRACK_CONVERTED_VOCAL),
        },
        assets,
    )
    if not default_tracks:
        return _with_video_track(package, session, assets)

    existing_roles = {track.role for track in session.tracks}
    missing_tracks = tuple(
        track for track in default_tracks if track.role not in existing_roles
    )
    if not missing_tracks:
        return _with_video_track(package, session, assets)
    return _with_video_track(
        package,
        _session_from_tracks(
            (*session.tracks, *missing_tracks),
            updated_at=session.updated_at,
        ),
        assets,
    )


def _normalized_session(
    package: SongPackage,
    session: StudioSession,
    assets: tuple[StudioSoundAsset, ...],
) -> StudioSession:
    tracks = tuple(_normalize_track(track) for track in session.tracks)
    tracks = tuple(track for track in tracks if track.track_id)
    session = _session_with_required_tracks(
        package,
        replace(session, tracks=tracks),
        assets,
    )
    return _session_from_tracks(
        session.tracks,
        updated_at=datetime.now(UTC).isoformat(),
    )


def _with_video_track(
    package: SongPackage,
    session: StudioSession,
    assets: tuple[StudioSoundAsset, ...],
) -> StudioSession:
    from jang_app.services.studio_assets import sync_studio_video_track

    return sync_studio_video_track(session, assets)


def _studio_assets(
    package: SongPackage,
    assets: tuple[StudioSoundAsset, ...] | None,
) -> tuple[StudioSoundAsset, ...]:
    if assets is not None:
        return assets
    from jang_app.services.studio_assets import studio_sound_pool

    return studio_sound_pool(package)


def _session_from_tracks(tracks: tuple[StudioTrack, ...], *, updated_at: str) -> StudioSession:
    states = {track.role: track.state for track in tracks}
    return StudioSession(
        original_vocal=states.get(TRACK_ORIGINAL_VOCAL, StudioTrackState()),
        instrumental=states.get(TRACK_INSTRUMENTAL, StudioTrackState()),
        converted_vocal=states.get(TRACK_CONVERTED_VOCAL, StudioTrackState()),
        tracks=tracks,
        updated_at=updated_at,
    )


def _tracks_from_data(value: object) -> tuple[StudioTrack, ...]:
    if not isinstance(value, list):
        return ()
    tracks: list[StudioTrack] = []
    seen_track_ids: set[str] = set()
    seen_clip_ids: set[str] = set()
    for raw in value:
        track = _track_from_data(raw, seen_clip_ids)
        if track is None or track.track_id in seen_track_ids:
            continue
        seen_track_ids.add(track.track_id)
        tracks.append(track)
    return tuple(tracks)


def _track_from_data(value: object, seen_clip_ids: set[str]) -> StudioTrack | None:
    if not isinstance(value, dict):
        return None
    track_id = str(value.get("track_id", "")).strip()
    role = str(value.get("role", TRACK_AUDIO)).strip()
    if not track_id or role not in SUPPORTED_TRACK_ROLES:
        return None
    clips: list[StudioClip] = []
    raw_clips = value.get("clips") if isinstance(value.get("clips"), list) else []
    for raw_clip in raw_clips:
        clip = _clip_from_data(raw_clip)
        if clip is None or clip.clip_id in seen_clip_ids:
            continue
        seen_clip_ids.add(clip.clip_id)
        clips.append(clip)
    return StudioTrack(
        track_id=track_id,
        name=str(value.get("name", "")).strip() or "Audio",
        role=role,
        muted=value.get("muted") is True,
        solo=value.get("solo") is True,
        volume_percent=_volume_percent(value.get("volume_percent")),
        pan_percent=_pan_percent(value.get("pan_percent")),
        collapsed=value.get("collapsed") is True,
        clips=tuple(sorted(clips, key=lambda clip: (clip.timeline_start_ms, clip.clip_id))),
    )


def _clip_from_data(value: object) -> StudioClip | None:
    if not isinstance(value, dict):
        return None
    clip_id = str(value.get("clip_id", "")).strip()
    asset_data = value.get("asset")
    if not clip_id or not isinstance(asset_data, dict):
        return None
    output_id = str(asset_data.get("output_id", "")).strip()
    role = str(asset_data.get("role", "")).strip()
    filename = Path(str(asset_data.get("filename", "")).strip()).name
    if not output_id or role not in SUPPORTED_TRACK_ROLES:
        return None
    source_start = _non_negative_int(value.get("source_start_ms"))
    source_end = _non_negative_int(value.get("source_end_ms"))
    if source_end <= source_start:
        return None
    fade_in, fade_out = _fade_lengths(
        source_end - source_start,
        value.get("fade_in_ms"),
        value.get("fade_out_ms"),
    )
    return StudioClip(
        clip_id=clip_id,
        asset=StudioAssetRef(output_id, role, filename),
        timeline_start_ms=_non_negative_int(value.get("timeline_start_ms")),
        source_start_ms=source_start,
        source_end_ms=source_end,
        gain_db=_gain_db(value.get("gain_db")),
        pitch_semitones=clamp_studio_clip_pitch(value.get("pitch_semitones")),
        muted=value.get("muted") is True,
        fade_in_ms=fade_in,
        fade_out_ms=fade_out,
        effects=_effects_from_data(value.get("effects")),
        media=_media_settings_from_data(value.get("media")),
    )


def _normalize_track(track: StudioTrack) -> StudioTrack:
    seen: set[str] = set()
    clips: list[StudioClip] = []
    for clip in track.clips:
        normalized = _normalize_clip(clip)
        if normalized is None or normalized.clip_id in seen:
            continue
        seen.add(normalized.clip_id)
        clips.append(normalized)
    role = track.role if track.role in SUPPORTED_TRACK_ROLES else TRACK_AUDIO
    return StudioTrack(
        track_id=track.track_id.strip(),
        name=track.name.strip() or "Audio",
        role=role,
        muted=bool(track.muted),
        solo=bool(track.solo),
        volume_percent=_volume_percent(track.volume_percent),
        pan_percent=_pan_percent(track.pan_percent),
        collapsed=bool(track.collapsed),
        clips=tuple(sorted(clips, key=lambda clip: (clip.timeline_start_ms, clip.clip_id))),
    )


def _normalize_clip(clip: StudioClip) -> StudioClip | None:
    start = _non_negative_int(clip.source_start_ms)
    end = _non_negative_int(clip.source_end_ms)
    if not clip.clip_id.strip() or not clip.asset.output_id.strip() or end <= start:
        return None
    role = clip.asset.role if clip.asset.role in SUPPORTED_TRACK_ROLES else TRACK_AUDIO
    fade_in, fade_out = _fade_lengths(end - start, clip.fade_in_ms, clip.fade_out_ms)
    return StudioClip(
        clip_id=clip.clip_id.strip(),
        asset=StudioAssetRef(
            clip.asset.output_id.strip(),
            role,
            Path(clip.asset.filename).name,
        ),
        timeline_start_ms=_non_negative_int(clip.timeline_start_ms),
        source_start_ms=start,
        source_end_ms=end,
        gain_db=_gain_db(clip.gain_db),
        pitch_semitones=clamp_studio_clip_pitch(clip.pitch_semitones),
        muted=bool(clip.muted),
        fade_in_ms=fade_in,
        fade_out_ms=fade_out,
        effects=_normalize_effects(clip.effects),
        media=_normalize_media_settings(clip.media),
    )


def _track_to_data(track: StudioTrack) -> dict[str, object]:
    return {
        "track_id": track.track_id,
        "name": track.name,
        "role": track.role,
        "muted": track.muted,
        "solo": track.solo,
        "volume_percent": track.volume_percent,
        "pan_percent": track.pan_percent,
        "collapsed": track.collapsed,
        "clips": [_clip_to_data(clip) for clip in track.clips],
    }


def _clip_to_data(clip: StudioClip) -> dict[str, object]:
    return {
        "clip_id": clip.clip_id,
        "asset": {
            "output_id": clip.asset.output_id,
            "role": clip.asset.role,
            "filename": clip.asset.filename,
        },
        "timeline_start_ms": clip.timeline_start_ms,
        "source_start_ms": clip.source_start_ms,
        "source_end_ms": clip.source_end_ms,
        "gain_db": clip.gain_db,
        "pitch_semitones": clip.pitch_semitones,
        "muted": clip.muted,
        "fade_in_ms": clip.fade_in_ms,
        "fade_out_ms": clip.fade_out_ms,
        "effects": [_effect_to_data(effect) for effect in clip.effects],
        "media": _media_settings_to_data(clip.media),
    }


def _media_settings_from_data(value: object) -> StudioMediaSettings:
    if not isinstance(value, dict):
        return StudioMediaSettings()
    return _normalize_media_settings(
        StudioMediaSettings(
            fit_mode=str(value.get("fit_mode", MEDIA_FIT)),
            scale_percent=value.get("scale_percent", 100),
            offset_x_percent=value.get("offset_x_percent", 0),
            offset_y_percent=value.get("offset_y_percent", 0),
            source_audio_enabled=value.get("source_audio_enabled") is True,
        )
    )


def _normalize_media_settings(settings: StudioMediaSettings) -> StudioMediaSettings:
    fit_mode = str(settings.fit_mode)
    if fit_mode not in SUPPORTED_MEDIA_FIT_MODES:
        fit_mode = MEDIA_FIT
    return StudioMediaSettings(
        fit_mode=fit_mode,
        scale_percent=max(25, min(400, _integer(settings.scale_percent, 100))),
        offset_x_percent=max(-100, min(100, _integer(settings.offset_x_percent, 0))),
        offset_y_percent=max(-100, min(100, _integer(settings.offset_y_percent, 0))),
        source_audio_enabled=bool(settings.source_audio_enabled),
    )


def _media_settings_to_data(settings: StudioMediaSettings) -> dict[str, object]:
    normalized = _normalize_media_settings(settings)
    return {
        "fit_mode": normalized.fit_mode,
        "scale_percent": normalized.scale_percent,
        "offset_x_percent": normalized.offset_x_percent,
        "offset_y_percent": normalized.offset_y_percent,
        "source_audio_enabled": normalized.source_audio_enabled,
    }


def _effects_from_data(value: object) -> tuple[StudioEffect, ...]:
    if not isinstance(value, list):
        return ()
    effects: list[StudioEffect] = []
    seen: set[str] = set()
    for raw in value:
        effect = _effect_from_data(raw)
        if effect is None or effect.effect_id in seen:
            continue
        seen.add(effect.effect_id)
        effects.append(effect)
    return tuple(effects)


def _effect_from_data(value: object) -> StudioEffect | None:
    if not isinstance(value, dict):
        return None
    effect_id = str(value.get("effect_id", "")).strip()
    kind = str(value.get("kind", "")).strip()
    if not effect_id or kind not in SUPPORTED_STUDIO_EFFECTS:
        return None
    settings = value.get("settings")
    effect = StudioEffect(
        effect_id=effect_id,
        kind=kind,
        enabled=value.get("enabled") is not False,
    )
    settings_loader = {
        STUDIO_EFFECT_REVERB: ("reverb", _reverb_settings_from_data),
        STUDIO_EFFECT_DELAY: ("delay", _delay_settings_from_data),
        STUDIO_EFFECT_DOUBLER: ("doubler", _doubler_settings_from_data),
        STUDIO_EFFECT_RADIO_FILTER: ("radio_filter", _radio_filter_settings_from_data),
        STUDIO_EFFECT_RING_MODULATOR: ("ring_modulator", _ring_modulator_settings_from_data),
        STUDIO_EFFECT_BITCRUSHER: ("bitcrusher", _bitcrusher_settings_from_data),
        STUDIO_EFFECT_DISTORTION: ("distortion", _distortion_settings_from_data),
        STUDIO_EFFECT_LEVEL_MATCH: ("level_match", _level_match_settings_from_data),
        STUDIO_EFFECT_HARD_TUNE: ("hard_tune", _hard_tune_settings_from_data),
    }
    field_name, loader = settings_loader[kind]
    return _normalized_effect(replace(effect, **{field_name: loader(settings)}))


def _normalize_effects(effects: tuple[StudioEffect, ...]) -> tuple[StudioEffect, ...]:
    normalized: list[StudioEffect] = []
    seen: set[str] = set()
    for effect in effects:
        effect_id = str(effect.effect_id).strip()
        if not effect_id or effect_id in seen or effect.kind not in SUPPORTED_STUDIO_EFFECTS:
            continue
        seen.add(effect_id)
        normalized.append(_normalized_effect(replace(effect, effect_id=effect_id)))
    return tuple(normalized)


def _normalized_effect(effect: StudioEffect) -> StudioEffect:
    return StudioEffect(
        effect_id=str(effect.effect_id).strip(),
        kind=effect.kind,
        enabled=bool(effect.enabled),
        reverb=_normalized_reverb_settings(effect.reverb),
        delay=_normalized_delay_settings(effect.delay),
        doubler=_normalized_doubler_settings(effect.doubler),
        radio_filter=_normalized_radio_filter_settings(effect.radio_filter),
        ring_modulator=_normalized_ring_modulator_settings(effect.ring_modulator),
        bitcrusher=_normalized_bitcrusher_settings(effect.bitcrusher),
        distortion=_normalized_distortion_settings(effect.distortion),
        level_match=_normalized_level_match_settings(effect.level_match),
        hard_tune=_normalized_hard_tune_settings(effect.hard_tune),
    )


def _effect_to_data(effect: StudioEffect) -> dict[str, object]:
    settings = {
        STUDIO_EFFECT_REVERB: _reverb_settings_to_data(effect.reverb),
        STUDIO_EFFECT_DELAY: _settings_to_data(
            _normalized_delay_settings(effect.delay)
        ),
        STUDIO_EFFECT_DOUBLER: _settings_to_data(
            _normalized_doubler_settings(effect.doubler)
        ),
        STUDIO_EFFECT_RADIO_FILTER: _settings_to_data(
            _normalized_radio_filter_settings(effect.radio_filter)
        ),
        STUDIO_EFFECT_RING_MODULATOR: _settings_to_data(
            _normalized_ring_modulator_settings(effect.ring_modulator)
        ),
        STUDIO_EFFECT_BITCRUSHER: _settings_to_data(
            _normalized_bitcrusher_settings(effect.bitcrusher)
        ),
        STUDIO_EFFECT_DISTORTION: _settings_to_data(
            _normalized_distortion_settings(effect.distortion)
        ),
        STUDIO_EFFECT_LEVEL_MATCH: _settings_to_data(
            _normalized_level_match_settings(effect.level_match)
        ),
        STUDIO_EFFECT_HARD_TUNE: _settings_to_data(
            _normalized_hard_tune_settings(effect.hard_tune)
        ),
    }.get(effect.kind, {})
    return {
        "effect_id": effect.effect_id,
        "kind": effect.kind,
        "enabled": effect.enabled,
        "settings": settings,
    }


def _radio_filter_settings_from_data(value: object) -> StudioRadioFilterSettings:
    data = value if isinstance(value, dict) else {}
    defaults = StudioRadioFilterSettings()
    return _normalized_radio_filter_settings(
        StudioRadioFilterSettings(
            low_cut_hz=_integer(data.get("low_cut_hz"), defaults.low_cut_hz),
            high_cut_hz=_integer(data.get("high_cut_hz"), defaults.high_cut_hz),
            mix_percent=_integer(data.get("mix_percent"), defaults.mix_percent),
        )
    )


def _delay_settings_from_data(value: object) -> StudioDelaySettings:
    data = value if isinstance(value, dict) else {}
    defaults = StudioDelaySettings()
    return _normalized_delay_settings(
        StudioDelaySettings(
            delay_ms=_integer(data.get("delay_ms"), defaults.delay_ms),
            feedback_percent=_integer(
                data.get("feedback_percent"), defaults.feedback_percent
            ),
            dry_wet_percent=_integer(
                data.get("dry_wet_percent"), defaults.dry_wet_percent
            ),
            stereo_width_percent=_integer(
                data.get("stereo_width_percent"), defaults.stereo_width_percent
            ),
        )
    )


def _doubler_settings_from_data(value: object) -> StudioDoublerSettings:
    data = value if isinstance(value, dict) else {}
    defaults = StudioDoublerSettings()
    return _normalized_doubler_settings(
        StudioDoublerSettings(
            voice_spacing_ms=_integer(
                data.get("voice_spacing_ms"), defaults.voice_spacing_ms
            ),
            pitch_spread_cents=_integer(
                data.get("pitch_spread_cents"), defaults.pitch_spread_cents
            ),
            stereo_width_percent=_integer(
                data.get("stereo_width_percent"), defaults.stereo_width_percent
            ),
            dry_wet_percent=_integer(
                data.get("dry_wet_percent"), defaults.dry_wet_percent
            ),
        )
    )


def _ring_modulator_settings_from_data(value: object) -> StudioRingModulatorSettings:
    data = value if isinstance(value, dict) else {}
    defaults = StudioRingModulatorSettings()
    return _normalized_ring_modulator_settings(
        StudioRingModulatorSettings(
            frequency_hz=_integer(data.get("frequency_hz"), defaults.frequency_hz),
            mix_percent=_integer(data.get("mix_percent"), defaults.mix_percent),
        )
    )


def _bitcrusher_settings_from_data(value: object) -> StudioBitcrusherSettings:
    data = value if isinstance(value, dict) else {}
    defaults = StudioBitcrusherSettings()
    return _normalized_bitcrusher_settings(
        StudioBitcrusherSettings(
            bit_depth=_integer(data.get("bit_depth"), defaults.bit_depth),
            sample_rate_hz=_integer(data.get("sample_rate_hz"), defaults.sample_rate_hz),
            mix_percent=_integer(data.get("mix_percent"), defaults.mix_percent),
        )
    )


def _distortion_settings_from_data(value: object) -> StudioDistortionSettings:
    data = value if isinstance(value, dict) else {}
    defaults = StudioDistortionSettings()
    return _normalized_distortion_settings(
        StudioDistortionSettings(
            drive_percent=_integer(data.get("drive_percent"), defaults.drive_percent),
            mix_percent=_integer(data.get("mix_percent"), defaults.mix_percent),
        )
    )


def _level_match_settings_from_data(value: object) -> StudioLevelMatchSettings:
    data = value if isinstance(value, dict) else {}
    defaults = StudioLevelMatchSettings()
    return _normalized_level_match_settings(
        StudioLevelMatchSettings(
            strength_percent=_integer(
                data.get("strength_percent"), defaults.strength_percent
            ),
            response_ms=_integer(data.get("response_ms"), defaults.response_ms),
            max_correction_db=_integer(
                data.get("max_correction_db"), defaults.max_correction_db
            ),
            silence_threshold_db=_integer(
                data.get("silence_threshold_db"), defaults.silence_threshold_db
            ),
        )
    )


def _hard_tune_settings_from_data(value: object) -> StudioHardTuneSettings:
    data = value if isinstance(value, dict) else {}
    defaults = StudioHardTuneSettings()
    return _normalized_hard_tune_settings(
        StudioHardTuneSettings(
            key_note=_integer(data.get("key_note"), defaults.key_note),
            scale=str(data.get("scale", defaults.scale)),
            strength_percent=_integer(
                data.get("strength_percent"), defaults.strength_percent
            ),
            response_ms=_integer(data.get("response_ms"), defaults.response_ms),
            vibrato_preserve_percent=_integer(
                data.get("vibrato_preserve_percent"),
                defaults.vibrato_preserve_percent,
            ),
        )
    )


def _normalized_radio_filter_settings(
    settings: StudioRadioFilterSettings,
) -> StudioRadioFilterSettings:
    low_cut = int(_clamp(settings.low_cut_hz, 20, 4_000))
    high_cut = int(_clamp(settings.high_cut_hz, low_cut + 100, 20_000))
    return StudioRadioFilterSettings(
        low_cut_hz=low_cut,
        high_cut_hz=high_cut,
        mix_percent=int(_clamp(settings.mix_percent, 0, 100)),
    )


def _normalized_delay_settings(settings: StudioDelaySettings) -> StudioDelaySettings:
    return StudioDelaySettings(
        delay_ms=int(_clamp(settings.delay_ms, 40, 2_000)),
        feedback_percent=int(_clamp(settings.feedback_percent, 0, 85)),
        dry_wet_percent=int(_clamp(settings.dry_wet_percent, 0, 100)),
        stereo_width_percent=int(_clamp(settings.stereo_width_percent, 0, 100)),
    )


def _normalized_doubler_settings(settings: StudioDoublerSettings) -> StudioDoublerSettings:
    return StudioDoublerSettings(
        voice_spacing_ms=int(_clamp(settings.voice_spacing_ms, 6, 40)),
        pitch_spread_cents=int(_clamp(settings.pitch_spread_cents, 0, 20)),
        stereo_width_percent=int(_clamp(settings.stereo_width_percent, 0, 100)),
        dry_wet_percent=int(_clamp(settings.dry_wet_percent, 0, 100)),
    )


def _normalized_ring_modulator_settings(
    settings: StudioRingModulatorSettings,
) -> StudioRingModulatorSettings:
    return StudioRingModulatorSettings(
        frequency_hz=int(_clamp(settings.frequency_hz, 1, 2_000)),
        mix_percent=int(_clamp(settings.mix_percent, 0, 100)),
    )


def _normalized_bitcrusher_settings(
    settings: StudioBitcrusherSettings,
) -> StudioBitcrusherSettings:
    return StudioBitcrusherSettings(
        bit_depth=int(_clamp(settings.bit_depth, 4, 16)),
        sample_rate_hz=int(_clamp(settings.sample_rate_hz, 2_000, 48_000)),
        mix_percent=int(_clamp(settings.mix_percent, 0, 100)),
    )


def _normalized_distortion_settings(
    settings: StudioDistortionSettings,
) -> StudioDistortionSettings:
    return StudioDistortionSettings(
        drive_percent=int(_clamp(settings.drive_percent, 0, 100)),
        mix_percent=int(_clamp(settings.mix_percent, 0, 100)),
    )


def _normalized_level_match_settings(
    settings: StudioLevelMatchSettings,
) -> StudioLevelMatchSettings:
    return StudioLevelMatchSettings(
        strength_percent=int(_clamp(settings.strength_percent, 0, 100)),
        response_ms=int(_clamp(settings.response_ms, 40, 1_000)),
        max_correction_db=int(_clamp(settings.max_correction_db, 1, 12)),
        silence_threshold_db=int(_clamp(settings.silence_threshold_db, -80, -30)),
    )


def _normalized_hard_tune_settings(
    settings: StudioHardTuneSettings,
) -> StudioHardTuneSettings:
    scale = str(settings.scale).strip().lower()
    if scale not in {"chromatic", "major", "minor"}:
        scale = "chromatic"
    return StudioHardTuneSettings(
        key_note=int(_clamp(settings.key_note, 0, 11)),
        scale=scale,
        strength_percent=int(_clamp(settings.strength_percent, 0, 100)),
        response_ms=int(_clamp(settings.response_ms, 5, 250)),
        vibrato_preserve_percent=int(
            _clamp(settings.vibrato_preserve_percent, 0, 100)
        ),
    )


def _settings_to_data(settings: object) -> dict[str, object]:
    return {item.name: getattr(settings, item.name) for item in fields(settings)}


def _reverb_settings_from_data(value: object) -> StudioReverbSettings:
    data = value if isinstance(value, dict) else {}
    defaults = StudioReverbSettings()
    return _normalized_reverb_settings(
        StudioReverbSettings(
            room_height_m=_number(data.get("room_height_m"), defaults.room_height_m),
            room_length_m=_number(data.get("room_length_m"), defaults.room_length_m),
            room_width_m=_number(data.get("room_width_m"), defaults.room_width_m),
            pre_delay_ms=_integer(data.get("pre_delay_ms"), defaults.pre_delay_ms),
            decay_ms=_integer(data.get("decay_ms"), defaults.decay_ms),
            distance_m=_number(data.get("distance_m"), defaults.distance_m),
            brightness_percent=_integer(
                data.get("brightness_percent"), defaults.brightness_percent
            ),
            modulation_percent=_integer(
                data.get("modulation_percent"), defaults.modulation_percent
            ),
            early_low_hz=_integer(data.get("early_low_hz"), defaults.early_low_hz),
            early_high_hz=_integer(data.get("early_high_hz"), defaults.early_high_hz),
            early_low_gain_db=_number(
                data.get("early_low_gain_db"), defaults.early_low_gain_db
            ),
            early_high_gain_db=_number(
                data.get("early_high_gain_db"), defaults.early_high_gain_db
            ),
            reverb_low_hz=_integer(data.get("reverb_low_hz"), defaults.reverb_low_hz),
            reverb_high_hz=_integer(data.get("reverb_high_hz"), defaults.reverb_high_hz),
            reverb_low_gain_db=_number(
                data.get("reverb_low_gain_db"), defaults.reverb_low_gain_db
            ),
            reverb_high_gain_db=_number(
                data.get("reverb_high_gain_db"), defaults.reverb_high_gain_db
            ),
            dry_wet_percent=_integer(
                data.get("dry_wet_percent"), defaults.dry_wet_percent
            ),
            direct_gain_db=_number(data.get("direct_gain_db"), defaults.direct_gain_db),
            early_gain_db=_number(data.get("early_gain_db"), defaults.early_gain_db),
            reverb_gain_db=_number(data.get("reverb_gain_db"), defaults.reverb_gain_db),
        )
    )


def _normalized_reverb_settings(settings: StudioReverbSettings) -> StudioReverbSettings:
    return StudioReverbSettings(
        room_height_m=_clamp(settings.room_height_m, 1.0, 30.0),
        room_length_m=_clamp(settings.room_length_m, 1.0, 30.0),
        room_width_m=_clamp(settings.room_width_m, 1.0, 30.0),
        pre_delay_ms=int(_clamp(settings.pre_delay_ms, -200, 200)),
        decay_ms=int(_clamp(settings.decay_ms, 100, 4_000)),
        distance_m=_clamp(settings.distance_m, 0.0, 30.0),
        brightness_percent=int(_clamp(settings.brightness_percent, 0, 100)),
        modulation_percent=int(_clamp(settings.modulation_percent, 0, 100)),
        early_low_hz=int(_clamp(settings.early_low_hz, 50, 500)),
        early_high_hz=int(_clamp(settings.early_high_hz, 1_000, 16_000)),
        early_low_gain_db=_clamp(settings.early_low_gain_db, -18.0, 6.0),
        early_high_gain_db=_clamp(settings.early_high_gain_db, -18.0, 6.0),
        reverb_low_hz=int(_clamp(settings.reverb_low_hz, 50, 500)),
        reverb_high_hz=int(_clamp(settings.reverb_high_hz, 1_000, 16_000)),
        reverb_low_gain_db=_clamp(settings.reverb_low_gain_db, -18.0, 6.0),
        reverb_high_gain_db=_clamp(settings.reverb_high_gain_db, -18.0, 6.0),
        dry_wet_percent=int(_clamp(settings.dry_wet_percent, 0, 100)),
        direct_gain_db=_clamp(settings.direct_gain_db, -60.0, 6.0),
        early_gain_db=_clamp(settings.early_gain_db, -60.0, 6.0),
        reverb_gain_db=_clamp(settings.reverb_gain_db, -60.0, 6.0),
    )


def _reverb_settings_to_data(settings: StudioReverbSettings) -> dict[str, object]:
    normalized = _normalized_reverb_settings(settings)
    return {
        name: getattr(normalized, name)
        for name in StudioReverbSettings.__dataclass_fields__
    }


def _number(value: object, default: float) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if math.isfinite(result) else default


def _integer(value: object, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return default


def _clamp(value: object, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, _number(value, minimum)))


def _track_state_from_data(value: object) -> StudioTrackState:
    if not isinstance(value, dict):
        return StudioTrackState()
    return StudioTrackState(
        muted=value.get("muted") is True,
        volume_percent=_volume_percent(value.get("volume_percent")),
        pan_percent=_pan_percent(value.get("pan_percent")),
    )


def _volume_percent(value: object) -> int:
    try:
        return max(0, min(200, int(value)))
    except (TypeError, ValueError):
        return 100


def _pan_percent(value: object) -> int:
    try:
        return max(-100, min(100, int(value)))
    except (TypeError, ValueError):
        return 0


def _fade_lengths(duration_ms: int, fade_in: object, fade_out: object) -> tuple[int, int]:
    duration = max(0, int(duration_ms))
    fade_in_ms = min(duration, _non_negative_int(fade_in))
    fade_out_ms = min(max(0, duration - fade_in_ms), _non_negative_int(fade_out))
    return fade_in_ms, fade_out_ms


def _non_negative_int(value: object) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def _gain_db(value: object) -> float:
    try:
        return clamp_studio_clip_gain_db(float(value))
    except (TypeError, ValueError):
        return 0.0
