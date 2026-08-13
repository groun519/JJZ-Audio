from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path

from jang_app.services.live_text_file import LiveTextFile


class LiveTextFileTests(unittest.TestCase):
    def test_follows_appended_lines_and_flushes_partial_line(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "train.log"
            path.write_text("old\n", encoding="utf-8")
            lines: list[str] = []
            with LiveTextFile(
                path,
                path.stat().st_size,
                lines.append,
                poll_seconds=0.05,
            ):
                with path.open("a", encoding="utf-8") as output:
                    output.write("epoch 1\npartial")
                    output.flush()
                time.sleep(0.1)

            self.assertEqual(lines, ["epoch 1", "partial"])


if __name__ == "__main__":
    unittest.main()
