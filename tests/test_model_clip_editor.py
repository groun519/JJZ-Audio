from __future__ import annotations

import unittest
import tempfile
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import (
    QApplication,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from jang_app.qt_app.model_clip_editor import ModelClipEditor
from jang_app.services.clip_edit_history import REVIEW_EDITING, TRAINING_MODE_CLIPS
from jang_app.services.model_dataset import ModelDatasetClip, ModelDatasetItem
from jang_app.services.segment_review import SEGMENT_HELD, SegmentCandidate


class ModelClipEditorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_selected_clip_handle_emits_non_destructive_range_update(self) -> None:
        editor = ModelClipEditor()
        editor.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
        editor.resize(1000, 420)
        editor.show()
        self.app.processEvents()
        editor.set_item(_item_with_clip())
        editor.clip_list.setCurrentRow(0)
        spy = QSignalSpy(editor.update_clip_requested)
        waveform = editor.waveform
        y_position = round(waveform._content_rect().center().y())
        start = QPoint(round(waveform._ms_to_x(100)), y_position)
        target = QPoint(round(waveform._ms_to_x(250)), y_position)

        QTest.mousePress(waveform, Qt.MouseButton.LeftButton, pos=start)
        QTest.mouseMove(waveform, target)
        QTest.mouseRelease(waveform, Qt.MouseButton.LeftButton, pos=target)

        self.assertEqual(spy.count(), 1)
        self.assertEqual(list(spy.at(0)), ["clip-1", 250, 900])
        editor.close()

    def test_candidate_is_refined_and_emitted_one_at_a_time(self) -> None:
        editor = ModelClipEditor()
        editor.set_item(_item_with_clip())
        editor.waveform.set_selection(150, 450)
        editor._on_selection_changed(150, 450)
        spy = QSignalSpy(editor.use_candidate_requested)

        editor.use_candidate_button.click()

        self.assertEqual(spy.count(), 1)
        self.assertEqual(list(spy.at(0)), ["candidate-1", 150, 450])
        editor.close()

    def test_candidate_can_be_held_from_review_queue(self) -> None:
        editor = ModelClipEditor()
        editor.set_item(_item_with_clip())
        spy = QSignalSpy(editor.candidate_status_requested)

        editor.hold_candidate_button.click()

        self.assertEqual(spy.count(), 1)
        self.assertEqual(list(spy.at(0)), ["candidate-1", SEGMENT_HELD])
        editor.close()

    def test_review_controls_share_one_primary_bar(self) -> None:
        editor = ModelClipEditor()

        for control in (
            editor.previous_button,
            editor.play_button,
            editor.next_button,
            editor.hold_candidate_button,
            editor.exclude_candidate_button,
            editor.use_candidate_button,
            editor.ready_button,
        ):
            self.assertTrue(editor.review_bar.isAncestorOf(control))
        layout = editor.layout()
        self.assertLess(
            layout.indexOf(editor.review_bar),
            layout.indexOf(editor.secondary_tools),
        )
        self.assertTrue(editor.secondary_tools.isAncestorOf(editor.cleanup_bar))
        self.assertTrue(editor.secondary_tools.isAncestorOf(editor.analysis_bar))
        self.assertEqual(editor.tool_stack.currentWidget(), editor.cleanup_bar)
        editor.analysis_tool_button.click()
        self.assertEqual(editor.tool_stack.currentWidget(), editor.analysis_bar)
        editor.close()

    def test_review_buttons_share_one_control_height(self) -> None:
        editor = ModelClipEditor()
        editor.resize(1200, 520)
        editor.show()
        self.app.processEvents()

        controls = (
            editor.previous_button,
            editor.play_button,
            editor.next_button,
            editor.queue_candidate_button,
            editor.hold_candidate_button,
            editor.exclude_candidate_button,
            editor.use_candidate_button,
            editor.ready_button,
            editor.loop_button,
            editor.split_button,
        )

        self.assertEqual({control.height() for control in controls}, {32})
        self.assertTrue(all(control.width() == 32 for control in controls[:3]))
        editor.close()

    def test_review_shortcuts_cover_playback_and_decisions(self) -> None:
        editor = ModelClipEditor()

        shortcuts = {
            shortcut.key().toString()
            for shortcut in editor._review_shortcuts
        }

        self.assertEqual(shortcuts, {"Space", "A", "H", "X", "R"})
        self.assertEqual(editor.play_shortcut_badge.text(), "SPACE")
        self.assertTrue(editor.use_candidate_button.text().endswith("A"))
        self.assertTrue(editor.hold_candidate_button.text().endswith("H"))
        self.assertTrue(editor.exclude_candidate_button.text().endswith("X"))
        self.assertTrue(editor.ready_button.text().endswith("R"))
        editor.close()

    def test_review_shortcuts_work_when_focus_remains_outside_editor(self) -> None:
        host = QWidget()
        host.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
        outside_button = QPushButton("Outside")
        editor = ModelClipEditor()
        layout = QVBoxLayout(host)
        layout.addWidget(outside_button)
        layout.addWidget(editor)
        editor.set_item(_item_with_clip())
        editor.play_button.clicked.disconnect(editor._toggle_playback)
        use_spy = QSignalSpy(editor.use_candidate_requested)
        play_spy = QSignalSpy(editor.play_button.clicked)
        outside_spy = QSignalSpy(outside_button.clicked)
        host.show()
        host.activateWindow()
        self.app.processEvents()
        outside_button.setFocus()
        self.app.processEvents()

        QTest.keyClick(outside_button, Qt.Key.Key_A)
        QTest.keyClick(outside_button, Qt.Key.Key_Space)

        self.assertEqual(use_spy.count(), 1)
        self.assertEqual(play_spy.count(), 1)
        self.assertEqual(outside_spy.count(), 0)
        host.close()

    def test_same_audio_refresh_preserves_zoom_after_using_region(self) -> None:
        editor = ModelClipEditor()
        item = _item_with_clip()
        editor.set_item(item)
        editor.zoom_slider.setValue(6)
        updated = replace(
            item,
            segment_candidates=(
                SegmentCandidate("candidate-2", 600, 1000),
            ),
        )

        editor.set_item(updated)

        self.assertEqual(editor.zoom_slider.value(), 6)
        self.assertEqual(editor.waveform.view_state().zoom, 6)
        editor.close()

    def test_switching_audio_resets_zoom(self) -> None:
        editor = ModelClipEditor()
        editor.set_item(_item_with_clip())
        editor.zoom_slider.setValue(6)

        editor.set_item(replace(_item_with_clip(), item_id="item-2"))

        self.assertEqual(editor.zoom_slider.value(), 1)
        self.assertEqual(editor.waveform.view_state().zoom, 1)
        editor.close()

    def test_close_button_requests_editor_dismissal(self) -> None:
        editor = ModelClipEditor()
        spy = QSignalSpy(editor.close_requested)

        editor.close_button.click()

        self.assertEqual(spy.count(), 1)
        editor.close()

    def test_denoise_controls_switch_preview_and_emit_settings(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            original = root / "original.wav"
            denoised = root / "denoised.wav"
            original.write_bytes(b"original")
            denoised.write_bytes(b"denoised")
            item = replace(
                _item_with_clip(),
                working_path=original,
                denoised_path=denoised,
                denoise_strength=64,
            )
            editor = ModelClipEditor()
            with patch(
                "jang_app.qt_app.clip_waveform_view.waveform_cache_key",
                side_effect=OSError,
            ):
                editor.set_item(item)
                self.assertEqual(editor._preview_version, "denoised")
                editor.original_source_button.click()
                self.assertEqual(editor._preview_version, "original")
                denoise_spy = QSignalSpy(editor.denoise_requested)
                remove_spy = QSignalSpy(editor.remove_denoise_requested)
                editor.set_noise_sample_button.click()
                editor.denoise_slider.setValue(72)
                editor.apply_denoise_button.click()
                editor.remove_denoise_button.click()

            self.assertEqual(list(denoise_spy.at(0)), [72, 100, 500])
            self.assertEqual(remove_spy.count(), 1)
            editor.close()


def _item_with_clip() -> ModelDatasetItem:
    clip = ModelDatasetClip("clip-1", 100, 900, Path("clip.wav"), "now")
    return ModelDatasetItem(
        item_id="item-1",
        source_name="voice.wav",
        source_path=Path("voice.wav"),
        original_path=Path("original.wav"),
        working_path=Path("working.wav"),
        added_at="now",
        duration_ms=1200,
        selected_order=0,
        clips=(clip,),
        training_mode=TRAINING_MODE_CLIPS,
        review_state=REVIEW_EDITING,
        segment_candidates=(SegmentCandidate("candidate-1", 100, 500),),
    )


if __name__ == "__main__":
    unittest.main()
