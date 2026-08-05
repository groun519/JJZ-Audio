from __future__ import annotations

import argparse
import shutil
from pathlib import Path


class RvcRuntimePatchError(RuntimeError):
    pass


def apply_rvc_runtime_patches(rvc_root: Path, overlay_root: Path) -> tuple[Path, ...]:
    root = rvc_root.expanduser().resolve()
    overlay = overlay_root.expanduser().resolve()
    if not root.is_dir():
        raise FileNotFoundError(f"RVC runtime root was not found: {root}")
    adapter = overlay / "lib" / "jjzero_device.py"
    if not adapter.is_file():
        raise FileNotFoundError(f"RVC overlay adapter was not found: {adapter}")

    changed: list[Path] = []
    target_adapter = root / "lib" / "jjzero_device.py"
    target_adapter.parent.mkdir(parents=True, exist_ok=True)
    if not target_adapter.is_file() or target_adapter.read_bytes() != adapter.read_bytes():
        shutil.copy2(adapter, target_adapter)
        changed.append(target_adapter)

    transformations = {
        "infer_cli.py": _patch_infer_cli,
        "extract_feature_print.py": _patch_feature_extraction,
        "extract_f0_rmvpe.py": _patch_rmvpe_extraction,
        "train_nsf_sim_cache_sid_load_pretrain.py": _patch_training_visibility,
    }
    for name, patcher in transformations.items():
        path = root / name
        if not path.is_file():
            raise FileNotFoundError(f"Required RVC script was not found: {path}")
        source = path.read_text(encoding="utf-8")
        patched = patcher(source)
        if patched != source:
            path.write_text(patched, encoding="utf-8")
            changed.append(path)
    return tuple(changed)


def _patch_infer_cli(source: str) -> str:
    if "from lib.jjzero_device import resolve_torch_device" not in source:
        source = _replace_once(
            source,
            "from vc_infer_pipeline import VC\n",
            "from vc_infer_pipeline import VC\nfrom lib.jjzero_device import resolve_torch_device\n",
            "infer_cli device import",
        )
    if "device, device_backend = resolve_torch_device(device)" not in source:
        source = _replace_once(
            source,
            "    print(sys.argv)\n\n\nclass Config:",
            "    print(sys.argv)\n\ndevice, device_backend = resolve_torch_device(device)\n\n\nclass Config:",
            "infer_cli device resolution",
        )
    if 'if device_backend == "directml":' not in source:
        source = _replace_once(
            source,
            '        if torch.cuda.is_available() and device != "cpu":\n'
            '            i_device = int(self.device.split(":")[-1])',
            '        if device_backend == "directml":\n'
            '            self.device = device\n'
            '            self.is_half = False\n'
            '        elif torch.cuda.is_available() and device != "cpu":\n'
            '            i_device = int(str(self.device).split(":")[-1])',
            "infer_cli DirectML branch",
        )
    return source


def _patch_feature_extraction(source: str) -> str:
    if "from lib.jjzero_device import resolve_torch_device" not in source:
        source = _replace_once(
            source,
            "import fairseq\n",
            "import fairseq\nfrom lib.jjzero_device import resolve_torch_device\n",
            "feature device import",
        )
    if "device, device_backend = resolve_torch_device(device)" not in source:
        start = source.find('if("privateuseone"not in device):')
        end_marker = "    fairseq.modules.grad_multiply.GradMultiply.forward=forward_dml\n"
        end = source.find(end_marker, start)
        if start < 0 or end < 0:
            raise RvcRuntimePatchError("Could not locate the legacy DirectML feature block.")
        end += len(end_marker)
        source = source[:start] + "device, device_backend = resolve_torch_device(device)\n" + source[end:]
    source = source.replace(
        'if device not in ["mps", "cpu"]:',
        'if device_backend in {"cuda", "rocm"}:',
    ).replace(
        'if device not in ["mps", "cpu"]\n',
        'if device_backend in {"cuda", "rocm"}\n',
    )
    if 'os.environ["HIP_VISIBLE_DEVICES"]' not in source:
        source = _replace_once(
            source,
            '    os.environ["CUDA_VISIBLE_DEVICES"] = str(i_gpu)\n',
            '    os.environ["CUDA_VISIBLE_DEVICES"] = str(i_gpu)\n'
            '    os.environ["HIP_VISIBLE_DEVICES"] = str(i_gpu)\n',
            "feature HIP visibility",
        )
    return source


def _patch_rmvpe_extraction(source: str) -> str:
    if "requested_device = sys.argv[3]" not in source:
        source = _replace_once(
            source,
            'i_gpu = sys.argv[3]\nos.environ["CUDA_VISIBLE_DEVICES"] = str(i_gpu)\n',
            'requested_device = sys.argv[3]\n'
            'if requested_device.isdigit():\n'
            '    requested_device = f"cuda:{requested_device}"\n'
            'if requested_device.startswith("cuda"):\n'
            '    visible_device = requested_device.split(":")[-1]\n'
            '    os.environ["CUDA_VISIBLE_DEVICES"] = visible_device\n'
            '    os.environ["HIP_VISIBLE_DEVICES"] = visible_device\n',
            "RMVPE device argument",
        )
    if "resolve_torch_device(requested_device)" not in source:
        source = _replace_once(
            source,
            '                self.model_rmvpe = RMVPE("rmvpe.pt", is_half=is_half, device="cuda")',
            '                from lib.jjzero_device import resolve_torch_device\n\n'
            '                device, backend = resolve_torch_device(requested_device)\n'
            '                self.model_rmvpe = RMVPE(\n'
            '                    "rmvpe.pt",\n'
            '                    is_half=is_half if backend in {"cuda", "rocm"} else False,\n'
            '                    device=device,\n'
            '                )',
            "RMVPE backend resolution",
        )
    return source


def _patch_training_visibility(source: str) -> str:
    if 'os.environ["HIP_VISIBLE_DEVICES"]' in source:
        return source
    return _replace_once(
        source,
        'os.environ["CUDA_VISIBLE_DEVICES"] = hps.gpus.replace("-", ",")\n',
        'os.environ["CUDA_VISIBLE_DEVICES"] = hps.gpus.replace("-", ",")\n'
        'os.environ["HIP_VISIBLE_DEVICES"] = hps.gpus.replace("-", ",")\n',
        "training HIP visibility",
    )


def _replace_once(source: str, old: str, new: str, label: str) -> str:
    if old not in source:
        raise RvcRuntimePatchError(f"Could not apply {label}; upstream RVC source changed.")
    return source.replace(old, new, 1)


def main() -> int:
    project_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description="Apply tracked JJZero patches to an RVC runtime copy.")
    parser.add_argument(
        "rvc_root",
        type=Path,
        nargs="?",
        default=project_root / "third_party" / "rvc",
    )
    parser.add_argument(
        "--overlay-root",
        type=Path,
        default=project_root / "packaging" / "rvc_overlay",
    )
    arguments = parser.parse_args()
    changed = apply_rvc_runtime_patches(arguments.rvc_root, arguments.overlay_root)
    print(f"RVC runtime patch complete: {len(changed)} file(s) updated")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
