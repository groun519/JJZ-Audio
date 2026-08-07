from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
from collections.abc import Callable, Sequence
from pathlib import Path

try:
    from scripts.prepare_rvc_runtime_profile import REPLACED_PACKAGE_PATTERNS
except ModuleNotFoundError:  # Direct script execution adds scripts/, not the project root.
    from prepare_rvc_runtime_profile import REPLACED_PACKAGE_PATTERNS


DIRECTML_VERSION = "0.2.5.dev240914"
DIRECTML_TORCH_VERSION = "2.4.1"
DIRECTML_ONNXRUNTIME_VERSION = "1.19.2"
DIRECTML_REQUIREMENTS = (
    f"torch-directml=={DIRECTML_VERSION}",
    f"torch=={DIRECTML_TORCH_VERSION}",
    f"torchaudio=={DIRECTML_TORCH_VERSION}",
    "torchvision==0.19.1",
    f"onnxruntime-directml=={DIRECTML_ONNXRUNTIME_VERSION}",
    "numpy==1.23.5",
)
DIRECTML_REPLACED_PACKAGE_PATTERNS = (
    "onnxruntime",
    "onnxruntime-*.dist-info",
    "onnxruntime_gpu-*.dist-info",
    "onnxruntime_directml-*.dist-info",
)
ROCM_WINDOWS_TORCH_VERSION = "2.9.1"
ROCM_WINDOWS_HIP_VERSION = "7.2.1"
ROCM_WINDOWS_HIP_SERIES = ".".join(ROCM_WINDOWS_HIP_VERSION.split(".")[:2])


def is_compatible_rocm_hip_version(value: object) -> bool:
    version = str(value or "")
    return version == ROCM_WINDOWS_HIP_SERIES or version.startswith(
        f"{ROCM_WINDOWS_HIP_SERIES}."
    )

CommandRunner = Callable[[Sequence[str], Path], subprocess.CompletedProcess[str]]


def prepare_directml_profile(
    source_runtime: Path,
    destination: Path,
    *,
    install_packages: bool = True,
    command_runner: CommandRunner | None = None,
) -> Path:
    source, target, staging, backup = _profile_paths(source_runtime, destination)
    _copy_runtime(source, staging, replace_torch=True, replace_onnxruntime=True)
    try:
        _copy_directml_rmvpe_model(source, target, staging)
        if install_packages:
            runner = command_runner or _run_command
            python = staging / "python.exe"
            _require_success(
                runner(
                    (
                        str(python),
                        "-m",
                        "pip",
                        "install",
                        "--disable-pip-version-check",
                        "--no-cache-dir",
                        "--upgrade",
                        "--force-reinstall",
                        *DIRECTML_REQUIREMENTS,
                    ),
                    staging,
                ),
                "Installing the RVC DirectML profile",
            )
            _patch_directml_staticmethod_defaults(staging)
            _validate_directml(python, staging, runner)
        write_accelerator_profile_manifest(
            staging,
            "directml",
            torch=f"{DIRECTML_TORCH_VERSION} / torch-directml {DIRECTML_VERSION}",
            python="3.9",
            hardware_validation="validated_at_build" if install_packages else "not_run",
            operation_validation=(
                "inference_forward_and_onnx_provider" if install_packages else "not_run"
            ),
            onnxruntime=f"{DIRECTML_ONNXRUNTIME_VERSION} / DirectML",
        )
        _swap_tree(staging, target, backup)
    except Exception:
        _remove_tree(staging)
        raise
    return target


def prepare_rocm_windows_profile(
    source_runtime: Path,
    destination: Path,
    *,
    validate_gpu: bool = True,
    command_runner: CommandRunner | None = None,
) -> Path:
    source, target, staging, backup = _profile_paths(source_runtime, destination)
    _copy_runtime(source, staging, replace_torch=False, replace_onnxruntime=False)
    try:
        if validate_gpu:
            _validate_rocm(staging / "python.exe", staging, command_runner or _run_command)
        write_accelerator_profile_manifest(
            staging,
            "rocm-win",
            torch=f"{ROCM_WINDOWS_TORCH_VERSION} / ROCm {ROCM_WINDOWS_HIP_VERSION}",
            python="3.12",
            hardware_validation="validated_at_build" if validate_gpu else "required_on_install",
            operation_validation="gpu_forward" if validate_gpu else "required_on_install",
        )
        _swap_tree(staging, target, backup)
    except Exception:
        _remove_tree(staging)
        raise
    return target


def _profile_paths(source_runtime: Path, destination: Path) -> tuple[Path, Path, Path, Path]:
    source = source_runtime.expanduser().resolve()
    target = destination.expanduser().resolve()
    if not (source / "python.exe").is_file():
        raise FileNotFoundError(f"RVC embedded Python was not found: {source}")
    if target == source or source in target.parents:
        raise ValueError("The profile destination must be outside the source runtime.")
    return (
        source,
        target,
        target.with_name(f".{target.name}.preparing"),
        target.with_name(f".{target.name}.previous"),
    )


def _copy_runtime(
    source: Path,
    staging: Path,
    *,
    replace_torch: bool,
    replace_onnxruntime: bool,
) -> None:
    _remove_tree(staging)
    patterns = ("__pycache__", "*.pyc", "*.pyo")
    if replace_torch:
        patterns += REPLACED_PACKAGE_PATTERNS
    if replace_onnxruntime:
        patterns += DIRECTML_REPLACED_PACKAGE_PATTERNS
    shutil.copytree(source, staging, ignore=shutil.ignore_patterns(*patterns))


def _copy_directml_rmvpe_model(source: Path, target: Path, staging: Path) -> Path:
    candidates = (
        target.parent / "assets" / "rmvpe.onnx",
        source.parent / "rmvpe.onnx",
    )
    model = next((path for path in candidates if path.is_file()), None)
    if model is None:
        raise FileNotFoundError(
            "The DirectML RMVPE model was not found. Prepare the base RVC runtime "
            "from a source containing rmvpe.onnx before building this profile."
        )
    destination = staging / "rmvpe.onnx"
    shutil.copy2(model, destination)
    return destination


def _validate_directml(python: Path, cwd: Path, runner: CommandRunner) -> None:
    script = (
        "import json; print('probe:faiss', flush=True); import faiss; "
        "print('probe:fairseq', flush=True); import fairseq; "
        "print('probe:numpy', flush=True); import numpy; "
        "print('probe:torch', flush=True); import torch; "
        "print('probe:torch_directml', flush=True); import torch_directml; "
        "print('probe:onnxruntime', flush=True); import onnxruntime as ort; "
        "providers=list(ort.get_available_providers()); "
        "rmvpe=(__import__('pathlib').Path.cwd() / 'rmvpe.onnx'); "
        "device=torch_directml.device(torch_directml.default_device()); "
        "left=torch.arange(1024, dtype=torch.float32).reshape(32, 32).to(device); "
        "conv1=torch.nn.Conv1d(4, 8, 3, padding=1).to(device); "
        "conv2=torch.nn.Conv2d(1, 4, 3, padding=1).to(device); "
        "values=(left @ left.T, conv1(torch.randn(1, 4, 128).to(device)), "
        "conv2(torch.randn(1, 1, 32, 32).to(device))); "
        "valid=all(bool(torch.isfinite(value.cpu()).all().item()) for value in values); "
        "print(json.dumps({'torch': torch.__version__, 'numpy': numpy.__version__, "
        "'device': str(device), 'valid': valid, 'providers': providers, "
        "'rmvpe_ready': rmvpe.is_file() and rmvpe.stat().st_size > 0}))"
    )
    result = runner((str(python), "-c", script), cwd)
    _require_success(result, "Validating the RVC DirectML profile")
    data = _json_result(result.stdout, "DirectML")
    if (
        not str(data.get("torch", "")).startswith(DIRECTML_TORCH_VERSION)
        or data.get("numpy") != "1.23.5"
        or not str(data.get("device", "")).startswith("privateuseone")
        or data.get("valid") is not True
        or "DmlExecutionProvider" not in data.get("providers", [])
        or data.get("rmvpe_ready") is not True
    ):
        raise RuntimeError(f"The RVC DirectML profile is incompatible: {data}")


def _patch_directml_staticmethod_defaults(root: Path) -> Path:
    target = root / "Lib" / "site-packages" / "torch_directml" / "__init__.py"
    if not target.is_file():
        target = root / "lib" / "site-packages" / "torch_directml" / "__init__.py"
    if not target.is_file():
        raise RuntimeError("The installed torch-directml package was not found.")
    source = target.read_text(encoding="utf-8")
    old = "device_id = default_device()"
    new = "device_id = torch_directml_native.get_default_device()"
    count = source.count(old)
    if count not in {0, 2}:
        raise RuntimeError(f"Unexpected torch-directml staticmethod layout: {count}")
    if count:
        target.write_text(source.replace(old, new), encoding="utf-8")
    return target


def _validate_rocm(python: Path, cwd: Path, runner: CommandRunner) -> None:
    script = (
        "import json, sys, faiss, fairseq, torch, torchaudio; "
        "available=torch.cuda.is_available(); "
        "left=torch.arange(1024, dtype=torch.float32, device='cuda:0').reshape(32, 32) if available else torch.zeros(1); "
        "conv1=torch.nn.Conv1d(4, 8, 3, padding=1).to('cuda:0') if available else None; "
        "conv2=torch.nn.Conv2d(1, 4, 3, padding=1).to('cuda:0') if available else None; "
        "values=(left @ left.T, conv1(torch.randn(1, 4, 128, device='cuda:0')), "
        "conv2(torch.randn(1, 1, 32, 32, device='cuda:0'))) if available else (); "
        "loss=(values[1].square().mean() + values[2].square().mean()) if available else torch.tensor(float('nan')); "
        "torch.cuda.synchronize(0) if available else None; "
        "valid=(bool(torch.isfinite(loss).item()) and all(bool(torch.isfinite(value).all().item()) for value in values)) if available else False; "
        "print(json.dumps({'python': sys.version.split()[0], 'torch': torch.__version__, "
        "'hip': getattr(torch.version, 'hip', '') or '', 'available': available, "
        "'valid': valid}))"
    )
    result = runner((str(python), "-c", script), cwd)
    _require_success(result, "Validating the RVC Windows ROCm profile")
    data = _json_result(result.stdout, "Windows ROCm")
    if (
        not str(data.get("python", "")).startswith("3.12")
        or not str(data.get("torch", "")).startswith(ROCM_WINDOWS_TORCH_VERSION)
        or not is_compatible_rocm_hip_version(data.get("hip"))
        or data.get("available") is not True
        or data.get("valid") is not True
    ):
        raise RuntimeError(f"The RVC Windows ROCm profile is incompatible: {data}")


def write_accelerator_profile_manifest(
    root: Path,
    profile: str,
    *,
    torch: str,
    python: str,
    hardware_validation: str,
    operation_validation: str,
    onnxruntime: str = "",
) -> None:
    (root / "jjzero-profile-build.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "profile": profile,
                "torch": torch,
                "python": python,
                "hardware_validation": hardware_validation,
                "operation_validation": operation_validation,
                "onnxruntime": onnxruntime,
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def _json_result(output: str, label: str) -> dict[str, object]:
    try:
        data = json.loads(_last_line(output))
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"The RVC {label} profile returned invalid metadata: {exc}") from exc
    if not isinstance(data, dict):
        raise RuntimeError(f"The RVC {label} profile returned invalid metadata.")
    return data


def _run_command(args: Sequence[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(args),
        cwd=cwd,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )


def _require_success(result: subprocess.CompletedProcess[str], operation: str) -> None:
    if result.returncode != 0:
        output = "\n".join(
            line.rstrip()
            for line in (result.stderr or result.stdout).splitlines()[-24:]
            if line.strip()
        )
        raise RuntimeError(
            f"{operation} failed with exit code {result.returncode}: "
            f"{output or 'No process output'}"
        )


def _last_line(value: str) -> str:
    lines = [line.strip() for line in value.splitlines() if line.strip()]
    return lines[-1] if lines else "No process output"


def _swap_tree(staging: Path, target: Path, backup: Path) -> None:
    _remove_tree(backup)
    moved = False
    try:
        if target.exists():
            os.replace(target, backup)
            moved = True
        os.replace(staging, target)
    except Exception:
        if moved and backup.exists() and not target.exists():
            os.replace(backup, target)
        raise
    _remove_tree(backup)


def _remove_tree(path: Path) -> None:
    if path.is_dir():
        shutil.rmtree(path)


def main() -> int:
    project_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description="Prepare an RVC accelerator runtime profile.")
    parser.add_argument("profile", choices=("directml", "rocm-win"))
    parser.add_argument("source_runtime", type=Path)
    parser.add_argument("--destination", type=Path)
    parser.add_argument(
        "--cross-build",
        action="store_true",
        help="Package ROCm without a local AMD GPU; activation remains mandatory on the target PC.",
    )
    arguments = parser.parse_args()
    destination = arguments.destination or (
        project_root / "third_party" / "rvc_profiles" / arguments.profile
    )
    if arguments.profile == "directml":
        result = prepare_directml_profile(arguments.source_runtime, destination)
    else:
        result = prepare_rocm_windows_profile(
            arguments.source_runtime,
            destination,
            validate_gpu=not arguments.cross_build,
        )
    print(f"Prepared RVC {arguments.profile} profile: {result}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
