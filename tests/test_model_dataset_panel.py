from __future__ import annotations

import tempfile
import unittest
import wave
from pathlib import Path
from unittest.mock import patch

from PySide6.QtWidgets import QApplication

from jang_app.qt_app.model_dataset_panel import ModelDatasetPanel
from jang_app.services.model_dataset import ModelDatasetStore


class ModelDatasetPanelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_close_editor_clears_training_selection_without_changing_data(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            store = ModelDatasetStore(root / "workspace")
            source = _wave_file(root / "voice.wav")
            item = store.add_sources("model", [source]).items[0]
            store.select_items("model", [item.item_id])
            panel = ModelDatasetPanel(store)
            with patch(
                "jang_app.qt_app.clip_waveform_view.waveform_cache_key",
                side_effect=OSError,
            ):
                panel.set_model("model")
                panel.training_list.setCurrentRow(0)

                panel.clip_editor.close_button.click()

                self.assertTrue(panel.clip_editor.isHidden())
                self.assertEqual(panel.training_list.selectedItems(), [])
                self.assertEqual(len(store.load("model").training_items), 1)
                panel.close()


def _wave_file(path: Path) -> Path:
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(8000)
        output.writeframes(b"\x00\x00" * 8000)
    return path


if __name__ == "__main__":
    unittest.main()
