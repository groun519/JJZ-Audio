from __future__ import annotations

import hashlib
import re
import secrets
import tempfile
from pathlib import Path

from jang_app.services.managed_files import link_or_copy_file


_KEY_PATTERN = re.compile(r"^[a-z][a-z0-9]*$")


def stable_storage_key(prefix: str, identity: str, *, length: int = 16) -> str:
    """Return a short, stable disk key without exposing a display name."""
    _validate_key_options(prefix, length)
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:length]
    return f"{prefix}_{digest}"


def new_storage_key(prefix: str, *, length: int = 12) -> str:
    """Return a collision-resistant key for a new run or take."""
    _validate_key_options(prefix, length)
    return f"{prefix}_{secrets.token_hex((length + 1) // 2)[:length]}"


class ToolWorkspace:
    """Short-lived, short-path workspace for native and bundled tools."""

    def __init__(self, base_dir: Path, tool: str) -> None:
        if not _KEY_PATTERN.fullmatch(tool):
            raise ValueError(f"Invalid tool workspace name: {tool}")
        self._base_dir = base_dir.expanduser().resolve() / tool
        self._temporary: tempfile.TemporaryDirectory[str] | None = None
        self.root = Path()

    def __enter__(self) -> ToolWorkspace:
        self._base_dir.mkdir(parents=True, exist_ok=True)
        self._temporary = tempfile.TemporaryDirectory(prefix="j_", dir=self._base_dir)
        self.root = Path(self._temporary.name)
        return self

    def __exit__(self, _exc_type, _exc, _traceback) -> None:
        if self._temporary is not None:
            self._temporary.cleanup()
        self._temporary = None
        self.root = Path()

    @property
    def output_dir(self) -> Path:
        self._require_open()
        target = self.root / "o"
        target.mkdir(parents=True, exist_ok=True)
        return target

    def stage_input(self, source: Path) -> Path:
        suffix = source.suffix.casefold() or ".bin"
        return self.stage_file(source, f"i{suffix}")

    def stage_file(self, source: Path, name: str) -> Path:
        self._require_open()
        if Path(name).name != name:
            raise ValueError("Staged file name must not contain a directory")
        target = self.root / name
        return link_or_copy_file(source, target)

    def publish_file(self, source: Path, target: Path) -> Path:
        self._require_open()
        return link_or_copy_file(source, target)

    def _require_open(self) -> None:
        if self._temporary is None:
            raise RuntimeError("Tool workspace is not open")


def _validate_key_options(prefix: str, length: int) -> None:
    if not _KEY_PATTERN.fullmatch(prefix):
        raise ValueError(f"Invalid storage key prefix: {prefix}")
    if not 8 <= length <= 32:
        raise ValueError("Storage key length must be between 8 and 32")
