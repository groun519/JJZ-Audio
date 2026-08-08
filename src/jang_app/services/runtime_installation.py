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
from jang_app.services.rvc_runtime_profile import (
    RVC_PROFILE_CU118,
    normalize_rvc_profile,
)
from jang_app.services.rvc_training_runtime import required_rvc_training_paths
from jang_app.services.rvc_profile_activation import validate_rvc_profile_activation
from jang_app.services.rvc_runtime_repair import repair_rvc_runtime_adapter


RUNTIME_STATE_NAME = "runtime-state.json"
RVC_PROFILE_STATE_NAME = "jjzero-runtime-profile.json"
_PRESERVED_DIRECTORIES = (
    Path("rvc/weights"),
    Path("rvc/logs"),
    Path("demucs/torch/hub/checkpoints"),
)


class RuntimeInstallationError(RuntimeError):
    pass


@dataclass(frozen=True)
class RuntimeInstallation:
    version: str
    root: Path
    package_count: int


@dataclass(frozen=True)
class RvcRuntimeProfileInstallation:
    profile: str
    version: str
    root: Path
    package_count: int = 0
    preferred_profile: str = ""
    preferred_version: str = ""
    activation_status: str = "active"
    validation_detail: str = ""
    failed_fallback_profile: str = ""
    failed_fallback_version: str = ""


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


def installed_rvc_runtime_profile(rvc_root: Path) -> RvcRuntimeProfileInstallation | None:
    root = rvc_root.expanduser().resolve()
    runtime = root / "runtime"
    state = runtime / RVC_PROFILE_STATE_NAME
    if not state.is_file() or not (runtime / "python.exe").is_file():
        return None
    try:
        data = json.loads(state.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    profile = data.get("profile")
    version = data.get("version")
    if (
        data.get("schema_version") != 1
        or not isinstance(profile, str)
        or normalize_rvc_profile(profile) != profile
        or not isinstance(version, str)
        or not version.strip()
    ):
        return None
    preferred_profile = data.get("preferred_profile")
    preferred_version = data.get("preferred_version")
    activation_status = data.get("activation_status")
    validation_detail = data.get("validation_detail")
    failed_fallback_profile = data.get("failed_fallback_profile")
    failed_fallback_version = data.get("failed_fallback_version")
    package_count = data.get("package_count")
    return RvcRuntimeProfileInstallation(
        profile,
        version.strip(),
        runtime,
        max(0, package_count) if isinstance(package_count, int) else 0,
        normalize_rvc_profile(preferred_profile) if isinstance(preferred_profile, str) else profile,
        preferred_version.strip() if isinstance(preferred_version, str) else version.strip(),
        activation_status.strip() if isinstance(activation_status, str) else "active",
        validation_detail.strip() if isinstance(validation_detail, str) else "",
        normalize_rvc_profile(failed_fallback_profile)
        if isinstance(failed_fallback_profile, str) and failed_fallback_profile.strip()
        else "",
        failed_fallback_version.strip()
        if isinstance(failed_fallback_version, str)
        else "",
    )


def runtime_packages_unpacked_size(packages: Iterable[Path]) -> int:
    """Return the validated expanded size of one runtime package set."""
    return _validated_unpacked_size(_validated_archives(packages, "runtime"))


def install_runtime_packages(
    packages: Iterable[Path],
    runtime_root: Path,
    version: str,
    *,
    progress: Callable[[int], None] | None = None,
) -> RuntimeInstallation:
    archives = _validated_archives(packages, "audio engine")
    root = runtime_root.expanduser().resolve()

    def prepare(staging: Path) -> None:
        _preserve_mutable_runtime_data(root, staging)
        repair_rvc_runtime_adapter(staging / "rvc")
        write_json_atomic(
            staging / RUNTIME_STATE_NAME,
            {
                "schema_version": 1,
                "component": "ai-runtime",
                "version": version,
                "package_count": len(archives),
            },
        )
        _write_rvc_profile_state(
            staging / "rvc" / "runtime",
            RVC_PROFILE_CU118,
            version,
            len(archives),
        )

    _install_archive_tree(
        archives,
        root,
        prepare=prepare,
        ready=_runtime_ready,
        incomplete_message="The extracted audio engine is incomplete.",
        progress=progress,
    )
    return RuntimeInstallation(version, root, len(archives))


def install_rvc_runtime_profile_packages(
    packages: Iterable[Path],
    rvc_root: Path,
    profile: str,
    version: str,
    *,
    progress: Callable[[int], None] | None = None,
    preferred_profile: str = "",
    preferred_version: str | None = None,
    activation_status: str = "active",
    validation_detail: str = "",
    activation_validator: Callable[[str, Path], object] | None = validate_rvc_profile_activation,
) -> RvcRuntimeProfileInstallation:
    normalized = normalize_rvc_profile(profile)
    archives = _validated_archives(packages, f"RVC {normalized} runtime")
    runtime = rvc_root.expanduser().resolve() / "runtime"

    def prepare(staging: Path) -> None:
        _write_rvc_profile_state(
            staging,
            normalized,
            version,
            len(archives),
            preferred_profile=preferred_profile or normalized,
            preferred_version=version if preferred_version is None else preferred_version,
            activation_status=activation_status,
            validation_detail=validation_detail,
        )

    def ready(staging: Path) -> bool:
        if not _rvc_profile_ready(staging):
            return False
        if activation_validator is not None:
            activation_validator(normalized, staging)
        return True

    _install_archive_tree(
        archives,
        runtime,
        prepare=prepare,
        ready=ready,
        incomplete_message=f"The extracted RVC {normalized} runtime is incomplete.",
        progress=progress,
    )
    return RvcRuntimeProfileInstallation(
        normalized,
        version,
        runtime,
        len(archives),
        normalize_rvc_profile(preferred_profile or normalized),
        version if preferred_version is None else preferred_version,
        activation_status,
        validation_detail,
    )


def mark_rvc_runtime_fallback(
    rvc_root: Path,
    *,
    active_profile: str,
    active_version: str,
    preferred_profile: str,
    preferred_version: str,
    detail: str,
    failed_fallback_profile: str = "",
    failed_fallback_version: str = "",
) -> RvcRuntimeProfileInstallation:
    root = rvc_root.expanduser().resolve()
    runtime = root / "runtime"
    if not _rvc_profile_ready(runtime):
        raise RuntimeInstallationError("The base RVC runtime is unavailable for CPU fallback.")
    _write_rvc_profile_state(
        runtime,
        active_profile,
        active_version,
        0,
        preferred_profile=preferred_profile,
        preferred_version=preferred_version,
        activation_status="fallback",
        validation_detail=detail,
        failed_fallback_profile=failed_fallback_profile,
        failed_fallback_version=failed_fallback_version,
    )
    return installed_rvc_runtime_profile(root) or RvcRuntimeProfileInstallation(
        normalize_rvc_profile(active_profile),
        active_version,
        runtime,
    )


def _validated_archives(packages: Iterable[Path], label: str) -> tuple[Path, ...]:
    archives = tuple(path.expanduser().resolve() for path in packages)
    if not archives:
        raise RuntimeInstallationError(f"No {label} packages were provided.")
    for archive in archives:
        if not archive.is_file():
            raise RuntimeInstallationError(f"{label} package is missing: {archive}")
    return archives


def _install_archive_tree(
    archives: tuple[Path, ...],
    root: Path,
    *,
    prepare: Callable[[Path], None],
    ready: Callable[[Path], bool],
    incomplete_message: str,
    progress: Callable[[int], None] | None,
) -> None:
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
        prepare(staging)
        if not ready(staging):
            raise RuntimeInstallationError(incomplete_message)
        _swap_runtime(staging, root, backup)
    except Exception:
        _remove_directory(staging)
        raise
    _report(progress, 100)


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
                            f"Duplicate audio engine file: {normalized}"
                        )
                    seen.add(normalized)
                    total += member.file_size
        except zipfile.BadZipFile as exc:
            raise RuntimeInstallationError(
                f"Audio engine package is not a valid ZIP file: {archive.name}"
            ) from exc
    if total <= 0:
        raise RuntimeInstallationError("Audio engine packages contain no files.")
    return total


def _safe_member_target(staging: Path, member: zipfile.ZipInfo) -> Path:
    name = _normalized_member_name(member)
    mode = member.external_attr >> 16
    if stat.S_ISLNK(mode):
        raise RuntimeInstallationError(f"Audio engine package contains a link: {name}")
    target = (staging / Path(*PurePosixPath(name).parts)).resolve()
    if target != staging and staging not in target.parents:
        raise RuntimeInstallationError(f"Unsafe audio engine package path: {name}")
    return target


def _normalized_member_name(member: zipfile.ZipInfo) -> str:
    name = member.filename.replace("\\", "/")
    path = PurePosixPath(name)
    if path.is_absolute() or not path.parts or any(part in {"", ".", ".."} for part in path.parts):
        raise RuntimeInstallationError(f"Unsafe audio engine package path: {name}")
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


def _rvc_profile_ready(root: Path) -> bool:
    return all(
        path.is_file()
        for path in (
            root / "python.exe",
            root / "python3.dll",
            root / "Lib" / "site-packages" / "torch" / "__init__.py",
            root / "Lib" / "site-packages" / "torchaudio" / "__init__.py",
            root / RVC_PROFILE_STATE_NAME,
        )
    )


def _write_rvc_profile_state(
    runtime_root: Path,
    profile: str,
    version: str,
    package_count: int,
    *,
    preferred_profile: str = "",
    preferred_version: str | None = None,
    activation_status: str = "active",
    validation_detail: str = "",
    failed_fallback_profile: str = "",
    failed_fallback_version: str = "",
) -> None:
    active = normalize_rvc_profile(profile)
    write_json_atomic(
        runtime_root / RVC_PROFILE_STATE_NAME,
        {
            "schema_version": 1,
            "profile": active,
            "version": version,
            "package_count": package_count,
            "preferred_profile": normalize_rvc_profile(preferred_profile or active),
            "preferred_version": version if preferred_version is None else preferred_version,
            "activation_status": activation_status,
            "validation_detail": validation_detail,
            "failed_fallback_profile": (
                normalize_rvc_profile(failed_fallback_profile)
                if failed_fallback_profile
                else ""
            ),
            "failed_fallback_version": failed_fallback_version,
        },
    )


def _remove_directory(path: Path) -> None:
    if path.is_dir():
        shutil.rmtree(path)


def _report(progress: Callable[[int], None] | None, value: int) -> None:
    if progress is not None:
        progress(max(0, min(value, 100)))
