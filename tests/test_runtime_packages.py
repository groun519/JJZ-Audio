from __future__ import annotations

import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from scripts.build_runtime_packages import build_component_packages, build_runtime_packages


V028_RUNTIME_REQUIRED_PATHS = (
    "ffmpeg/bin/ffmpeg.exe",
    "ffmpeg/bin/ffprobe.exe",
    "demucs/torch/hub/checkpoints/955717e8-8726e21a.th",
    "rvc/infer_cli.py",
    "rvc/runtime/python.exe",
    "rvc/hubert_base.pt",
    "rvc/rmvpe.pt",
    "rvc/configs/40k.json",
    "rvc/trainset_preprocess_pipeline_print.py",
    "rvc/extract_f0_rmvpe.py",
    "rvc/extract_feature_print.py",
    "rvc/train_nsf_sim_cache_sid_load_pretrain.py",
    "rvc/lib/jjzero_device.py",
    "rvc/lib/i18n/en_US.json",
    "rvc/lib/train/utils.py",
    "rvc/lib/infer_pack/models.py",
    "rvc/pretrained_v2/f0G40k.pth",
    "rvc/pretrained_v2/f0D40k.pth",
    "rvc/logs/mute/0_gt_wavs/mute40k.wav",
    "rvc/logs/mute/0_gt_wavs/mute40k.spec.pt",
    "rvc/logs/mute/2a_f0/mute.wav.npy",
    "rvc/logs/mute/2b-f0nsf/mute.wav.npy",
    "rvc/logs/mute/3_feature768/mute.npy",
)


class RuntimePackagesTests(unittest.TestCase):
    def test_builds_bounded_deterministic_runtime_parts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            runtime = root / "runtime"
            release = root / "release"
            (runtime / "rvc").mkdir(parents=True)
            (runtime / "rvc" / "a.bin").write_bytes(b"a" * 7)
            (runtime / "rvc" / "b.bin").write_bytes(b"b" * 6)
            (runtime / "rvc" / "runtime").mkdir()
            (runtime / "rvc" / "runtime" / "python.exe").write_bytes(b"legacy")
            (runtime / "rvc" / "__pycache__").mkdir()
            (runtime / "rvc" / "__pycache__" / "infer_cli.pyc").write_bytes(b"cache")
            (runtime / "rvc" / "web.js.map").write_bytes(b"source-map")
            (runtime / "ffmpeg.exe").write_bytes(b"f" * 5)

            index = build_runtime_packages(runtime, release, "3", part_limit=11)

            data = json.loads(index.read_text(encoding="utf-8"))
            self.assertEqual(data["version"], "3")
            self.assertTrue(data["requires_rvc_profile"])
            self.assertEqual(len(data["artifacts"]), 2)
            archived: set[str] = set()
            for artifact in data["artifacts"]:
                self.assertLessEqual(artifact["unpacked_size"], 11)
                with zipfile.ZipFile(release / artifact["name"]) as package:
                    archived.update(package.namelist())
            self.assertEqual(
                archived,
                {"ffmpeg.exe", "rvc/a.bin", "rvc/b.bin"},
            )
            self.assertNotIn("rvc/runtime/python.exe", archived)
            self.assertNotIn("rvc/__pycache__/infer_cli.pyc", archived)
            self.assertNotIn("rvc/web.js.map", archived)

    def test_builds_legacy_compatible_runtime_with_base_rvc_profile(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            runtime = root / "runtime"
            release = root / "release"
            for relative in V028_RUNTIME_REQUIRED_PATHS:
                path = runtime / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"runtime")

            index = build_runtime_packages(
                runtime,
                release,
                "3",
                part_limit=100,
                include_base_rvc_profile=True,
            )

            data = json.loads(index.read_text(encoding="utf-8"))
            self.assertFalse(data["requires_rvc_profile"])
            extracted = root / "extracted"
            for artifact in data["artifacts"]:
                with zipfile.ZipFile(release / artifact["name"]) as package:
                    package.extractall(extracted)
            self.assertTrue(
                all((extracted / relative).is_file() for relative in V028_RUNTIME_REQUIRED_PATHS)
            )

    def test_builds_named_rvc_profile_component(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            profile = root / "cu128"
            release = root / "release"
            profile.mkdir()
            (profile / "python.exe").write_bytes(b"python")
            (profile / "module" / "__pycache__").mkdir(parents=True)
            (profile / "module" / "__pycache__" / "cache.pyc").write_bytes(b"cache")
            (profile / "web.js.map").write_bytes(b"source-map")

            index = build_component_packages(
                profile,
                release,
                "2",
                component="rvc-runtime-cu128",
                package_prefix="JJZero-RVC-cu128-2",
                index_name="rvc-runtime-cu128-packages.json",
                part_limit=100,
                excluded_directory_names={"__pycache__"},
                excluded_suffixes={".map"},
            )

            data = json.loads(index.read_text(encoding="utf-8"))
            self.assertEqual(data["component"], "rvc-runtime-cu128")
            self.assertEqual(data["artifacts"][0]["name"], "JJZero-RVC-cu128-2-part01.zip")
            with zipfile.ZipFile(release / data["artifacts"][0]["name"]) as package:
                self.assertEqual(package.namelist(), ["python.exe"])


if __name__ == "__main__":
    unittest.main()
