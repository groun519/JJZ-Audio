from __future__ import annotations

import unittest
import tempfile
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QApplication

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
