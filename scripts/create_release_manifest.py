from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


MANIFEST_NAME = "latest.json"


def main() -> int:
    parser = argparse.ArgumentParser(description="Create the JJZero Audio release manifest.")
    parser.add_argument("release_dir", type=Path)
    parser.add_argument("version")
    arguments = parser.parse_args()
    manifest = create_release_manifest(arguments.release_dir, arguments.version)
    print(f"Created release manifest: {manifest}")
    return 0


def create_release_manifest(release_dir: Path, version: str) -> Path:
    resolved_release = release_dir.expanduser().resolve()
    artifacts = sorted(
        path
        for path in resolved_release.glob(f"JJZero-Audio-{version}-Setup*")
        if path.is_file()
    )
    if not artifacts:
        raise FileNotFoundError(
            f"No installer artifacts were found for version {version}: {resolved_release}"
        )

    data = {
        "schema_version": 1,
        "product": "JJZero Audio",
        "version": version,
        "architecture": "x64",
        "minimum_windows": "10.0.17763",
        "artifacts": [
            {
                "name": path.name,
                "size": path.stat().st_size,
                "sha256": _sha256(path),
            }
            for path in artifacts
        ],
    }
    manifest = resolved_release / MANIFEST_NAME
    manifest.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return manifest


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
