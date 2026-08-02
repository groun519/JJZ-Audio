from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PySide6.QtWidgets import QApplication, QLabel, QWidget

from jang_app.qt_app.localization import apply_widget_language, set_translated_text
from jang_app.services import settings as settings_module
from jang_app.services.i18n import LANGUAGE_ENGLISH, LANGUAGE_KOREAN, set_language, tr
from jang_app.services.settings import AppSettings, load_app_settings, save_app_settings


class LocalizationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def tearDown(self) -> None:
        set_language(LANGUAGE_KOREAN)

    def test_widget_text_switches_between_korean_and_english(self) -> None:
        root = QWidget()
        label = QLabel("Library", root)
        count_label = QLabel(root)
        set_translated_text(count_label, "Clips {count}", count=3)

        set_language(LANGUAGE_KOREAN)
        apply_widget_language(root)
        self.assertEqual(label.text(), "라이브러리")
        self.assertEqual(count_label.text(), "클립 3")

        set_language(LANGUAGE_ENGLISH)
        apply_widget_language(root)
        self.assertEqual(label.text(), "Library")
        self.assertEqual(count_label.text(), "Clips 3")
        root.close()

    def test_existing_settings_without_language_migrate_to_korean(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            settings_file = Path(temporary_directory) / "app_settings.json"
            settings_file.write_text(json.dumps({"theme_mode": "dark"}), encoding="utf-8")
            with patch.object(settings_module, "SETTINGS_FILE", settings_file):
                loaded = load_app_settings()

        self.assertEqual(loaded.theme_mode, "dark")
        self.assertEqual(loaded.language, LANGUAGE_KOREAN)

    def test_selected_language_is_persisted(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            settings_file = Path(temporary_directory) / "app_settings.json"
            with patch.object(settings_module, "SETTINGS_FILE", settings_file):
                save_app_settings(AppSettings(language=LANGUAGE_ENGLISH))
                loaded = load_app_settings()

        self.assertEqual(loaded.language, LANGUAGE_ENGLISH)

    def test_dynamic_error_prefix_is_translated(self) -> None:
        set_language(LANGUAGE_KOREAN)
        self.assertEqual(tr("Export failed: disk full"), "저장 실패: disk full")
        set_language(LANGUAGE_ENGLISH)
        self.assertEqual(tr("Export failed: disk full"), "Export failed: disk full")


if __name__ == "__main__":
    unittest.main()
