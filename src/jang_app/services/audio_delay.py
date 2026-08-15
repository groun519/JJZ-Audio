from __future__ import annotations

import math

import numpy as np

from jang_app.services.realtime_delay import RealtimeDelay
from jang_app.services.studio_session import StudioDelaySettings


_TAIL_FLOOR = 0.001
_MAX_TAIL_MS = 12_000
_MAX_REPEATS = 32


def apply_delay(
    audio: np.ndarray,
    sample_rate: int,
    settings: StudioDelaySettings,
) -> np.ndarray:
    """Render delay with the same stateful processor used by Studio preview."""
    source = np.asarray(audio, dtype=np.float32)
    if source.shape[0] == 0 or sample_rate <= 0:
        return source.copy()
    if settings.dry_wet_percent <= 0:
        return source.copy()

    processor = RealtimeDelay(sample_rate, settings)
    rendered = [processor.process(source)]
    tail_frames = round(delay_tail_ms(settings) * sample_rate / 1_000.0)
    if tail_frames > 0:
        channels = rendered[0].shape[1]
        rendered.append(
            processor.process(np.zeros((tail_frames, channels), dtype=np.float32))
        )
    return np.concatenate(rendered, axis=0)


def delay_tail_ms(settings: StudioDelaySettings) -> int:
    if settings.dry_wet_percent <= 0:
        return 0
    delay_ms = max(40, min(2_000, int(settings.delay_ms)))
    feedback = max(0.0, min(0.85, settings.feedback_percent / 100.0))
    repeats = 1 if feedback <= 0.0 else math.ceil(
        math.log(_TAIL_FLOOR) / math.log(feedback)
    )
    repeats = max(1, min(_MAX_REPEATS, repeats))
    stereo_scale = 1.0 + 0.24 * max(
        0.0,
        min(1.0, settings.stereo_width_percent / 100.0),
    )
    return min(_MAX_TAIL_MS, math.ceil(delay_ms * stereo_scale * repeats))
