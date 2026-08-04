from __future__ import annotations

import json
import os
import shutil
import stat
import zipfile
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from jang_app.runtime_version import AI_RUNTIME_VERSION
from jang_app.services.managed_files import write_json_atomic
from jang_app.services.rvc_training_runtime import required_rvc_training_paths


RUNTIME_STATE_NAME = "runtime-state.json"
_PRESERVED_DIRECTORIES = (Path("rvc/weights"), Path("rvc/logs"))


class RuntimeInstallationError(RuntimeError):
    pass


@dataclass(frozen=True)
class RuntimeInstallation:
    version: str
    root: Path
    package_count: int


def installed_runtime_version(runtime_root: Path) -> str | None:
    root = runtime_root.expanduser().resolve()
    state = root / RUNTIME_STATE_NAME
    if state.is_file():
        try:
            data = json.loads(state.read_text(encoding="utf-8"))
            version = data.get("version")
            if isinstance(version, str) and version.strip() and _runtime_ready(root):
                return version.strip()
        except (OSError, json.JSONDecodeError):
            return None
    return AI_RUNTIME_VERSION if _runtime_ready(root) else None


def install_runtime_packages(
    packages: Iterable[Path],
    runtime_root: Path,
    version: str,
    *,
    progress: Callable[[int], None] | None = None,
) -> RuntimeInstallation:
    archives = tuple(path.expanduser().resolve() for path in packages)
    if not archives:
        raise RuntimeInstallationError("No AI runtime packages were provided.")
    for archive in archives:
        if not archive.is_file():
            raise RuntimeInstallationError(f"AI runtime package is missing: {archive}")

    root = runtime_root.expanduser().resolve()
    staging = root.with_name(f".{root.name}.installing")
    backup = root.with_name(f".{root.name}.previous")
    _remove_directory(staging)
    staging.mkdir(parents=True)
    total_size = _validated_unpacked_size(archives)
    extracted = 0
    try:
        for archive in archives:
            with zipfile.ZipFile(archive) as package:
                for member in package.infolist():
                    target = _safe_member_target(staging, member)
                    if member.is_dir():
                        target.mkdir(parents=True, exist_ok=True)
                        continue
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with package.open(member) as source, target.open("wb") as destination:
                        while chunk := source.read(8 * 1024 * 1024):
                            destination.write(chunk)
                            extracted += len(chunk)
                            _report(progress, int(extracted * 95 / total_size))
        _preserve_mutable_runtime_data(root, staging)
        write_json_atomic(
            staging / RUNTIME_STATE_NAME,
            {
                "schema_version": 1,
                "component": "ai-runtime",
                "version": version,
                "package_count": len(archives),
            },
        )
        if not _runtime_ready(staging):
            raise RuntimeInstallationError("The extracted AI runtime is incomplete.")
        _swap_runtime(staging, root, backup)
    except Exception:
        _remove_directory(staging)
        raise
    _report(progress, 100)
    return RuntimeInstallation(version, root, len(archives))


def _validated_unpacked_size(archives: tuple[Path, ...]) -> int:
    total = 0
    seen: set[str] = set()
    for archive in archives:
        try:
            with zipfile.ZipFile(archive) as package:
                for member in package.infolist():
                    normalized = _normalized_member_name(member)
                    if normalized in seen and not member.is_dir():
                        raise RuntimeInstallationError(
                            f"Duplicate AI runtime file: {normalized}"
                        )
                    seen.add(normalized)
                    total += member.file_size
        except zipfile.BadZipFile as exc:
            raise RuntimeInstallationError(
                f"AI runtime package is not a valid ZIP file: {archive.name}"
            ) from exc
    if total <= 0:
        raise RuntimeInstallationError("AI runtime packages contain no files.")
    return total


def _safe_member_target(staging: Path, member: zipfile.ZipInfo) -> Path:
    name = _normalized_member_name(member)
    mode = member.external_attr >> 16
    if stat.S_ISLNK(mode):
        raise RuntimeInstallationError(f"AI runtime package contains a link: {name}")
    target = (staging / Path(*PurePosixPath(name).parts)).resolve()
    if target != staging and staging not in target.parents:
        raise RuntimeInstallationError(f"Unsafe AI runtime package path: {name}")
    return target


def _normalized_member_name(member: zipfile.ZipInfo) -> str:
    name = member.filename.replace("\\", "/")
    path = PurePosixPath(name)
    if path.is_absolute() or not path.parts or any(part in {"", ".", ".."} for part in path.parts):
        raise RuntimeInstallationError(f"Unsafe AI runtime package path: {name}")
    return path.as_posix()


def _preserve_mutable_runtime_data(current: Path, staging: Path) -> None:
    if not current.is_dir():
        return
    for relative in _PRESERVED_DIRECTORIES:
        source = current / relative
        if source.is_dir():
            shutil.copytree(source, staging / relative, dirs_exist_ok=True)


def _swap_runtime(staging: Path, root: Path, backup: Path) -> None:
    _remove_directory(backup)
    moved_current = False
    try:
        if root.exists():
            os.replace(root, backup)
            moved_current = True
        os.replace(staging, root)
    except Exception:
        if moved_current and backup.exists() and not root.exists():
            os.replace(backup, root)
        raise
    _remove_directory(backup)


def _runtime_ready(root: Path) -> bool:
    rvc_root = root / "rvc"
    required = (
        root / "ffmpeg" / "bin" / "ffmpeg.exe",
        root / "ffmpeg" / "bin" / "ffprobe.exe",
        root / "demucs" / "torch" / "hub" / "checkpoints" / "955717e8-8726e21a.th",
        rvc_root / "infer_cli.py",
        rvc_root / "runtime" / "python.exe",
        rvc_root / "hubert_base.pt",
        rvc_root / "rmvpe.pt",
        *(rvc_root / path for path in required_rvc_training_paths()),
    )
    return all(path.is_file() for path in required)


def _remove_directory(path: Path) -> None:
    if path.is_dir():
        shutil.rmtree(path)


def _report(progress: Callable[[int], None] | None, value: int) -> None:
    if progress is not None:
        progress(max(0, min(value, 100)))
