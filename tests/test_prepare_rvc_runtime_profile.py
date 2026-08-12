from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from scripts.prepare_rvc_runtime_profile import prepare_cu128_profile


class PrepareRvcRuntimeProfileTests(unittest.TestCase):
    def test_copies_profile_without_modifying_source(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            destination = root / "profiles" / "cu128"
            source.mkdir()
            (source / "python.exe").write_bytes(b"python")
            (source / "source.txt").write_text("original", encoding="utf-8")

            result = prepare_cu128_profile(
                source,
                destination,
                install_packages=False,
            )

            self.assertEqual(result, destination.resolve())
            self.assertEqual((source / "source.txt").read_text(encoding="utf-8"), "original")
            manifest = json.loads(
                (destination / "jjzero-profile-build.json").read_text(encoding="utf-8")
            )
            self.assertEqual(manifest["profile"], "cu128")

    def test_rejects_destination_inside_source(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "source"
            source.mkdir()
            (source / "python.exe").write_bytes(b"python")

            with self.assertRaises(ValueError):
                prepare_cu128_profile(
                    source,
                    source / "cu128",
                    install_packages=False,
                )

    def test_installs_precision_separator_for_the_profile_python(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            destination = root / "profiles" / "cu128"
            source.mkdir()
            (source / "python.exe").write_bytes(b"python")
            commands: list[tuple[str, ...]] = []

            def run(args, cwd):
                command = tuple(args)
                commands.append(command)
                if "--target" in command:
                    target = Path(command[command.index("--target") + 1])
                    package = target / "audio_separator"
                    package.mkdir(parents=True)
                    (package / "__init__.py").write_text("", encoding="utf-8")
                output = ""
                if "-c" in command:
                    output = json.dumps(
                        {
                            "torch": "2.7.1+cu128",
                            "torchaudio": "2.7.1+cu128",
                            "numpy": "1.23.5",
                            "cuda": "12.8",
                            "arches": ["sm_120"],
                        }
                    )
                return subprocess.CompletedProcess(command, 0, output, "")

            prepare_cu128_profile(
                source,
                destination,
                command_runner=run,
            )

            precision_commands = [command for command in commands if "--target" in command]
            self.assertEqual(len(precision_commands), 1)
            self.assertTrue(
                (
                    destination
                    / "jjzero-roformer-packages"
                    / "audio_separator"
                    / "__init__.py"
                ).is_file()
            )


if __name__ == "__main__":
    unittest.main()
