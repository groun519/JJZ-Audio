from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from jang_app.rvc_tools.rvc_artifact_worker import inspect_model


class RvcArtifactWorkerTests(unittest.TestCase):
    def test_model_inspection_uses_restricted_checkpoint_loading(self) -> None:
        calls: list[dict[str, object]] = []

        def load(path, **kwargs):
            calls.append({"path": path, **kwargs})
            return {
                "weight": {"emb_g.weight": object()},
                "config": [0] * 17 + [40000],
                "version": "v2",
                "sr": "40k",
                "f0": 1,
                "info": "test",
            }

        with tempfile.TemporaryDirectory() as directory:
            model = Path(directory) / "voice.pth"
            model.write_bytes(b"checkpoint")
            fake_torch = SimpleNamespace(load=load)
            with patch.dict(sys.modules, {"torch": fake_torch}):
                report = inspect_model(model)

        self.assertEqual(report["weight_count"], 1)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["map_location"], "cpu")
        self.assertIs(calls[0]["weights_only"], True)


if __name__ == "__main__":
    unittest.main()
