from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from jang_app.services import settings as settings_module
from jang_app.services.settings import (
    AppSettings,
    RvcSettings,
    StudioLayoutSettings,
    load_app_settings,
    save_app_settings,
)
from jang_app.services.rvc_inference_settings import RvcInferenceSettings


class RvcSettingsTests(unittest.TestCase):
    def test_model_id_is_persisted_for_library_selection(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            settings_file = Path(temporary) / "settings.json"
            expected = AppSettings(
                rvc=RvcSettings(
                    root=Path("D:/JJZero/RVC"),
                    model_id="voice-id",
                    voice_model="D:/JJZero/models/voice.pth",
                )
            )

            with patch.object(settings_module, "SETTINGS_FILE", settings_file):
                save_app_settings(expected)
                loaded = load_app_settings()

            self.assertEqual(loaded.rvc.model_id, "voice-id")
            self.assertEqual(loaded.rvc.voice_model, expected.rvc.voice_model)

    def test_inference_quality_values_are_persisted(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            settings_file = Path(temporary) / "settings.json"
            expected = RvcInferenceSettings(
                index_rate=0.62,
                filter_radius=5,
                rms_mix_rate=0.4,
                protect=0.18,
            )
            with patch.object(settings_module, "SETTINGS_FILE", settings_file):
                save_app_settings(AppSettings(rvc=RvcSettings(inference=expected)))
                loaded = load_app_settings()

            self.assertEqual(loaded.rvc.inference, expected)

    def test_legacy_settings_without_model_id_remain_compatible(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            settings_file = Path(temporary) / "settings.json"
            settings_file.write_text(
                '{"rvc": {"root": "D:/RVC", "voice_model": "weights/voice.pth"}}',
                encoding="utf-8",
            )

            with patch.object(settings_module, "SETTINGS_FILE", settings_file):
                loaded = load_app_settings()

            self.assertEqual(loaded.rvc.model_id, "")
            self.assertEqual(loaded.rvc.voice_model, "weights/voice.pth")
            self.assertEqual(loaded.rvc.inference, RvcInferenceSettings())

    def test_studio_layout_sizes_are_persisted_and_invalid_values_use_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            settings_file = Path(temporary) / "settings.json"
            expected = StudioLayoutSettings(
                workspace_sizes=(220, 1_050, 310),
                center_sizes=(410, 590),
                left_sizes=(650, 350),
            )
            with patch.object(settings_module, "SETTINGS_FILE", settings_file):
                save_app_settings(AppSettings(studio_layout=expected))
                loaded = load_app_settings()
                settings_file.write_text(
                    '{"studio_layout": {"workspace_sizes": [0, 0, 0]}}',
                    encoding="utf-8",
                )
                invalid = load_app_settings()

            self.assertEqual(loaded.studio_layout, expected)
            self.assertEqual(
                invalid.studio_layout.workspace_sizes,
                StudioLayoutSettings().workspace_sizes,
            )
            self.assertEqual(
                invalid.studio_layout.left_sizes,
                StudioLayoutSettings().left_sizes,
            )

    def test_removed_conversion_monitor_preference_is_discarded(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            settings_file = Path(temporary) / "settings.json"
            settings_file.write_text(
                '{"conversion_auto_monitor": false}',
                encoding="utf-8",
            )
            with patch.object(settings_module, "SETTINGS_FILE", settings_file):
                loaded = load_app_settings()
                save_app_settings(loaded)

            self.assertFalse(hasattr(loaded, "conversion_auto_monitor"))
            self.assertNotIn("conversion_auto_monitor", settings_file.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
