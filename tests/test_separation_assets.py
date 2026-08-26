from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from jang_app.services.separation_assets import (
    RoFormerModelAssets,
    RoFormerModelFile,
    record_roformer_model_files_verified,
    separation_asset_status,
    separation_recipe_asset_status,
)
from jang_app.services.separation_recipe import (
    EFFECT_REMOVAL_RECIPE,
    MAXIMUM_RECIPE,
    PRECISION_RECIPE,
    VOCAL_MELBAND_RECIPE,
)


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

    def test_precision_recipe_tracks_roformer_checkpoint_and_config(self) -> None:
        model_payload = b"model"
        config_payload = b"cfg"
        assets = RoFormerModelAssets(
            PRECISION_RECIPE.model,
            "precision.yaml",
            "Precision",
            (
                RoFormerModelFile(
                    PRECISION_RECIPE.model,
                    len(model_payload),
                    hashlib.sha256(model_payload).hexdigest(),
                    "https://example/model",
                ),
                RoFormerModelFile(
                    "precision.yaml",
                    len(config_payload),
                    hashlib.sha256(config_payload).hexdigest(),
                    "https://example/config",
                ),
            ),
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            model_root = root / "models"
            model_root.mkdir(parents=True)
            (model_root / PRECISION_RECIPE.model).write_bytes(model_payload)

            with patch.dict(
                "jang_app.services.separation_assets._ROFORMER_MODEL_ASSETS",
                {PRECISION_RECIPE.model: assets},
                clear=False,
            ):
                status = separation_recipe_asset_status(PRECISION_RECIPE, root)

            self.assertFalse(status.ready)
            self.assertEqual(status.present_files, 0)
            self.assertEqual(status.required_files, 2)
            self.assertEqual(status.missing_bytes, len(config_payload))
            self.assertEqual(status.verification_required_files, 1)

    def test_vocal_melband_recipe_reports_its_first_use_download(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            status = separation_recipe_asset_status(
                VOCAL_MELBAND_RECIPE,
                Path(temporary),
            )

            self.assertFalse(status.ready)
            self.assertEqual(status.required_files, 2)
            self.assertEqual(status.missing_bytes, 913_107_868)

    def test_effect_removal_recipe_requires_both_roformer_stages(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            status = separation_recipe_asset_status(
                EFFECT_REMOVAL_RECIPE,
                Path(temporary),
            )

            self.assertFalse(status.ready)
            self.assertEqual(status.required_files, 4)
            self.assertEqual(status.missing_bytes, 1_083_881_045)

    def test_same_size_corrupt_roformer_model_is_not_ready(self) -> None:
        good = b"GOOD"
        asset = RoFormerModelFile(
            "test.ckpt",
            len(good),
            hashlib.sha256(good).hexdigest(),
            "https://example/test.ckpt",
        )
        assets = RoFormerModelAssets(
            "test.ckpt",
            "",
            "Test",
            (asset,),
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            model_root = root / "models"
            model_root.mkdir()
            (model_root / asset.filename).write_bytes(b"BADD")
            with patch.dict(
                "jang_app.services.separation_assets._ROFORMER_MODEL_ASSETS",
                {assets.model: assets},
                clear=False,
            ):
                status = separation_asset_status(assets.model, root)

        self.assertFalse(status.ready)
        self.assertEqual(status.present_files, 0)
        self.assertEqual(status.missing_bytes, 0)
        self.assertEqual(status.verification_required_files, 1)

    def test_verified_roformer_status_uses_integrity_record_without_rehashing(self) -> None:
        payload = b"GOOD"
        asset = RoFormerModelFile(
            "test.ckpt",
            len(payload),
            hashlib.sha256(payload).hexdigest(),
            "https://example/test.ckpt",
        )
        assets = RoFormerModelAssets("test.ckpt", "", "Test", (asset,))
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            model_root = root / "models"
            model_root.mkdir()
            (model_root / asset.filename).write_bytes(payload)
            record_roformer_model_files_verified(model_root, assets.files)
            with (
                patch.dict(
                    "jang_app.services.separation_assets._ROFORMER_MODEL_ASSETS",
                    {assets.model: assets},
                    clear=False,
                ),
                patch(
                    "jang_app.services.separation_assets.file_sha256",
                    side_effect=AssertionError("status must not hash model files"),
                ),
            ):
                status = separation_asset_status(assets.model, root)

        self.assertTrue(status.ready)
        self.assertEqual(status.verification_required_files, 0)


if __name__ == "__main__":
    unittest.main()
