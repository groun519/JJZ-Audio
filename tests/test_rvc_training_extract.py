from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import numpy as np

from jang_app.services.command import CommandCancellation, CommandResult
from jang_app.services.model_dataset import ModelDatasetStore
from jang_app.services.rvc_model_package import RvcModelPackageLayout
from jang_app.services.rvc_training_control import RvcTrainingCancelled
from jang_app.services.rvc_training_dataset import RvcTrainingSnapshotStore
from jang_app.services.rvc_training_extract import (
    RvcTrainingExtractError,
    extract_rvc_training_features,
)
from jang_app.services.rvc_training_preprocess import preprocess_rvc_training_dataset
from jang_app.services.rvc_training_runtime import (
    RvcTrainingRuntimeInspection,
    required_rvc_training_paths,
)
from jang_app.services.rvc_training_state import RvcTrainingPhase, RvcTrainingStateStore


class RvcTrainingExtractTests(unittest.TestCase):
    def test_cancellation_is_recorded_as_stopped_instead_of_failed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            model_id, layout, runtime = _extraction_setup(Path(temporary))
            cancellation = CommandCancellation()

            def runner(args, cwd=None, env=None, output_callback=None, cancellation=None):
                cancellation.request_cancel()
                return CommandResult(args, 1, "", "stopped", cancelled=True)

            with self.assertRaises(RvcTrainingCancelled):
                extract_rvc_training_features(
                    model_id,
                    layout,
                    runtime,
                    cancellation=cancellation,
                    cancellable_runner=runner,
                    runtime_inspector=_ready_runtime,
                )

            self.assertEqual(
                RvcTrainingStateStore(model_id, layout).load().phase,
                RvcTrainingPhase.STOPPED,
            )

    def test_extracts_and_publishes_valid_f0_and_hubert_arrays(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            model_id, layout, runtime = _extraction_setup(Path(temporary), input_count=2)
            calls: list[list[str]] = []
            launcher_sources: list[str] = []
            progress: list[int] = []

            def runner(args, cwd=None, env=None, output_callback=None):
                calls.append(args)
                if Path(args[1]).name == "extract_feature_print.py":
                    launcher_sources.append(Path(args[1]).read_text(encoding="utf-8"))
                _write_extraction_outputs(args)
                return CommandResult(args, 0, "", "")

            result = extract_rvc_training_features(
                model_id,
                layout,
                runtime,
                progress=progress.append,
                command_runner=runner,
                runtime_inspector=_ready_runtime,
            )

            self.assertEqual([Path(args[1]).name for args in calls], [
                "extract_f0_rmvpe.py",
                "extract_feature_print.py",
            ])
            self.assertEqual(Path(calls[1][1]).parent.name, ".jjzero-launchers")
            self.assertIn("sys.path.insert(0, str(RVC_ROOT))", launcher_sources[0])
            self.assertIn("extract_feature_print.py", launcher_sources[0])
            self.assertEqual(len(result.f0_files), 2)
            self.assertEqual(len(result.f0_nsf_files), 2)
            self.assertEqual(len(result.feature_files), 2)
            self.assertEqual(progress, [0, 45, 90, 100])
            self.assertEqual(
                RvcTrainingStateStore(model_id, layout).load().phase,
                RvcTrainingPhase.FEATURES_READY,
            )

    def test_nan_feature_is_rejected_without_replacing_previous_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            model_id, layout, runtime = _extraction_setup(Path(temporary))

            def valid_runner(args, cwd=None, env=None, output_callback=None):
                _write_extraction_outputs(args)
                return CommandResult(args, 0, "", "")

            first = extract_rvc_training_features(
                model_id,
                layout,
                runtime,
                command_runner=valid_runner,
                runtime_inspector=_ready_runtime,
            )
            original = first.feature_files[0].read_bytes()

            def invalid_runner(args, cwd=None, env=None, output_callback=None):
                _write_extraction_outputs(args, nan_feature=Path(args[1]).name == "extract_feature_print.py")
                return CommandResult(args, 0, "", "")

            with self.assertRaises(RvcTrainingExtractError):
                extract_rvc_training_features(
                    model_id,
                    layout,
                    runtime,
                    command_runner=invalid_runner,
                    runtime_inspector=_ready_runtime,
                )

            self.assertEqual(first.feature_files[0].read_bytes(), original)
            state = RvcTrainingStateStore(model_id, layout).load()
            self.assertEqual(state.phase, RvcTrainingPhase.FAILED)
            self.assertIn("invalid", state.last_error)

    def test_missing_f0_pair_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            model_id, layout, runtime = _extraction_setup(Path(temporary), input_count=2)

            def runner(args, cwd=None, env=None, output_callback=None):
                _write_extraction_outputs(args, limit=1)
                return CommandResult(args, 0, "", "")

            with self.assertRaises(RvcTrainingExtractError):
                extract_rvc_training_features(
                    model_id,
                    layout,
                    runtime,
                    command_runner=runner,
                    runtime_inspector=_ready_runtime,
                )

            self.assertFalse((layout.experiment_dir / "2a_f0").exists())

    def test_gpu_extraction_recovers_only_missing_outputs_on_cpu(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            model_id, layout, runtime = _extraction_setup(Path(temporary), input_count=2)
            devices: list[str] = []

            def runner(args, cwd=None, env=None, output_callback=None):
                script_name = Path(args[1]).name
                device = args[4] if script_name == "extract_f0_rmvpe.py" else args[2]
                devices.append(device)
                if device.startswith("cuda"):
                    _write_extraction_outputs(args, limit=1)
                else:
                    _write_extraction_outputs(args)
                return CommandResult(args, 0, "", "")

            result = extract_rvc_training_features(
                model_id,
                layout,
                runtime,
                command_runner=runner,
                runtime_inspector=_ready_runtime,
            )

            self.assertEqual(len(result.feature_files), 2)
            self.assertEqual(devices, ["cuda:0", "cuda:0", "cpu", "cpu"])

    def test_incomplete_extraction_reports_missing_stage_and_preserves_log(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            model_id, layout, runtime = _extraction_setup(Path(temporary), input_count=2)

            def runner(args, cwd=None, env=None, output_callback=None):
                _write_extraction_outputs(args, limit=1)
                return CommandResult(args, 0, "", "")

            with self.assertRaises(RvcTrainingExtractError) as raised:
                extract_rvc_training_features(
                    model_id,
                    layout,
                    runtime,
                    command_runner=runner,
                    runtime_inspector=_ready_runtime,
                )

            detail = str(raised.exception)
            self.assertIn("F0=1/2", detail)
            self.assertIn("continuous F0=1/2", detail)
            self.assertIn("HuBERT=1/2", detail)
            self.assertIn("Diagnostic log:", detail)
            self.assertTrue(
                (layout.model_dir / "training" / "diagnostics" / "extract-failed.log").is_file()
            )

    def test_cuda_unavailable_is_rejected_before_state_changes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            model_id, layout, runtime = _extraction_setup(Path(temporary))

            def unavailable(root, check_cuda=False):
                return RvcTrainingRuntimeInspection(Path(root).resolve(), (), False, 0, "")

            with self.assertRaises(RvcTrainingExtractError):
                extract_rvc_training_features(
                    model_id,
                    layout,
                    runtime,
                    runtime_inspector=unavailable,
                )

            self.assertEqual(
                RvcTrainingStateStore(model_id, layout).load().phase,
                RvcTrainingPhase.PREPROCESSED,
            )


def _extraction_setup(
    root: Path,
    *,
    input_count: int = 1,
) -> tuple[str, RvcModelPackageLayout, Path]:
    model_id = "created-voice"
    datasets = ModelDatasetStore(root / "workspace")
    sources = [
        _audio_file(root / "inputs" / f"voice-{index}.wav", f"voice-{index}".encode())
        for index in range(input_count)
    ]
    dataset = datasets.add_sources(model_id, sources)
    datasets.select_items(model_id, [item.item_id for item in dataset.items])
    for item in dataset.items:
        datasets.mark_item_ready(model_id, item.item_id)
    layout = RvcModelPackageLayout(root / "model", "voice")
    layout.create()
    RvcTrainingSnapshotStore(model_id, layout).build(datasets.load(model_id))
    runtime = root / "runtime"
    for relative_path in required_rvc_training_paths():
        path = runtime / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"runtime")

    def preprocess_runner(args, cwd=None, env=None, output_callback=None):
        staging = Path(args[5])
        input_dir = Path(args[2])
        lines: list[str] = []
        for index, source in enumerate(sorted(input_dir.iterdir())):
            for directory in ("0_gt_wavs", "1_16k_wavs"):
                target = staging / directory / f"{index}_0.wav"
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(b"wave")
            line = f"{source}->Suc."
            lines.append(line)
            if output_callback is not None:
                output_callback(line)
        (staging / "preprocess.log").write_text("\n".join(lines), encoding="utf-8")
        return CommandResult(args, 0, "", "")

    preprocess_rvc_training_dataset(
        model_id,
        layout,
        runtime,
        command_runner=preprocess_runner,
    )
    return model_id, layout, runtime


def _write_extraction_outputs(
    args: list[str],
    *,
    nan_feature: bool = False,
    limit: int | None = None,
) -> None:
    script_name = Path(args[1]).name
    staging = Path(args[-2])
    sources = sorted((staging / "1_16k_wavs").glob("*.wav"))[:limit]
    log_path = staging / "extract_f0_feature.log"
    if script_name == "extract_f0_rmvpe.py":
        for source in sources:
            coarse = np.array([1, 64, 128], dtype=np.int64)
            continuous = np.array([0.0, 220.0, 221.0], dtype=np.float32)
            (staging / "2a_f0").mkdir(parents=True, exist_ok=True)
            (staging / "2b-f0nsf").mkdir(parents=True, exist_ok=True)
            np.save(staging / "2a_f0" / source.name, coarse, allow_pickle=False)
            np.save(staging / "2b-f0nsf" / source.name, continuous, allow_pickle=False)
        _append_log(log_path, "f0 done")
        return

    for source in sources:
        feature = np.ones((2, 768), dtype=np.float32)
        if nan_feature:
            feature[0, 0] = np.nan
        (staging / "3_feature768").mkdir(parents=True, exist_ok=True)
        np.save(staging / "3_feature768" / f"{source.stem}.npy", feature, allow_pickle=False)
    _append_log(log_path, "all-feature-done")


def _append_log(path: Path, line: str) -> None:
    with path.open("a", encoding="utf-8") as output:
        output.write(f"{line}\n")


def _ready_runtime(root: Path, check_cuda: bool = False) -> RvcTrainingRuntimeInspection:
    return RvcTrainingRuntimeInspection(Path(root).resolve(), (), True, 1, "")


def _audio_file(path: Path, content: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


if __name__ == "__main__":
    unittest.main()
