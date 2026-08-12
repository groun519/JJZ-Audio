from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
from collections.abc import Callable, Sequence
from pathlib import Path


TORCH_VERSION = "2.7.1"
CUDA_INDEX_URL = "https://download.pytorch.org/whl/cu128"
ROFORMER_REQUIREMENTS = Path(__file__).resolve().parents[1] / "requirements-roformer-runtime.txt"
PRECISION_PACKAGE_DIRNAME = "jjzero-roformer-packages"
PRECISION_MARKER_FILE = "jjzero-precision-build.json"
PROFILE_REQUIREMENTS = (
    f"torch=={TORCH_VERSION}+cu128",
    f"torchaudio=={TORCH_VERSION}+cu128",
    "torchvision==0.22.1+cu128",
    "numpy==1.23.5",
)
REPLACED_PACKAGE_PATTERNS = (
    "torch",
    "torch-*.dist-info",
    "torchgen",
    "torchaudio",
    "torchaudio-*.dist-info",
    "torchvision",
    "torchvision-*.dist-info",
    "torch_directml",
    "torch_directml-*.dist-info",
    "functorch",
    "xformers",
    "xformers-*.dist-info",
)


CommandRunner = Callable[[Sequence[str], Path], subprocess.CompletedProcess[str]]


def prepare_cu128_profile(
    source_runtime: Path,
    destination: Path,
    *,
    install_packages: bool = True,
    command_runner: CommandRunner | None = None,
) -> Path:
    source = source_runtime.expanduser().resolve()
    target = destination.expanduser().resolve()
    if not (source / "python.exe").is_file():
        raise FileNotFoundError(f"RVC embedded Python was not found: {source}")
    if target == source or source in target.parents:
        raise ValueError("The cu128 profile destination must be outside the source runtime.")

    staging = target.with_name(f".{target.name}.preparing")
    backup = target.with_name(f".{target.name}.previous")
    _remove_tree(staging)
    shutil.copytree(
        source,
        staging,
        ignore=shutil.ignore_patterns(
            "__pycache__",
            "*.pyc",
            "*.pyo",
            *REPLACED_PACKAGE_PATTERNS,
        ),
    )
    try:
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
                        "--index-url",
                        CUDA_INDEX_URL,
                        "--extra-index-url",
                        "https://pypi.org/simple",
                        *PROFILE_REQUIREMENTS,
                    ),
                    staging,
                ),
                "Installing the RVC cu128 Torch profile",
            )
            _validate_profile(python, staging, runner)
            install_precision_packages(python, staging, runner)
        _write_build_manifest(staging)
        _swap_tree(staging, target, backup)
    except Exception:
        _remove_tree(staging)
        raise
    return target


def install_precision_packages(
    python: Path,
    runtime_root: Path,
    runner: CommandRunner | None = None,
) -> Path:
    root = runtime_root.expanduser().resolve()
    target = root / PRECISION_PACKAGE_DIRNAME
    requirements_hash = hashlib.sha256(ROFORMER_REQUIREMENTS.read_bytes()).hexdigest()
    marker = target / PRECISION_MARKER_FILE
    package = target / "audio_separator" / "__init__.py"
    if package.is_file() and _precision_marker_matches(marker, requirements_hash):
        return target

    staging = root / f".{PRECISION_PACKAGE_DIRNAME}.preparing"
    backup = root / f".{PRECISION_PACKAGE_DIRNAME}.previous"
    _remove_tree(staging)
    command_runner = runner or _run_command
    try:
        _require_success(
            command_runner(
                (
                    str(python),
                    "-m",
                    "pip",
                    "install",
                    "--disable-pip-version-check",
                    "--no-cache-dir",
                    "--no-deps",
                    "--target",
                    str(staging),
                    "-r",
                    str(ROFORMER_REQUIREMENTS),
                ),
                root,
            ),
            "Installing the precision separation runtime",
        )
        if not (staging / "audio_separator" / "__init__.py").is_file():
            raise RuntimeError("The precision separation package was not installed.")
        (staging / PRECISION_MARKER_FILE).write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "requirements_sha256": requirements_hash,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        _swap_tree(staging, target, backup)
    except Exception:
        _remove_tree(staging)
        raise
    return target


def _precision_marker_matches(marker: Path, requirements_hash: str) -> bool:
    try:
        value = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return False
    return (
        isinstance(value, dict)
        and value.get("schema_version") == 1
        and value.get("requirements_sha256") == requirements_hash
    )


def _validate_profile(python: Path, cwd: Path, runner: CommandRunner) -> None:
    script = (
        "import json, faiss, fairseq, numpy, torch, torchaudio; "
        "print(json.dumps({'torch': torch.__version__, 'torchaudio': torchaudio.__version__, "
        "'numpy': numpy.__version__, 'cuda': torch.version.cuda or '', "
        "'arches': list(torch.cuda.get_arch_list())}))"
    )
    result = runner((str(python), "-c", script), cwd)
    _require_success(result, "Validating the RVC cu128 Torch profile")
    try:
        data = json.loads(_last_line(result.stdout))
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"The RVC cu128 profile returned invalid metadata: {exc}") from exc
    if (
        not str(data.get("torch", "")).startswith(TORCH_VERSION)
        or str(data.get("numpy", "")) != "1.23.5"
        or not str(data.get("cuda", "")).startswith("12.8")
        or "sm_120" not in data.get("arches", [])
    ):
        raise RuntimeError(f"The RVC cu128 profile is incompatible: {data}")


def _write_build_manifest(root: Path) -> None:
    (root / "jjzero-profile-build.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "profile": "cu128",
                "torch": f"{TORCH_VERSION}+cu128",
                "index_url": CUDA_INDEX_URL,
            },
            indent=2,
        ),
        encoding="utf-8",
    )


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
    if result.returncode == 0:
        return
    detail = _last_line(result.stderr or result.stdout)
    raise RuntimeError(f"{operation} failed with exit code {result.returncode}: {detail}")


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
    parser = argparse.ArgumentParser(
        description="Prepare an RTX 50-series RVC cu128 runtime profile without modifying its source."
    )
    parser.add_argument(
        "source_runtime",
        type=Path,
        nargs="?",
        default=project_root / "third_party" / "rvc" / "runtime",
    )
    parser.add_argument(
        "--destination",
        type=Path,
        default=project_root / "third_party" / "rvc_profiles" / "cu128",
    )
    arguments = parser.parse_args()
    result = prepare_cu128_profile(arguments.source_runtime, arguments.destination)
    print(f"Prepared RVC cu128 profile: {result}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
