from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from jang_app.services.command import CommandResult
from jang_app.services.rvc_training_extract import extract_rvc_training_features
from jang_app.services.rvc_training_filelist import (
    RvcTrainingFilelistError,
    build_rvc_training_filelist,
    load_rvc_training_filelist,
)
from jang_app.services.rvc_training_state import RvcTrainingPhase, RvcTrainingStateStore
from tests.test_rvc_training_extract import (
    _extraction_setup,
    _ready_runtime,
    _write_extraction_outputs,
)


class RvcTrainingFilelistTests(unittest.TestCase):
    def test_builds_deterministic_portable_v2_filelist(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            model_id, layout, runtime = _ready_extraction(Path(temporary), input_count=2)

            result = build_rvc_training_filelist(model_id, layout, runtime)
            first_content = result.path.read_bytes()
            lines = result.path.read_text(encoding="utf-8").splitlines()

            self.assertEqual(result.real_entry_count, 2)
            self.assertEqual(result.mute_entry_count, 2)
            self.assertEqual(result.entry_count, 4)
            self.assertEqual(lines[-1], lines[-2])
            self.assertEqual([_entry_paths(line)[0].stem for line in lines[:2]], ["0_0", "1_0"])
            for line in lines:
                fields = line.split("|")
                self.assertEqual(len(fields), 5)
                self.assertEqual(fields[-1], "0")
                self.assertTrue(all(path.is_file() for path in _entry_paths(line)))
            self.assertTrue(
                (layout.root / "logs" / "mute" / "0_gt_wavs" / "mute40k.spec.pt").is_file()
            )
            self.assertEqual(
                RvcTrainingStateStore(model_id, layout).load().phase,
                RvcTrainingPhase.FILELIST_READY,
            )

            rebuilt = build_rvc_training_filelist(model_id, layout, runtime)
            self.assertEqual(rebuilt.path.read_bytes(), first_content)

    def test_modified_filelist_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            model_id, layout, runtime = _ready_extraction(Path(temporary))
            result = build_rvc_training_filelist(model_id, layout, runtime)
            result.path.write_text("modified\n", encoding="utf-8")

            with self.assertRaises(RvcTrainingFilelistError):
                load_rvc_training_filelist(model_id, layout)

    def test_missing_runtime_asset_preserves_existing_filelist_and_state(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            model_id, layout, runtime = _ready_extraction(Path(temporary))
            result = build_rvc_training_filelist(model_id, layout, runtime)
            original = result.path.read_bytes()
            (runtime / "logs" / "mute" / "3_feature768" / "mute.npy").unlink()

            with self.assertRaises(RvcTrainingFilelistError):
                build_rvc_training_filelist(model_id, layout, runtime)

            self.assertEqual(result.path.read_bytes(), original)
            self.assertEqual(
                RvcTrainingStateStore(model_id, layout).load().phase,
                RvcTrainingPhase.FILELIST_READY,
            )

    def test_reextracting_features_invalidates_previous_filelist(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            model_id, layout, runtime = _ready_extraction(Path(temporary))
            result = build_rvc_training_filelist(model_id, layout, runtime)
            manifest = layout.experiment_dir / "jjzero_filelist.json"

            def runner(args, cwd=None, env=None, output_callback=None):
                _write_extraction_outputs(args)
                return CommandResult(args, 0, "", "")

            extract_rvc_training_features(
                model_id,
                layout,
                runtime,
                command_runner=runner,
                runtime_inspector=_ready_runtime,
            )

            self.assertFalse(result.path.exists())
            self.assertFalse(manifest.exists())


def _ready_extraction(root: Path, *, input_count: int = 1):
    model_id, layout, runtime = _extraction_setup(root, input_count=input_count)

    def runner(args, cwd=None, env=None, output_callback=None):
        _write_extraction_outputs(args)
        return CommandResult(args, 0, "", "")

    extract_rvc_training_features(
        model_id,
        layout,
        runtime,
        command_runner=runner,
        runtime_inspector=_ready_runtime,
    )
    return model_id, layout, runtime


def _entry_paths(line: str) -> tuple[Path, ...]:
    fields = line.split("|")
    return tuple(Path(value.replace("\\\\", "\\")) for value in fields[:4])


if __name__ == "__main__":
    unittest.main()
