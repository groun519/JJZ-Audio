from __future__ import annotations

import numpy as np

from jang_app.services.realtime_reverb import RealtimeReverb
from jang_app.services.studio_session import STUDIO_EFFECT_REVERB, StudioEffect


class RealtimeEffectChain:
    def __init__(self, sample_rate: int, effects: tuple[StudioEffect, ...] = ()) -> None:
        self._sample_rate = sample_rate
        self._effects: tuple[StudioEffect, ...] = ()
        self._reverbs: dict[str, RealtimeReverb] = {}
        self.update(effects)

    @property
    def effects(self) -> tuple[StudioEffect, ...]:
        return self._effects

    def update(self, effects: tuple[StudioEffect, ...]) -> None:
        active_ids = {
            effect.effect_id
            for effect in effects
            if effect.enabled and effect.kind == STUDIO_EFFECT_REVERB
        }
        self._reverbs = {
            effect_id: processor
            for effect_id, processor in self._reverbs.items()
            if effect_id in active_ids
        }
        for effect in effects:
            if not effect.enabled or effect.kind != STUDIO_EFFECT_REVERB:
                continue
            processor = self._reverbs.get(effect.effect_id)
            if processor is None:
                processor = RealtimeReverb(self._sample_rate, effect.reverb)
                self._reverbs[effect.effect_id] = processor
            else:
                processor.update(effect.reverb)
        self._effects = effects

    def process(self, audio: np.ndarray) -> np.ndarray:
        processed = audio
        for effect in self._effects:
            if not effect.enabled or effect.kind != STUDIO_EFFECT_REVERB:
                continue
            processor = self._reverbs.get(effect.effect_id)
            if processor is not None:
                processed = processor.process(processed)
        return processed
