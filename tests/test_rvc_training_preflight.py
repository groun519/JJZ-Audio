from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from jang_app.services.clip_edit_history import REVIEW_READY
from jang_app.services.model_dataset import ModelDataset, ModelDatasetItem
from jang_app.services.rvc_hardware import RvcComputeBackend
from jang_app.services.rvc_training_preflight import (
    RvcTrainingCheckLevel,
    inspect_rvc_training_preflight,
)
from jang_app.services.rvc_training_runtime import required_rvc_training_paths


class RvcTrainingPreflightTests(unittest.TestCase):
    def test_ready_dataset_can_start_with_a_cached_clean_analysis(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            runtime = root / "runtime-root"
            workspace = root / "workspace"
            workspace.mkdir()
            _create_runtime(runtime)
            dataset = _dataset(root, ready=True)
            analysis = SimpleNamespace(
                selected_item_count=1,
                ready_item_count=1,
                attention_count=0,
            )

            result = inspect_rvc_training_preflight(
                managed_model=True,
                dataset=dataset,
                analysis=analysis,
                runtime_root=runtime,
                workspace_root=workspace,
                training_backend=RvcComputeBackend.CUDA,
                adapter_name="NVIDIA GeForce GTX 1650",
                adapter_memory_bytes=4 * 1024**3,
                disk_usage=lambda _path: SimpleNamespace(free=20 * 1024**3),
            )

            self.assertTrue(result.can_start)
            self.assertFalse(result.warnings)
            self.assertEqual(_check(result, "device").level, RvcTrainingCheckLevel.READY)

    def test_missing_analysis_and_cpu_training_are_warnings_only(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            runtime = root / "runtime-root"
            workspace = root / "workspace"
            workspace.mkdir()
            _create_runtime(runtime)

            result = inspect_rvc_training_preflight(
                managed_model=True,
                dataset=_dataset(root, ready=True),
                analysis=None,
                runtime_root=runtime,
                workspace_root=workspace,
                training_backend=RvcComputeBackend.CPU,
                disk_usage=lambda _path: SimpleNamespace(free=20 * 1024**3),
            )

            self.assertTrue(result.can_start)
            self.assertEqual(
                {check.key for check in result.warnings},
                {"analysis", "device"},
            )

    def test_missing_runtime_and_storage_are_blockers(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = root / "workspace"
            workspace.mkdir()

            result = inspect_rvc_training_preflight(
                managed_model=True,
                dataset=_dataset(root, ready=True),
                analysis=None,
                runtime_root=root / "missing-runtime",
                workspace_root=workspace,
                training_backend=RvcComputeBackend.CPU,
                disk_usage=lambda _path: SimpleNamespace(free=1024),
            )

            self.assertFalse(result.can_start)
            self.assertEqual(
                {check.key for check in result.blockers},
                {"runtime", "storage"},
            )

    def test_unreviewed_or_missing_audio_blocks_training(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            runtime = root / "runtime-root"
            workspace = root / "workspace"
            workspace.mkdir()
            _create_runtime(runtime)
            dataset = _dataset(root, ready=False)
            dataset.training_items[0].working_path.unlink()

            result = inspect_rvc_training_preflight(
                managed_model=True,
                dataset=dataset,
                analysis=None,
                runtime_root=runtime,
                workspace_root=workspace,
                training_backend=RvcComputeBackend.CPU,
                disk_usage=lambda _path: SimpleNamespace(free=20 * 1024**3),
            )

            self.assertFalse(result.can_start)
            self.assertEqual(
                _check(result, "materials").level,
                RvcTrainingCheckLevel.BLOCKER,
            )


def _dataset(root: Path, *, ready: bool) -> ModelDataset:
    audio = root / "voice.wav"
    audio.write_bytes(b"audio" * 1024)
    item = ModelDatasetItem(
        item_id="voice",
        source_name="voice.wav",
        source_path=audio,
        original_path=audio,
        working_path=audio,
        added_at="2026-01-01T00:00:00+00:00",
        duration_ms=60_000,
        selected_order=1,
        review_state=REVIEW_READY if ready else "unreviewed",
    )
    return ModelDataset("voice", (item,))


def _create_runtime(root: Path) -> None:
    for relative_path in required_rvc_training_paths():
        path = root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"runtime")


def _check(result, key: str):
    return next(check for check in result.checks if check.key == key)


if __name__ == "__main__":
    unittest.main()
