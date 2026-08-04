from __future__ import annotations

import argparse
import json
import os
import subprocess
import tempfile
from dataclasses import replace
from pathlib import Path

from jang_app.services.app_paths import discover_app_paths
from jang_app.services.app_update import (
    parse_release_manifest,
    verify_artifact,
    verify_authenticode_signature,
)
from jang_app.services.runtime_bootstrap import provision_ai_runtime_offline
from jang_app.services.system_diagnostics import run_system_diagnostics


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
