from __future__ import annotations

import numpy as np

from jang_app.services.realtime_doubler import (
    RealtimeDoubler,
    doubler_max_delay_frames,
)
from jang_app.services.studio_session import StudioDoublerSettings


def apply_doubler(
    audio: np.ndarray,
    sample_rate: int,
    settings: StudioDoublerSettings,
) -> np.ndarray:
    """Render the same stateful doubler used by Studio preview."""
    source = np.asarray(audio, dtype=np.float32)
    if source.shape[0] == 0 or sample_rate <= 0:
        return source.copy()
    if settings.dry_wet_percent <= 0:
        return source.copy()

    processor = RealtimeDoubler(sample_rate, settings)
    rendered = [processor.process(source)]
    tail_frames = round(doubler_tail_ms(settings, sample_rate) * sample_rate / 1_000.0)
    if tail_frames > 0:
        channels = rendered[0].shape[1]
        rendered.append(
            processor.process(np.zeros((tail_frames, channels), dtype=np.float32))
        )
    return np.concatenate(rendered, axis=0)


def doubler_tail_ms(settings: StudioDoublerSettings, sample_rate: int = 48_000) -> int:
    if settings.dry_wet_percent <= 0:
        return 0
    rate = max(1, int(sample_rate))
    frames = doubler_max_delay_frames(settings, rate)
    return max(1, round(frames * 1_000 / rate + 0.5))
