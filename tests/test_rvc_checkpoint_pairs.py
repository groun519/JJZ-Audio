from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from jang_app.services.rvc_checkpoint_pairs import (
    checkpoint_identity,
    checkpoint_pairs,
    latest_checkpoint_pair,
)


class RvcCheckpointPairTests(unittest.TestCase):
    def test_latest_pair_uses_numeric_common_generation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name in (
                "G_9.pth",
                "D_9.pth",
                "G_100.pth",
                "D_100.pth",
                "G_200.pth",
                "D_150.pth",
            ):
                (root / name).write_bytes(name.encode())

            pairs = checkpoint_pairs(root)
            generator, discriminator, step = latest_checkpoint_pair(root)

            self.assertEqual(set(pairs), {9, 100})
            self.assertEqual(step, 100)
            self.assertEqual(generator.name, "G_100.pth")
            self.assertEqual(discriminator.name, "D_100.pth")

    def test_checkpoint_identity_rejects_similar_non_checkpoint_names(self) -> None:
        self.assertEqual(checkpoint_identity(Path("g_12.PTH")), ("G", 12))
        self.assertIsNone(checkpoint_identity(Path("G_latest.pth")))
        self.assertIsNone(checkpoint_identity(Path("G_12.pth.partial")))


if __name__ == "__main__":
    unittest.main()
