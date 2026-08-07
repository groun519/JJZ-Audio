from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from urllib.parse import quote

from jang_app.runtime_version import AI_RUNTIME_VERSION, RVC_RUNTIME_PROFILE_VERSIONS


MANIFEST_NAME = "latest.json"
RUNTIME_INDEX_NAME = "runtime-packages.json"
GITHUB_ASSET_LIMIT = 2 * 1024 * 1024 * 1024
GITHUB_RELEASE_DOWNLOAD_ROOT = (
    "https://github.com/groun519/JJZ-Audio/releases/download"
)
_RELEASE_TAG_PATTERN = re.compile(r"^v?(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")


def main() -> int:
    parser = argparse.ArgumentParser(description="Create the JJZero Audio release manifest.")
    parser.add_argument("release_dir", type=Path)
    parser.add_argument("version")
    parser.add_argument("--signing-publisher", default="")
    parser.add_argument("--runtime-release-tag", default="")
    arguments = parser.parse_args()
    manifest = create_release_manifest(
        arguments.release_dir,
        arguments.version,
        signing_publisher=arguments.signing_publisher,
        runtime_release_tag=arguments.runtime_release_tag,
    )
    print(f"Created release manifest: {manifest}")
    return 0


def create_release_manifest(
    release_dir: Path,
    version: str,
    runtime_version: str = AI_RUNTIME_VERSION,
    signing_publisher: str = "",
    runtime_release_tag: str = "",
) -> Path:
    resolved_release = release_dir.expanduser().resolve()
    runtime_tag = _validated_release_tag(runtime_release_tag)
    artifacts = sorted(
        path
        for path in resolved_release.glob(f"JJZero-Audio-{version}-Setup*")
        if path.is_file()
    )
    if not artifacts:
        raise FileNotFoundError(
            f"No installer artifacts were found for version {version}: {resolved_release}"
        )
    for artifact in artifacts:
        _validate_asset_size(artifact)

    components = [
        {
            "id": "application",
            "version": version,
            "install_mode": "installer",
            "artifacts": [
                _artifact_data(path, signing_publisher=signing_publisher)
                for path in artifacts
            ],
        }
    ]
    runtime_index = resolved_release / RUNTIME_INDEX_NAME
    if runtime_index.is_file():
        runtime_data = json.loads(runtime_index.read_text(encoding="utf-8"))
        if runtime_data.get("version") != runtime_version:
            raise ValueError(
                "Runtime package version does not match the release runtime version."
            )
        runtime_artifacts = runtime_data.get("artifacts")
        if not isinstance(runtime_artifacts, list) or not runtime_artifacts:
            raise ValueError("Runtime package index has no artifacts.")
        runtime_artifacts = [
            _validated_index_artifact(resolved_release, artifact)
            for artifact in runtime_artifacts
        ]
        runtime_artifacts = _with_release_urls(runtime_artifacts, runtime_tag)
        components.append(
            {
                "id": "ai-runtime",
                "version": runtime_version,
                "install_mode": "extract",
                "artifacts": runtime_artifacts,
            }
        )

    for profile, profile_version in RVC_RUNTIME_PROFILE_VERSIONS.items():
        component = f"rvc-runtime-{profile}"
        profile_index = resolved_release / f"{component}-packages.json"
        if profile_index.is_file():
            _append_component_index(
                components,
                resolved_release,
                profile_index,
                expected_component=component,
                expected_version=profile_version,
                release_tag=runtime_tag,
            )

    component_ids = {str(component.get("id", "")) for component in components}
    if "rvc-runtime-rocm-win" in component_ids and "rvc-runtime-directml" not in component_ids:
        raise ValueError("The Windows ROCm release requires a DirectML fallback component.")

    data = {
        "schema_version": 2,
        "product": "JJZero Audio",
        "version": version,
        "architecture": "x64",
        "minimum_windows": "10.0.17763",
        "disabled_features": [],
        "components": components,
    }
    manifest = resolved_release / MANIFEST_NAME
    manifest.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return manifest


def _append_component_index(
    components: list[dict[str, object]],
    release_dir: Path,
    index_path: Path,
    *,
    expected_component: str,
    expected_version: str,
    release_tag: str = "",
) -> None:
    data = json.loads(index_path.read_text(encoding="utf-8"))
    if data.get("component") != expected_component or data.get("version") != expected_version:
        raise ValueError(f"{expected_component} package index metadata does not match.")
    raw_artifacts = data.get("artifacts")
    if not isinstance(raw_artifacts, list) or not raw_artifacts:
        raise ValueError(f"{expected_component} package index has no artifacts.")
    artifacts = [
        _validated_index_artifact(release_dir, artifact)
        for artifact in raw_artifacts
    ]
    artifacts = _with_release_urls(artifacts, release_tag)
    components.append(
        {
            "id": expected_component,
            "version": expected_version,
            "install_mode": "extract",
            "artifacts": artifacts,
        }
    )


def _artifact_data(path: Path, *, signing_publisher: str = "") -> dict[str, object]:
    data: dict[str, object] = {
        "name": path.name,
        "size": path.stat().st_size,
        "sha256": _sha256(path),
    }
    if signing_publisher:
        data["authenticode"] = {
            "required": True,
            "publisher": signing_publisher,
        }
    return data


def _validated_index_artifact(
    release_dir: Path,
    data: object,
) -> dict[str, object]:
    if not isinstance(data, dict):
        raise ValueError("Runtime package artifact must be an object.")
    name = data.get("name")
    if not isinstance(name, str) or Path(name).name != name:
        raise ValueError(f"Unsafe runtime package name: {name!r}")
    package = release_dir / name
    if not package.is_file():
        raise FileNotFoundError(f"Runtime package was not found: {package}")
    _validate_asset_size(package)
    expected_size = data.get("size")
    expected_hash = data.get("sha256")
    if expected_size != package.stat().st_size or expected_hash != _sha256(package):
        raise ValueError(f"Runtime package index verification failed: {name}")
    return dict(data)


def _validate_asset_size(path: Path) -> None:
    if path.stat().st_size >= GITHUB_ASSET_LIMIT:
        raise ValueError(f"Release asset exceeds GitHub's 2 GiB limit: {path.name}")


def _validated_release_tag(value: str) -> str:
    tag = value.strip()
    if not tag:
        return ""
    if _RELEASE_TAG_PATTERN.fullmatch(tag) is None:
        raise ValueError(f"Invalid runtime release tag: {value!r}")
    return tag if tag.startswith("v") else f"v{tag}"


def _with_release_urls(
    artifacts: list[dict[str, object]],
    release_tag: str,
) -> list[dict[str, object]]:
    if not release_tag:
        return artifacts
    return [
        {
            **artifact,
            "url": (
                f"{GITHUB_RELEASE_DOWNLOAD_ROOT}/{quote(release_tag, safe='')}/"
                f"{quote(str(artifact['name']), safe='')}"
            ),
        }
        for artifact in artifacts
    ]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
