from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from jang_app.services.rvc_model_package import RvcModelPackageLayout
from jang_app.services.rvc_training_storage import (
    RvcTrainingStorageError,
    inspect_rvc_training_storage,
    prepare_rvc_training_storage,
)


class RvcTrainingStorageTests(unittest.TestCase):
    def test_removes_incomplete_spectrogram_cache(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            layout = _layout(Path(temporary))
            corrupt = _audio(layout, "broken", 1024).with_suffix(".spec.pt")
            corrupt.write_bytes(b"partial")
            valid = _audio(layout, "ready", 1024).with_suffix(".spec.pt")
            valid.write_bytes(b"cache" * 1024)

            inspection = prepare_rvc_training_storage(
                layout,
                disk_usage=lambda _path: SimpleNamespace(free=20 * 1024**3),
            )

            self.assertEqual(inspection.corrupt_spectrograms, (corrupt,))
            self.assertFalse(corrupt.exists())
            self.assertTrue(valid.is_file())

    def test_reports_required_space_before_training(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            layout = _layout(Path(temporary))
            _audio(layout, "voice", 1024)

            inspection = inspect_rvc_training_storage(
                layout,
                disk_usage=lambda _path: SimpleNamespace(free=0),
            )

            self.assertFalse(inspection.ready)
            with self.assertRaisesRegex(RvcTrainingStorageError, "Required:.*available:"):
                prepare_rvc_training_storage(
                    layout,
                    disk_usage=lambda _path: SimpleNamespace(free=0),
                )

    def test_reserves_space_for_runtime_memory_pressure(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            layout = _layout(Path(temporary))
            _audio(layout, "voice", 1024)

            inspection = inspect_rvc_training_storage(
                layout,
                disk_usage=lambda _path: SimpleNamespace(free=8 * 1024**3),
            )

            self.assertFalse(inspection.ready)


def _layout(root: Path) -> RvcModelPackageLayout:
    layout = RvcModelPackageLayout(root / "model", "voice")
    layout.create()
    return layout


def _audio(layout: RvcModelPackageLayout, name: str, size: int) -> Path:
    path = layout.experiment_dir / "0_gt_wavs" / f"{name}.wav"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"a" * size)
    return path


if __name__ == "__main__":
    unittest.main()
