from __future__ import annotations

import unittest
from pathlib import Path

from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import QApplication

from jang_app.qt_app.separation_stem_pool import SeparationStemPoolPanel
from jang_app.qt_app.sound_pool_item import SoundPoolItemCard
from jang_app.services.song_library import SongVocalVersion


class SeparationStemPoolPanelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_paired_mode_selects_both_stems_from_one_result(self) -> None:
        panel = SeparationStemPoolPanel()
        first, second = _version("fast"), _version("precision")
        panel.set_versions((first, second), first.job_dir)
        changed = QSignalSpy(panel.selection_changed)

        panel.vocal_pool.cards[str(second.job_dir.resolve())].activated.emit(
            str(second.job_dir.resolve())
        )

        self.assertEqual(panel.selected_versions(), (second, second))
        self.assertEqual(changed.count(), 1)
        panel.close()

    def test_unpaired_mode_allows_independent_stem_selection(self) -> None:
        panel = SeparationStemPoolPanel()
        first, second = _version("fast"), _version("precision")
        panel.set_versions((first, second), first.job_dir)
        panel.set_paired(False)

        panel.instrumental_pool.cards[str(second.job_dir.resolve())].activated.emit(
            str(second.job_dir.resolve())
        )

        self.assertEqual(panel.selected_versions(), (first, second))
        self.assertFalse(panel.is_paired())
        panel.close()

    def test_cards_reuse_shared_sound_pool_item(self) -> None:
        panel = SeparationStemPoolPanel()
        version = _version("fast")
        panel.set_versions((version,), version.job_dir)

        card = next(iter(panel.vocal_pool.cards.values()))
        self.assertIsInstance(card, SoundPoolItemCard)
        self.assertEqual(card.path, version.vocals_path)
        panel.close()

    def test_pool_can_expand_when_the_result_panel_is_compressed(self) -> None:
        panel = SeparationStemPoolPanel()

        self.assertGreater(panel.maximumWidth(), 1_000)
        self.assertEqual(panel.minimumWidth(), 260)
        panel.close()

    def test_pair_mode_uses_link_icon_and_yellow_selection_surface(self) -> None:
        panel = SeparationStemPoolPanel()
        version = _version("fast")
        panel.set_versions((version,), version.job_dir)

        self.assertEqual(panel.pair_button.icon_name(), "link")
        self.assertTrue(panel.pair_status_label.property("paired"))
        palette = panel.pair_button._button_palette()
        self.assertEqual(palette["icon"].name(), "#8a6200")
        linked_card = next(iter(panel.vocal_pool.cards.values()))
        self.assertTrue(linked_card.property("linkedSelection"))

        panel.set_paired(False)
        self.assertFalse(panel.pair_status_label.property("paired"))
        self.assertFalse(linked_card.property("linkedSelection"))
        self.assertTrue(linked_card.property("selected"))
        self.assertEqual(
            panel.pair_button._button_palette()["icon"].name(),
            "#6e6a61",
        )

        panel.set_theme_mode("dark")
        stylesheet = panel.styleSheet()
        self.assertIn(
            'QFrame#VocalVersionCard[selected="true"][linkedSelection="true"]',
            stylesheet,
        )
        self.assertIn("background: #302817", stylesheet)
        panel.close()


def _version(name: str) -> SongVocalVersion:
    return SongVocalVersion(
        version_id=f"output-{name}",
        label=name.title(),
        job_dir=Path(name),
        added_at="2026-08-12T10:30:00+09:00",
        vocals_path=Path(f"{name}-vocals.wav"),
        instrumental_path=Path(f"{name}-instrumental.wav"),
        converted_vocal_paths=(),
        separation_recipe_label=f"{name.title()} Separation",
    )


if __name__ == "__main__":
    unittest.main()
