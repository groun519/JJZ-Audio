from __future__ import annotations

import json
import math
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path

from jang_app.services.managed_files import write_json_atomic
from jang_app.services.song_package import STUDIO_STAGE, SongPackage


STUDIO_SESSION_VERSION = 5
STUDIO_SESSION_PREVIOUS_VERSIONS = {2, 3, 4}
STUDIO_SESSION_LEGACY_VERSION = 1
STUDIO_SESSION_NAME = "session.json"
TRACK_ORIGINAL_VOCAL = "original_vocal"
TRACK_INSTRUMENTAL = "instrumental"
TRACK_CONVERTED_VOCAL = "converted_vocal"
TRACK_AUDIO = "audio"
TRACK_VIDEO = "video"
STUDIO_EFFECT_REVERB = "reverb"
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
class StudioEffect:
    effect_id: str
    kind: str
    enabled: bool = True
    reverb: StudioReverbSettings = field(default_factory=StudioReverbSettings)


@dataclass(frozen=True)
class StudioClip:
    clip_id: str
    asset: StudioAssetRef
    timeline_start_ms: int
    source_start_ms: int
    source_end_ms: int
    gain_db: float = 0.0
    muted: bool = False
    fade_in_ms: int = 0
    fade_out_ms: int = 0
    effects: tuple[StudioEffect, ...] = ()

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


def load_studio_session(package: SongPackage) -> StudioSession:
    path = studio_session_path(package)
    if not path.is_file():
        return _session_with_default_tracks(package, StudioSession())
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return _session_with_default_tracks(package, StudioSession())
    if not isinstance(data, dict) or data.get("song_id") not in (None, "", package.song_id):
        return _session_with_default_tracks(package, StudioSession())

    version = data.get("version")
    if version == STUDIO_SESSION_LEGACY_VERSION:
        legacy = _legacy_session_from_data(data)
        return _session_with_default_tracks(package, legacy)
    if version not in (*STUDIO_SESSION_PREVIOUS_VERSIONS, STUDIO_SESSION_VERSION):
        return _session_with_default_tracks(package, StudioSession())

    tracks = _tracks_from_data(data.get("tracks"))
    if not tracks:
        return _session_with_default_tracks(package, StudioSession(updated_at=str(data.get("updated_at", ""))))
    return _session_with_required_tracks(
        package,
        _session_from_tracks(tracks, updated_at=str(data.get("updated_at", ""))),
    )


def save_studio_session(package: SongPackage, session: StudioSession) -> Path:
    path = studio_session_path(package)
    normalized = _normalized_session(package, session)
    write_json_atomic(
        path,
        {
            "version": STUDIO_SESSION_VERSION,
            "song_id": package.song_id,
            "updated_at": normalized.updated_at,
            "tracks": [_track_to_data(track) for track in normalized.tracks],
        },
    )
    return path


def studio_session_path(package: SongPackage) -> Path:
    return package.folder / STUDIO_STAGE / STUDIO_SESSION_NAME


def _legacy_session_from_data(data: dict[str, object]) -> StudioSession:
    tracks = data.get("tracks") if isinstance(data.get("tracks"), dict) else {}
    return StudioSession(
        original_vocal=_track_state_from_data(tracks.get(TRACK_ORIGINAL_VOCAL)),
        instrumental=_track_state_from_data(tracks.get(TRACK_INSTRUMENTAL)),
        converted_vocal=_track_state_from_data(tracks.get(TRACK_CONVERTED_VOCAL)),
        updated_at=str(data.get("updated_at", "")),
    )


def _session_with_default_tracks(package: SongPackage, session: StudioSession) -> StudioSession:
    return _session_with_required_tracks(package, session)


def _session_with_required_tracks(package: SongPackage, session: StudioSession) -> StudioSession:
    from jang_app.services.studio_assets import build_default_studio_tracks

    default_tracks = build_default_studio_tracks(
        package,
        {
            TRACK_ORIGINAL_VOCAL: session.state_for(TRACK_ORIGINAL_VOCAL),
            TRACK_INSTRUMENTAL: session.state_for(TRACK_INSTRUMENTAL),
            TRACK_CONVERTED_VOCAL: session.state_for(TRACK_CONVERTED_VOCAL),
        },
    )
    if not default_tracks:
        return _with_video_track(package, session)

    existing_roles = {track.role for track in session.tracks}
    missing_tracks = tuple(
        track for track in default_tracks if track.role not in existing_roles
    )
    if not missing_tracks:
        return _with_video_track(package, session)
    return _with_video_track(
        package,
        _session_from_tracks(
            (*session.tracks, *missing_tracks),
            updated_at=session.updated_at,
        ),
    )


def _normalized_session(package: SongPackage, session: StudioSession) -> StudioSession:
    tracks = tuple(_normalize_track(track) for track in session.tracks)
    tracks = tuple(track for track in tracks if track.track_id)
    session = _session_with_required_tracks(package, replace(session, tracks=tracks))
    return _session_from_tracks(
        session.tracks,
        updated_at=datetime.now(UTC).isoformat(),
    )


def _with_video_track(package: SongPackage, session: StudioSession) -> StudioSession:
    from jang_app.services.studio_assets import studio_sound_pool, sync_studio_video_track

    assets = studio_sound_pool(package)
    return sync_studio_video_track(package, session, assets)


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
        muted=value.get("muted") is True,
        fade_in_ms=fade_in,
        fade_out_ms=fade_out,
        effects=_effects_from_data(value.get("effects")),
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
        muted=bool(clip.muted),
        fade_in_ms=fade_in,
        fade_out_ms=fade_out,
        effects=_normalize_effects(clip.effects),
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
        "muted": clip.muted,
        "fade_in_ms": clip.fade_in_ms,
        "fade_out_ms": clip.fade_out_ms,
        "effects": [_effect_to_data(effect) for effect in clip.effects],
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
    if not effect_id or kind != STUDIO_EFFECT_REVERB:
        return None
    settings = value.get("settings")
    return StudioEffect(
        effect_id=effect_id,
        kind=kind,
        enabled=value.get("enabled") is not False,
        reverb=_reverb_settings_from_data(settings),
    )


def _normalize_effects(effects: tuple[StudioEffect, ...]) -> tuple[StudioEffect, ...]:
    normalized: list[StudioEffect] = []
    seen: set[str] = set()
    for effect in effects:
        effect_id = str(effect.effect_id).strip()
        if not effect_id or effect_id in seen or effect.kind != STUDIO_EFFECT_REVERB:
            continue
        seen.add(effect_id)
        normalized.append(
            StudioEffect(
                effect_id=effect_id,
                kind=STUDIO_EFFECT_REVERB,
                enabled=bool(effect.enabled),
                reverb=_normalized_reverb_settings(effect.reverb),
            )
        )
    return tuple(normalized)


def _effect_to_data(effect: StudioEffect) -> dict[str, object]:
    return {
        "effect_id": effect.effect_id,
        "kind": effect.kind,
        "enabled": effect.enabled,
        "settings": _reverb_settings_to_data(effect.reverb),
    }


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
        return max(-60.0, min(12.0, float(value)))
    except (TypeError, ValueError):
        return 0.0
