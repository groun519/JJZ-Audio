from __future__ import annotations

import unittest
from pathlib import Path

from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import QApplication

from jang_app.qt_app.sound_pool_item import SoundPoolItemCard
from jang_app.qt_app.vocal_version_pool import VocalVersionPool
from jang_app.services.song_library import SongVocalVersion


class VocalVersionPoolTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_pool_contains_only_the_requested_stem_role(self) -> None:
        version = _version("precision")
        pool = VocalVersionPool("vocal", title_key="Conversion Input")

        pool.set_versions((version,), version.job_dir)

        card = pool.cards[str(version.job_dir.resolve())]
        self.assertIsInstance(card, SoundPoolItemCard)
        self.assertEqual(card.path, version.vocals_path)
        self.assertEqual(card.role, "original_vocal")
        self.assertEqual(pool.selected_version(), version)
        pool.close()

    def test_clicking_a_card_emits_the_selected_version(self) -> None:
        first, second = _version("fast"), _version("precision")
        pool = VocalVersionPool("vocal")
        pool.set_versions((first, second), first.job_dir)
        selected = QSignalSpy(pool.selection_changed)

        pool.cards[str(second.job_dir.resolve())].activated.emit(
            str(second.job_dir.resolve())
        )

        self.assertEqual(pool.selected_version(), second)
        self.assertIs(selected.at(0)[0], second)
        pool.close()

    def test_refresh_preserves_explicit_input_selection(self) -> None:
        first, second = _version("fast"), _version("precision")
        pool = VocalVersionPool("vocal")
        pool.set_versions((first, second), first.job_dir)
        pool.select_version(second.job_dir)

        pool.set_versions((first, second), first.job_dir)

        self.assertEqual(pool.selected_version(), second)
        pool.close()

    def test_linked_selection_highlight_can_be_released(self) -> None:
        version = _version("precision")
        pool = VocalVersionPool("vocal")
        pool.set_linked_selection(True)
        pool.set_versions((version,), version.job_dir)
        card = next(iter(pool.cards.values()))
        self.assertTrue(card.property("linkedSelection"))

        pool.set_linked_selection(False)

        self.assertFalse(card.property("linkedSelection"))
        self.assertTrue(card.property("selected"))
        pool.close()


def _version(name: str) -> SongVocalVersion:
    root = Path("output") / name
    return SongVocalVersion(
        version_id=name,
        label=name.title(),
        job_dir=root,
        added_at="2026-08-12T10:30:00+09:00",
        vocals_path=root / "vocals.wav",
        instrumental_path=root / "no_vocals.wav",
        converted_vocal_paths=(),
        separation_recipe_label=f"{name.title()} Separation",
        separation_recipe_summary=f"{name} recipe",
    )


if __name__ == "__main__":
    unittest.main()
