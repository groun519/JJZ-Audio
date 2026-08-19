from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from PySide6.QtWidgets import QApplication

from jang_app.qt_app.main_window import MainWindow
from jang_app.qt_app.conversion_input_pool import ConversionInputPool
from jang_app.qt_app.vocal_version_pool import VocalVersionPool
from jang_app.services.output_catalog import OutputSoundSet
from jang_app.services.song_library import SongVocalVersion
from jang_app.services.vocal_input import VocalInputChoice
from jang_app.services.work_convert import WorkConvertSession


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

    def test_split_vocal_is_used_as_input_without_changing_the_output_job(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            job_dir = root / "separation"
            job_dir.mkdir()
            original = job_dir / "vocals.wav"
            instrumental = job_dir / "no_vocals.wav"
            split = job_dir / "vocal_splits" / "run-1" / "lead.wav"
            split.parent.mkdir(parents=True)
            for path in (original, instrumental, split):
                path.write_bytes(b"audio")
            version = SongVocalVersion(
                version_id="precision",
                label="Precision",
                job_dir=job_dir,
                added_at="2026-08-18T00:00:00+09:00",
                vocals_path=original,
                instrumental_path=instrumental,
                converted_vocal_paths=(),
                separation_recipe_label="Precision Separation",
            )
            choice = VocalInputChoice(
                "split:run-1:lead",
                version,
                split,
                "Lead Vocal",
                kind="lead",
            )
            pool = ConversionInputPool()
            pool.set_choices((choice,), selected_job_dir=job_dir)
            session = WorkConvertSession()
            session.refresh((version,), current_output_job_dir=job_dir)
            sound_set = OutputSoundSet(
                "Precision",
                job_dir,
                original,
                instrumental,
                (),
            )
            window = SimpleNamespace(
                conversion_input_pool=pool,
                work_convert_session=session,
                settings=SimpleNamespace(output_root=root),
            )

            with patch(
                "jang_app.qt_app.main_window.load_output_sound_set",
                return_value=sound_set,
            ):
                selected = MainWindow._conversion_input_sound_set(window)

            self.assertIsNotNone(selected)
            self.assertEqual(selected.vocals_path, split)
            self.assertEqual(selected.job_dir, job_dir)
            pool.close()

    def test_vocal_split_results_are_not_offered_as_conversion_inputs(self) -> None:
        version = _version("precision")
        window = SimpleNamespace()

        choices = MainWindow._conversion_input_choices(window, (version,))

        self.assertEqual(len(choices), 1)
        self.assertEqual(choices[0].kind, "original")
        self.assertEqual(choices[0].path, version.vocals_path)

    def test_preview_refresh_does_not_replace_the_explicit_conversion_input(self) -> None:
        first = _version("standard")
        second = _version("maximum")
        versions = (first, second)
        pool = VocalVersionPool("vocal")
        window = SimpleNamespace(
            conversion_input_pool=pool,
            vocal_project_store=SimpleNamespace(load=lambda _job_dir: None),
            conversion_result_browser=SimpleNamespace(
                select_converted=lambda _path: True,
                set_versions=lambda *_args, **_kwargs: None,
                selected_path=lambda: None,
                version_for_path=lambda _path: None,
                projects=lambda: (),
                converted_paths=lambda: (),
            ),
            _on_conversion_project_load_failed=lambda *_args: None,
            _apply_conversion_result_context=lambda _version, **_kwargs: None,
        )

        MainWindow._refresh_conversion_input_choices(window, versions, first.job_dir)
        pool.select_version(second.job_dir)
        MainWindow._on_conversion_input_version_changed(window, second)
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

    def test_manual_conversion_input_selection_clears_selected_converted_preview(self) -> None:
        first = _version("standard", (Path("output/standard/rvc.wav"),))
        second = _version("maximum")
        cleared: list[Path | None] = []
        previewed: list[tuple[SongVocalVersion | None, Path | None]] = []
        window = SimpleNamespace(
            conversion_result_browser=SimpleNamespace(
                select_converted=lambda path: cleared.append(path) or True,
                projects=lambda: (),
                selected_path=lambda: None,
                converted_paths=lambda: (),
            ),
            _apply_conversion_result_context=lambda version, **kwargs: previewed.append(
                (version, kwargs.get("selected_converted_path"))
            ),
        )
        MainWindow._work_convert_session(window).refresh(
            (first, second),
            current_output_job_dir=first.job_dir,
            preferred_converted_path=first.converted_vocal_paths[0],
        )

        MainWindow._on_conversion_input_version_changed(window, second)

        self.assertEqual(cleared, [None])
        self.assertIs(
            MainWindow._work_convert_session(window).input_version(),
            second,
        )
        self.assertEqual(
            previewed,
            [(second, None)],
        )

    def test_rename_vocal_take_uses_selected_take_owner_job_dir(self) -> None:
        current_output = _version("standard")
        owner = _version("maximum", (Path("output/maximum/rvc.wav"),))
        selected_take = SimpleNamespace(
            output_path=owner.converted_vocal_paths[0],
            label="Old label",
        )
        renamed: list[tuple[Path, Path, str] | tuple[str]] = []
        window = SimpleNamespace(
            current_output_set=SimpleNamespace(job_dir=current_output.job_dir),
            vocal_results_panel=SimpleNamespace(current_take=lambda: selected_take),
            settings=SimpleNamespace(theme_mode="dark"),
            vocal_project_store=SimpleNamespace(
                rename_take=lambda job_dir, path, label: renamed.append(
                    (job_dir, path, label)
                )
            ),
            _refresh_vocal_project_panel=lambda: renamed.append(("refreshed",)),
            rvc_action=SimpleNamespace(set_status=lambda _message: None),
            work_convert_session=WorkConvertSession(),
        )
        window.work_convert_session.refresh(
            (current_output, owner),
            current_output_job_dir=current_output.job_dir,
        )

        with patch(
            "jang_app.qt_app.main_window.TextInputDialog.get_text",
            return_value=("New label", True),
        ):
            MainWindow._rename_vocal_take(window, owner.converted_vocal_paths[0])

        self.assertEqual(
            renamed,
            [
                (owner.job_dir, owner.converted_vocal_paths[0], "New label"),
                ("refreshed",),
            ],
        )

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
