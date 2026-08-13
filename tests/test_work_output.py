from __future__ import annotations

import unittest
from pathlib import Path

from jang_app.services.output_catalog import OutputSoundSet
from jang_app.services.song_library import SongItem
from jang_app.services.work_output import WorkOutputSession


def _sound_set(name: str) -> OutputSoundSet:
    root = Path("output") / name
    return OutputSoundSet(
        label=name,
        job_dir=root,
        vocals_path=root / "vocals.wav",
        instrumental_path=root / "no_vocals.wav",
        converted_vocal_paths=(),
    )


def _song(song_id: str, *, kind: str = "source", output_job_dir: Path | None = None) -> SongItem:
    return SongItem(song_id, Path(f"{song_id}.wav"), kind=kind, output_job_dir=output_job_dir)


class WorkOutputSessionTests(unittest.TestCase):
    def test_refresh_catalog_prefers_requested_job_dir(self) -> None:
        standard = _sound_set("standard")
        maximum = _sound_set("maximum")
        session = WorkOutputSession()

        selection = session.refresh_catalog(
            (standard, maximum),
            preferred_job_dir=maximum.job_dir,
        )

        self.assertIs(selection.sound_set, maximum)
        self.assertEqual(selection.selected_index, 1)
        self.assertIs(session.sound_set, maximum)

    def test_refresh_catalog_clears_when_no_fallback_is_allowed(self) -> None:
        session = WorkOutputSession(_sound_set("standard"))

        selection = session.refresh_catalog((), select_fallback=False)

        self.assertIsNone(selection.sound_set)
        self.assertEqual(selection.selected_index, -1)
        self.assertIsNone(session.sound_set)

    def test_refresh_target_keeps_current_output_for_different_song(self) -> None:
        current = _sound_set("current")
        session = WorkOutputSession(current)
        current_item = _song("song-b", output_job_dir=current.job_dir)

        target = session.refresh_target("song-a", Path("output/completed"), current_item)

        self.assertEqual(target.preferred_job_dir, current.job_dir)
        self.assertTrue(target.select_fallback)

    def test_refresh_target_clears_when_different_song_has_no_output_selected(self) -> None:
        session = WorkOutputSession()

        target = session.refresh_target("song-a", Path("output/completed"), _song("song-b"))

        self.assertIsNone(target.preferred_job_dir)
        self.assertFalse(target.select_fallback)

    def test_matches_work_item_compares_selected_output_job(self) -> None:
        selected = _sound_set("precision")
        session = WorkOutputSession(selected)

        self.assertTrue(session.matches_work_item(_song("song", output_job_dir=selected.job_dir)))
        self.assertFalse(session.matches_work_item(_song("song", output_job_dir=Path("output/other"))))

    def test_linked_output_item_is_disabled_while_source_song_is_selected(self) -> None:
        selected = _sound_set("precision")
        session = WorkOutputSession(selected)
        items = {
            "output-song": _song("output-song", kind="output", output_job_dir=selected.job_dir),
        }

        linked = session.linked_output_item(
            items,
            current_source_item=_song("source-song"),
        )

        self.assertIsNone(linked)

    def test_linked_output_item_returns_matching_output_item(self) -> None:
        selected = _sound_set("precision")
        item = _song("output-song", kind="output", output_job_dir=selected.job_dir)
        session = WorkOutputSession(selected)

        linked = session.linked_output_item({"output-song": item})

        self.assertIs(linked, item)

    def test_selected_index_for_job_uses_cached_catalog(self) -> None:
        standard = _sound_set("standard")
        maximum = _sound_set("maximum")
        session = WorkOutputSession(sound_sets=(standard, maximum))

        self.assertEqual(session.selected_index_for_job(maximum.job_dir), 1)
        self.assertEqual(session.selected_index_for_job(Path("output/missing")), -1)

    def test_load_sound_set_reuses_cached_catalog_entry(self) -> None:
        standard = _sound_set("standard")
        session = WorkOutputSession(sound_sets=(standard,))
        loaded: list[Path] = []

        def loader(job_dir: Path, _output_root: Path) -> OutputSoundSet:
            loaded.append(job_dir)
            return _sound_set("reloaded")

        result = session.load_sound_set(
            standard.job_dir,
            Path("output"),
            loader=loader,
        )

        self.assertIs(result, standard)
        self.assertEqual(loaded, [])

    def test_load_sound_set_caches_loader_result(self) -> None:
        session = WorkOutputSession()
        loaded: list[Path] = []
        fresh = _sound_set("fresh")

        def loader(job_dir: Path, _output_root: Path) -> OutputSoundSet:
            loaded.append(job_dir)
            return fresh

        first = session.load_sound_set(fresh.job_dir, Path("output"), loader=loader)
        second = session.load_sound_set(fresh.job_dir, Path("output"), loader=loader)

        self.assertIs(first, fresh)
        self.assertIs(second, fresh)
        self.assertEqual(loaded, [fresh.job_dir])


if __name__ == "__main__":
    unittest.main()
