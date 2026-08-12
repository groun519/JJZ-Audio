from __future__ import annotations

import tempfile
import unittest
import wave
from pathlib import Path
from unittest.mock import patch

from PySide6.QtWidgets import QApplication

from jang_app.qt_app.model_dataset_panel import ModelDatasetPanel
from jang_app.qt_app.widgets import DangerIconButton
from jang_app.services.i18n import tr
from jang_app.services.model_dataset import ModelDatasetStore


class ModelDatasetPanelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_source_removal_uses_the_shared_danger_button(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            panel = ModelDatasetPanel(ModelDatasetStore(Path(temporary) / "workspace"))

            self.assertIsInstance(panel.remove_button, DangerIconButton)
            self.assertEqual(panel.remove_button.icon_name(), "trash")
            self.assertTrue(panel.remove_button.property("persistentDanger"))
            panel.close()

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

                self.assertTrue(panel.footer.isHidden())

                panel.clip_editor.close_button.click()

                self.assertTrue(panel.clip_editor.isHidden())
                self.assertFalse(panel.footer.isHidden())
                self.assertEqual(panel.training_list.selectedItems(), [])
                self.assertEqual(len(store.load("model").training_items), 1)
                panel.close()

    def test_open_training_item_selects_the_requested_material(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            store = ModelDatasetStore(root / "workspace")
            items = store.add_sources(
                "model",
                (_wave_file(root / "first.wav"), _wave_file(root / "second.wav")),
            ).items
            store.select_items("model", (item.item_id for item in items))
            panel = ModelDatasetPanel(store)
            with patch(
                "jang_app.qt_app.clip_waveform_view.waveform_cache_key",
                side_effect=OSError,
            ):
                panel.set_model("model")

                opened = panel.open_training_item(items[1].item_id)

                self.assertTrue(opened)
                self.assertEqual(panel.training_list.currentRow(), 1)
                self.assertFalse(panel.clip_editor.isHidden())
                panel.close()

    def test_mark_ready_advances_to_the_next_unreviewed_audio(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            store = ModelDatasetStore(root / "workspace")
            items = store.add_sources(
                "model",
                (_wave_file(root / "first.wav"), _wave_file(root / "second.wav")),
            ).items
            store.select_items("model", (item.item_id for item in items))
            panel = ModelDatasetPanel(store)
            with patch(
                "jang_app.qt_app.clip_waveform_view.waveform_cache_key",
                side_effect=OSError,
            ):
                panel.set_model("model")
                panel.training_list.setCurrentRow(0)

                panel.clip_editor.ready_button.click()

                dataset = store.load("model")
                self.assertEqual(dataset.training_items[0].review_state, "ready")
                self.assertEqual(panel.training_list.currentRow(), 1)
                panel.close()

    def test_held_clips_are_visible_but_do_not_block_ready_state(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            store = ModelDatasetStore(root / "workspace")
            source = _wave_file(root / "voice.wav")
            item = store.add_sources("model", [source]).items[0]
            store.select_items("model", [item.item_id])
            queued = store.replace_segment_candidates(
                "model",
                item.item_id,
                ((100, 400), (500, 800)),
            ).items[0]
            accepted = store.accept_segment_candidate(
                "model",
                item.item_id,
                queued.segment_candidates[0].candidate_id,
                100,
                400,
            ).items[0]
            store.set_segment_candidate_status(
                "model",
                item.item_id,
                accepted.segment_candidates[0].candidate_id,
                "held",
            )
            panel = ModelDatasetPanel(store)
            with patch(
                "jang_app.qt_app.clip_waveform_view.waveform_cache_key",
                side_effect=OSError,
            ):
                panel.set_model("model")
                panel.training_list.setCurrentRow(0)

                row = panel.training_list.itemWidget(panel.training_list.item(0))
                self.assertIn(tr("{count} HELD", count=1), row.metadata_label.text())
                self.assertTrue(panel.clip_editor.ready_button.isEnabled())

                panel.clip_editor.ready_button.click()

                ready = store.load("model").training_items[0]
                self.assertEqual(ready.review_state, "ready")
                self.assertEqual(ready.held_segment_count, 1)
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
