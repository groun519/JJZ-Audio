from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from jang_app.services.rvc_execution_runtime import settings_for_managed_rvc_runtime
from jang_app.services.settings import RvcSettings


class RvcExecutionRuntimeTests(unittest.TestCase):
    def test_routes_execution_to_managed_runtime_and_preserves_external_model_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "external-rvc"
            managed = root / "managed-rvc"
            settings = RvcSettings(
                root=source,
                voice_model="weights/voice.pth",
                index_file="logs/voice/added.index",
            )

            routed = settings_for_managed_rvc_runtime(settings, managed)

            self.assertEqual(routed.root, managed.resolve())
            self.assertEqual(routed.voice_model, str((source / "weights/voice.pth").resolve()))
            self.assertEqual(routed.index_file, str((source / "logs/voice/added.index").resolve()))

    def test_keeps_absolute_model_paths_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            model = (root / "models" / "voice.pth").resolve()
            settings = RvcSettings(root=root / "external", voice_model=str(model))

            routed = settings_for_managed_rvc_runtime(settings, root / "managed")

            self.assertEqual(routed.voice_model, str(model))


if __name__ == "__main__":
    unittest.main()
