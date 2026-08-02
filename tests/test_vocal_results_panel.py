from __future__ import annotations

import unittest
from pathlib import Path

from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import QApplication

from jang_app.qt_app.vocal_results_panel import VocalResultsPanel
from jang_app.qt_app.widgets import TrackRow
from jang_app.services.song_library import SongVocalVersion


class VocalResultsPanelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_selects_output_and_converted_versions_without_emitting_during_load(self) -> None:
        panel = VocalResultsPanel()
        first = _version("first", (Path("first-a.wav"),))
        second = _version("second", (Path("second-a.wav"), Path("second-b.wav")), Path("second-b.wav"))
        output_changed = QSignalSpy(panel.output_selected)
        converted_changed = QSignalSpy(panel.converted_selected)

        panel.set_versions((first, second), second.job_dir)

        self.assertEqual(output_changed.count(), 0)
        self.assertEqual(converted_changed.count(), 0)
        self.assertEqual(panel.current_version(), second)
        self.assertEqual(panel.converted_waveform.current_path(), Path("second-b.wav"))

        panel.version_combo.setCurrentIndex(0)
        self.assertEqual(output_changed.count(), 1)
        self.assertEqual(output_changed.at(0)[0], first.job_dir)

        panel.version_combo.setCurrentIndex(1)
        panel.converted_waveform.path_combo.setCurrentIndex(0)
        self.assertEqual(converted_changed.count(), 1)
        self.assertEqual(converted_changed.at(0)[0], Path("second-a.wav"))
        panel.close()

    def test_output_actions_emit_the_selected_job_directory(self) -> None:
        panel = VocalResultsPanel()
        version = _version("selected", ())
        opened = QSignalSpy(panel.open_location_requested)
        removed = QSignalSpy(panel.remove_output_requested)
        panel.set_versions((version,), version.job_dir)

        panel.open_location_button.click()
        panel.remove_output_button.click()

        self.assertEqual(opened.at(0)[0], version.job_dir)
        self.assertEqual(removed.at(0)[0], version.job_dir)
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
