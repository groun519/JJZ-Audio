from __future__ import annotations

import argparse
import json
import os
import subprocess
import tempfile
import zipfile
from dataclasses import replace
from pathlib import Path

from jang_app.services.app_paths import discover_app_paths
from jang_app.services.app_update import (
    parse_release_manifest,
    verify_artifact,
    verify_authenticode_signature,
)
from jang_app.services.runtime_bootstrap import provision_ai_runtime_offline
from jang_app.services.runtime_installation import (
    install_rvc_runtime_profile_packages,
    installed_rvc_runtime_profile,
)
from jang_app.services.system_diagnostics import run_system_diagnostics
from jang_app.runtime_version import RVC_RUNTIME_PROFILE_VERSIONS


GITHUB_ASSET_LIMIT = 2 * 1024 * 1024 * 1024


def verify_component_release(
    release_dir: Path,
    distribution: Path,
    *,
    install_runtime: bool,
) -> None:
    release_root = release_dir.expanduser().resolve()
    app_root = distribution.expanduser().resolve()
    manifest_path = release_root / "latest.json"
    manifest = parse_release_manifest(
        json.loads(manifest_path.read_text(encoding="utf-8")),
        "https://example.invalid/releases/latest/download/latest.json",
    )
    for component in manifest.components:
        for artifact in component.artifacts:
            path = release_root / artifact.name
            if path.stat().st_size >= GITHUB_ASSET_LIMIT:
                raise RuntimeError(f"Release asset exceeds 2 GiB: {path.name}")
            if not verify_artifact(path, artifact):
                raise RuntimeError(f"Release artifact verification failed: {path.name}")
            if artifact.signature_required and not verify_authenticode_signature(
                path,
                artifact.publisher,
            ):
                raise RuntimeError(f"Release signature verification failed: {path.name}")
    _verify_cu128_package_layout(manifest, release_root)
    _verify_accelerator_package_layouts(manifest, release_root)
    if not install_runtime:
        return

    with tempfile.TemporaryDirectory(prefix="jjzero-component-release-") as temporary:
        root = Path(temporary)
        paths = discover_app_paths(
            app_root / "_internal" / "jang_app",
            environ={"LOCALAPPDATA": str(root / "data")},
            frozen=True,
            executable=app_root / "JJZero Audio.exe",
        )
        paths = replace(
            paths,
            runtime_root=root / "runtime",
            workspace_root=root / "media" / "workspace",
            workspace_anchor=root / "media",
            output_root=root / "media" / "output",
        )
        for directory in (
            paths.data_root,
            paths.workspace_root,
            paths.output_root,
        ):
            directory.mkdir(parents=True, exist_ok=True)
        provision_ai_runtime_offline(paths, release_root / "runtime-packages.json")
        diagnostics = run_system_diagnostics(paths)
        if not diagnostics.ready:
            failed = next(check for check in diagnostics.checks if check.status == "fail")
            raise RuntimeError(f"Installed runtime diagnostics failed: {failed.title}: {failed.detail}")

        environment = os.environ.copy()
        environment.update(
            {
                "JJZERO_DATA_ROOT": str(paths.data_root),
                "JJZERO_WORKSPACE_ROOT": str(paths.workspace_root),
                "JJZERO_WORKSPACE_ANCHOR": str(paths.workspace_anchor),
                "JJZERO_RUNTIME_ROOT": str(paths.runtime_root),
                "QT_QPA_PLATFORM": "offscreen",
            }
        )
        completed = subprocess.run(
            [str(app_root / "JJZero Audio.exe"), "--startup-smoke-test"],
            cwd=app_root,
            env=environment,
            check=False,
            timeout=120,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if completed.returncode != 0:
            raise RuntimeError(
                f"App-only distribution failed with installed runtime: {completed.returncode}"
            )
        _verify_cu128_profile(manifest, release_root, paths.runtime_root)


def _verify_cu128_profile(manifest, release_root: Path, runtime_root: Path) -> None:
    component = manifest.rvc_runtime_profile("cu128")
    if component is None:
        return
    packages = tuple(release_root / artifact.name for artifact in component.artifacts)
    install_rvc_runtime_profile_packages(
        packages,
        runtime_root / "rvc",
        "cu128",
        component.version,
        activation_validator=None,
    )
    installed = installed_rvc_runtime_profile(runtime_root / "rvc")
    if installed is None or installed.profile != "cu128":
        raise RuntimeError("RVC cu128 runtime profile state was not installed.")
    script = (
        "import json, faiss, fairseq, numpy, torch, torchaudio; "
        "index=faiss.IndexFlatL2(2); "
        "print(json.dumps({'torch': torch.__version__, 'cuda': torch.version.cuda or '', "
        "'numpy': numpy.__version__, 'faiss_total': index.ntotal, "
        "'arches': list(torch.cuda.get_arch_list())}))"
    )
    completed = subprocess.run(
        [str(installed.root / "python.exe"), "-c", script],
        cwd=runtime_root / "rvc",
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if completed.returncode != 0:
        raise RuntimeError(f"RVC cu128 profile import failed: {completed.stderr.strip()}")
    data = json.loads(completed.stdout.splitlines()[-1])
    if (
        not str(data.get("torch", "")).startswith("2.7.1")
        or not str(data.get("cuda", "")).startswith("12.8")
        or data.get("numpy") != "1.23.5"
        or data.get("faiss_total") != 0
        or "sm_120" not in data.get("arches", [])
    ):
        raise RuntimeError(f"RVC cu128 profile metadata is incompatible: {data}")


def _verify_cu128_package_layout(manifest, release_root: Path) -> None:
    component = manifest.rvc_runtime_profile("cu128")
    if component is None:
        return
    required = {
        "python.exe",
        "python3.dll",
        "Lib/site-packages/torch/__init__.py",
        "Lib/site-packages/torchaudio/__init__.py",
        "Lib/site-packages/numpy/__init__.py",
        "Lib/site-packages/faiss/__init__.py",
        "Lib/site-packages/fairseq/__init__.py",
        "jjzero-profile-build.json",
    }
    found: set[str] = set()
    metadata: dict[str, object] | None = None
    for artifact in component.artifacts:
        with zipfile.ZipFile(release_root / artifact.name) as package:
            names = set(package.namelist())
            found.update(required & names)
            if "jjzero-profile-build.json" in names:
                try:
                    value = json.loads(package.read("jjzero-profile-build.json"))
                except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                    raise RuntimeError("RVC cu128 profile build metadata is invalid.") from exc
                metadata = value if isinstance(value, dict) else None
    missing = sorted(required - found)
    if missing:
        raise RuntimeError(f"RVC cu128 package is incomplete: {missing[0]}")
    if (
        metadata is None
        or metadata.get("schema_version") != 1
        or metadata.get("profile") != "cu128"
        or not str(metadata.get("torch", "")).startswith("2.7.1+cu128")
    ):
        raise RuntimeError(f"RVC cu128 profile build metadata is incompatible: {metadata}")


def _verify_accelerator_package_layouts(manifest, release_root: Path) -> None:
    for profile in ("directml", "rocm-win"):
        component = manifest.rvc_runtime_profile(profile)
        if component is None:
            continue
        required = {
            "python.exe",
            "python3.dll",
            "Lib/site-packages/torch/__init__.py",
            "Lib/site-packages/torchaudio/__init__.py",
            "Lib/site-packages/numpy/__init__.py",
            "Lib/site-packages/faiss/__init__.py",
            "Lib/site-packages/fairseq/__init__.py",
            "jjzero-profile-build.json",
        }
        if profile == "directml":
            required.update(
                {
                    "Lib/site-packages/torch_directml/__init__.py",
                    "Lib/site-packages/onnxruntime/__init__.py",
                    "Lib/site-packages/onnxruntime_directml-1.19.2.dist-info/METADATA",
                    "rmvpe.onnx",
                }
            )
        found: set[str] = set()
        metadata: dict[str, object] | None = None
        for artifact in component.artifacts:
            with zipfile.ZipFile(release_root / artifact.name) as package:
                names = set(package.namelist())
                found.update(required & names)
                if "jjzero-profile-build.json" in names:
                    try:
                        value = json.loads(package.read("jjzero-profile-build.json"))
                    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                        raise RuntimeError(
                            f"RVC {profile} profile build metadata is invalid."
                        ) from exc
                    metadata = value if isinstance(value, dict) else None
        missing = sorted(required - found)
        if missing:
            raise RuntimeError(f"RVC {profile} package is incomplete: {missing[0]}")
        if (
            metadata is None
            or metadata.get("schema_version") != 1
            or metadata.get("profile") != profile
            or component.version != RVC_RUNTIME_PROFILE_VERSIONS[profile]
            or not _accelerator_metadata_matches(profile, metadata)
        ):
            raise RuntimeError(
                f"RVC {profile} profile build metadata is incompatible: {metadata}"
            )


def _accelerator_metadata_matches(profile: str, metadata: dict[str, object]) -> bool:
    torch_version = str(metadata.get("torch", ""))
    python_version = str(metadata.get("python", ""))
    hardware_validation = str(metadata.get("hardware_validation", ""))
    operation_validation = str(metadata.get("operation_validation", ""))
    onnxruntime = str(metadata.get("onnxruntime", ""))
    if profile == "directml":
        return (
            torch_version.startswith("2.4.1 / torch-directml 0.2.5.dev240914")
            and python_version.startswith("3.9")
            and hardware_validation == "validated_at_build"
            and operation_validation == "inference_forward_and_onnx_provider"
            and onnxruntime.startswith("1.19.2 / DirectML")
        )
    return (
        torch_version.startswith("2.9.1 / ROCm 7.2.1")
        and python_version.startswith("3.12")
        and hardware_validation in {"validated_at_build", "required_on_install"}
        and operation_validation in {"gpu_forward", "required_on_install"}
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify a JJZero component release payload.")
    parser.add_argument("release_dir", type=Path)
    parser.add_argument("distribution", type=Path)
    parser.add_argument("--install-runtime", action="store_true")
    arguments = parser.parse_args()
    verify_component_release(
        arguments.release_dir,
        arguments.distribution,
        install_runtime=arguments.install_runtime,
    )
    print(f"Verified component release: {arguments.release_dir.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
