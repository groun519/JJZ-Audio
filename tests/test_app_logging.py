from __future__ import annotations

import logging
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from jang_app.services import app_logging
from jang_app.version import __version__


class AppLoggingTests(unittest.TestCase):
    def test_logger_records_one_versioned_session_banner_when_initialized(self) -> None:
        logger = logging.getLogger(app_logging.LOGGER_NAME)
        original_handlers = list(logger.handlers)
        original_level = logger.level
        original_propagate = logger.propagate
        logger.handlers = []

        try:
            with tempfile.TemporaryDirectory() as temporary:
                log_file = Path(temporary) / "jang.log"
                with patch.object(app_logging, "LOG_FILE", log_file):
                    configured = app_logging.get_logger()
                    self.assertIs(configured, app_logging.get_logger())
                    for handler in configured.handlers:
                        handler.flush()
                        handler.close()
                    configured.handlers = []

                text = log_file.read_text(encoding="utf-8")
                self.assertEqual(text.count("Application session started"), 1)
                self.assertIn(f"version={__version__}", text)
                self.assertIn("mode=source", text)
                self.assertIn("python=", text)
                self.assertIn("executable=", text)
        finally:
            for handler in logger.handlers:
                handler.close()
            logger.handlers = original_handlers
            logger.setLevel(original_level)
            logger.propagate = original_propagate


if __name__ == "__main__":
    unittest.main()
