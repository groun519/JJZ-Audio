from __future__ import annotations

import json
import os
import sys
from collections.abc import Mapping
from pathlib import Path


DIRECT_CHANNEL = "direct"
STORE_CHANNEL = "store"
DISTRIBUTION_CHANNEL_ENV = "JJZERO_DISTRIBUTION_CHANNEL"
DISTRIBUTION_MARKER_NAME = "distribution-channel.json"


def current_distribution_channel(
    *,
    environ: Mapping[str, str] | None = None,
    frozen: bool | None = None,
    executable: Path | None = None,
) -> str:
    environment = os.environ if environ is None else environ
    configured = _supported_channel(environment.get(DISTRIBUTION_CHANNEL_ENV, ""))
    if configured:
        return configured

    is_frozen = bool(getattr(sys, "frozen", False)) if frozen is None else frozen
    if not is_frozen:
        return DIRECT_CHANNEL

    app_executable = (executable or Path(sys.executable)).expanduser().resolve()
    return _channel_from_marker(app_executable.parent / DISTRIBUTION_MARKER_NAME)


def application_updates_enabled(**channel_options: object) -> bool:
    return current_distribution_channel(**channel_options) == DIRECT_CHANNEL


def _channel_from_marker(path: Path) -> str:
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return DIRECT_CHANNEL
    if not isinstance(data, dict):
        return DIRECT_CHANNEL
    return _supported_channel(data.get("channel")) or DIRECT_CHANNEL


def _supported_channel(value: object) -> str:
    normalized = str(value or "").strip().casefold()
    if normalized in {DIRECT_CHANNEL, STORE_CHANNEL}:
        return normalized
    return ""
