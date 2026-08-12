from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import urllib.request
import zipfile
from pathlib import Path

try:
    from scripts.prepare_rvc_accelerator_profile import (
        ROCM_WINDOWS_HIP_VERSION,
        ROCM_WINDOWS_TORCH_VERSION,
        is_compatible_rocm_hip_version,
        write_accelerator_profile_manifest,
    )
except ModuleNotFoundError:  # Direct execution adds scripts/, not the project root.
    from prepare_rvc_accelerator_profile import (
        ROCM_WINDOWS_HIP_VERSION,
        ROCM_WINDOWS_TORCH_VERSION,
        is_compatible_rocm_hip_version,
        write_accelerator_profile_manifest,
    )


PYTHON_VERSION = "3.12.10"
PYTHON_EMBED_URL = (
    f"https://www.python.org/ftp/python/{PYTHON_VERSION}/"
    f"python-{PYTHON_VERSION}-embed-amd64.zip"
)
GET_PIP_URL = "https://bootstrap.pypa.io/get-pip.py"
ROCM_RELEASE_ROOT = "https://repo.radeon.com/rocm/windows/rocm-rel-7.2.1"
ROCM_SDK_REQUIREMENTS = (
    f"{ROCM_RELEASE_ROOT}/rocm_sdk_core-7.2.1-py3-none-win_amd64.whl",
    f"{ROCM_RELEASE_ROOT}/rocm_sdk_devel-7.2.1-py3-none-win_amd64.whl",
    f"{ROCM_RELEASE_ROOT}/rocm_sdk_libraries_custom-7.2.1-py3-none-win_amd64.whl",
    f"{ROCM_RELEASE_ROOT}/rocm-7.2.1.tar.gz",
)
ROCM_TORCH_REQUIREMENTS = (
    f"{ROCM_RELEASE_ROOT}/torch-2.9.1%2Brocm7.2.1-cp312-cp312-win_amd64.whl",
    f"{ROCM_RELEASE_ROOT}/torchaudio-2.9.1%2Brocm7.2.1-cp312-cp312-win_amd64.whl",
    f"{ROCM_RELEASE_ROOT}/torchvision-0.24.1%2Brocm7.2.1-cp312-cp312-win_amd64.whl",
)
HYDRA_VERSION = "1.3.2"
OMEGACONF_VERSION = "2.3.0"
RVC_PYTHON_REQUIREMENTS = (
    "numpy==1.26.4",
    "scipy==1.12.0",
    "librosa==0.10.2.post1",
    "soundfile==0.12.1",
    "praat-parselmouth==0.4.4",
    "pyworld==0.3.5",
    "faiss-cpu==1.9.0.post1",
    "torchcrepe==0.0.24",
    "tensorboard==2.18.0",
    "tensorboardX==2.6.2.2",
    "matplotlib==3.9.2",
    "scikit-learn==1.5.2",
    "bitarray==3.0.0",
    "cffi==1.17.1",
    f"hydra-core=={HYDRA_VERSION}",
    f"omegaconf=={OMEGACONF_VERSION}",
    "regex==2024.11.6",
    "sacrebleu==2.4.3",
    "tqdm==4.67.1",
)
SHARED_AUDIO_REQUIREMENTS = Path(__file__).resolve().parents[1] / "requirements-rvc-runtime.txt"
ROFORMER_REQUIREMENTS = Path(__file__).resolve().parents[1] / "requirements-roformer-runtime.txt"
ROFORMER_PACKAGE_DIRNAME = "jjzero-roformer-packages"
FAIRSEQ_REQUIREMENT = "fairseq==0.12.2"
_MUTABLE_DATACLASS_DEFAULT = re.compile(
    r"^(?P<indent>\s+)(?P<name>[A-Za-z_]\w*):\s*"
    r"(?P<type>[A-Za-z_]\w*)\s*=\s*(?P=type)\(\)\s*$",
    re.MULTILINE,
)
_MUTABLE_FIELD_DEFAULT = re.compile(
    r"field\(\s*default\s*=\s*(?P<type>[A-Za-z_]\w*)\(\)\s*\)"
)


def bootstrap_rocm_windows_runtime(
    destination: Path,
    *,
    download_dir: Path,
) -> Path:
    target = destination.expanduser().resolve()
    staging = target.with_name(f".{target.name}.preparing")
    backup = target.with_name(f".{target.name}.previous")
    _remove_tree(staging)
    staging.mkdir(parents=True)
    cache = download_dir.expanduser().resolve()
    cache.mkdir(parents=True, exist_ok=True)
    try:
        archive = _download(PYTHON_EMBED_URL, cache / Path(PYTHON_EMBED_URL).name)
        with zipfile.ZipFile(archive) as package:
            package.extractall(staging)
        _enable_site_packages(staging)
        python = staging / "python.exe"
        get_pip = _download(GET_PIP_URL, cache / "get-pip.py")
        _run((str(python), str(get_pip), "pip==24.0", "setuptools==70.3.0", "wheel==0.43.0"), staging)
        _pip_install(python, staging, ROCM_SDK_REQUIREMENTS)
        _pip_install(python, staging, ROCM_TORCH_REQUIREMENTS)
        _pip_install(python, staging, ("Cython<3", *RVC_PYTHON_REQUIREMENTS))
        _pip_install(
            python,
            staging,
            _requirement_lines(SHARED_AUDIO_REQUIREMENTS),
            no_deps=True,
        )
        _pip_install(
            python,
            staging,
            _requirement_lines(ROFORMER_REQUIREMENTS),
            no_deps=True,
            target=staging / ROFORMER_PACKAGE_DIRNAME,
        )
        _pip_install(
            python,
            staging,
            (FAIRSEQ_REQUIREMENT,),
            no_deps=True,
            no_build_isolation=True,
            environment={"READTHEDOCS": "1"},
        )
        fairseq_root = staging / "Lib" / "site-packages" / "fairseq"
        _patch_fairseq_dataclasses(fairseq_root)
        _patch_fairseq_hydra_initialization(fairseq_root)
        _pip_install(python, staging, ("numpy==1.26.4",))
        _validate_static_runtime(python, staging)
        write_accelerator_profile_manifest(
            staging,
            "rocm-win",
            torch=f"{ROCM_WINDOWS_TORCH_VERSION} / ROCm {ROCM_WINDOWS_HIP_VERSION}",
            python="3.12",
            hardware_validation="required_on_install",
            operation_validation="required_on_install",
        )
        _swap_tree(staging, target, backup)
    except Exception:
        _remove_tree(staging)
        raise
    return target


def _enable_site_packages(root: Path) -> None:
    pth_files = tuple(root.glob("python312._pth"))
    if len(pth_files) != 1:
        raise RuntimeError("Python 3.12 embedded path configuration was not found.")
    path_file = pth_files[0]
    lines = [line.strip() for line in path_file.read_text(encoding="utf-8").splitlines()]
    lines = ["import site" if line == "#import site" else line for line in lines]
    if "Lib/site-packages" not in lines:
        lines.insert(-1 if "import site" in lines else len(lines), "Lib/site-packages")
    if "import site" not in lines:
        lines.append("import site")
    (root / "Lib" / "site-packages").mkdir(parents=True, exist_ok=True)
    path_file.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _requirement_lines(path: Path) -> tuple[str, ...]:
    return tuple(
        line
        for raw_line in path.read_text(encoding="utf-8").splitlines()
        if (line := raw_line.strip()) and not line.startswith("#")
    )


def _patch_fairseq_dataclasses(root: Path) -> int:
    return _patch_mutable_dataclass_defaults(root, "Fairseq")


def _patch_fairseq_hydra_initialization(root: Path) -> None:
    path = root / "dataclass" / "initialize.py"
    if not path.is_file():
        raise RuntimeError("Fairseq Hydra initialization module was not installed.")
    source = path.read_text(encoding="utf-8")
    original = (
        "    for k in FairseqConfig.__dataclass_fields__:\n"
        "        v = FairseqConfig.__dataclass_fields__[k].default\n"
        "        try:\n"
    )
    replacement = (
        "    for k, field_info in FairseqConfig.__dataclass_fields__.items():\n"
        "        v = field_info.default\n"
        "        if v is dataclasses.MISSING and field_info.default_factory is not dataclasses.MISSING:\n"
        "            v = field_info.default_factory()\n"
        "        if v is dataclasses.MISSING:\n"
        "            continue\n"
        "        try:\n"
    )
    if replacement in source:
        return
    if original not in source:
        raise RuntimeError("Fairseq Hydra initialization compatibility patch did not match.")
    source = source.replace("import logging\n", "import dataclasses\nimport logging\n", 1)
    path.write_text(source.replace(original, replacement, 1), encoding="utf-8")


def _patch_mutable_dataclass_defaults(root: Path, package_name: str) -> int:
    if not root.is_dir():
        raise RuntimeError(f"{package_name} was not installed into the ROCm runtime.")
    changed = 0
    for path in root.rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        patched, direct_count = _MUTABLE_DATACLASS_DEFAULT.subn(
            lambda match: (
                f"{match.group('indent')}{match.group('name')}: "
                f"{match.group('type')} = field(default_factory={match.group('type')})"
            ),
            source,
        )
        patched, field_count = _MUTABLE_FIELD_DEFAULT.subn(
            lambda match: f"field(default_factory={match.group('type')})",
            patched,
        )
        count = direct_count + field_count
        if not count:
            continue
        dataclass_import = re.search(r"^from dataclasses import (?P<names>.+)$", patched, re.MULTILINE)
        if dataclass_import and "field" not in {
            name.strip() for name in dataclass_import.group("names").split(",")
        }:
            patched = patched.replace(
                dataclass_import.group(0),
                f"{dataclass_import.group(0)}, field",
                1,
            )
        elif not dataclass_import:
            patched = f"from dataclasses import field\n{patched}"
        path.write_text(patched, encoding="utf-8")
        changed += count
    if not changed:
        raise RuntimeError(
            f"{package_name} Python 3.12 dataclass compatibility patch was not applied."
        )
    return changed


def _validate_static_runtime(python: Path, cwd: Path) -> None:
    probe = (
        "import json, sys, faiss, fairseq, hydra, librosa, numpy, omegaconf, parselmouth, pyworld, scipy, soundfile, torch, torchaudio; "
        "from fairseq import checkpoint_utils; "
        "print(json.dumps({'python': sys.version.split()[0], 'torch': torch.__version__, "
        "'hip': getattr(torch.version, 'hip', '') or '', 'numpy': numpy.__version__, "
        "'hydra': hydra.__version__, 'omegaconf': omegaconf.__version__}))"
    )
    result = _run((str(python), "-c", probe), cwd, capture=True)
    output = (result.stdout or "").strip().splitlines()
    if not output:
        raise RuntimeError("ROCm runtime validation returned no metadata.")
    import json

    data = json.loads(output[-1])
    if (
        not str(data.get("python", "")).startswith("3.12")
        or not str(data.get("torch", "")).startswith(ROCM_WINDOWS_TORCH_VERSION)
        or not is_compatible_rocm_hip_version(data.get("hip"))
        or data.get("numpy") != "1.26.4"
        or data.get("hydra") != HYDRA_VERSION
        or data.get("omegaconf") != OMEGACONF_VERSION
    ):
        raise RuntimeError(f"ROCm runtime metadata is incompatible: {data}")


def _pip_install(
    python: Path,
    cwd: Path,
    requirements: tuple[str, ...],
    *,
    no_deps: bool = False,
    no_build_isolation: bool = False,
    environment: dict[str, str] | None = None,
    target: Path | None = None,
) -> None:
    args = [
        str(python),
        "-m",
        "pip",
        "install",
        "--disable-pip-version-check",
        "--no-cache-dir",
    ]
    if no_deps:
        args.append("--no-deps")
    if no_build_isolation:
        args.append("--no-build-isolation")
    if target is not None:
        args.extend(("--target", str(target)))
    _run((*args, *requirements), cwd, environment=environment)


def _download(url: str, destination: Path) -> Path:
    if destination.is_file() and destination.stat().st_size > 0:
        return destination
    partial = destination.with_suffix(f"{destination.suffix}.part")
    partial.unlink(missing_ok=True)
    with urllib.request.urlopen(url, timeout=120) as response, partial.open("wb") as output:
        shutil.copyfileobj(response, output, 8 * 1024 * 1024)
    os.replace(partial, destination)
    return destination


def _run(
    args: tuple[str, ...],
    cwd: Path,
    *,
    capture: bool = False,
    environment: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    command_label = " ".join(args[1:5])
    print(f"[ROCm build] {Path(args[0]).name}: {command_label}", flush=True)
    result = subprocess.run(
        list(args),
        cwd=cwd,
        env={**os.environ, **(environment or {})},
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if result.returncode != 0:
        detail = "\n".join(
            line
            for line in (result.stdout or "", result.stderr or "")
            if line.strip()
        ).strip().splitlines()
        detail_tail = "\n".join(detail[-24:]) if detail else command_label
        raise RuntimeError(
            f"ROCm runtime command failed with exit code {result.returncode}:\n"
            f"{detail_tail}"
        )
    if not capture and result.stdout:
        summary = result.stdout.strip().splitlines()
        if summary:
            print(f"[ROCm build] {summary[-1]}", flush=True)
    return result


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
        description="Build a complete Python 3.12 RVC Windows ROCm runtime."
    )
    parser.add_argument(
        "--destination",
        type=Path,
        default=project_root / "third_party" / "rvc_profiles" / "rocm-win",
    )
    parser.add_argument(
        "--download-dir",
        type=Path,
        default=project_root / "build" / "downloads" / "rocm-win",
    )
    arguments = parser.parse_args()
    result = bootstrap_rocm_windows_runtime(
        arguments.destination,
        download_dir=arguments.download_dir,
    )
    print(f"Prepared RVC rocm-win profile: {result}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
