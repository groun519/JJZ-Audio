from __future__ import annotations

import unittest
from pathlib import Path

from PySide6.QtWidgets import QApplication

from jang_app.qt_app.quick_create_panel import QuickCreatePanel
from jang_app.services.rvc_model_choices import RvcModelChoice


class QuickCreatePanelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.panel = QuickCreatePanel()

    def tearDown(self) -> None:
        self.panel.close()
        self.panel.deleteLater()

    def test_requires_both_work_song_and_model(self) -> None:
        self.assertFalse(self.panel.action_button.isEnabled())

        self.panel.set_work_song(
            can_create=True,
        )
        self.assertFalse(self.panel.action_button.isEnabled())

        self.panel.set_model_choices((_choice(),))
        self.panel.model_combo.setCurrentIndex(1)
        self.assertTrue(self.panel.action_button.isEnabled())

    def test_start_emits_selected_model_and_pitch(self) -> None:
        choice = _choice(pitch=-12)
        emitted: list[tuple[RvcModelChoice, int]] = []
        self.panel.start_requested.connect(
            lambda selected, pitch: emitted.append((selected, pitch))
        )
        self.panel.set_work_song(
            can_create=True,
        )
        self.panel.set_model_choices((choice,))
        self.panel.model_combo.setCurrentIndex(1)
        self.panel.pitch_spin.setValue(-9)

        self.panel.action_button.click()

        self.assertEqual(emitted, [(choice, -9)])

    def test_model_selection_applies_its_default_pitch(self) -> None:
        choice = _choice(pitch=7)
        self.panel.set_model_choices((choice,))

        self.panel.model_combo.setCurrentIndex(1)

        self.assertEqual(self.panel.pitch(), 7)

    def test_running_state_locks_controls_until_completion(self) -> None:
        self.panel.set_work_song(
            can_create=True,
        )
        self.panel.set_model_choices((_choice(),))
        self.panel.model_combo.setCurrentIndex(1)

        self.panel.set_running(True)
        self.panel.set_progress(46)

        self.assertFalse(self.panel.action_button.isEnabled())
        self.assertFalse(self.panel.model_combo.isEnabled())
        self.assertEqual(self.panel.progress_bar.value(), 46)

        self.panel.set_running(False)
        self.assertTrue(self.panel.action_button.isEnabled())


def _choice(*, pitch: int = 0) -> RvcModelChoice:
    return RvcModelChoice(
        choice_id="library:voice",
        label="Voice",
        root=Path("C:/rvc"),
        model_path=Path("C:/models/voice.pth"),
        model_id="voice",
        pitch=pitch,
    )


if __name__ == "__main__":
    unittest.main()
