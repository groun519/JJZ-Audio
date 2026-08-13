from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from PySide6.QtWidgets import QApplication

from jang_app.pipeline.quick_production import QuickProductionResult
from jang_app.pipeline.rvc_convert import RvcConversionResult
from jang_app.pipeline.separation_engine import SeparationResult
from jang_app.qt_app.main_window import MainWindow, PAGE_STUDIO
from jang_app.services.output_catalog import OutputSoundSet
from jang_app.services.rvc_inference_settings import (
    PRESET_BALANCED,
    rvc_inference_preset,
)
from jang_app.services.rvc_model_choices import RvcModelChoice
from jang_app.services.separation_recipe import FAST_RECIPE
from jang_app.services.work_scope import WorkTaskScope


class MainWindowQuickCreateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_start_uses_fast_separation_and_balanced_conversion(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "song.wav"
            source.write_bytes(b"audio")
            job_dir = root / "run"
            model_path = root / "voice.pth"
            model_path.write_bytes(b"model")
            work_song = SimpleNamespace(
                id="song-1",
                title="Song",
                kind="source",
                path=source,
            )
            progress: list[int] = []
            run_calls: list[dict[str, object]] = []
            queued: list[object] = []
            panel = _PanelState()
            window = SimpleNamespace(
                current_work_item=work_song,
                quick_create_panel=panel,
                library=SimpleNamespace(
                    create_vocal_separation_run=lambda _song_id: job_dir,
                ),
                _reusable_fast_separation=lambda _song: None,
                _stop_playback=lambda: None,
                _run_worker=lambda worker, *_args, **_kwargs: queued.append(worker),
            )
            choice = RvcModelChoice(
                choice_id="library:voice",
                label="Voice",
                root=root,
                model_path=model_path,
                model_id="voice",
                pitch=-12,
                device="cpu",
            )

            with patch(
                "jang_app.qt_app.main_window.run_quick_production",
                side_effect=lambda **kwargs: run_calls.append(kwargs) or object(),
            ):
                MainWindow._start_quick_creation(window, choice, -9)
                queued[0]._task(progress.append)

            self.assertTrue(panel.running)
            self.assertEqual(panel.progress, 0)
            self.assertEqual(len(run_calls), 1)
            call = run_calls[0]
            self.assertEqual(call["source_path"], source)
            self.assertEqual(call["separation_output_root"], job_dir)
            self.assertIsNone(call["reusable_sound_set"])
            self.assertEqual(call["progress_callback"], progress.append)
            settings = call["rvc_settings"]
            self.assertEqual(settings.pitch, -9)
            self.assertEqual(settings.inference, rvc_inference_preset(PRESET_BALANCED))

    def test_success_registers_new_separation_and_opens_studio(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "song.wav"
            job_dir = root / "run"
            sound_set = OutputSoundSet(
                FAST_RECIPE.label,
                job_dir,
                job_dir / "vocals.wav",
                job_dir / "no_vocals.wav",
                (),
            )
            separation = SeparationResult(
                source,
                job_dir,
                sound_set.vocals_path,
                sound_set.instrumental_path,
                FAST_RECIPE,
            )
            conversion = RvcConversionResult(
                sound_set.vocals_path,
                job_dir / "vocals_rvc.wav",
                root / "voice.pth",
                None,
            )
            result = QuickProductionResult(sound_set, conversion, separation)
            work_song = SimpleNamespace(id="song-1")
            registered: list[tuple[str, Path, str]] = []
            converted: list[tuple[Path, Path]] = []
            navigation: list[int] = []
            panel = _PanelState()
            window = SimpleNamespace(
                current_work_item=work_song,
                quick_create_panel=panel,
                library=SimpleNamespace(
                    register_output=lambda song_id, path, label: (
                        registered.append((song_id, path, label))
                        or SimpleNamespace(id=song_id)
                    )
                ),
                _song_items_by_id={},
                _on_rvc_succeeded=lambda _scope, path, conversion_result, **kwargs: converted.append(
                    (path, kwargs["preferred_job_dir"])
                ),
                _sync_quick_create_panel=lambda: None,
                _navigate_to_page=navigation.append,
                _refresh_song_list=lambda: None,
            )

            MainWindow._on_quick_creation_succeeded(
                window,
                WorkTaskScope(work_song.id),
                result,
            )

            self.assertEqual(
                registered,
                [(work_song.id, job_dir, FAST_RECIPE.label)],
            )
            self.assertEqual(converted, [(job_dir, job_dir)])
            self.assertEqual(panel.progress, 100)
            self.assertEqual(panel.status, "Done")
            self.assertEqual(navigation, [PAGE_STUDIO])


class _PanelState:
    def __init__(self) -> None:
        self.running = False
        self.progress = -1
        self.status = ""
        self.status_label = SimpleNamespace(setToolTip=lambda _text: None)

    def set_running(self, running: bool) -> None:
        self.running = running

    def set_progress(self, progress: int) -> None:
        self.progress = progress

    def set_status(self, status: str) -> None:
        self.status = status


if __name__ == "__main__":
    unittest.main()
