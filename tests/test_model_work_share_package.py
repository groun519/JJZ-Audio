from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
import wave
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from jang_app.services.managed_transaction import (
    ManagedPathTransaction,
    recover_managed_transactions,
)
from jang_app.services.model_dataset import ModelDatasetError, ModelDatasetStore
from jang_app.services.model_work_share_package import (
    MODEL_WORK_SHARE_MANIFEST,
    ModelWorkSharePackageError,
    ModelWorkShareStorageError,
    create_model_work_share_package,
    import_model_work_share_package,
    inspect_model_work_share_package,
)
from jang_app.services.rvc_model_workspace import RvcModelWorkspace


class ModelWorkSharePackageTests(unittest.TestCase):
    def test_managed_model_work_round_trip_restores_dataset_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workspace = RvcModelWorkspace(root / "workspace")
            record = workspace.create_model("Voice One", root / "runtime")
            source_audio = root / "voice.wav"
            _write_test_wav(source_audio)

            store = ModelDatasetStore(workspace.root)
            dataset = store.add_sources(record.model_id, (source_audio,))
            dataset = store.select_items(record.model_id, (dataset.items[0].item_id,))

            with _ample_disk_space():
                package = create_model_work_share_package(
                    workspace,
                    record,
                    root / "packages",
                )

            imported_workspace = RvcModelWorkspace(root / "imported_workspace")
            imported = import_model_work_share_package(package.path, imported_workspace)
            imported_dataset = ModelDatasetStore(imported_workspace.root).load(
                record.model_id
            )

            self.assertEqual(imported.record.model_id, record.model_id)
            self.assertEqual(imported.record.name, record.name)
            self.assertEqual(
                imported.record.runtime_root,
                imported_workspace.library_dir / record.model_id / "rvc",
            )
            self.assertEqual(len(imported_dataset.items), 1)
            self.assertEqual(len(imported_dataset.training_items), 1)
            self.assertEqual(
                imported_dataset.items[0].source_name,
                source_audio.name,
            )

    def test_work_import_registers_latest_complete_checkpoint_pair(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workspace = RvcModelWorkspace(root / "workspace")
            record = workspace.create_model("Voice One", root / "runtime")
            experiment = (
                workspace.library_dir
                / record.model_id
                / "rvc"
                / "logs"
                / record.name
            )
            for name in (
                "G_9.pth",
                "D_9.pth",
                "G_100.pth",
                "D_100.pth",
                "G_200.pth",
            ):
                (experiment / name).write_bytes(name.encode())
            source_audio = root / "voice.wav"
            _write_test_wav(source_audio)
            store = ModelDatasetStore(workspace.root)
            dataset = store.add_sources(record.model_id, (source_audio,))
            store.select_items(record.model_id, (dataset.items[0].item_id,))
            with _ample_disk_space():
                package = create_model_work_share_package(
                    workspace,
                    record,
                    root / "packages",
                )

            imported = import_model_work_share_package(
                package.path,
                RvcModelWorkspace(root / "imported_workspace"),
            )

            self.assertEqual(imported.record.generator_checkpoint.name, "G_100.pth")
            self.assertEqual(
                imported.record.discriminator_checkpoint.name,
                "D_100.pth",
            )

    def test_failed_dataset_validation_does_not_register_ghost_model(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workspace = RvcModelWorkspace(root / "workspace")
            record = workspace.create_model("Voice One", root / "runtime")
            source_audio = root / "voice.wav"
            _write_test_wav(source_audio)
            store = ModelDatasetStore(workspace.root)
            dataset = store.add_sources(record.model_id, (source_audio,))
            store.select_items(record.model_id, (dataset.items[0].item_id,))
            with _ample_disk_space():
                package = create_model_work_share_package(
                    workspace,
                    record,
                    root / "packages",
                )
            imported_workspace = RvcModelWorkspace(root / "imported_workspace")

            with patch.object(
                ModelDatasetStore,
                "load",
                side_effect=ModelDatasetError("invalid dataset"),
            ):
                with self.assertRaisesRegex(ModelDatasetError, "invalid dataset"):
                    import_model_work_share_package(
                        package.path,
                        imported_workspace,
                    )

            self.assertEqual(imported_workspace.records(), [])
            self.assertFalse(
                (imported_workspace.library_dir / record.model_id).exists()
            )
            self.assertFalse(
                (ModelDatasetStore(imported_workspace.root).root / record.model_id).exists()
            )

            imported = import_model_work_share_package(
                package.path,
                imported_workspace,
            )
            self.assertEqual(imported.record.model_id, record.model_id)

    def test_manifest_size_must_match_zip_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            package = Path(directory) / "invalid-size.zip"
            archive_path = "model/model.json"
            payload = b"{}"
            manifest = _work_manifest(archive_path, payload)
            manifest["files"][0]["size"] = len(payload) + 1
            with zipfile.ZipFile(package, "w") as archive:
                archive.writestr(archive_path, payload)
                archive.writestr(MODEL_WORK_SHARE_MANIFEST, json.dumps(manifest))

            with self.assertRaisesRegex(ModelWorkSharePackageError, "file size"):
                inspect_model_work_share_package(package)

    def test_import_rejects_unsafe_model_identity_before_extraction(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            package = root / "unsafe-identity.zip"
            entries = {
                "model/model.json": b"{}",
                "dataset/dataset.json": b"{}",
            }
            manifest = {
                "format": "jjzero-rvc-model-work",
                "version": 1,
                "model": {"id": "../escape", "name": "Voice"},
                "files": [
                    _work_file_entry(path, payload)
                    for path, payload in entries.items()
                ],
            }
            with zipfile.ZipFile(package, "w") as archive:
                for path, payload in entries.items():
                    archive.writestr(path, payload)
                archive.writestr(MODEL_WORK_SHARE_MANIFEST, json.dumps(manifest))

            with self.assertRaisesRegex(ModelWorkSharePackageError, "unsafe"):
                import_model_work_share_package(
                    package,
                    RvcModelWorkspace(root / "workspace"),
                )
            self.assertFalse((root / "escape").exists())

    def test_import_rejects_insufficient_workspace_space_before_extraction(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workspace = RvcModelWorkspace(root / "workspace")
            record = workspace.create_model("Voice One", root / "runtime")
            source_audio = root / "voice.wav"
            _write_test_wav(source_audio)
            store = ModelDatasetStore(workspace.root)
            dataset = store.add_sources(record.model_id, (source_audio,))
            store.select_items(record.model_id, (dataset.items[0].item_id,))
            with _ample_disk_space():
                package = create_model_work_share_package(
                    workspace,
                    record,
                    root / "packages",
                )
            imported_workspace = RvcModelWorkspace(root / "imported_workspace")

            with patch(
                "jang_app.services.model_work_share_package.shutil.disk_usage",
                return_value=SimpleNamespace(free=0),
            ):
                with self.assertRaises(ModelWorkShareStorageError):
                    import_model_work_share_package(
                        package.path,
                        imported_workspace,
                    )

            self.assertEqual(imported_workspace.records(), [])

    def test_startup_recovery_removes_interrupted_work_import(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source_workspace = RvcModelWorkspace(root / "source_workspace")
            record = source_workspace.create_model("Voice One", root / "runtime")
            source_audio = root / "voice.wav"
            _write_test_wav(source_audio)
            store = ModelDatasetStore(source_workspace.root)
            dataset = store.add_sources(record.model_id, (source_audio,))
            store.select_items(record.model_id, (dataset.items[0].item_id,))
            with _ample_disk_space():
                package = create_model_work_share_package(
                    source_workspace,
                    record,
                    root / "packages",
                )
            imported_workspace = RvcModelWorkspace(root / "imported_workspace")

            with patch.object(
                ManagedPathTransaction,
                "mark_committed",
                side_effect=SystemExit,
            ):
                with self.assertRaises(SystemExit):
                    import_model_work_share_package(
                        package.path,
                        imported_workspace,
                    )

            reports = recover_managed_transactions(imported_workspace.root)

            self.assertEqual(reports[0].action, "rolled_back")
            self.assertEqual(imported_workspace.records(), [])
            self.assertFalse(
                (imported_workspace.library_dir / record.model_id).exists()
            )
            self.assertFalse(
                (ModelDatasetStore(imported_workspace.root).root / record.model_id).exists()
            )

    def test_startup_recovery_removes_interrupted_work_extraction(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source_workspace = RvcModelWorkspace(root / "source_workspace")
            record = source_workspace.create_model("Voice One", root / "runtime")
            source_audio = root / "voice.wav"
            _write_test_wav(source_audio)
            store = ModelDatasetStore(source_workspace.root)
            dataset = store.add_sources(record.model_id, (source_audio,))
            store.select_items(record.model_id, (dataset.items[0].item_id,))
            with _ample_disk_space():
                package = create_model_work_share_package(
                    source_workspace,
                    record,
                    root / "packages",
                )
            imported_workspace = RvcModelWorkspace(root / "imported_workspace")

            with patch(
                "jang_app.services.model_work_share_package._report",
                side_effect=SystemExit,
            ):
                with self.assertRaises(SystemExit):
                    import_model_work_share_package(
                        package.path,
                        imported_workspace,
                    )

            reports = recover_managed_transactions(imported_workspace.root)

            self.assertEqual(reports[0].action, "rolled_back")
            self.assertEqual(imported_workspace.records(), [])
            self.assertFalse(
                (imported_workspace.root / ".jjzero-transactions").exists()
            )


def _write_test_wav(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(16000)
        wav_file.writeframes(b"\x00\x00" * 16000)


def _work_file_entry(path: str, payload: bytes) -> dict[str, object]:
    return {
        "path": path,
        "size": len(payload),
        "modified_ns": 0,
        "sha256": hashlib.sha256(payload).hexdigest(),
    }


def _work_manifest(path: str, payload: bytes) -> dict[str, object]:
    return {
        "format": "jjzero-rvc-model-work",
        "version": 1,
        "model": {"id": "voice", "name": "Voice"},
        "files": [_work_file_entry(path, payload)],
    }


def _ample_disk_space():
    return patch(
        "jang_app.services.model_work_share_package.shutil.disk_usage",
        return_value=SimpleNamespace(free=10 * 1024**3),
    )


if __name__ == "__main__":
    unittest.main()
