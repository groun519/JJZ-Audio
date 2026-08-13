from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from jang_app.services.song_library import SongVocalVersion
from jang_app.services.work_convert import WorkConvertSession


def _version(
    name: str,
    converted: tuple[Path, ...] = (),
    *,
    active: Path | None = None,
) -> SongVocalVersion:
    root = Path("output") / name
    return SongVocalVersion(
        version_id=name,
        label=name.title(),
        job_dir=root,
        added_at="2026-08-13T10:00:00+09:00",
        vocals_path=root / "vocals.wav",
        instrumental_path=root / "no_vocals.wav",
        converted_vocal_paths=converted,
        active_converted_path=active,
        separation_recipe_label=name.title(),
        separation_recipe_summary=f"{name} recipe",
    )


class WorkConvertSessionTests(unittest.TestCase):
    def test_refresh_defaults_input_to_current_output_job(self) -> None:
        standard = _version("standard")
        maximum = _version("maximum")
        session = WorkConvertSession()

        context = session.refresh(
            (standard, maximum),
            current_output_job_dir=maximum.job_dir,
        )

        self.assertIs(context.input_version, maximum)
        self.assertIs(context.result_version, maximum)

    def test_refresh_preserves_explicit_input_selection(self) -> None:
        standard = _version("standard")
        maximum = _version("maximum")
        session = WorkConvertSession()
        session.refresh((standard, maximum), current_output_job_dir=standard.job_dir)
        session.select_input_job_dir(maximum.job_dir)

        context = session.refresh(
            (standard, maximum),
            current_output_job_dir=standard.job_dir,
        )

        self.assertIs(context.input_version, maximum)

    def test_refresh_defaults_to_active_converted_take(self) -> None:
        converted = (Path("output/maximum/rvc.wav"),)
        version = _version("maximum", converted, active=converted[0])
        session = WorkConvertSession()

        context = session.refresh((version,), current_output_job_dir=version.job_dir)

        self.assertEqual(
            context.selected_converted_path,
            converted[0],
        )
        self.assertIs(context.result_version, version)

    def test_select_input_can_clear_selected_converted_path(self) -> None:
        converted = (Path("output/maximum/rvc.wav"),)
        version = _version("maximum", converted, active=converted[0])
        session = WorkConvertSession()
        session.refresh((version,), current_output_job_dir=version.job_dir)
        session.select_converted_path(converted[0])

        context = session.select_input_job_dir(
            version.job_dir,
            clear_selected_converted=True,
        )

        self.assertIsNone(context.selected_converted_path)
        self.assertIs(context.result_version, version)

    def test_job_dir_for_converted_path_prefers_owner_over_fallback(self) -> None:
        standard = _version("standard")
        converted = Path("output/maximum/rvc.wav")
        maximum = _version("maximum", (converted,))
        session = WorkConvertSession()
        session.refresh(
            (standard, maximum),
            current_output_job_dir=standard.job_dir,
        )

        self.assertEqual(
            session.job_dir_for_converted_path(
                converted,
                fallback_job_dir=standard.job_dir,
            ),
            maximum.job_dir,
        )

    def test_input_sound_set_loads_selected_input_version(self) -> None:
        version = _version("maximum")
        session = WorkConvertSession()
        session.refresh((version,), current_output_job_dir=version.job_dir)

        with patch(
            "jang_app.services.work_convert.load_output_sound_set",
            return_value=object(),
        ) as loader:
            result = session.input_sound_set(Path("output"))

        self.assertIsNotNone(result)
        loader.assert_called_once_with(version.job_dir, Path("output"))

    def test_projects_cache_loaded_results_for_repeated_refresh(self) -> None:
        version = _version("maximum", (Path("output/maximum/rvc.wav"),))
        session = WorkConvertSession()
        session.refresh((version,), current_output_job_dir=version.job_dir)
        loaded: list[Path] = []
        project = object()

        def loader(job_dir: Path) -> object:
            loaded.append(job_dir)
            return project

        first = session.projects(loader)
        second = session.projects(loader)

        self.assertEqual(first, {version.job_dir: project})
        self.assertEqual(second, {version.job_dir: project})
        self.assertEqual(loaded, [version.job_dir])


if __name__ == "__main__":
    unittest.main()
