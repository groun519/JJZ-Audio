from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from jang_app.services import settings as settings_module
from jang_app.services.settings import (
    AppSettings,
    RvcSettings,
    load_app_settings,
    save_app_settings,
)


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


if __name__ == "__main__":
    unittest.main()
