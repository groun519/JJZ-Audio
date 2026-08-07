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
from jang_app.qt_app.theme import build_stylesheet
from jang_app.qt_app.widgets import TransparentContainer
from jang_app.services.clip_edit_history import REVIEW_EDITING, TRAINING_MODE_CLIPS
from jang_app.services.i18n import LANGUAGE_KOREAN, current_language, set_language
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
        editor._show_clips_page()
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

    def test_used_clip_can_move_to_review_with_shared_status_controls(self) -> None:
        editor = ModelClipEditor()
        editor.set_item(_item_with_clip())
        editor._show_clips_page()
        editor.clip_list.setCurrentRow(0)
        clip_spy = QSignalSpy(editor.clip_status_requested)
        candidate_spy = QSignalSpy(editor.candidate_status_requested)

        editor.hold_candidate_button.click()

        self.assertEqual(clip_spy.count(), 1)
        self.assertEqual(list(clip_spy.at(0)), ["clip-1", SEGMENT_HELD])
        self.assertEqual(candidate_spy.count(), 0)
        self.assertTrue(editor.use_candidate_button.property("active"))
        self.assertFalse(editor.use_candidate_button.isEnabled())
        editor.close()

    def test_editor_controls_are_grouped_by_navigation_editing_and_tools(self) -> None:
        editor = ModelClipEditor()

        for control in (editor.previous_button, editor.next_button):
            self.assertTrue(editor.editor_header.isAncestorOf(control))
        for control in (
            editor.play_button,
            editor.queue_candidate_button,
            editor.hold_candidate_button,
            editor.exclude_candidate_button,
            editor.use_candidate_button,
            editor.ready_button,
        ):
            self.assertTrue(editor.command_bar.isAncestorOf(control))
        self.assertTrue(editor.audio_inspector.isAncestorOf(editor.cleanup_bar))
        self.assertTrue(editor.audio_inspector.isAncestorOf(editor.analysis_bar))
        self.assertEqual(editor.tool_stack.currentWidget(), editor.cleanup_bar)
        self.assertEqual(editor.audio_inspector.minimumWidth(), 320)
        self.assertEqual(editor.audio_inspector.maximumWidth(), 320)
        self.assertFalse(editor.audio_inspector.isAncestorOf(editor.command_bar))
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
        self.assertEqual(editor.previous_button.width(), 32)
        self.assertEqual(editor.play_button.width(), 32)
        self.assertEqual(editor.next_button.width(), 32)
        self.assertTrue(editor.command_bar.isAncestorOf(editor.play_button))
        editor.close()

    def test_tool_switch_keeps_waveform_geometry_fixed(self) -> None:
        editor = ModelClipEditor()
        editor.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
        editor.resize(1200, 620)
        editor.set_item(_item_with_clip())
        editor.show()
        self.app.processEvents()
        cleanup_geometry = editor.waveform.geometry()

        editor.analysis_tool_button.click()
        self.app.processEvents()

        self.assertEqual(editor.waveform.geometry(), cleanup_geometry)
        self.assertEqual(editor.audio_inspector.width(), 320)
        self.assertEqual(editor.play_shortcut_badge.text(), "SPACE")
        editor.close()

    def test_review_text_buttons_share_font_metrics(self) -> None:
        previous_stylesheet = self.app.styleSheet()
        self.app.setStyleSheet(build_stylesheet("dark"))
        try:
            editor = ModelClipEditor()
            editor.show()
            self.app.processEvents()
            controls = (
                editor.queue_candidate_button,
                editor.hold_candidate_button,
                editor.exclude_candidate_button,
                editor.use_candidate_button,
                editor.ready_button,
            )
            metrics = {
                (button.font().family(), button.font().pixelSize(), button.font().weight())
                for button in controls
            }
            self.assertEqual(len(metrics), 1)
            editor.close()
        finally:
            self.app.setStyleSheet(previous_stylesheet)

    def test_noise_tool_uses_plain_professional_korean(self) -> None:
        previous_language = current_language()
        set_language(LANGUAGE_KOREAN)
        try:
            editor = ModelClipEditor()
            editor.apply_language()

            self.assertEqual(editor.cleanup_bar.automatic_reference_button.text(), "자동 분석")
            self.assertEqual(editor.cleanup_bar.selection_reference_button.text(), "선택 구간")
            self.assertEqual(editor.cleanup_bar.sample_button.text(), "현재 선택 구간 지정")
            self.assertEqual(editor.preview_denoise_button.text(), "결과 미리듣기")
            self.assertEqual(editor.apply_denoise_button.text(), "전체 음원에 적용")
            self.assertEqual(editor.cleanup_bar.safety_label.text(), "원본 보존 · 언제든 되돌리기 가능")
            self.assertEqual(editor.add_clip_button.text(), "선택 구간 추가")
            editor.close()
        finally:
            set_language(previous_language)

    def test_clip_detection_settings_explain_effects_and_starting_values(self) -> None:
        previous_language = current_language()
        set_language(LANGUAGE_KOREAN)
        try:
            editor = ModelClipEditor()
            editor.apply_language()
            info_buttons = (
                editor.analysis_bar.threshold_info,
                editor.analysis_bar.silence_info,
                editor.analysis_bar.padding_info,
                editor.analysis_bar.max_clip_info,
            )

            self.assertTrue(all(button.size().width() == 18 for button in info_buttons))
            self.assertIn("작은 목소리가 제외", editor.analysis_bar.threshold_info.toolTip())
            self.assertIn("권장 시작값: -40 dB", editor.analysis_bar.threshold_info.toolTip())
            self.assertIn("클립이 많아지고", editor.analysis_bar.silence_info.toolTip())
            self.assertIn("발음이 잘릴 수", editor.analysis_bar.padding_info.toolTip())
            self.assertIn("권장 시작값: 12초", editor.analysis_bar.max_clip_info.toolTip())
            editor.close()
        finally:
            set_language(previous_language)

    def test_clip_detection_field_headers_use_transparent_theme_container(self) -> None:
        editor = ModelClipEditor()

        field_headers = editor.analysis_bar.findChildren(
            QWidget,
            "DatasetToolFieldHeader",
        )

        self.assertEqual(len(field_headers), 4)
        self.assertTrue(all(isinstance(header, TransparentContainer) for header in field_headers))
        self.assertTrue(all(header.property("surfaceRole") == "transparent" for header in field_headers))
        editor.close()

    def test_audio_tool_auxiliary_containers_share_transparent_theme(self) -> None:
        editor = ModelClipEditor()

        transparent_containers = editor.audio_inspector.findChildren(
            TransparentContainer,
        )

        self.assertGreaterEqual(len(transparent_containers), 8)
        self.assertTrue(
            all(container.property("surfaceRole") == "transparent" for container in transparent_containers)
        )
        self.assertIn(
            'QWidget[surfaceRole="transparent"]',
            build_stylesheet("dark"),
        )
        editor.close()

    def test_header_navigation_shows_current_training_audio_position(self) -> None:
        editor = ModelClipEditor()
        editor.set_item(_item_with_clip())

        editor.set_navigation_state(True, True, 3, 8)

        self.assertEqual(editor.editor_header.navigation_label.text(), "3 / 8")
        self.assertTrue(editor.previous_button.isEnabled())
        self.assertTrue(editor.next_button.isEnabled())
        editor.close()

    def test_low_frequency_clip_actions_live_in_overflow_menu(self) -> None:
        editor = ModelClipEditor()
        editor.set_item(_item_with_clip())
        editor._show_clips_page()
        editor.clip_list.setCurrentRow(0)
        remove_spy = QSignalSpy(editor.remove_clip_requested)

        editor.remove_clip_action.trigger()

        self.assertEqual(remove_spy.count(), 1)
        self.assertEqual(list(remove_spy.at(0)), ["clip-1"])
        self.assertTrue(editor.reset_action.isEnabled())
        editor.close()

    def test_review_shortcuts_cover_playback_and_decisions(self) -> None:
        editor = ModelClipEditor()

        shortcuts = {
            shortcut.key().toString()
            for shortcut in editor._review_shortcuts
        }

        self.assertEqual(shortcuts, {"Space", "Q", "W", "E", "R", "T"})
        self.assertIn("Space", editor.play_button.toolTip())
        self.assertTrue(editor.queue_candidate_button.text().endswith("Q"))
        self.assertTrue(editor.hold_candidate_button.text().endswith("W"))
        self.assertTrue(editor.exclude_candidate_button.text().endswith("E"))
        self.assertTrue(editor.use_candidate_button.text().endswith("R"))
        self.assertTrue(editor.ready_button.text().endswith("T"))
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

        QTest.keyClick(outside_button, Qt.Key.Key_R)
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
                editor.waveform.set_selection(100, 700)
                editor._on_selection_changed(100, 700)
                editor.cleanup_bar.selection_reference_button.click()
                editor.set_noise_sample_button.click()
                editor.denoise_slider.setValue(72)
                editor.apply_denoise_button.click()
                editor.restore_denoise_button.click()

            self.assertEqual(list(denoise_spy.at(0)), [72, 100, 700])
            self.assertEqual(remove_spy.count(), 1)
            editor.close()

    def test_denoise_reference_mode_is_explicit_and_changes_render_parameters(self) -> None:
        editor = ModelClipEditor()
        editor.set_item(_item_with_clip())
        denoise_spy = QSignalSpy(editor.denoise_requested)

        self.assertTrue(editor.cleanup_bar.automatic_reference_button.isChecked())
        self.assertTrue(editor.cleanup_bar.sample_detail.isHidden())

        editor.cleanup_bar.selection_reference_button.click()
        self.assertFalse(editor.apply_denoise_button.isEnabled())
        self.assertFalse(editor.cleanup_bar.sample_detail.isHidden())

        editor.waveform.set_selection(100, 700)
        editor._on_selection_changed(100, 700)
        editor.set_noise_sample_button.click()
        editor.apply_denoise_button.click()
        editor.cleanup_bar.automatic_reference_button.click()
        editor.apply_denoise_button.click()

        self.assertEqual(list(denoise_spy.at(0)), [50, 100, 700])
        self.assertEqual(list(denoise_spy.at(1)), [50, 0, 0])
        editor.close()

    def test_denoise_preview_uses_bounded_selection_and_exposes_ab_controls(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            preview = Path(temporary) / "preview.wav"
            preview.write_bytes(b"preview")
            editor = ModelClipEditor()
            spy = QSignalSpy(editor.denoise_preview_requested)
            with patch(
                "jang_app.qt_app.clip_waveform_view.waveform_cache_key",
                side_effect=OSError,
            ):
                editor.set_item(_item_with_clip())
                editor.waveform.set_selection(100, 1100)
                editor._on_selection_changed(100, 1100)
                editor.preview_denoise_button.click()
                editor.set_denoise_preview(preview, 100, 1100)

            self.assertEqual(list(spy.at(0)), [50, 0, 0, 100, 1100])
            self.assertTrue(editor.cleanup_bar.result_control.isVisibleTo(editor.cleanup_bar))
            self.assertEqual(editor._preview_version, "denoised")
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
