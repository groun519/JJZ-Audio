from __future__ import annotations

import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from PySide6.QtWidgets import QApplication

from jang_app.qt_app.main_window import MainWindow
from jang_app.qt_app.vocal_version_pool import VocalVersionPool
from jang_app.services.song_library import SongVocalVersion


class MainWindowConversionSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_conversion_input_comes_from_the_explicit_input_selector(self) -> None:
        selected_job = Path("output/maximum")
        expected = SimpleNamespace(job_dir=selected_job)
        pool = VocalVersionPool("vocal")
        pool.set_versions((_version("maximum"),), selected_job)
        window = SimpleNamespace(
            conversion_input_pool=pool,
            settings=SimpleNamespace(output_root=Path("output")),
        )

        with patch(
            "jang_app.qt_app.main_window.load_output_sound_set",
            return_value=expected,
        ) as loader:
            result = MainWindow._conversion_input_sound_set(window)

        self.assertIs(result, expected)
        loader.assert_called_once_with(selected_job, Path("output"))
        pool.close()

    def test_preview_refresh_does_not_replace_the_explicit_conversion_input(self) -> None:
        first = _version("standard")
        second = _version("maximum")
        versions = (first, second)
        pool = VocalVersionPool("vocal")
        window = SimpleNamespace(
            conversion_input_pool=pool,
            conversion_result_browser=SimpleNamespace(
                set_versions=lambda *_args, **_kwargs: None,
                selected_path=lambda: None,
                version_for_path=lambda _path: None,
            ),
            _conversion_projects=lambda _versions: {},
            _apply_conversion_result_context=lambda _version, **_kwargs: None,
        )

        MainWindow._refresh_conversion_input_choices(window, versions, first.job_dir)
        pool.select_version(second.job_dir)
        MainWindow._refresh_conversion_input_choices(window, versions, first.job_dir)

        self.assertIs(pool.selected_version(), second)
        pool.close()

    def test_clicking_a_vocal_pool_card_changes_only_the_input_selection(self) -> None:
        first = _version("standard")
        second = _version("maximum")
        pool = VocalVersionPool("vocal")
        pool.set_versions((first, second), first.job_dir)

        pool.cards[str(second.job_dir.resolve())].activated.emit(
            str(second.job_dir.resolve())
        )

        self.assertIs(pool.selected_version(), second)
        pool.close()

    def test_rvc_selection_changes_the_result_preview_to_its_source_version(self) -> None:
        source = _version("precision", (Path("converted.wav"),))
        selected_path = source.converted_vocal_paths[0]
        previewed: list[tuple[SongVocalVersion | None, Path | None]] = []
        window = SimpleNamespace(
            conversion_result_browser=SimpleNamespace(
                version_for_path=lambda path: source if path == selected_path else None,
                select_converted=lambda _path: True,
            ),
            current_output_set=None,
            current_work_item=SimpleNamespace(id="song-1"),
            vocal_project_store=SimpleNamespace(set_active_take=lambda *_args: None),
            library=SimpleNamespace(activate_converted_output=lambda *_args: None),
            _song_items_by_id={},
            converted_track=SimpleNamespace(select_path=lambda _path: True),
            _apply_conversion_result_context=lambda version, **kwargs: previewed.append(
                (version, kwargs.get("selected_converted_path"))
            ),
            _refresh_output_playback_queue=lambda _scope: None,
            _logger=SimpleNamespace(warning=lambda *_args: None),
        )

        MainWindow._activate_vocal_converted_version(window, selected_path)

        self.assertEqual(previewed, [(source, selected_path)])

    def test_successful_conversion_selects_the_new_take(self) -> None:
        converted_job = Path("output/maximum")
        previous_preview = Path("output/standard")
        refreshed: list[tuple[Path | None, bool]] = []
        selected: list[Path] = []
        window = SimpleNamespace(
            vocal_project_store=SimpleNamespace(),
            current_output_set=SimpleNamespace(job_dir=previous_preview),
            current_work_item=SimpleNamespace(id="song-1"),
            _refresh_output_sets=lambda preferred_job_dir=None, select_fallback=True: refreshed.append(
                (preferred_job_dir, select_fallback)
            ),
            _activate_vocal_converted_version=selected.append,
            rvc_action=SimpleNamespace(set_progress=lambda _value: None, set_status=lambda _value: None),
            _logger=SimpleNamespace(warning=lambda *_args: None),
        )
        scope = SimpleNamespace(is_current=lambda item: item is window.current_work_item)
        result = SimpleNamespace(output_path=converted_job / "vocals_rvc_new.wav")

        MainWindow._on_rvc_succeeded(window, scope, converted_job, result)

        self.assertEqual(refreshed, [(previous_preview, True)])
        self.assertEqual(selected, [result.output_path])

    def test_finished_conversion_for_an_inactive_song_does_not_replace_playback(self) -> None:
        converted_job = Path("output/maximum")
        selected: list[Path] = []
        window = SimpleNamespace(
            vocal_project_store=SimpleNamespace(),
            current_output_set=SimpleNamespace(job_dir=Path("output/standard")),
            current_work_item=SimpleNamespace(id="song-1"),
            _refresh_output_sets=lambda **_kwargs: None,
            _activate_vocal_converted_version=selected.append,
            rvc_action=SimpleNamespace(set_progress=lambda _value: None, set_status=lambda _value: None),
            _logger=SimpleNamespace(warning=lambda *_args: None),
        )
        scope = SimpleNamespace(is_current=lambda _item: False)

        MainWindow._on_rvc_succeeded(
            window,
            scope,
            converted_job,
            SimpleNamespace(output_path=converted_job / "vocals_rvc_new.wav"),
        )

        self.assertEqual(selected, [])


def _version(name: str, converted: tuple[Path, ...] = ()) -> SongVocalVersion:
    root = Path("output") / name
    return SongVocalVersion(
        version_id=name,
        label=name.title(),
        job_dir=root,
        added_at="2026-08-09T12:34:00+09:00",
        vocals_path=root / "vocals.wav",
        instrumental_path=root / "no_vocals.wav",
        converted_vocal_paths=converted,
        separation_recipe_label=name.title(),
        separation_recipe_summary=f"{name} recipe",
    )


if __name__ == "__main__":
    unittest.main()
