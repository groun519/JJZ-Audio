from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from jang_app.services.file_names import (
    safe_display_filename_stem,
    unique_display_path,
)


class DisplayFileNameTests(unittest.TestCase):
    def test_preserves_unicode_and_removes_windows_invalid_characters(self) -> None:
        result = safe_display_filename_stem("윤하: 사건/지평선? ")

        self.assertEqual(result, "윤하 사건 지평선")

    def test_avoids_reserved_windows_names(self) -> None:
        self.assertEqual(safe_display_filename_stem("CON"), "CON_file")

    def test_display_duplicates_use_readable_numbers(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            original = Path(temporary) / "Song - Audio Mix.wav"
            original.write_bytes(b"mix")

            self.assertEqual(
                unique_display_path(original).name,
                "Song - Audio Mix (2).wav",
            )


if __name__ == "__main__":
    unittest.main()
