from __future__ import annotations

import unittest
from pathlib import Path

from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import QApplication

from jang_app.qt_app.conversion_input_pool import ConversionInputPool
from jang_app.services.song_library import SongVocalVersion
from jang_app.services.vocal_input import original_vocal_choice, split_vocal_choice
from jang_app.services.vocal_split import VocalSplitRun, VocalSplitStem


class ConversionInputPoolTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_original_and_split_vocals_are_independent_choices(self) -> None:
        version = _version()
        stem = VocalSplitStem("lead", "lead", "Lead Vocal", Path("lead.wav"))
        run = VocalSplitRun(
            "run-1",
            version.job_dir,
            version.vocals_path,
            "lead-backing-v1",
            "Lead / Backing",
            "model.pth",
            "2026-08-18T00:00:00+00:00",
            (stem,),
        )
        original = original_vocal_choice(version)
        lead = split_vocal_choice(version, run, stem)
        pool = ConversionInputPool()
        changed = QSignalSpy(pool.choice_changed)

        pool.set_choices((original, lead), selected_job_dir=version.job_dir)
        pool.cards[lead.choice_id].activated.emit(lead.choice_id)

        self.assertEqual(pool.selected_path(), stem.path)
        self.assertEqual(pool.selected_version(), version)
        self.assertEqual(changed.count(), 1)
        pool.close()


def _version() -> SongVocalVersion:
    return SongVocalVersion(
        version_id="output-1",
        label="Precision",
        job_dir=Path("run-1"),
        added_at="2026-08-18T00:00:00+00:00",
        vocals_path=Path("vocals.wav"),
        instrumental_path=Path("no_vocals.wav"),
        converted_vocal_paths=(),
        separation_recipe_label="Precision Separation",
    )


if __name__ == "__main__":
    unittest.main()
