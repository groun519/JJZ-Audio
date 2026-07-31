from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class OutputSoundSet:
    label: str
    job_dir: Path
    vocals_path: Path
    instrumental_path: Path
    converted_vocal_paths: tuple[Path, ...]


def scan_output_sound_sets(output_root: Path) -> list[OutputSoundSet]:
    root = output_root.expanduser().resolve()
    if not root.exists():
        return []

    sound_sets = [
        sound_set
        for sound_set in (_load_output_sound_set(job_dir, root) for job_dir in _candidate_job_dirs(root))
        if sound_set is not None
    ]
    return sorted(sound_sets, key=lambda sound_set: _latest_mtime(sound_set.job_dir), reverse=True)


def load_output_sound_set(job_dir: Path, output_root: Path) -> OutputSoundSet | None:
    return _load_output_sound_set(job_dir.expanduser().resolve(), output_root.expanduser().resolve())


def _candidate_job_dirs(root: Path) -> list[Path]:
    return [
        path
        for path in root.rglob("*")
        if path.is_dir() and path.name != "exports" and (path / "vocals.wav").is_file() and (path / "no_vocals.wav").is_file()
    ]


def _load_output_sound_set(job_dir: Path, output_root: Path) -> OutputSoundSet | None:
    vocals_path = job_dir / "vocals.wav"
    instrumental_path = job_dir / "no_vocals.wav"
    if not vocals_path.is_file() or not instrumental_path.is_file():
        return None

    converted_paths = tuple(
        sorted(
            job_dir.glob("vocals_rvc*.wav"),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
    )
    return OutputSoundSet(
        label=_relative_label(job_dir, output_root),
        job_dir=job_dir,
        vocals_path=vocals_path,
        instrumental_path=instrumental_path,
        converted_vocal_paths=converted_paths,
    )


def _relative_label(job_dir: Path, output_root: Path) -> str:
    try:
        return str(job_dir.relative_to(output_root))
    except ValueError:
        return str(job_dir)


def _latest_mtime(job_dir: Path) -> float:
    files = [path for path in job_dir.glob("*.wav") if path.is_file()]
    if not files:
        return job_dir.stat().st_mtime
    return max(path.stat().st_mtime for path in files)
