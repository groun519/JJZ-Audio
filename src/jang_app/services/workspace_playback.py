from __future__ import annotations

from enum import StrEnum


class WorkspacePlaybackScope(StrEnum):
    SEPARATION = "separation"
    CONVERSION = "conversion"
    STUDIO = "studio"


_TRACK_IDS_BY_SCOPE: dict[WorkspacePlaybackScope, tuple[str, ...]] = {
    WorkspacePlaybackScope.SEPARATION: ("original", "instrumental"),
    WorkspacePlaybackScope.CONVERSION: ("original", "converted"),
    WorkspacePlaybackScope.STUDIO: ("original", "instrumental", "converted"),
}

_LABEL_BY_SCOPE: dict[WorkspacePlaybackScope, str] = {
    WorkspacePlaybackScope.SEPARATION: "Separation Preview",
    WorkspacePlaybackScope.CONVERSION: "Conversion Compare",
    WorkspacePlaybackScope.STUDIO: "Studio Mix",
}


def scope_track_ids(scope: WorkspacePlaybackScope) -> tuple[str, ...]:
    return _TRACK_IDS_BY_SCOPE[scope]


def scope_label(scope: WorkspacePlaybackScope) -> str:
    return _LABEL_BY_SCOPE[scope]
