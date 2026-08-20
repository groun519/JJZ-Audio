from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from jang_app.qt_app.main_window import (
    SEPARATION_MODE_AUDIO,
    SEPARATION_MODE_CLEANUP,
    MainWindow,
)
from jang_app.services.song_library import SongVocalVersion
from jang_app.services.vocal_split import VocalReferenceRegion
from jang_app.services.vocal_split_store import VocalSplitStore


class MainWindowVocalSplitTests(unittest.TestCase):
    def test_unavailable_vocal_mode_request_does_not_navigate(self) -> None:
        navigated: list[int] = []
        window = SimpleNamespace(
            _on_separation_submode_changed=lambda _mode: self.fail(
                "Unavailable vocal separation must not be selected"
            ),
            _navigate_to_page=navigated.append,
        )

        MainWindow._on_primary_page_option_requested(window, 2, "vocal")

        self.assertEqual(navigated, [])

    def test_unfinished_cleanup_mode_request_does_not_navigate(self) -> None:
        navigated: list[int] = []
        window = SimpleNamespace(
            _on_separation_submode_changed=lambda _mode: self.fail(
                "Unfinished vocal cleanup must not be selected"
            ),
            _navigate_to_page=navigated.append,
        )

        MainWindow._on_primary_page_option_requested(
            window,
            2,
            SEPARATION_MODE_CLEANUP,
        )

        self.assertEqual(navigated, [])

    def test_direct_cleanup_mode_request_falls_back_to_audio(self) -> None:
        window = SimpleNamespace(_separation_submode=SEPARATION_MODE_AUDIO)

        MainWindow._on_separation_submode_changed(window, SEPARATION_MODE_CLEANUP)

        self.assertEqual(window._separation_submode, SEPARATION_MODE_AUDIO)

    def test_group_creation_is_immediate_and_selects_the_new_group(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            job_dir = root / "separation"
            job_dir.mkdir()
            source = job_dir / "vocals.wav"
            source.write_bytes(b"source")
            version = _version(job_dir, source)
            refreshed: list[tuple[object, object, str]] = []
            playback_scopes: list[object] = []
            window = SimpleNamespace(
                vocal_split_store=VocalSplitStore(),
                vocal_split_workspace=SimpleNamespace(
                    action=SimpleNamespace(set_status=lambda _text: None)
                ),
                _refresh_vocal_split_runs=lambda selected, preferred_path=None, preferred_group_id="": (
                    refreshed.append((selected, preferred_path, preferred_group_id))
                ),
                _refresh_output_playback_queue=playback_scopes.append,
            )

            MainWindow._create_vocal_split_group(window, version)

            groups = window.vocal_split_store.runs(job_dir)
            self.assertEqual(len(groups), 1)
            self.assertEqual(len(groups[0].stems), 1)
            self.assertEqual(refreshed, [(version, source.resolve(), groups[0].run_id)])
            self.assertEqual(len(playback_scopes), 1)

    def test_unavailable_backend_is_reported_without_starting_a_worker(self) -> None:
        statuses: list[str] = []
        group = SimpleNamespace()
        stem = SimpleNamespace(label="Vocal 1")
        workspace = SimpleNamespace(
            selected_version=lambda: SimpleNamespace(),
            selected_group=lambda: group,
            selected_stem=lambda: stem,
            reference_regions=lambda: (
                VocalReferenceRegion("solo-1", 7_000, 24_000),
            ),
            action=SimpleNamespace(set_status=statuses.append),
        )
        window = SimpleNamespace(
            vocal_split_workspace=workspace,
            current_work_item=SimpleNamespace(id="song-1", title="Song"),
        )

        MainWindow._start_vocal_split(window)

        self.assertEqual(statuses, ["Singer separation model is not connected yet."])


def _version(job_dir: Path, source: Path) -> SongVocalVersion:
    return SongVocalVersion(
        version_id="precision",
        label="Precision",
        job_dir=job_dir,
        added_at="2026-08-19T00:00:00+09:00",
        vocals_path=source,
        instrumental_path=job_dir / "instrumental.wav",
        converted_vocal_paths=(),
        separation_recipe_label="Precision Separation",
    )


if __name__ == "__main__":
    unittest.main()
