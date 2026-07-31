from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from jang_app.services.rvc_model_workspace import RvcModelWorkspace, discover_rvc_models


class RvcModelWorkspaceTests(unittest.TestCase):
    def test_discovers_one_model_per_experiment(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = _build_rvc_root(Path(temporary))
            models = discover_rvc_models(root)

            self.assertEqual([model.name for model in models], ["standalone", "voice-a"])
            voice = next(model for model in models if model.name == "voice-a")
            self.assertEqual(voice.inference_model.name, "voice-a.pth")
            self.assertEqual(voice.generator_checkpoint.name, "G_100.pth")
            self.assertEqual(voice.discriminator_checkpoint.name, "D_100.pth")
            self.assertEqual(voice.index_file.name, "added_voice-a.index")

    def test_linked_catalog_preserves_resume_state(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            source = _build_rvc_root(base / "source")
            workspace = RvcModelWorkspace(base / "workspace")

            workspace.link_folder(source / "logs" / "voice-a")
            records = workspace.records()

            self.assertEqual(len(records), 1)
            self.assertEqual(records[0].status_label, "Resume Ready")
            self.assertFalse(records[0].is_managed)

    def test_import_creates_baseline_without_changing_source(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            source = _build_rvc_root(base / "source")
            source_files = [path for path in source.rglob("*") if path.is_file()]
            original_bytes = {path: path.read_bytes() for path in source_files}
            workspace = RvcModelWorkspace(base / "workspace")

            record = workspace.import_folder(source / "logs" / "voice-a")[0]
            model_dir = base / "workspace" / "library" / record.model_id

            self.assertTrue(record.is_managed)
            self.assertTrue(record.can_resume)
            self.assertTrue((model_dir / "baseline" / "inference" / "voice-a.pth").is_file())
            self.assertTrue((model_dir / "baseline" / "checkpoints" / "G_100.pth").is_file())
            self.assertTrue((model_dir / "manifest.json").is_file())
            self.assertEqual(original_bytes, {path: path.read_bytes() for path in source_files})

    def test_profile_survives_source_rescan(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            source = _build_rvc_root(base / "source")
            workspace = RvcModelWorkspace(base / "workspace")
            linked = workspace.link_folder(source / "logs" / "voice-a")[0]

            workspace.update_profile(
                linked.model_id,
                display_name="Voice A Clean",
                tags=("bright", "female", "bright"),
                notes="Preferred revision",
                default_pitch=-12,
                default_device="cpu",
            )
            workspace.link_folder(source / "logs" / "voice-a")
            record = workspace.records()[0]

            self.assertEqual(record.title, "Voice A Clean")
            self.assertEqual(record.tags, ("bright", "female"))
            self.assertEqual(record.notes, "Preferred revision")
            self.assertEqual(record.default_pitch, -12)
            self.assertEqual(record.default_device, "cpu")

    def test_managed_artifact_repair_copies_replacement_into_baseline(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            source = _build_rvc_root(base / "source")
            workspace = RvcModelWorkspace(base / "workspace")
            record = workspace.import_folder(source / "logs" / "voice-a")[0]
            replacement = base / "repair" / "added_voice-a.index"
            replacement.parent.mkdir()
            replacement.write_bytes(b"other")

            updated = workspace.replace_artifact(record.model_id, "index_file", replacement)

            self.assertNotEqual(updated.index_file, replacement)
            self.assertEqual(updated.index_file.read_bytes(), b"other")
            self.assertEqual(replacement.read_bytes(), b"other")
            self.assertIn("baseline", updated.index_file.parts)

    def test_linked_index_repair_recovers_missing_file_state(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            source = _build_rvc_root(base / "source")
            workspace = RvcModelWorkspace(base / "workspace")
            record = workspace.link_folder(source / "logs" / "voice-a")[0]
            record.index_file.unlink()
            replacement = base / "replacement.index"
            replacement.write_bytes(b"replacement")

            self.assertEqual(workspace.records()[0].status_label, "Missing Files")
            repaired = workspace.replace_artifact(record.model_id, "index_file", replacement)

            self.assertEqual(repaired.status_label, "Resume Ready")
            self.assertEqual(repaired.index_file, replacement.resolve())


def _build_rvc_root(root: Path) -> Path:
    weights = root / "weights"
    experiment = root / "logs" / "voice-a"
    runtime = root / "runtime"
    weights.mkdir(parents=True)
    experiment.mkdir(parents=True)
    runtime.mkdir(parents=True)
    (runtime / "python.exe").write_bytes(b"runtime")
    (root / "infer_cli.py").write_text("", encoding="utf-8")
    (weights / "voice-a.pth").write_bytes(b"inference")
    (weights / "voice-a_e50_s500.pth").write_bytes(b"old inference")
    (weights / "standalone.pth").write_bytes(b"standalone")
    (experiment / "added_voice-a.index").write_bytes(b"index")
    (experiment / "G_50.pth").write_bytes(b"old generator")
    (experiment / "D_50.pth").write_bytes(b"old discriminator")
    (experiment / "G_100.pth").write_bytes(b"generator")
    (experiment / "D_100.pth").write_bytes(b"discriminator")
    return root


if __name__ == "__main__":
    unittest.main()
