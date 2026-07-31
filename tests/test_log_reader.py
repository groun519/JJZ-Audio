from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from jang_app.services.log_reader import read_log_tail


class LogReaderTests(unittest.TestCase):
    def test_returns_empty_text_for_missing_log(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            self.assertEqual(read_log_tail(Path(temporary) / "missing.log"), "")

    def test_returns_requested_tail_lines(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            log_path = Path(temporary) / "app.log"
            log_path.write_text("one\ntwo\nthree\nfour\n", encoding="utf-8")

            self.assertEqual(read_log_tail(log_path, max_lines=2), "three\nfour")

    def test_discards_partial_first_line_when_byte_limited(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            log_path = Path(temporary) / "app.log"
            log_path.write_bytes(b"first line\nsecond line\nthird line\n")

            self.assertEqual(read_log_tail(log_path, max_bytes=23), "second line\nthird line")


if __name__ == "__main__":
    unittest.main()
