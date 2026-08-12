from __future__ import annotations

import unittest
from pathlib import Path

from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import QApplication

from jang_app.qt_app.conversion_result_browser import ConversionResultBrowser
from jang_app.qt_app.sound_pool_item import SoundPoolItemCard
from jang_app.services.song_library import SongVocalVersion
from jang_app.services.vocal_project import (
    UNASSIGNED_SPEAKER_ID,
    VOCAL_PROJECT_SCHEMA_VERSION,
    VocalProject,
    VocalSegment,
    VocalSpeaker,
    VocalTake,
)


class ConversionResultBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_pool_contains_rvc_takes_from_every_separation_result(self) -> None:
        first = Path("first.wav")
        second = Path("second.wav")
        maximum = _version("maximum", (first,), first)
        precision = _version("precision", (second,), second)
        panel = ConversionResultBrowser()

        panel.set_versions(
            (maximum, precision),
            projects={
                maximum.job_dir: _project((
                    VocalTake("take-1", "Bright", first, "2026-08-09T12:30:00+09:00"),
                )),
                precision.job_dir: _project((
                    VocalTake("take-2", "Warm", second, "2026-08-09T12:35:00+09:00"),
                )),
            },
        )

        self.assertEqual(set(panel.cards), {first.resolve(), second.resolve()})
        self.assertTrue(all(isinstance(card, SoundPoolItemCard) for card in panel.cards.values()))
        self.assertFalse(hasattr(panel, "separation_layout"))
        self.assertIs(panel.version_for_path(first), maximum)
        self.assertIs(panel.version_for_path(second), precision)
        self.assertEqual(panel.selected_path(), first.resolve())
        panel.close()

    def test_rvc_card_selects_the_converted_vocal(self) -> None:
        first = Path("first.wav")
        second = Path("second.wav")
        panel = ConversionResultBrowser()
        selected = QSignalSpy(panel.converted_selected)
        panel.set_result(_version("maximum", (first, second), second))

        panel.cards[first.resolve()].activated.emit(str(first.resolve()))

        self.assertEqual(panel.selected_path(), first.resolve())
        self.assertTrue(panel.cards[first.resolve()].property("selected"))
        self.assertFalse(panel.cards[second.resolve()].property("selected"))
        self.assertEqual(selected.at(0)[0], first.resolve())
        panel.close()

    def test_empty_result_shows_no_rvc_cards(self) -> None:
        panel = ConversionResultBrowser()

        panel.set_result(None)

        self.assertIsNone(panel.selected_path())
        self.assertEqual(panel.cards, {})
        self.assertFalse(panel.empty_label.isHidden())
        self.assertEqual(panel.count_label.text(), "0")
        panel.close()

    def test_pool_header_uses_section_title_style(self) -> None:
        panel = ConversionResultBrowser()

        self.assertEqual(panel.title_label.objectName(), "ConversionPoolTitle")
        self.assertFalse(hasattr(panel, "auto_monitor_button"))
        panel.close()


def _version(
    name: str,
    converted: tuple[Path, ...] = (),
    active: Path | None = None,
) -> SongVocalVersion:
    root = Path("output") / name
    return SongVocalVersion(
        version_id=name,
        label=name,
        job_dir=root,
        added_at="2026-08-09T12:34:00+09:00",
        vocals_path=root / "vocals.wav",
        instrumental_path=root / "no_vocals.wav",
        converted_vocal_paths=converted,
        active_converted_path=active,
        separation_recipe_label=name.title(),
    )


def _project(takes: tuple[VocalTake, ...]) -> VocalProject:
    return VocalProject(
        schema_version=VOCAL_PROJECT_SCHEMA_VERSION,
        project_id="conversion-browser",
        created_at="2026-08-09T12:00:00+09:00",
        updated_at="2026-08-09T12:40:00+09:00",
        duration_ms=12_000,
        vocals_path=Path("vocals.wav"),
        instrumental_path=Path("no_vocals.wav"),
        speakers=(VocalSpeaker(UNASSIGNED_SPEAKER_ID, "Unassigned", "#898780"),),
        segments=(VocalSegment("segment-1", 0, 12_000, UNASSIGNED_SPEAKER_ID),),
        takes=takes,
        active_take_id=takes[-1].take_id if takes else None,
    )


if __name__ == "__main__":
    unittest.main()
