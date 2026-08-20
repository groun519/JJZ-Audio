from __future__ import annotations

from PySide6.QtWidgets import QWidget

from jang_app.qt_app.studio_simple_effect_editor import (
    SimpleEffectEditorSpec,
    SimpleEffectField,
    SimpleEffectPreset,
    StudioSimpleEffectEditor,
)
from jang_app.services.studio_hard_tune_presets import (
    CUSTOM_HARD_TUNE_PRESET,
    STUDIO_HARD_TUNE_PRESETS,
)
from jang_app.services.studio_session import (
    STUDIO_EFFECT_HARD_TUNE,
    StudioHardTuneSettings,
)


_NOTE_CHOICES = tuple(
    enumerate(("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"))
)
_SCALE_CHOICES = (
    ("chromatic", "Chromatic"),
    ("major", "Major"),
    ("minor", "Minor"),
)

_SPEC = SimpleEffectEditorSpec(
    effect_kind=STUDIO_EFFECT_HARD_TUNE,
    settings_field="hard_tune",
    settings_factory=StudioHardTuneSettings,
    custom_preset=CUSTOM_HARD_TUNE_PRESET,
    presets=tuple(
        SimpleEffectPreset(preset.key, preset.name, preset.settings)
        for preset in STUDIO_HARD_TUNE_PRESETS
    ),
    groups=(
        ("Music", ("key_note", "scale")),
        ("Correction", ("strength_percent", "response_ms")),
        ("Expression", ("vibrato_preserve_percent",)),
    ),
    fields=(
        SimpleEffectField(
            "key_note",
            "Key",
            0,
            11,
            1,
            "",
            "Sets the root note used by Major and Minor scales.",
            "The key is ignored in Chromatic mode.",
            _NOTE_CHOICES,
        ),
        SimpleEffectField(
            "scale",
            "Musical Scale",
            0,
            2,
            1,
            "",
            "Chooses which notes the vocal is allowed to lock onto.",
            "Use Chromatic when the song key is unknown.",
            _SCALE_CHOICES,
        ),
        SimpleEffectField(
            "strength_percent",
            "Tune Strength",
            0,
            100,
            1,
            "%",
            "Controls how firmly detected pitch is pulled toward the target note.",
            "Use 85-100% for an obvious synthetic vocal sound.",
        ),
        SimpleEffectField(
            "response_ms",
            "Retune Speed",
            5,
            250,
            5,
            " ms",
            "Controls how quickly pitch correction reacts to a new note.",
            "Use 10-40 ms for hard tuning and higher values for smoother correction.",
        ),
        SimpleEffectField(
            "vibrato_preserve_percent",
            "Vibrato Preserve",
            0,
            100,
            1,
            "%",
            "Leaves part of the singer's small pitch movement untouched.",
            "Use 0-20% for a synthetic sound and 40% or more for natural vibrato.",
        ),
    ),
    preset_detail="Choose how tightly the vocal should lock to musical notes.",
    preset_recommendation="Synth is the recommended starting point for a Vocaloid-style sound.",
)


class StudioHardTuneEditor(StudioSimpleEffectEditor):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(_SPEC, parent)
        self.setObjectName("StudioHardTuneEditor")
