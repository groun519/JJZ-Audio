from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from jang_app.services.export_catalog import list_exported_files, rename_exported_file


class ExportCatalogTests(unittest.TestCase):
    def test_multiple_patterns_include_every_supported_audio_format(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            wav = root / "master.wav"
            flac = root / "lossless.flac"
            mp3 = root / "share.mp3"
            ignored = root / "notes.txt"
            for path in (wav, flac, mp3, ignored):
                path.write_bytes(path.suffix.encode("ascii"))

            exports = list_exported_files(root, ("*.wav", "*.flac", "*.mp3"))

            self.assertEqual({item.path for item in exports}, {wav.resolve(), flac.resolve(), mp3.resolve()})

    def test_rename_preserves_extension_and_sanitizes_the_display_name(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "mix.wav"
            source.write_bytes(b"audio")

            renamed = rename_exported_file(source, "  Final: Mix.wav  ")

            self.assertEqual(renamed.name, "Final Mix.wav")
            self.assertEqual(renamed.read_bytes(), b"audio")
            self.assertFalse(source.exists())

    def test_rename_never_overwrites_an_existing_export(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "mix.wav"
            existing = root / "Final Mix.wav"
            source.write_bytes(b"source")
            existing.write_bytes(b"existing")

            renamed = rename_exported_file(source, "Final Mix")

            self.assertEqual(renamed.name, "Final Mix (2).wav")
            self.assertEqual(existing.read_bytes(), b"existing")


if __name__ == "__main__":
    unittest.main()
