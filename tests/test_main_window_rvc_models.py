from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from PySide6.QtWidgets import QApplication, QComboBox, QLineEdit, QSpinBox

from jang_app.qt_app.main_window import MainWindow
from jang_app.services.rvc_model_choices import RvcModelChoice
from jang_app.services.rvc_model_workspace import RvcModelRecord
from jang_app.services.settings import AppSettings, RvcSettings


class MainWindowRvcModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_model_id_restores_selection_when_the_model_path_changes(self) -> None:
        combo = QComboBox()
        window = SimpleNamespace(model_combo=combo)
        first = RvcModelChoice(
            "library:first",
            "First",
            Path("C:/rvc"),
            Path("C:/models/first.pth"),
            model_id="first",
        )
        moved = RvcModelChoice(
            "library:voice",
            "Voice",
            Path("C:/rvc"),
            Path("D:/moved/voice.pth"),
            model_id="voice",
        )

        MainWindow._populate_model_combo(
            window,
            (first, moved),
            "voice",
            Path("C:/rvc"),
            "C:/old/voice.pth",
        )

        self.assertEqual(combo.currentData(), moved)

    def test_selecting_library_model_applies_every_conversion_default(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            model = root / "voice.pth"
            index = root / "voice.index"
            model.write_bytes(b"model")
            index.write_bytes(b"index")
            choice = RvcModelChoice(
                "library:voice",
                "Voice",
                root,
                model,
                model_id="voice",
                index_path=index,
                pitch=-12,
                device="gpu",
            )
            window = SimpleNamespace(
                _is_loading_rvc_settings=False,
                rvc_root_edit=QLineEdit(),
                pitch_spin=QSpinBox(),
                device_combo=QComboBox(),
                index_combo=QComboBox(),
                settings=AppSettings(rvc=RvcSettings(root=root)),
            )
            window.device_combo.addItems(("auto", "gpu", "cpu"))
            window._populate_combo = lambda *args: MainWindow._populate_combo(
                window,
                *args,
            )

            with patch("jang_app.qt_app.main_window.save_app_settings"):
                MainWindow._apply_rvc_model_choice(window, choice)

            self.assertEqual(window.settings.rvc.model_id, "voice")
            self.assertEqual(window.settings.rvc.voice_model, str(model))
            self.assertEqual(window.settings.rvc.index_file, str(index))
            self.assertEqual(window.settings.rvc.pitch, -12)
            self.assertEqual(window.settings.rvc.device, "gpu")

    def test_refresh_tracks_replaced_artifacts_by_model_id(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            old_root = root / "old"
            model_root = root / "managed"
            model_root.mkdir()
            model = model_root / "voice.pth"
            index = model_root / "voice.index"
            model.write_bytes(b"model")
            index.write_bytes(b"index")
            record = RvcModelRecord(
                model_id="voice",
                name="voice",
                mode="managed",
                runtime_root=model_root,
                source_folder=None,
                inference_model=model,
                index_file=index,
                generator_checkpoint=None,
                discriminator_checkpoint=None,
                created_at="2026-01-01T00:00:00+00:00",
                display_name="Voice",
            )
            window = SimpleNamespace(
                _is_loading_rvc_settings=False,
                rvc_root_edit=QLineEdit(str(old_root)),
                model_combo=QComboBox(),
                index_combo=QComboBox(),
                pitch_spin=QSpinBox(),
                device_combo=QComboBox(),
                model_workspace=SimpleNamespace(records=lambda: (record,)),
                settings=AppSettings(
                    rvc=RvcSettings(
                        root=old_root,
                        model_id="voice",
                        voice_model="old.pth",
                        pitch=7,
                        device="cpu",
                    )
                ),
            )
            window.pitch_spin.setValue(7)
            window.device_combo.addItems(("auto", "gpu", "cpu"))
            window.device_combo.setCurrentText("cpu")
            window._populate_model_combo = lambda *args: (
                MainWindow._populate_model_combo(window, *args)
            )
            window._populate_combo = lambda *args: MainWindow._populate_combo(
                window,
                *args,
            )
            window._save_rvc_settings_from_controls = lambda *args: (
                MainWindow._save_rvc_settings_from_controls(window, *args)
            )

            with patch("jang_app.qt_app.main_window.save_app_settings"):
                MainWindow._refresh_rvc_choices(window)

            self.assertEqual(window.settings.rvc.root, model_root.resolve())
            self.assertEqual(window.settings.rvc.voice_model, str(model.resolve()))
            self.assertEqual(window.settings.rvc.index_file, str(index.resolve()))
            self.assertEqual(window.settings.rvc.pitch, 7)
            self.assertEqual(window.settings.rvc.device, "cpu")


if __name__ == "__main__":
    unittest.main()
