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
class StudioSession:
    original_vocal: StudioTrackState = field(default_factory=StudioTrackState)
    instrumental: StudioTrackState = field(default_factory=StudioTrackState)
    converted_vocal: StudioTrackState = field(default_factory=StudioTrackState)
    updated_at: str = ""

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
    )


def save_studio_session(package: SongPackage, session: StudioSession) -> Path:
    path = studio_session_path(package)
    normalized = StudioSession(
        original_vocal=_normalize_track_state(session.original_vocal),
        instrumental=_normalize_track_state(session.instrumental),
        converted_vocal=_normalize_track_state(session.converted_vocal),
        updated_at=datetime.now(UTC).isoformat(),
    )
    write_json_atomic(
        path,
        {
            "version": STUDIO_SESSION_VERSION,
            "song_id": package.song_id,
            "updated_at": normalized.updated_at,
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


def _volume_percent(value: object) -> int:
    try:
        return max(0, min(200, int(value)))
    except (TypeError, ValueError):
        return 100
