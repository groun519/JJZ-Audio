from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from scripts.patch_rvc_runtime import RvcRuntimePatchError, apply_rvc_runtime_patches


class PatchRvcRuntimeTests(unittest.TestCase):
    def test_applies_tracked_overlay_once(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            runtime = root / "rvc"
            overlay = root / "overlay"
            (runtime / "lib").mkdir(parents=True)
            (overlay / "lib").mkdir(parents=True)
            (overlay / "lib" / "jjzero_device.py").write_text("ADAPTER = True\n", encoding="utf-8")
            _write_legacy_runtime(runtime)

            changed = apply_rvc_runtime_patches(runtime, overlay)
            repeated = apply_rvc_runtime_patches(runtime, overlay)

            self.assertEqual(len(changed), 5)
            self.assertEqual(repeated, ())
            self.assertEqual(
                (runtime / "lib" / "jjzero_device.py").read_text(encoding="utf-8"),
                "ADAPTER = True\n",
            )
            self.assertIn(
                "device, device_backend = resolve_torch_device(device)",
                (runtime / "infer_cli.py").read_text(encoding="utf-8"),
            )
            self.assertIn(
                'if device_backend in {"cuda", "rocm"}:',
                (runtime / "extract_feature_print.py").read_text(encoding="utf-8"),
            )
            self.assertIn(
                "resolve_torch_device(requested_device)",
                (runtime / "extract_f0_rmvpe.py").read_text(encoding="utf-8"),
            )
            self.assertIn(
                'os.environ["HIP_VISIBLE_DEVICES"]',
                (runtime / "train_nsf_sim_cache_sid_load_pretrain.py").read_text(encoding="utf-8"),
            )

    def test_rejects_unknown_upstream_layout(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            runtime = root / "rvc"
            overlay = root / "overlay"
            (runtime / "lib").mkdir(parents=True)
            (overlay / "lib").mkdir(parents=True)
            (overlay / "lib" / "jjzero_device.py").write_text("adapter\n", encoding="utf-8")
            for name in (
                "infer_cli.py",
                "extract_feature_print.py",
                "extract_f0_rmvpe.py",
                "train_nsf_sim_cache_sid_load_pretrain.py",
            ):
                (runtime / name).write_text("unsupported upstream\n", encoding="utf-8")

            with self.assertRaises(RvcRuntimePatchError):
                apply_rvc_runtime_patches(runtime, overlay)


def _write_legacy_runtime(runtime: Path) -> None:
    (runtime / "infer_cli.py").write_text(
        "from vc_infer_pipeline import VC\n"
        "if using_cli:\n"
        "    print(sys.argv)\n\n\n"
        "class Config:\n"
        "    def device_config(self):\n"
        '        if torch.cuda.is_available() and device != "cpu":\n'
        '            i_device = int(self.device.split(":")[-1])\n',
        encoding="utf-8",
    )
    (runtime / "extract_feature_print.py").write_text(
        "import fairseq\n"
        "device = sys.argv[1]\n"
        'if("privateuseone"not in device):\n'
        "    device = torch.device(device)\n"
        "else:\n"
        "    def forward_dml(ctx, x, scale):\n"
        "        return x\n"
        "    fairseq.modules.grad_multiply.GradMultiply.forward=forward_dml\n"
        '    os.environ["CUDA_VISIBLE_DEVICES"] = str(i_gpu)\n'
        'if device not in ["mps", "cpu"]:\n'
        "    model = model.half()\n",
        encoding="utf-8",
    )
    (runtime / "extract_f0_rmvpe.py").write_text(
        "i_gpu = sys.argv[3]\n"
        'os.environ["CUDA_VISIBLE_DEVICES"] = str(i_gpu)\n'
        "class FeatureInput:\n"
        "    def go(self):\n"
        '                self.model_rmvpe = RMVPE("rmvpe.pt", is_half=is_half, device="cuda")\n',
        encoding="utf-8",
    )
    (runtime / "train_nsf_sim_cache_sid_load_pretrain.py").write_text(
        'os.environ["CUDA_VISIBLE_DEVICES"] = hps.gpus.replace("-", ",")\n',
        encoding="utf-8",
    )


if __name__ == "__main__":
    unittest.main()
