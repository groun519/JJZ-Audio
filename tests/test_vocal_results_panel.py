from __future__ import annotations

import unittest
from pathlib import Path

from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import QApplication

from jang_app.qt_app.vocal_results_panel import VocalResultsPanel
from jang_app.qt_app.widgets import TrackRow
from jang_app.services.song_library import SongVocalVersion
from jang_app.services.vocal_project import VocalConversionSettings, VocalTake


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

    def test_converted_selector_is_hidden_until_multiple_versions_exist(self) -> None:
        panel = VocalResultsPanel()
        panel.set_result(_version("single", (Path("single.wav"),)))
        self.assertTrue(panel.converted_waveform.path_combo.isHidden())

        panel.set_result(_version("multiple", (Path("first.wav"), Path("second.wav"))))
        self.assertFalse(panel.converted_waveform.path_combo.isHidden())
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


if __name__ == "__main__":
    unittest.main()
