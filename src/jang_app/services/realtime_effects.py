from __future__ import annotations

import numpy as np

from jang_app.services.audio_character_fx import (
    CharacterEffectProcessor,
    create_character_effect_processor,
)
from jang_app.services.realtime_delay import RealtimeDelay
from jang_app.services.realtime_doubler import RealtimeDoubler
from jang_app.services.realtime_reverb import RealtimeReverb
from jang_app.services.studio_character_fx_presets import CHARACTER_EFFECT_KINDS
from jang_app.services.studio_session import (
    STUDIO_EFFECT_DELAY,
    STUDIO_EFFECT_DOUBLER,
    STUDIO_EFFECT_REVERB,
    StudioEffect,
)


class RealtimeEffectChain:
    def __init__(self, sample_rate: int, effects: tuple[StudioEffect, ...] = ()) -> None:
        self._sample_rate = sample_rate
        self._effects: tuple[StudioEffect, ...] = ()
        self._reverbs: dict[str, RealtimeReverb] = {}
        self._delays: dict[str, RealtimeDelay] = {}
        self._doublers: dict[str, RealtimeDoubler] = {}
        self._character_effects: dict[str, CharacterEffectProcessor] = {}
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
        delay_ids = {
            effect.effect_id
            for effect in effects
            if effect.enabled and effect.kind == STUDIO_EFFECT_DELAY
        }
        self._delays = {
            effect_id: processor
            for effect_id, processor in self._delays.items()
            if effect_id in delay_ids
        }
        doubler_ids = {
            effect.effect_id
            for effect in effects
            if effect.enabled and effect.kind == STUDIO_EFFECT_DOUBLER
        }
        self._doublers = {
            effect_id: processor
            for effect_id, processor in self._doublers.items()
            if effect_id in doubler_ids
        }
        character_ids = {
            effect.effect_id
            for effect in effects
            if effect.enabled and effect.kind in CHARACTER_EFFECT_KINDS
        }
        self._character_effects = {
            effect_id: processor
            for effect_id, processor in self._character_effects.items()
            if effect_id in character_ids
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
        for effect in effects:
            if not effect.enabled or effect.kind != STUDIO_EFFECT_DELAY:
                continue
            processor = self._delays.get(effect.effect_id)
            if processor is None:
                processor = RealtimeDelay(self._sample_rate, effect.delay)
                self._delays[effect.effect_id] = processor
            else:
                processor.update(effect.delay)
        for effect in effects:
            if not effect.enabled or effect.kind != STUDIO_EFFECT_DOUBLER:
                continue
            processor = self._doublers.get(effect.effect_id)
            if processor is None:
                processor = RealtimeDoubler(self._sample_rate, effect.doubler)
                self._doublers[effect.effect_id] = processor
            else:
                processor.update(effect.doubler)
        for effect in effects:
            if not effect.enabled or effect.kind not in CHARACTER_EFFECT_KINDS:
                continue
            processor = self._character_effects.get(effect.effect_id)
            if processor is None or processor.kind != effect.kind:
                processor = create_character_effect_processor(self._sample_rate, effect)
                self._character_effects[effect.effect_id] = processor
            else:
                processor.update(effect)
        self._effects = effects

    def process(self, audio: np.ndarray) -> np.ndarray:
        processed = audio
        for effect in self._effects:
            if not effect.enabled:
                continue
            if effect.kind == STUDIO_EFFECT_REVERB:
                processor = self._reverbs.get(effect.effect_id)
            elif effect.kind == STUDIO_EFFECT_DELAY:
                processor = self._delays.get(effect.effect_id)
            elif effect.kind == STUDIO_EFFECT_DOUBLER:
                processor = self._doublers.get(effect.effect_id)
            else:
                processor = self._character_effects.get(effect.effect_id)
            if processor is not None:
                processed = processor.process(processed)
        return processed
