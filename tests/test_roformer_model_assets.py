from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from jang_app.services.roformer_model_assets import prepare_roformer_model_assets
from jang_app.services.separation_assets import RoFormerModelAssets, RoFormerModelFile


class RoFormerModelAssetTests(unittest.TestCase):
    def test_preparation_downloads_files_and_registers_legacy_runtime_model(self) -> None:
        assets = RoFormerModelAssets(
            model="vocal.ckpt",
            config="vocal.yaml",
            registry_name="Test Vocal Model",
            files=(
                RoFormerModelFile("vocal.ckpt", 4, "a" * 64, "https://example/model"),
                RoFormerModelFile("vocal.yaml", 3, "b" * 64, "https://example/config"),
            ),
            managed_download=True,
        )
        updates: list[int] = []

        def download(artifact, destination, **kwargs):
            target = destination / artifact.name
            target.write_bytes(b"x" * artifact.size)
            kwargs["progress"](100)
            return target

        with (
            tempfile.TemporaryDirectory() as temporary,
            patch(
                "jang_app.services.roformer_model_assets.roformer_model_assets",
                return_value=assets,
            ),
            patch(
                "jang_app.services.roformer_model_assets.download_artifact",
                side_effect=download,
            ),
        ):
            prepared = prepare_roformer_model_assets(
                assets.model,
                Path(temporary),
                updates.append,
            )
            registry = json.loads(prepared.registry.read_text(encoding="utf-8"))

        self.assertEqual([path.name for path in prepared.files], ["vocal.ckpt", "vocal.yaml"])
        self.assertEqual(
            registry["roformer_download_list"]["Test Vocal Model"],
            {"vocal.ckpt": "vocal.yaml"},
        )
        self.assertEqual(updates, sorted(updates))
        self.assertEqual(updates[-1], 100)

    def test_preparing_multiple_models_preserves_existing_registry_entries(self) -> None:
        first = RoFormerModelAssets(
            "first.ckpt",
            "first.yaml",
            "First",
            (
                RoFormerModelFile("first.ckpt", 1, "a" * 64, "https://example/first"),
                RoFormerModelFile(
                    "first.yaml",
                    1,
                    "c" * 64,
                    "https://example/first-config",
                ),
            ),
            True,
        )
        second = RoFormerModelAssets(
            "second.ckpt",
            "second.yaml",
            "Second",
            (
                RoFormerModelFile(
                    "second.ckpt",
                    1,
                    "b" * 64,
                    "https://example/second",
                ),
                RoFormerModelFile(
                    "second.yaml",
                    1,
                    "d" * 64,
                    "https://example/second-config",
                ),
            ),
            True,
        )

        def download(artifact, destination, **kwargs):
            target = destination / artifact.name
            target.write_bytes(b"x")
            kwargs["progress"](100)
            return target

        with (
            tempfile.TemporaryDirectory() as temporary,
            patch(
                "jang_app.services.roformer_model_assets.roformer_model_assets",
                side_effect=(first, second),
            ),
            patch(
                "jang_app.services.roformer_model_assets.download_artifact",
                side_effect=download,
            ),
        ):
            root = Path(temporary)
            prepare_roformer_model_assets(first.model, root)
            prepared = prepare_roformer_model_assets(second.model, root)
            registry = json.loads(prepared.registry.read_text(encoding="utf-8"))

        self.assertEqual(
            set(registry["roformer_download_list"]),
            {"First", "Second"},
        )

    def test_preparation_builds_a_runtime_compatibility_config(self) -> None:
        assets = RoFormerModelAssets(
            model="effect.ckpt",
            config="effect-runtime.yaml",
            registry_name="Effect",
            files=(
                RoFormerModelFile("effect.ckpt", 1, "a" * 64, "https://example/model"),
                RoFormerModelFile(
                    "effect-upstream.yaml",
                    11,
                    "b" * 64,
                    "https://example/config",
                ),
            ),
            managed_download=True,
            config_source="effect-upstream.yaml",
            config_replacements=(("size: 801", "size: 690"),),
        )

        def download(artifact, destination, **kwargs):
            target = destination / artifact.name
            content = b"x" if artifact.name.endswith(".ckpt") else b"size: 801\n"
            target.write_bytes(content)
            kwargs["progress"](100)
            return target

        with (
            tempfile.TemporaryDirectory() as temporary,
            patch(
                "jang_app.services.roformer_model_assets.roformer_model_assets",
                return_value=assets,
            ),
            patch(
                "jang_app.services.roformer_model_assets.download_artifact",
                side_effect=download,
            ),
        ):
            prepared = prepare_roformer_model_assets(assets.model, Path(temporary))
            registry = json.loads(prepared.registry.read_text(encoding="utf-8"))
            runtime_config = Path(temporary) / assets.config

            self.assertEqual(runtime_config.read_text(encoding="utf-8"), "size: 690\n")
            self.assertIn(runtime_config, prepared.files)
            self.assertEqual(
                registry["roformer_download_list"]["Effect"],
                {"effect.ckpt": "effect-runtime.yaml"},
            )

    def test_preparation_registers_a_configless_vr_model(self) -> None:
        assets = RoFormerModelAssets(
            model="deecho.pth",
            config="",
            registry_name="Test De-Echo",
            files=(
                RoFormerModelFile("deecho.pth", 4, "a" * 64, "https://example/model"),
            ),
            managed_download=True,
            registry_group="vr_download_list",
        )

        def download(artifact, destination, **kwargs):
            target = destination / artifact.name
            target.write_bytes(b"x" * artifact.size)
            kwargs["progress"](100)
            return target

        with (
            tempfile.TemporaryDirectory() as temporary,
            patch(
                "jang_app.services.roformer_model_assets.roformer_model_assets",
                return_value=assets,
            ),
            patch(
                "jang_app.services.roformer_model_assets.download_artifact",
                side_effect=download,
            ),
        ):
            prepared = prepare_roformer_model_assets(assets.model, Path(temporary))
            registry = json.loads(prepared.registry.read_text(encoding="utf-8"))

        self.assertEqual([path.name for path in prepared.files], ["deecho.pth"])
        self.assertEqual(
            registry["vr_download_list"]["Test De-Echo"],
            "deecho.pth",
        )


if __name__ == "__main__":
    unittest.main()
