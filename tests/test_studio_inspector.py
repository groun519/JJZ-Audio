from __future__ import annotations

import tempfile
import unittest
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


if __name__ == "__main__":
    unittest.main()
