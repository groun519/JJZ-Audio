from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from jang_app.services.command import CommandResult
from jang_app.services.rvc_training_spectrogram import (
    RvcTrainingSpectrogramError,
    load_rvc_training_spectrogram_cache,
    prepare_rvc_training_spectrogram_cache,
)
from tests.test_rvc_training_extract import _ready_runtime
from tests.test_rvc_training_train import _training_setup


class RvcTrainingSpectrogramTests(unittest.TestCase):
    def setUp(self) -> None:
        storage = patch(
            "jang_app.services.rvc_training_spectrogram.prepare_rvc_training_storage"
        )
        storage.start()
        self.addCleanup(storage.stop)

    def test_prepares_atomic_cache_and_reuses_valid_result(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            model_id, layout, runtime = _training_setup(Path(temporary))
            progress: list[int] = []

            result = prepare_rvc_training_spectrogram_cache(
                model_id,
                layout,
                runtime,
                progress=progress.append,
                command_runner=_successful_runner,
                runtime_inspector=_ready_runtime,
            )

            self.assertEqual(result.audio_count, 2)
            self.assertEqual(result.created_count, 2)
            self.assertEqual(result.reused_count, 0)
            self.assertEqual(progress[-1], 100)
            self.assertEqual(
                load_rvc_training_spectrogram_cache(model_id, layout).audio_count,
                2,
            )
            worker = layout.root / ".jjzero" / "cache_spectrograms.py"
            self.assertIn(
                "os.replace(temporary, target)",
                worker.read_text(encoding="utf-8"),
            )

    def test_rejects_cache_that_was_damaged_after_preparation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            model_id, layout, runtime = _training_setup(Path(temporary))
            prepare_rvc_training_spectrogram_cache(
                model_id,
                layout,
                runtime,
                command_runner=_successful_runner,
                runtime_inspector=_ready_runtime,
            )
            damaged = next(layout.experiment_dir.glob("0_gt_wavs/*.spec.pt"))
            damaged.write_bytes(b"partial")

            with self.assertRaisesRegex(
                RvcTrainingSpectrogramError,
                "incomplete or stale",
            ):
                load_rvc_training_spectrogram_cache(model_id, layout)


def _successful_runner(args, cwd=None, env=None, output_callback=None, cancellation=None):
    filelist = Path(args[-1])
    audio_paths = {
        Path(line.split("|", 1)[0].replace("\\\\", "\\"))
        for line in filelist.read_text(encoding="utf-8").splitlines()
        if line.strip()
    }
    total = len(audio_paths)
    for current, audio in enumerate(sorted(audio_paths), 1):
        audio.with_suffix(".spec.pt").write_bytes(b"cache" * 1024)
        if output_callback is not None:
            output_callback(f"JJZERO_SPEC_CACHE|{current}|{total}|{current}|0")
    return CommandResult(args, 0, "", "")


if __name__ == "__main__":
    unittest.main()
