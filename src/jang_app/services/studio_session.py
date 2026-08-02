from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from jang_app.services.managed_files import write_json_atomic
from jang_app.services.song_package import STUDIO_STAGE, SongPackage


STUDIO_SESSION_VERSION = 1
STUDIO_SESSION_NAME = "session.json"
TRACK_ORIGINAL_VOCAL = "original_vocal"
TRACK_INSTRUMENTAL = "instrumental"
TRACK_CONVERTED_VOCAL = "converted_vocal"


@dataclass(frozen=True)
class StudioTrackState:
    muted: bool = False
    volume_percent: int = 100


@dataclass(frozen=True)
class StudioTimelineState:
    start_ms: int = 0
    end_ms: int = 0


@dataclass(frozen=True)
class StudioMasterState:
    gain_db: int = 0
    stereo_width_percent: int = 100


@dataclass(frozen=True)
class StudioSession:
    original_vocal: StudioTrackState = field(default_factory=StudioTrackState)
    instrumental: StudioTrackState = field(default_factory=StudioTrackState)
    converted_vocal: StudioTrackState = field(default_factory=StudioTrackState)
    updated_at: str = ""
    timeline: StudioTimelineState = field(default_factory=StudioTimelineState)
    master: StudioMasterState = field(default_factory=StudioMasterState)

    def state_for(self, track_key: str) -> StudioTrackState:
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
        return StudioSession()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return StudioSession()
    if (
        not isinstance(data, dict)
        or data.get("version") != STUDIO_SESSION_VERSION
        or data.get("song_id") not in (None, "", package.song_id)
    ):
        return StudioSession()
    tracks = data.get("tracks") if isinstance(data.get("tracks"), dict) else {}
    return StudioSession(
        original_vocal=_track_state_from_data(tracks.get(TRACK_ORIGINAL_VOCAL)),
        instrumental=_track_state_from_data(tracks.get(TRACK_INSTRUMENTAL)),
        converted_vocal=_track_state_from_data(tracks.get(TRACK_CONVERTED_VOCAL)),
        updated_at=str(data.get("updated_at", "")),
        timeline=_timeline_state_from_data(data.get("timeline")),
        master=_master_state_from_data(data.get("master")),
    )


def save_studio_session(package: SongPackage, session: StudioSession) -> Path:
    path = studio_session_path(package)
    normalized = StudioSession(
        original_vocal=_normalize_track_state(session.original_vocal),
        instrumental=_normalize_track_state(session.instrumental),
        converted_vocal=_normalize_track_state(session.converted_vocal),
        updated_at=datetime.now(UTC).isoformat(),
        timeline=_normalize_timeline_state(session.timeline),
        master=_normalize_master_state(session.master),
    )
    write_json_atomic(
        path,
        {
            "version": STUDIO_SESSION_VERSION,
            "song_id": package.song_id,
            "updated_at": normalized.updated_at,
            "timeline": {
                "start_ms": normalized.timeline.start_ms,
                "end_ms": normalized.timeline.end_ms,
            },
            "master": {
                "gain_db": normalized.master.gain_db,
                "stereo_width_percent": normalized.master.stereo_width_percent,
            },
            "tracks": {
                TRACK_ORIGINAL_VOCAL: _track_state_to_data(normalized.original_vocal),
                TRACK_INSTRUMENTAL: _track_state_to_data(normalized.instrumental),
                TRACK_CONVERTED_VOCAL: _track_state_to_data(normalized.converted_vocal),
            },
        },
    )
    return path


def studio_session_path(package: SongPackage) -> Path:
    return package.folder / STUDIO_STAGE / STUDIO_SESSION_NAME


def _track_state_from_data(value: object) -> StudioTrackState:
    if not isinstance(value, dict):
        return StudioTrackState()
    return StudioTrackState(
        muted=value.get("muted") is True,
        volume_percent=_volume_percent(value.get("volume_percent")),
    )


def _normalize_track_state(state: StudioTrackState) -> StudioTrackState:
    return StudioTrackState(bool(state.muted), _volume_percent(state.volume_percent))


def _track_state_to_data(state: StudioTrackState) -> dict[str, object]:
    return {
        "muted": state.muted,
        "volume_percent": state.volume_percent,
    }


def _timeline_state_from_data(value: object) -> StudioTimelineState:
    if not isinstance(value, dict):
        return StudioTimelineState()
    return _normalize_timeline_state(
        StudioTimelineState(
            start_ms=_nonnegative_int(value.get("start_ms")),
            end_ms=_nonnegative_int(value.get("end_ms")),
        )
    )


def _normalize_timeline_state(state: StudioTimelineState) -> StudioTimelineState:
    start_ms = _nonnegative_int(state.start_ms)
    end_ms = _nonnegative_int(state.end_ms)
    if end_ms and end_ms <= start_ms:
        return StudioTimelineState()
    return StudioTimelineState(start_ms, end_ms)


def _master_state_from_data(value: object) -> StudioMasterState:
    if not isinstance(value, dict):
        return StudioMasterState()
    return _normalize_master_state(
        StudioMasterState(
            gain_db=_int_value(value.get("gain_db")),
            stereo_width_percent=_int_value(value.get("stereo_width_percent"), fallback=100),
        )
    )


def _normalize_master_state(state: StudioMasterState) -> StudioMasterState:
    return StudioMasterState(
        gain_db=max(-24, min(12, _int_value(state.gain_db))),
        stereo_width_percent=max(0, min(200, _int_value(state.stereo_width_percent, fallback=100))),
    )


def _volume_percent(value: object) -> int:
    try:
        return max(0, min(200, int(value)))
    except (TypeError, ValueError):
        return 100


def _nonnegative_int(value: object) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def _int_value(value: object, *, fallback: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback
