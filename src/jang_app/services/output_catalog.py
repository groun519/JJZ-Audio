from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path


_CONVERTED_VOCAL_PREFIXES = ("vocals_rvc", "rvc_")


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

    discovered: list[tuple[float, OutputSoundSet]] = []
    for job_dir in _candidate_job_dirs(root):
        wav_files = _job_wav_files(job_dir)
        sound_set = _load_output_sound_set(job_dir, root, wav_files)
        if sound_set is not None:
            discovered.append((_latest_mtime(job_dir, wav_files), sound_set))
    ordered = sorted(discovered, key=lambda item: item[0], reverse=True)
    return [sound_set for _mtime, sound_set in ordered]


def load_output_sound_set(job_dir: Path, output_root: Path) -> OutputSoundSet | None:
    return _load_output_sound_set(job_dir.expanduser().resolve(), output_root.expanduser().resolve())


def converted_vocal_paths(job_dir: Path) -> tuple[Path, ...]:
    root = job_dir.expanduser().resolve()
    return _converted_vocal_paths(_job_wav_files(root))


def _candidate_job_dirs(root: Path) -> Iterator[Path]:
    for vocals_path in root.rglob("vocals.wav"):
        job_dir = vocals_path.parent
        if (
            vocals_path.is_file()
            and job_dir.name != "exports"
            and (job_dir / "no_vocals.wav").is_file()
        ):
            yield job_dir


def _load_output_sound_set(
    job_dir: Path,
    output_root: Path,
    wav_files: tuple[Path, ...] | None = None,
) -> OutputSoundSet | None:
    vocals_path = job_dir / "vocals.wav"
    instrumental_path = job_dir / "no_vocals.wav"
    if not vocals_path.is_file() or not instrumental_path.is_file():
        return None

    files = wav_files if wav_files is not None else _job_wav_files(job_dir)
    return OutputSoundSet(
        label=_relative_label(job_dir, output_root),
        job_dir=job_dir,
        vocals_path=vocals_path,
        instrumental_path=instrumental_path,
        converted_vocal_paths=_converted_vocal_paths(files),
    )


def _relative_label(job_dir: Path, output_root: Path) -> str:
    try:
        return str(job_dir.relative_to(output_root))
    except ValueError:
        return str(job_dir)


def _job_wav_files(job_dir: Path) -> tuple[Path, ...]:
    return tuple(path for path in job_dir.glob("*.wav") if path.is_file())


def _converted_vocal_paths(wav_files: tuple[Path, ...]) -> tuple[Path, ...]:
    converted = (
        path.resolve()
        for path in wav_files
        if _is_converted_vocal_path(path)
    )
    return tuple(sorted(converted, key=_path_mtime, reverse=True))


def _is_converted_vocal_path(path: Path) -> bool:
    name = path.name.casefold()
    return name.startswith(_CONVERTED_VOCAL_PREFIXES) or "_rvc_" in path.stem.casefold()


def _latest_mtime(job_dir: Path, wav_files: tuple[Path, ...]) -> float:
    timestamps = tuple(_path_mtime(path) for path in wav_files)
    return max(timestamps, default=_path_mtime(job_dir))


def _path_mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0
