from __future__ import annotations

import re
from pathlib import Path


_CHECKPOINT_PATTERN = re.compile(
    r"^(?P<kind>[GD])_(?P<step>\d+)\.pth$",
    re.IGNORECASE,
)


def checkpoint_identity(path: Path) -> tuple[str, int] | None:
    match = _CHECKPOINT_PATTERN.fullmatch(path.name)
    if match is None:
        return None
    return match.group("kind").upper(), int(match.group("step"))


def checkpoint_step(path: Path | None, expected_kind: str = "") -> int | None:
    if path is None:
        return None
    identity = checkpoint_identity(path)
    if identity is None:
        return None
    kind, step = identity
    if expected_kind and kind != expected_kind.upper():
        return None
    return step


def checkpoint_pairs(folder: Path) -> dict[int, tuple[Path, Path]]:
    generators: dict[int, Path] = {}
    discriminators: dict[int, Path] = {}
    if folder.is_dir():
        for path in folder.iterdir():
            identity = checkpoint_identity(path) if path.is_file() else None
            if identity is None:
                continue
            kind, step = identity
            target = generators if kind == "G" else discriminators
            target[step] = path.resolve()
    return {
        step: (generators[step], discriminators[step])
        for step in generators.keys() & discriminators.keys()
    }


def latest_checkpoint_pair(
    folder: Path,
) -> tuple[Path | None, Path | None, int]:
    pairs = checkpoint_pairs(folder)
    if not pairs:
        return None, None, 0
    step = max(pairs)
    generator, discriminator = pairs[step]
    return generator, discriminator, step
