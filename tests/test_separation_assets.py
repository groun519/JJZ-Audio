from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from jang_app.services.separation_assets import (
    separation_asset_status,
    separation_recipe_asset_status,
)
from jang_app.services.separation_recipe import MAXIMUM_RECIPE


class SeparationAssetStatusTests(unittest.TestCase):
    def test_finetuned_model_requires_all_four_checkpoints(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            checkpoint_root = root / "torch" / "hub" / "checkpoints"
            checkpoint_root.mkdir(parents=True)
            (checkpoint_root / "f7e0c4bc-ba3fe64a.th").write_bytes(b"model")

            status = separation_asset_status("htdemucs_ft", root)

            self.assertFalse(status.ready)
            self.assertEqual(status.present_files, 1)
            self.assertEqual(status.required_files, 4)
            self.assertGreater(status.missing_bytes, 0)

    def test_base_model_is_ready_when_packaged_checkpoint_exists(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            checkpoint_root = root / "torch" / "hub" / "checkpoints"
            checkpoint_root.mkdir(parents=True)
            (checkpoint_root / "955717e8-8726e21a.th").write_bytes(b"model")

            self.assertTrue(separation_asset_status("htdemucs", root).ready)

    def test_maximum_recipe_requires_both_model_sets(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            checkpoint_root = root / "torch" / "hub" / "checkpoints"
            checkpoint_root.mkdir(parents=True)
            for filename in (
                "f7e0c4bc-ba3fe64a.th",
                "d12395a8-e57c48e6.th",
                "92cfc3b6-ef3bcb9c.th",
                "04573f0d-f3cf25b2.th",
            ):
                (checkpoint_root / filename).write_bytes(b"model")

            status = separation_recipe_asset_status(MAXIMUM_RECIPE, root)

            self.assertFalse(status.ready)
            self.assertEqual(status.present_files, 4)
            self.assertEqual(status.required_files, 5)
            self.assertGreater(status.missing_bytes, 0)


if __name__ == "__main__":
    unittest.main()
