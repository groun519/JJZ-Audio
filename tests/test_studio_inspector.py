from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

import numpy as np
import soundfile as sf
from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import QApplication

from jang_app.qt_app.studio_inspector import StudioInspector
from jang_app.qt_app.theme import build_stylesheet
from jang_app.qt_app.widgets import COMPACT_ICON_BUTTON_SIZE, TimecodeSpinBox
from jang_app.services.i18n import tr
from jang_app.services.studio_assets import StudioSoundAsset
from jang_app.services.studio_session import (
    TRACK_ORIGINAL_VOCAL,
    StudioAssetRef,
    StudioClip,
    StudioEffect,
    StudioTrack,
)


class StudioInspectorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_timecode_editor_formats_and_parses_milliseconds(self) -> None:
        spin = TimecodeSpinBox()

        self.assertEqual(spin.textFromValue(72_345), "01:12.345")
        self.assertEqual(spin.textFromValue(3_672_345), "01:01:12.345")
        self.assertEqual(spin.valueFromText("01:12.345"), 72_345)
        self.assertEqual(spin.valueFromText("1:01:12.345"), 3_672_345)
        spin.lineEdit().setText("01:12.345")
        self.assertTrue(spin.lineEdit().hasAcceptableInput())
        spin.interpretText()
        self.assertEqual(spin.value(), 72_345)

    def test_context_switches_between_empty_clip_and_track_pages(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "vocals.wav"
            sf.write(path, np.ones(16_000, dtype=np.float32), 8_000)
            reference = StudioAssetRef("output-1", TRACK_ORIGINAL_VOCAL)
            asset = StudioSoundAsset(reference, "Maximum / Original Vocal", path, 2_000)
            clip = StudioClip(
                "clip-1",
                reference,
                500,
                0,
                2_000,
                gain_db=-2.5,
                fade_in_ms=100,
                fade_out_ms=200,
            )
            track = StudioTrack(
                "track-original-vocal",
                "Original Vocal",
                TRACK_ORIGINAL_VOCAL,
                pan_percent=-20,
                clips=(clip,),
            )
            inspector = StudioInspector()
            changed = QSignalSpy(inspector.clip_values_changed)

            inspector.set_selection(track, clip, asset)
            self.assertEqual(inspector.stack.currentIndex(), inspector.CLIP_PAGE)
            self.assertEqual(inspector.duration_value.text(), "00:02.000")
            self.assertEqual(inspector.gain_spin.value(), -2.5)
            self.assertEqual(inspector.gain_spin.width(), 112)
            inspector.setStyleSheet(build_stylesheet("dark"))
            inspector.resize(300, 720)
            inspector.show()
            self.app.processEvents()
            self.assertEqual(inspector.gain_spin.width(), 112)
            self.assertGreaterEqual(inspector.gain_slider.width(), 100)
            self.assertEqual(inspector.clip_mute_button.text(), "")
            self.assertFalse(hasattr(inspector, "remove_button"))
            self.assertEqual(inspector.clip_mute_button.icon_name(), "speaker")
            self.assertEqual(
                inspector.clip_mute_button.size().toTuple(),
                (COMPACT_ICON_BUTTON_SIZE, COMPACT_ICON_BUTTON_SIZE),
            )
            self.assertGreaterEqual(
                inspector.clip_section.header_layout.indexOf(inspector.clip_mute_button),
                0,
            )
            inspector.fade_in_spin.setValue(150)
            inspector._emit_clip_values()
            self.assertEqual(changed.count(), 1)
            self.assertEqual(changed.at(0)[6], 150)

            inspector.clip_mute_button.click()
            self.assertEqual(changed.count(), 2)
            self.assertTrue(changed.at(1)[5])
            self.assertEqual(inspector.clip_mute_button.toolTip(), tr("Unmute Clip"))

            inspector.set_selection(track, None, None)
            self.assertEqual(inspector.stack.currentIndex(), inspector.TRACK_PAGE)
            self.assertEqual(inspector.pan_slider.value(), -20)

            inspector.clear_selection()
            self.assertEqual(inspector.stack.currentIndex(), inspector.EMPTY_PAGE)
            inspector.close()

    def test_clip_effects_add_reverb_tabs_and_forward_changes(self) -> None:
        reference = StudioAssetRef("output-1", TRACK_ORIGINAL_VOCAL)
        effect = StudioEffect("fx-reverb", "reverb")
        clip = StudioClip("clip-1", reference, 0, 0, 2_000, effects=(effect,))
        track = StudioTrack(
            "track-original-vocal",
            "Original Vocal",
            TRACK_ORIGINAL_VOCAL,
            clips=(clip,),
        )
        inspector = StudioInspector()
        changed = QSignalSpy(inspector.effect_changed)
        removed = QSignalSpy(inspector.effect_remove_requested)

        inspector.set_selection(track, clip, None)

        self.assertEqual(inspector.effect_tab_ids(), (effect.effect_id,))
        inspector.open_effect_tab(effect.effect_id)
        self.assertEqual(inspector.clip_detail_stack.currentIndex(), 1)
        editor = inspector.effect_editors[effect.effect_id]
        editor.controls["dry_wet_percent"].setValue(44)
        editor._emit_changed()
        editor.remove_button.click()

        self.assertEqual(changed.at(0)[0], clip.clip_id)
        self.assertEqual(changed.at(0)[1].reverb.dry_wet_percent, 44)
        self.assertEqual(tuple(removed.at(0)), (clip.clip_id, effect.effect_id))
        inspector.close()

    def test_selecting_another_clip_resets_the_active_effect_tab(self) -> None:
        reference = StudioAssetRef("output-1", TRACK_ORIGINAL_VOCAL)
        effect = StudioEffect("fx-reverb", "reverb")
        first_clip = StudioClip("clip-1", reference, 0, 0, 1_000, effects=(effect,))
        second_clip = StudioClip("clip-2", reference, 1_000, 1_000, 2_000, effects=(effect,))
        track = StudioTrack(
            "track-original-vocal",
            "Original Vocal",
            TRACK_ORIGINAL_VOCAL,
            clips=(first_clip, second_clip),
        )
        inspector = StudioInspector()

        inspector.set_selection(track, first_clip, None)
        inspector.open_effect_tab(effect.effect_id)
        self.assertEqual(inspector.clip_detail_stack.currentIndex(), 1)

        inspector.set_selection(track, second_clip, None)

        self.assertEqual(inspector.clip_detail_stack.currentIndex(), 0)
        self.assertTrue(inspector.clip_tab_button.isChecked())
        inspector.close()

    def test_repeated_effect_refresh_reuses_the_existing_tab_and_editor(self) -> None:
        reference = StudioAssetRef("output-1", TRACK_ORIGINAL_VOCAL)
        effect = StudioEffect("fx-reverb", "reverb")
        clip = StudioClip("clip-1", reference, 0, 0, 2_000, effects=(effect,))
        track = StudioTrack(
            "track-original-vocal",
            "Original Vocal",
            TRACK_ORIGINAL_VOCAL,
            clips=(clip,),
        )
        inspector = StudioInspector()
        changed = QSignalSpy(inspector.effect_changed)

        inspector.set_selection(track, clip, None)
        button = inspector.effect_tab_buttons[effect.effect_id]
        editor = inspector.effect_editors[effect.effect_id]
        updated_effect = replace(
            effect,
            reverb=replace(effect.reverb, dry_wet_percent=61),
        )
        updated_clip = replace(clip, effects=(updated_effect,))

        for _ in range(3):
            inspector.set_selection(track, updated_clip, None)

        self.assertIs(inspector.effect_tab_buttons[effect.effect_id], button)
        self.assertIs(inspector.effect_editors[effect.effect_id], editor)
        self.assertEqual(inspector.clip_tabs_layout.count(), 3)
        self.assertEqual(inspector.clip_detail_stack.count(), 2)
        self.assertEqual(editor.controls["dry_wet_percent"].value(), 61)

        editor._emit_changed()
        self.assertEqual(changed.count(), 1)
        inspector.close()


if __name__ == "__main__":
    unittest.main()
