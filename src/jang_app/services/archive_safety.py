from __future__ import annotations

import stat
import unicodedata
import zipfile
from dataclasses import dataclass
from pathlib import Path


MAX_ARCHIVE_MEMBERS = 100_000
MAX_ARCHIVE_FILE_SIZE = 64 * 1024**3
MAX_ARCHIVE_TOTAL_SIZE = 512 * 1024**3
MAX_ARCHIVE_COMPRESSION_RATIO = 200
MAX_ARCHIVE_MANIFEST_SIZE = 8 * 1024**2

_WINDOWS_RESERVED_NAMES = {
    "con",
    "prn",
    "aux",
    "nul",
    *(f"com{index}" for index in range(1, 10)),
    *(f"lpt{index}" for index in range(1, 10)),
}
_WINDOWS_INVALID_CHARACTERS = frozenset('<>:"|?*')


class ArchiveSafetyError(ValueError):
    """Raised when an untrusted ZIP cannot be extracted safely."""


@dataclass(frozen=True)
class ArchiveInventory:
    files: dict[str, zipfile.ZipInfo]
    total_size_bytes: int


def inspect_archive(archive: zipfile.ZipFile) -> ArchiveInventory:
    members = archive.infolist()
    if len(members) > MAX_ARCHIVE_MEMBERS:
        raise ArchiveSafetyError("The archive contains too many files.")

    files: dict[str, zipfile.ZipInfo] = {}
    destination_keys: set[str] = set()
    total_size = 0
    for member in members:
        name = normalized_archive_path(member.filename, directory=member.is_dir())
        destination_key = windows_destination_key(name)
        if destination_key in destination_keys:
            raise ArchiveSafetyError(f"The archive contains a duplicate path: {name}")
        destination_keys.add(destination_key)

        mode = member.external_attr >> 16
        if stat.S_ISLNK(mode):
            raise ArchiveSafetyError(f"The archive contains a link: {name}")
        if member.flag_bits & 0x1:
            raise ArchiveSafetyError(f"The archive contains an encrypted file: {name}")
        if member.is_dir():
            continue
        if member.file_size < 0 or member.file_size > MAX_ARCHIVE_FILE_SIZE:
            raise ArchiveSafetyError(f"The archive file is too large: {name}")
        if member.file_size and (
            member.compress_size <= 0
            or member.file_size
            > member.compress_size * MAX_ARCHIVE_COMPRESSION_RATIO
        ):
            raise ArchiveSafetyError(
                f"The archive file has an unsafe compression ratio: {name}"
            )
        total_size += member.file_size
        if total_size > MAX_ARCHIVE_TOTAL_SIZE:
            raise ArchiveSafetyError("The archive expands beyond the supported size.")
        files[name] = member
    return ArchiveInventory(files=files, total_size_bytes=total_size)


def normalized_archive_path(value: str, *, directory: bool = False) -> str:
    if not value or "\x00" in value or "\\" in value:
        raise ArchiveSafetyError("The archive contains an unsafe path.")
    candidate = value[:-1] if directory and value.endswith("/") else value
    parts = candidate.split("/")
    if not candidate or candidate.startswith("/") or any(
        part in {"", ".", ".."} for part in parts
    ):
        raise ArchiveSafetyError("The archive contains an unsafe path.")
    for part in parts:
        if part.endswith((" ", ".")) or any(
            character in _WINDOWS_INVALID_CHARACTERS for character in part
        ):
            raise ArchiveSafetyError("The archive contains an unsafe Windows path.")
        stem = part.split(".", 1)[0].casefold()
        if stem in _WINDOWS_RESERVED_NAMES:
            raise ArchiveSafetyError("The archive contains an unsafe Windows path.")
    return "/".join(parts)


def windows_destination_key(value: str) -> str:
    normalized = normalized_archive_path(value)
    return "/".join(
        unicodedata.normalize("NFC", part).casefold()
        for part in normalized.split("/")
    )


def archive_member(
    inventory: ArchiveInventory,
    path: str,
) -> tuple[str, zipfile.ZipInfo]:
    normalized = normalized_archive_path(path)
    member = inventory.files.get(normalized)
    if member is None:
        raise ArchiveSafetyError(f"The archive is missing a file: {normalized}")
    return normalized, member


def read_archive_member(
    archive: zipfile.ZipFile,
    inventory: ArchiveInventory,
    path: str,
    *,
    maximum_size: int = MAX_ARCHIVE_MANIFEST_SIZE,
) -> bytes:
    normalized, member = archive_member(inventory, path)
    if member.file_size > maximum_size:
        raise ArchiveSafetyError(f"The archive metadata is too large: {normalized}")
    with archive.open(member, "r") as source:
        payload = source.read(maximum_size + 1)
    if len(payload) > maximum_size or len(payload) != member.file_size:
        raise ArchiveSafetyError(f"The archive file size is invalid: {normalized}")
    return payload


def extraction_target(root: Path, path: str) -> Path:
    normalized = normalized_archive_path(path)
    resolved_root = root.resolve()
    target = resolved_root.joinpath(*normalized.split("/")).resolve()
    if target == resolved_root or resolved_root not in target.parents:
        raise ArchiveSafetyError("The archive contains an unsafe path.")
    return target
