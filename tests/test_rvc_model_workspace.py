from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from jang_app.services.rvc_model_workspace import (
    RvcModelWorkspace,
    RvcModelWorkspaceError,
    discover_rvc_models,
)


class RvcModelWorkspaceTests(unittest.TestCase):
    def test_records_reuses_catalog_until_the_file_changes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            runtime = _build_rvc_root(base / "runtime")
            RvcModelWorkspace(base / "workspace").create_model("Voice One", runtime)
            workspace = RvcModelWorkspace(base / "workspace")

            with patch.object(
                workspace,
                "_record_from_data",
                wraps=workspace._record_from_data,
            ) as decode:
                first = workspace.records()
                second = workspace.records()

            self.assertEqual(first, second)
            self.assertEqual(decode.call_count, 1)

    def test_records_reloads_an_externally_changed_catalog(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            runtime = _build_rvc_root(base / "runtime")
            creator = RvcModelWorkspace(base / "workspace")
            creator.create_model("Voice One", runtime)
            workspace = RvcModelWorkspace(base / "workspace")
            self.assertEqual(workspace.records()[0].title, "Voice One")

            catalog = json.loads(workspace.catalog_path.read_text(encoding="utf-8"))
            catalog["models"][0]["display_name"] = "Externally Renamed Voice"
            workspace.catalog_path.write_text(json.dumps(catalog), encoding="utf-8")

            self.assertEqual(workspace.records()[0].title, "Externally Renamed Voice")

    def test_create_model_builds_empty_managed_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            runtime = _build_rvc_root(base / "runtime")
            workspace = RvcModelWorkspace(base / "workspace")

            record = workspace.create_model("  My   Voice  ", runtime)

            model_dir = workspace.library_dir / record.model_id
            self.assertEqual(record.name, "My Voice")
            self.assertEqual(record.mode, "created")
            self.assertTrue(record.is_managed)
            self.assertEqual(record.mode_label, "New Model")
            self.assertEqual(record.source_folder, model_dir / "rvc" / "logs" / "My Voice")
            self.assertTrue((model_dir / "rvc" / "weights").is_dir())
            self.assertTrue((model_dir / "rvc" / "logs" / "My Voice").is_dir())
            self.assertTrue((model_dir / "model.json").is_file())
            self.assertEqual(workspace.records()[0], record)
            with self.assertRaises(RvcModelWorkspaceError):
                workspace.create_model("my voice", runtime)

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

    def test_link_inference_file_accepts_pth_without_index(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            model_file = base / "solo_voice.pth"
            model_file.write_bytes(b"inference")
            workspace = RvcModelWorkspace(base / "workspace")

            record = workspace.link_inference_file(model_file)

            self.assertEqual(record.name, "solo_voice")
            self.assertEqual(record.inference_model, model_file.resolve())
            self.assertIsNone(record.index_file)
            self.assertTrue(record.can_convert)
            self.assertEqual(record.status_label, "Inference Only")
            self.assertFalse(record.is_managed)

    def test_import_inference_file_copies_only_pth_and_matching_index(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            source = base / "source"
            source.mkdir()
            model_file = source / "voice_e100_s200.pth"
            index_file = source / "added_voice.index"
            unrelated = source / "unrelated.pth"
            model_file.write_bytes(b"inference")
            index_file.write_bytes(b"index")
            unrelated.write_bytes(b"unrelated")
            workspace = RvcModelWorkspace(base / "workspace")

            record = workspace.import_inference_file(model_file)

            self.assertEqual(record.name, "voice")
            self.assertTrue(record.is_managed)
            self.assertEqual(record.inference_model.read_bytes(), b"inference")
            self.assertEqual(record.index_file.read_bytes(), b"index")
            self.assertFalse(any(path.name == unrelated.name for path in workspace.library_dir.rglob("*.pth")))
            self.assertEqual(model_file.read_bytes(), b"inference")
            self.assertEqual(index_file.read_bytes(), b"index")
            self.assertEqual(unrelated.read_bytes(), b"unrelated")

    def test_inference_file_in_weights_finds_index_in_webui_logs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            runtime = base / "rvc"
            weights = runtime / "weights"
            experiment = runtime / "logs" / "voice"
            weights.mkdir(parents=True)
            experiment.mkdir(parents=True)
            model_file = weights / "voice.pth"
            index_file = experiment / "added_voice.index"
            model_file.write_bytes(b"inference")
            index_file.write_bytes(b"index")
            workspace = RvcModelWorkspace(base / "workspace")

            record = workspace.link_inference_file(model_file)

            self.assertEqual(record.runtime_root, runtime.resolve())
            self.assertEqual(record.index_file, index_file.resolve())
            self.assertTrue(record.has_index)

    def test_inference_file_rejects_training_checkpoint(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            checkpoint = base / "G_100.pth"
            checkpoint.write_bytes(b"checkpoint")
            workspace = RvcModelWorkspace(base / "workspace")

            with self.assertRaisesRegex(RvcModelWorkspaceError, "training checkpoints"):
                workspace.link_inference_file(checkpoint)

    def test_import_preserves_webui_layout_without_changing_source(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            source = _build_rvc_root(base / "source")
            source_files = [path for path in source.rglob("*") if path.is_file()]
            original_bytes = {path: path.read_bytes() for path in source_files}
            workspace = RvcModelWorkspace(base / "workspace")

            record = workspace.import_folder(source / "logs" / "voice-a")[0]
            model_dir = base / "workspace" / "library" / record.model_id
            package_root = model_dir / "rvc"

            self.assertTrue(record.is_managed)
            self.assertTrue(record.can_resume)
            self.assertEqual(record.inference_model, package_root / "weights" / "voice-a.pth")
            self.assertEqual(record.index_file, package_root / "logs" / "voice-a" / "added_voice-a.index")
            self.assertTrue((package_root / "weights" / "voice-a_e50_s500.pth").is_file())
            self.assertTrue((package_root / "logs" / "voice-a" / "0_gt_wavs" / "sample.wav").is_file())
            self.assertTrue((package_root / "logs" / "voice-a" / "2a_f0").is_dir())
            self.assertTrue((package_root / "logs" / "voice-a" / "3_feature768" / "sample.npy").is_file())
            self.assertTrue((package_root / "logs" / "voice-a" / "train.log").is_file())
            self.assertTrue((model_dir / "model.json").is_file())
            self.assertEqual(workspace.portable_rvc_root(record.model_id), package_root)
            self.assertEqual(record.primary_location, package_root)
            manifest = json.loads((model_dir / "model.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["rvc_name"], "voice-a")
            self.assertEqual(manifest["rvc"]["root"], "rvc")
            self.assertEqual(manifest["rvc"]["artifacts"]["inference_model"], "rvc/weights/voice-a.pth")
            self.assertEqual(
                manifest["rvc"]["artifacts"]["generator_checkpoint"],
                "rvc/logs/voice-a/G_100.pth",
            )
            self.assertEqual([model.name for model in discover_rvc_models(model_dir)], ["voice-a"])
            self.assertEqual(original_bytes, {path: path.read_bytes() for path in source_files})

    def test_remove_managed_model_deletes_package_and_training_work(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            runtime = _build_rvc_root(base / "runtime")
            workspace = RvcModelWorkspace(base / "workspace")
            record = workspace.create_model("Voice One", runtime)
            package_dir = workspace.library_dir / record.model_id
            work_dir = workspace.root / record.model_id
            (work_dir / "datasets").mkdir(parents=True)
            (work_dir / "datasets" / "dataset.json").write_text("{}", encoding="utf-8")

            removed = workspace.remove_model(record.model_id)

            self.assertEqual(removed, record)
            self.assertEqual(workspace.records(), [])
            self.assertFalse(package_dir.exists())
            self.assertFalse(work_dir.exists())

    def test_remove_linked_model_keeps_external_files_and_deletes_local_work(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            source = _build_rvc_root(base / "source")
            workspace = RvcModelWorkspace(base / "workspace")
            record = workspace.link_folder(source / "logs" / "voice-a")[0]
            work_dir = workspace.root / record.model_id
            work_dir.mkdir(parents=True)
            (work_dir / "dataset.json").write_text("{}", encoding="utf-8")

            workspace.remove_model(record.model_id)

            self.assertEqual(workspace.records(), [])
            self.assertFalse(work_dir.exists())
            self.assertTrue((source / "weights" / "voice-a.pth").is_file())
            self.assertTrue((source / "logs" / "voice-a" / "G_100.pth").is_file())

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

    def test_managed_artifact_repair_keeps_webui_relative_path(self) -> None:
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
            self.assertEqual(
                updated.index_file.relative_to(base / "workspace" / "library" / record.model_id).as_posix(),
                "rvc/logs/voice-a/added_voice-a.index",
            )

    def test_legacy_baseline_is_copied_to_rvc_package_without_deletion(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            runtime = _build_rvc_root(base / "runtime")
            workspace_root = base / "workspace"
            model_id = "managed-legacy"
            model_dir = workspace_root / "library" / model_id
            legacy_inference = model_dir / "baseline" / "inference" / "voice-a.pth"
            legacy_index = model_dir / "baseline" / "inference" / "added_voice-a.index"
            legacy_generator = model_dir / "baseline" / "checkpoints" / "G_100.pth"
            legacy_discriminator = model_dir / "baseline" / "checkpoints" / "D_100.pth"
            for path, content in (
                (legacy_inference, b"inference"),
                (legacy_index, b"index"),
                (legacy_generator, b"generator"),
                (legacy_discriminator, b"discriminator"),
            ):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(content)
            workspace_root.mkdir(parents=True, exist_ok=True)
            (workspace_root / "catalog.json").write_text(
                json.dumps(
                    {
                        "version": 1,
                        "models": [
                            {
                                "id": model_id,
                                "name": "voice-a",
                                "mode": "managed",
                                "runtime_root": str(runtime),
                                "source_folder": str(model_dir),
                                "inference_model": str(legacy_inference),
                                "index_file": str(legacy_index),
                                "generator_checkpoint": str(legacy_generator),
                                "discriminator_checkpoint": str(legacy_discriminator),
                                "created_at": "2026-01-01T00:00:00+00:00",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            record = RvcModelWorkspace(workspace_root).records()[0]

            self.assertEqual(record.inference_model, model_dir / "rvc" / "weights" / "voice-a.pth")
            self.assertEqual(record.generator_checkpoint, model_dir / "rvc" / "logs" / "voice-a" / "G_100.pth")
            self.assertTrue(legacy_inference.is_file())
            self.assertTrue(legacy_generator.is_file())
            self.assertTrue((model_dir / "model.json").is_file())

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
    (experiment / "0_gt_wavs").mkdir()
    (experiment / "0_gt_wavs" / "sample.wav").write_bytes(b"wave")
    (experiment / "2a_f0").mkdir()
    (experiment / "3_feature768").mkdir()
    (experiment / "3_feature768" / "sample.npy").write_bytes(b"features")
    (experiment / "config.json").write_text("{}", encoding="utf-8")
    (experiment / "filelist.txt").write_text("sample", encoding="utf-8")
    (experiment / "train.log").write_text("trained", encoding="utf-8")
    (experiment / "G_50.pth").write_bytes(b"old generator")
    (experiment / "D_50.pth").write_bytes(b"old discriminator")
    (experiment / "G_100.pth").write_bytes(b"generator")
    (experiment / "D_100.pth").write_bytes(b"discriminator")
    return root


if __name__ == "__main__":
    unittest.main()
