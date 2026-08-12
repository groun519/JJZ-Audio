from __future__ import annotations

import argparse
import hashlib
import json
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath


DEFAULT_PART_LIMIT = 1700 * 1024 * 1024
GITHUB_ASSET_LIMIT = 2 * 1024 * 1024 * 1024
INDEX_NAME = "runtime-packages.json"
DEFAULT_EXCLUDED_TOP_LEVEL = {"rvc_profiles"}
DEFAULT_EXCLUDED_PREFIXES = {"rvc/runtime"}
DEFAULT_EXCLUDED_DIRECTORY_NAMES = {"__pycache__"}
DEFAULT_EXCLUDED_SUFFIXES = {".map"}


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
    include_base_rvc_profile: bool = False,
) -> Path:
    return build_component_packages(
        runtime_root,
        release_dir,
        runtime_version,
        component="ai-runtime",
        package_prefix=f"JJZero-Runtime-{runtime_version}",
        index_name=INDEX_NAME,
        part_limit=part_limit,
        excluded_top_level=DEFAULT_EXCLUDED_TOP_LEVEL,
        excluded_prefixes=(
            set() if include_base_rvc_profile else DEFAULT_EXCLUDED_PREFIXES
        ),
        excluded_directory_names=DEFAULT_EXCLUDED_DIRECTORY_NAMES,
        excluded_suffixes=DEFAULT_EXCLUDED_SUFFIXES,
        metadata={"requires_rvc_profile": not include_base_rvc_profile},
    )


def build_component_packages(
    source_root: Path,
    release_dir: Path,
    version: str,
    *,
    component: str,
    package_prefix: str,
    index_name: str,
    part_limit: int = DEFAULT_PART_LIMIT,
    excluded_top_level: set[str] | None = None,
    excluded_prefixes: set[str] | None = None,
    excluded_directory_names: set[str] | None = None,
    excluded_suffixes: set[str] | None = None,
    metadata: dict[str, object] | None = None,
) -> Path:
    source = source_root.expanduser().resolve()
    destination = release_dir.expanduser().resolve()
    if not source.is_dir():
        raise FileNotFoundError(f"Runtime directory was not found: {source}")
    if part_limit <= 0 or part_limit >= GITHUB_ASSET_LIMIT:
        raise ValueError("Runtime package part limit must be between 1 and 2 GiB.")
    prefixes = tuple(
        PurePosixPath(value.replace("\\", "/"))
        for value in (excluded_prefixes or set())
    )
    directory_names = {value.casefold() for value in (excluded_directory_names or set())}
    suffixes = {value.casefold() for value in (excluded_suffixes or set())}
    files = sorted(
        (
            path
            for path in source.rglob("*")
            if path.is_file()
            and path.relative_to(source).parts[0]
            not in (excluded_top_level or set())
            and not _matches_prefix(path.relative_to(source), prefixes)
            and not _contains_directory(path.relative_to(source), directory_names)
            and path.suffix.casefold() not in suffixes
        ),
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
        _write_package(source, destination, package_prefix, index, group)
        for index, group in enumerate(groups, start=1)
    ]
    data = {
        "schema_version": 1,
        "component": component,
        "version": version,
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
    data.update(metadata or {})
    index_path = destination / index_name
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
    package_prefix: str,
    index: int,
    files: list[Path],
) -> RuntimePackage:
    output = destination / f"{package_prefix}-part{index:02d}.zip"
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
    parser.add_argument("--component", default="ai-runtime")
    parser.add_argument("--package-prefix", default="")
    parser.add_argument("--index-name", default=INDEX_NAME)
    parser.add_argument("--exclude-top-level", action="append", default=[])
    parser.add_argument("--exclude-prefix", action="append", default=[])
    parser.add_argument("--exclude-directory", action="append", default=[])
    parser.add_argument("--exclude-suffix", action="append", default=[])
    parser.add_argument("--include-base-rvc-profile", action="store_true")
    arguments = parser.parse_args()
    if arguments.component == "ai-runtime" and not arguments.package_prefix:
        index = build_runtime_packages(
            arguments.runtime_root,
            arguments.release_dir,
            arguments.runtime_version,
            part_limit=arguments.part_limit,
            include_base_rvc_profile=arguments.include_base_rvc_profile,
        )
    else:
        prefix = arguments.package_prefix or f"JJZero-{arguments.component}-{arguments.runtime_version}"
        index = build_component_packages(
            arguments.runtime_root,
            arguments.release_dir,
            arguments.runtime_version,
            component=arguments.component,
            package_prefix=prefix,
            index_name=arguments.index_name,
            part_limit=arguments.part_limit,
            excluded_top_level=set(arguments.exclude_top_level),
            excluded_prefixes=set(arguments.exclude_prefix),
            excluded_directory_names=set(arguments.exclude_directory),
            excluded_suffixes=set(arguments.exclude_suffix),
        )
    print(f"Created runtime package index: {index}")
    return 0


def _matches_prefix(path: Path, prefixes: tuple[PurePosixPath, ...]) -> bool:
    relative = PurePosixPath(path.as_posix())
    return any(relative == prefix or prefix in relative.parents for prefix in prefixes)


def _contains_directory(path: Path, names: set[str]) -> bool:
    return any(part.casefold() in names for part in path.parts[:-1])


if __name__ == "__main__":
    raise SystemExit(main())
