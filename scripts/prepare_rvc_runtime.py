from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from pathlib import Path

from jang_app.services.rvc_training_runtime import (
    RVC_TRAINING_ASSET_FILES,
    RVC_TRAINING_SCRIPT_FILES,
)


RUNTIME_DIRECTORIES = ("runtime", "configs", "lib")
RUNTIME_FILES = (
    *(path.name for path in RVC_TRAINING_SCRIPT_FILES),
    "infer_cli.py",
    "vc_infer_pipeline.py",
    "trainset_preprocess_pipeline_print.py",
    "hubert_base.pt",
    "rmvpe.pt",
    "LICENSE",
    "requirements.txt",
)
DIRECTML_PROFILE_ASSET_FILES = ("rmvpe.onnx",)
TRAINING_ASSET_FILES = RVC_TRAINING_ASSET_FILES
MANIFEST_FILE = "jjzero_runtime.json"
SHARED_AUDIO_REQUIREMENTS = (
    Path(__file__).resolve().parents[1] / "requirements-rvc-runtime.txt"
)
ROFORMER_REQUIREMENTS = (
    Path(__file__).resolve().parents[1] / "requirements-roformer-runtime.txt"
)
ROFORMER_PACKAGE_DIRNAME = "jjzero-roformer-packages"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Copy the RVC inference and training runtime without modifying its source folder."
    )
    parser.add_argument("source", type=Path, help="Existing RVC WebUI root")
    parser.add_argument(
        "--destination",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "third_party" / "rvc",
        help="Prepared runtime destination",
    )
    parser.add_argument(
        "--skip-demucs",
        action="store_true",
        help="Skip installing the shared Demucs packages into the copied runtime",
    )
    arguments = parser.parse_args()
    prepare_rvc_runtime(
        arguments.source,
        arguments.destination,
        install_demucs=not arguments.skip_demucs,
    )
    print(f"Prepared RVC runtime: {arguments.destination.expanduser().resolve()}")
    return 0


def prepare_rvc_runtime(
    source: Path,
    destination: Path,
    *,
    install_demucs: bool = True,
) -> Path:
    resolved_source = source.expanduser().resolve()
    resolved_destination = destination.expanduser().resolve()
    _validate_locations(resolved_source, resolved_destination)
    _validate_source(resolved_source)

    resolved_destination.mkdir(parents=True, exist_ok=True)
    for directory_name in RUNTIME_DIRECTORIES:
        shutil.copytree(
            resolved_source / directory_name,
            resolved_destination / directory_name,
            dirs_exist_ok=True,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo"),
        )
    for file_name in RUNTIME_FILES:
        shutil.copy2(resolved_source / file_name, resolved_destination / file_name)
    for relative_path in TRAINING_ASSET_FILES:
        target = resolved_destination / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(resolved_source / relative_path, target)

    directml_assets = resolved_destination.parent / "rvc_profiles" / "assets"
    directml_assets.mkdir(parents=True, exist_ok=True)
    for file_name in DIRECTML_PROFILE_ASSET_FILES:
        shutil.copy2(resolved_source / file_name, directml_assets / file_name)

    for model_directory in ("weights", "logs"):
        (resolved_destination / model_directory).mkdir(exist_ok=True)
    if install_demucs:
        _install_audio_worker_runtime(resolved_destination)
    _write_manifest(resolved_destination, resolved_source.name)
    return resolved_destination


def _validate_locations(source: Path, destination: Path) -> None:
    if not source.is_dir():
        raise FileNotFoundError(f"RVC source folder was not found: {source}")
    if destination == source or source in destination.parents:
        raise ValueError("RVC runtime destination must be outside the source folder.")


def _validate_source(source: Path) -> None:
    missing = [
        path
        for path in (
            *(source / name for name in RUNTIME_DIRECTORIES),
            *(source / name for name in RUNTIME_FILES),
            *(source / name for name in DIRECTML_PROFILE_ASSET_FILES),
            *(source / path for path in TRAINING_ASSET_FILES),
            source / "runtime" / "python.exe",
        )
        if not path.exists()
    ]
    if missing:
        formatted = "\n".join(f"- {path}" for path in missing)
        raise FileNotFoundError(f"RVC source is incomplete:\n{formatted}")


def _write_manifest(destination: Path, source_name: str) -> None:
    data = {
        "layout_version": 2,
        "source_name": source_name,
        "purpose": "JJZero Audio shared AI runtime",
        "audio_worker_requirements": SHARED_AUDIO_REQUIREMENTS.name,
        "precision_separation_requirements": ROFORMER_REQUIREMENTS.name,
        "model_storage": ["weights", "logs"],
        "training_profile": {
            "version": "v2",
            "sample_rate": 40000,
            "f0_method": "rmvpe",
        },
    }
    (destination / MANIFEST_FILE).write_text(
        json.dumps(data, indent=2),
        encoding="utf-8",
    )


def _install_audio_worker_runtime(destination: Path) -> None:
    runtime_python = destination / "runtime" / "python.exe"
    completed = subprocess.run(
        [
            str(runtime_python),
            "-m",
            "pip",
            "install",
            "--disable-pip-version-check",
            "--no-deps",
            "-r",
            str(SHARED_AUDIO_REQUIREMENTS),
        ],
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"Audio worker runtime preparation failed with exit code {completed.returncode}."
        )
    roformer_packages = destination / "runtime" / ROFORMER_PACKAGE_DIRNAME
    shutil.rmtree(roformer_packages, ignore_errors=True)
    completed = subprocess.run(
        [
            str(runtime_python),
            "-m",
            "pip",
            "install",
            "--disable-pip-version-check",
            "--no-deps",
            "--target",
            str(roformer_packages),
            "-r",
            str(ROFORMER_REQUIREMENTS),
        ],
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            "Precision separation runtime preparation failed with exit code "
            f"{completed.returncode}."
        )


if __name__ == "__main__":
    raise SystemExit(main())
