from __future__ import annotations

import unittest
from pathlib import Path

from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import QApplication

from jang_app.qt_app.vocal_results_panel import VocalResultsPanel
from jang_app.qt_app.widgets import TrackMixControl, TrackRow
from jang_app.services.i18n import tr
from jang_app.services.song_library import SongVocalVersion
from jang_app.services.vocal_project import (
    UNASSIGNED_SPEAKER_ID,
    VOCAL_PROJECT_SCHEMA_VERSION,
    VocalConversionSettings,
    VocalProject,
    VocalSegment,
    VocalSpeaker,
    VocalTake,
)


class VocalResultsPanelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_applies_one_active_result_and_selects_converted_versions(self) -> None:
        panel = VocalResultsPanel()
        second = _version("second", (Path("second-a.wav"), Path("second-b.wav")), Path("second-b.wav"))
        converted_changed = QSignalSpy(panel.converted_selected)

        panel.set_result(second)

        self.assertEqual(converted_changed.count(), 0)
        self.assertEqual(panel.current_result(), second)
        self.assertEqual(panel.converted_waveform.current_path(), Path("second-b.wav"))
        self.assertFalse(panel.converted_waveform.path_combo.isHidden())

        panel.converted_waveform.path_combo.setCurrentIndex(0)
        self.assertEqual(converted_changed.count(), 1)
        self.assertEqual(converted_changed.at(0)[0], Path("second-a.wav"))
        panel.close()

    def test_header_exposes_only_the_active_result_location(self) -> None:
        panel = VocalResultsPanel()
        version = _version("selected", ())
        opened = QSignalSpy(panel.open_location_requested)
        panel.set_result(version)

        panel.open_location_button.click()

        self.assertEqual(opened.at(0)[0], version.job_dir)
        self.assertFalse(hasattr(panel, "version_combo"))
        self.assertFalse(hasattr(panel, "remove_output_button"))
        panel.close()

    def test_conversion_mode_shows_the_active_separation_context(self) -> None:
        panel = VocalResultsPanel(mode="conversion")
        version = _version("selected", ())

        panel.set_result(version)

        self.assertIn(version.label, panel.context_label.text())
        self.assertTrue(panel.result_combo.isHidden())
        panel.close()

    def test_converted_selector_is_hidden_until_multiple_versions_exist(self) -> None:
        panel = VocalResultsPanel()
        panel.set_result(_version("single", (Path("single.wav"),)))
        self.assertTrue(panel.converted_waveform.path_combo.isHidden())

        panel.set_result(_version("multiple", (Path("first.wav"), Path("second.wav"))))
        self.assertFalse(panel.converted_waveform.path_combo.isHidden())
        panel.close()

    def test_conversion_mode_exposes_one_header_selector_for_converted_takes(self) -> None:
        panel = VocalResultsPanel(mode="conversion")
        first = Path("first.wav")
        second = Path("second.wav")
        project = VocalProject(
            schema_version=VOCAL_PROJECT_SCHEMA_VERSION,
            project_id="vocal-selector-test",
            created_at="2026-08-08T12:00:00+00:00",
            updated_at="2026-08-08T12:34:00+00:00",
            duration_ms=12_000,
            vocals_path=Path("vocals.wav"),
            instrumental_path=Path("no_vocals.wav"),
            speakers=(VocalSpeaker(UNASSIGNED_SPEAKER_ID, "Unassigned", "#898780"),),
            segments=(VocalSegment("segment-001", 0, 12_000, UNASSIGNED_SPEAKER_ID),),
            takes=(
                _take("take-first", "Bright", first, 0),
                _take("take-second", "Warm", second, -5),
            ),
            active_take_id="take-second",
        )
        selected = QSignalSpy(panel.converted_selected)

        panel.set_result(_version("multiple", (first, second), second), project)

        self.assertFalse(panel.conversion_take_combo.isHidden())
        self.assertEqual(panel.conversion_take_combo.count(), 2)
        self.assertTrue(panel.converted_waveform.path_combo.isHidden())
        self.assertIn("Warm", panel.conversion_take_combo.currentText())
        self.assertIn("-5", panel.conversion_take_combo.currentText())

        panel.conversion_take_combo.setCurrentIndex(0)

        self.assertEqual(selected.count(), 1)
        self.assertEqual(selected.at(0)[0], first)
        self.assertEqual(panel.converted_waveform.current_path(), first)
        panel.close()

    def test_separation_mode_selects_a_saved_run(self) -> None:
        panel = VocalResultsPanel(mode="separation")
        first = _version("first", ())
        second = _version("second", ())
        selected = QSignalSpy(panel.result_selected)

        panel.set_versions((first, second), second.job_dir)
        self.assertEqual(panel.result_combo.currentData(), str(second.job_dir))
        panel.result_combo.setCurrentIndex(0)

        self.assertEqual(selected.at(0)[0], first.job_dir)
        self.assertNotIn(panel.converted_waveform, panel.result_waveforms)
        panel.close()

    def test_separation_selector_is_always_visible_and_labeled(self) -> None:
        panel = VocalResultsPanel(mode="separation")

        self.assertFalse(panel.result_selector_label.isHidden())
        self.assertEqual(panel.result_selector_label.text(), tr("Current separation result"))
        self.assertFalse(panel.result_combo.isHidden())
        panel.close()

    def test_current_result_falls_back_into_an_empty_separation_list(self) -> None:
        panel = VocalResultsPanel(mode="separation")
        current = _version("current", ())

        panel.set_versions((), None)
        panel.set_result(current)

        self.assertEqual(panel.result_combo.count(), 1)
        self.assertEqual(panel.result_combo.currentData(), str(current.job_dir))
        self.assertTrue(panel.result_combo.isEnabled())
        panel.close()

    def test_converted_take_exposes_metadata_and_management_actions(self) -> None:
        panel = VocalResultsPanel()
        path = Path("voice.wav")
        take = VocalTake(
            "take-voice",
            "Warm take",
            path,
            "2026-08-06T01:20:00+00:00",
            VocalConversionSettings(
                "weights/voice.pth",
                "logs/voice/added.index",
                -12,
                "gpu",
                "cuda:0",
                "rmvpe",
            ),
        )
        renamed = QSignalSpy(panel.rename_take_requested)
        reconverted = QSignalSpy(panel.reconvert_take_requested)

        panel.converted_waveform.set_takes([path], (take,), path)
        panel.converted_waveform.rename_button.click()
        panel.converted_waveform.reconvert_button.click()

        self.assertEqual(panel.converted_waveform.path_combo.currentText(), "Warm take")
        self.assertIn("voice", panel.converted_waveform.metadata_label.text())
        self.assertIn("-12", panel.converted_waveform.metadata_label.text())
        self.assertEqual(renamed.at(0)[0], path)
        self.assertEqual(reconverted.at(0)[0], path)
        panel.close()

    def test_studio_track_can_restore_a_converted_version_without_user_signal(self) -> None:
        row = TrackRow("Converted Vocal", allow_selection=True)
        changed = QSignalSpy(row.source_changed)
        first = Path("first.wav")
        second = Path("second.wav")

        row.set_options([first, second], second)
        self.assertEqual(row.current_path(), second)
        self.assertEqual(changed.count(), 0)

        self.assertTrue(row.select_path(first))
        self.assertEqual(row.current_path(), first)
        self.assertEqual(changed.count(), 0)
        row.close()

    def test_studio_track_restores_mix_state_without_emitting_change(self) -> None:
        row = TrackRow("Original Vocal")
        changed = QSignalSpy(row.playback_settings_changed)

        row.set_mix_state(muted=True, volume_percent=175)

        self.assertTrue(row.is_muted())
        self.assertEqual(row.volume_percent(), 175)
        self.assertEqual(row.volume(), 1.75)
        self.assertEqual(changed.count(), 0)
        row.close()

    def test_result_track_exposes_the_shared_mix_control(self) -> None:
        panel = VocalResultsPanel(mode="separation")
        panel.set_result(_version("selected", ()))
        changed = QSignalSpy(panel.playback_settings_changed)

        self.assertIsInstance(panel.original_waveform.mix_control, TrackMixControl)
        panel.original_waveform.mix_control.mute_button.click()
        panel.original_waveform.mix_control.volume_slider.setValue(150)

        self.assertEqual(changed.count(), 2)
        self.assertEqual(changed.at(0), ["original", True, 100])
        self.assertEqual(changed.at(1), ["original", True, 150])
        panel.close()

    def test_result_mix_state_sync_does_not_emit_a_user_change(self) -> None:
        panel = VocalResultsPanel(mode="conversion")
        panel.set_result(_version("selected", (Path("converted.wav"),)))
        changed = QSignalSpy(panel.playback_settings_changed)

        panel.set_mix_state("converted", muted=True, volume_percent=175)

        control = panel.converted_waveform.mix_control
        self.assertTrue(control.is_muted())
        self.assertEqual(control.volume_percent(), 175)
        self.assertEqual(changed.count(), 0)
        panel.close()


def _version(
    name: str,
    converted_paths: tuple[Path, ...],
    active_converted: Path | None = None,
) -> SongVocalVersion:
    return SongVocalVersion(
        version_id=f"output-{name}",
        label=name.title(),
        job_dir=Path(name),
        added_at="2026-08-02T10:30:00+00:00",
        vocals_path=Path(f"{name}-vocals.wav"),
        instrumental_path=Path(f"{name}-instrumental.wav"),
        converted_vocal_paths=converted_paths,
        active_converted_path=active_converted,
    )


def _take(take_id: str, label: str, path: Path, pitch: int) -> VocalTake:
    return VocalTake(
        take_id,
        label,
        path,
        "2026-08-08T12:34:00+00:00",
        VocalConversionSettings(
            "weights/voice-model.pth",
            "",
            pitch,
            "gpu",
            "cuda:0",
            "rmvpe",
        ),
    )


if __name__ == "__main__":
    unittest.main()
