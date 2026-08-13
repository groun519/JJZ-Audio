from __future__ import annotations

import tempfile
import unittest
import wave
from pathlib import Path

from jang_app.services.model_dataset import ModelDatasetStore
from jang_app.services.model_work_share_package import (
    create_model_work_share_package,
    import_model_work_share_package,
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
            self.assertEqual(len(imported_dataset.items), 1)
            self.assertEqual(len(imported_dataset.training_items), 1)
            self.assertEqual(
                imported_dataset.items[0].source_name,
                source_audio.name,
            )


def _write_test_wav(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(16000)
        wav_file.writeframes(b"\x00\x00" * 16000)


if __name__ == "__main__":
    unittest.main()
