from __future__ import annotations

import argparse
import hashlib
import json
import zipfile
from dataclasses import dataclass
from pathlib import Path


DEFAULT_PART_LIMIT = 1700 * 1024 * 1024
GITHUB_ASSET_LIMIT = 2 * 1024 * 1024 * 1024
INDEX_NAME = "runtime-packages.json"


@dataclass(frozen=True)
class RuntimePackage:
    path: Path
    unpacked_size: int
    file_count: int


def build_runtime_packages(
    runtime_root: Path,
    release_dir: Path,
    runtime_version: str,
    *,
    part_limit: int = DEFAULT_PART_LIMIT,
) -> Path:
    source = runtime_root.expanduser().resolve()
    destination = release_dir.expanduser().resolve()
    if not source.is_dir():
        raise FileNotFoundError(f"Runtime directory was not found: {source}")
    if part_limit <= 0 or part_limit >= GITHUB_ASSET_LIMIT:
        raise ValueError("Runtime package part limit must be between 1 and 2 GiB.")
    files = sorted(
        (path for path in source.rglob("*") if path.is_file()),
        key=lambda path: path.relative_to(source).as_posix(),
    )
    if not files:
        raise FileNotFoundError(f"Runtime directory contains no files: {source}")
    oversized = [path for path in files if path.stat().st_size > part_limit]
    if oversized:
        raise ValueError(f"Runtime file exceeds the package part limit: {oversized[0]}")

    destination.mkdir(parents=True, exist_ok=True)
    groups = _group_files(files, part_limit)
    packages = [
        _write_package(source, destination, runtime_version, index, group)
        for index, group in enumerate(groups, start=1)
    ]
    data = {
        "schema_version": 1,
        "component": "ai-runtime",
        "version": runtime_version,
        "unpacked_size": sum(item.unpacked_size for item in packages),
        "artifacts": [
            {
                "name": item.path.name,
                "size": item.path.stat().st_size,
                "unpacked_size": item.unpacked_size,
                "file_count": item.file_count,
                "sha256": _sha256(item.path),
            }
            for item in packages
        ],
    }
    index_path = destination / INDEX_NAME
    index_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return index_path


def _group_files(files: list[Path], part_limit: int) -> list[list[Path]]:
    groups: list[list[Path]] = []
    sizes: list[int] = []
    for path in sorted(files, key=lambda item: (-item.stat().st_size, str(item))):
        size = path.stat().st_size
        target = next(
            (index for index, total in enumerate(sizes) if total + size <= part_limit),
            None,
        )
        if target is None:
            groups.append([path])
            sizes.append(size)
        else:
            groups[target].append(path)
            sizes[target] += size
    return groups


def _write_package(
    source: Path,
    destination: Path,
    version: str,
    index: int,
    files: list[Path],
) -> RuntimePackage:
    output = destination / f"JJZero-Runtime-{version}-part{index:02d}.zip"
    with zipfile.ZipFile(
        output,
        "w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=6,
        allowZip64=True,
    ) as archive:
        for path in sorted(files, key=lambda item: item.relative_to(source).as_posix()):
            archive.write(path, path.relative_to(source).as_posix())
    if output.stat().st_size >= GITHUB_ASSET_LIMIT:
        output.unlink()
        raise ValueError(f"Runtime package exceeds GitHub's 2 GiB asset limit: {output}")
    return RuntimePackage(
        output,
        sum(path.stat().st_size for path in files),
        len(files),
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(8 * 1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description="Build versioned JJZero AI runtime packages.")
    parser.add_argument("runtime_root", type=Path)
    parser.add_argument("release_dir", type=Path)
    parser.add_argument("runtime_version")
    parser.add_argument("--part-limit", type=int, default=DEFAULT_PART_LIMIT)
    arguments = parser.parse_args()
    index = build_runtime_packages(
        arguments.runtime_root,
        arguments.release_dir,
        arguments.runtime_version,
        part_limit=arguments.part_limit,
    )
    print(f"Created runtime package index: {index}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
