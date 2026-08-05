from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from jang_app.services.app_logging import get_logger
from jang_app.services.command import (
    CommandCancellation,
    CommandResult,
    run_cancellable_command,
)
from jang_app.services.managed_files import file_sha256, write_json_atomic, write_text_atomic
from jang_app.services.rvc_environment import build_rvc_environment
from jang_app.services.rvc_model_package import RvcModelPackageLayout
from jang_app.services.rvc_training_control import (
    RvcTrainingCancelled,
    raise_if_training_cancelled,
)
from jang_app.services.rvc_training_filelist import load_rvc_training_filelist
from jang_app.services.rvc_training_runtime import (
    RvcTrainingRuntimeInspection,
    inspect_rvc_training_runtime,
)
from jang_app.services.rvc_training_storage import (
    RvcTrainingStorageError,
    prepare_rvc_training_storage,
)


SPECTROGRAM_MANIFEST_NAME = "jjzero_spectrogram.json"
_MANIFEST_VERSION = 1
_MIN_SPECTROGRAM_BYTES = 4096
_PROGRESS_PREFIX = "JJZERO_SPEC_CACHE|"
_PROGRESS_PATTERN = re.compile(
    rf"^{re.escape(_PROGRESS_PREFIX)}(?P<current>\d+)\|(?P<total>\d+)\|"
    r"(?P<created>\d+)\|(?P<reused>\d+)$"
)


class RvcTrainingSpectrogramError(RuntimeError):
    """Raised when RVC spectrogram caches cannot be prepared or verified."""


@dataclass(frozen=True)
class RvcTrainingSpectrogramResult:
    manifest_path: Path
    audio_count: int
    created_count: int
    reused_count: int


SpectrogramCommandRunner = Callable[..., CommandResult]


def load_rvc_training_spectrogram_cache(
    model_id: str,
    layout: RvcModelPackageLayout,
) -> RvcTrainingSpectrogramResult:
    filelist = load_rvc_training_filelist(model_id, layout)
    manifest_path = layout.experiment_dir / SPECTROGRAM_MANIFEST_NAME
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RvcTrainingSpectrogramError(
            "RVC spectrogram cache manifest cannot be read."
        ) from exc

    audio_paths = _audio_paths(filelist.path, layout)
    expected_entries = [_cache_entry(path, layout) for path in audio_paths]
    if (
        not isinstance(data, dict)
        or data.get("version") != _MANIFEST_VERSION
        or data.get("filelist_sha256") != file_sha256(filelist.path)
        or data.get("entries") != expected_entries
    ):
        raise RvcTrainingSpectrogramError(
            "RVC spectrogram cache does not match the training audio."
        )
    return RvcTrainingSpectrogramResult(
        manifest_path=manifest_path,
        audio_count=len(audio_paths),
        created_count=0,
        reused_count=len(audio_paths),
    )


def prepare_rvc_training_spectrogram_cache(
    model_id: str,
    layout: RvcModelPackageLayout,
    runtime_root: Path,
    *,
    cancellation: CommandCancellation | None = None,
    progress: Callable[[int], None] | None = None,
    output_callback: Callable[[str], None] | None = None,
    command_runner: SpectrogramCommandRunner = run_cancellable_command,
    runtime_inspector: Callable[..., RvcTrainingRuntimeInspection] = inspect_rvc_training_runtime,
) -> RvcTrainingSpectrogramResult:
    runtime = runtime_root.expanduser().resolve()
    inspection = runtime_inspector(runtime)
    if not inspection.assets_ready:
        missing = ", ".join(path.as_posix() for path in inspection.missing_paths)
        raise RvcTrainingSpectrogramError(f"RVC training runtime is incomplete: {missing}")

    filelist = load_rvc_training_filelist(model_id, layout)
    try:
        prepare_rvc_training_storage(layout)
    except RvcTrainingStorageError as exc:
        raise RvcTrainingSpectrogramError(str(exc)) from exc

    token = cancellation or CommandCancellation()
    raise_if_training_cancelled(token)
    worker = layout.root / ".jjzero" / "cache_spectrograms.py"
    write_text_atomic(worker, _SPECTROGRAM_WORKER)
    counts = {"created": 0, "reused": 0}

    def handle_output(line: str) -> None:
        match = _PROGRESS_PATTERN.fullmatch(line.strip())
        if match is None:
            if output_callback is not None:
                output_callback(line)
            return
        current = int(match.group("current"))
        total = int(match.group("total"))
        counts["created"] = int(match.group("created"))
        counts["reused"] = int(match.group("reused"))
        if progress is not None:
            progress(100 if total <= 0 else round(current * 100 / total))

    result = command_runner(
        [
            str(runtime / "runtime" / "python.exe"),
            str(worker),
            str(runtime),
            str(filelist.path),
        ],
        cwd=layout.root,
        env=build_rvc_environment(runtime),
        output_callback=handle_output,
        cancellation=token,
    )
    if result.cancelled or token.is_requested:
        raise RvcTrainingCancelled("RVC training was stopped.")
    if result.returncode != 0:
        detail = result.output or f"spectrogram worker exited with code {result.returncode}"
        raise RvcTrainingSpectrogramError(
            f"RVC spectrogram cache preparation failed: {detail}"
        )

    audio_paths = _audio_paths(filelist.path, layout)
    entries = [_cache_entry(path, layout) for path in audio_paths]
    manifest_path = layout.experiment_dir / SPECTROGRAM_MANIFEST_NAME
    write_json_atomic(
        manifest_path,
        {
            "version": _MANIFEST_VERSION,
            "filelist_sha256": file_sha256(filelist.path),
            "entries": entries,
        },
    )
    if progress is not None:
        progress(100)
    result_data = RvcTrainingSpectrogramResult(
        manifest_path=manifest_path,
        audio_count=len(audio_paths),
        created_count=counts["created"],
        reused_count=counts["reused"],
    )
    get_logger().info(
        "RVC spectrogram cache ready: model=%s audio=%s created=%s reused=%s",
        model_id,
        result_data.audio_count,
        result_data.created_count,
        result_data.reused_count,
    )
    return result_data


def _audio_paths(filelist: Path, layout: RvcModelPackageLayout) -> tuple[Path, ...]:
    try:
        lines = filelist.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise RvcTrainingSpectrogramError("RVC training file list cannot be read.") from exc

    paths: dict[str, Path] = {}
    for line in lines:
        if not line.strip():
            continue
        value = line.split("|", 1)[0].replace("\\\\", "\\")
        audio = Path(value).expanduser().resolve()
        if not layout.contains(audio) or not audio.is_file():
            raise RvcTrainingSpectrogramError(
                f"RVC training audio is outside the managed model or missing: {audio}"
            )
        paths[str(audio).casefold()] = audio
    if not paths:
        raise RvcTrainingSpectrogramError("RVC training file list has no audio entries.")
    return tuple(paths[key] for key in sorted(paths))


def _cache_entry(audio: Path, layout: RvcModelPackageLayout) -> dict[str, int | str]:
    spectrogram = audio.with_suffix(".spec.pt")
    try:
        audio_stat = audio.stat()
        spec_stat = spectrogram.stat()
    except OSError as exc:
        raise RvcTrainingSpectrogramError(
            f"RVC spectrogram cache is missing: {spectrogram}"
        ) from exc
    if (
        spec_stat.st_size < _MIN_SPECTROGRAM_BYTES
        or spec_stat.st_mtime_ns < audio_stat.st_mtime_ns
    ):
        raise RvcTrainingSpectrogramError(
            f"RVC spectrogram cache is incomplete or stale: {spectrogram}"
        )
    return {
        "audio": audio.relative_to(layout.root.resolve()).as_posix(),
        "audio_size": audio_stat.st_size,
        "audio_mtime_ns": audio_stat.st_mtime_ns,
        "spectrogram_size": spec_stat.st_size,
        "spectrogram_mtime_ns": spec_stat.st_mtime_ns,
    }


_SPECTROGRAM_WORKER = r'''from __future__ import annotations

import os
import sys
from pathlib import Path


MIN_CACHE_BYTES = 4096
PROGRESS_PREFIX = "JJZERO_SPEC_CACHE|"
SAMPLE_RATE = 40000
FILTER_LENGTH = 2048
HOP_LENGTH = 400
WIN_LENGTH = 2048


def audio_paths(filelist: Path):
    unique = {}
    for line in filelist.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        value = line.split("|", 1)[0].replace("\\\\", "\\")
        path = Path(value).expanduser().resolve()
        unique[str(path).casefold()] = path
    return [unique[key] for key in sorted(unique)]


def valid_cache(torch, audio: Path, target: Path) -> bool:
    if not target.is_file():
        return False
    if target.stat().st_size < MIN_CACHE_BYTES or target.stat().st_mtime_ns < audio.stat().st_mtime_ns:
        return False
    try:
        value = torch.load(str(target), map_location="cpu")
        del value
        return True
    except Exception:
        return False


def main() -> None:
    rvc_root = Path(sys.argv[1]).expanduser().resolve()
    filelist = Path(sys.argv[2]).expanduser().resolve()
    sys.path.insert(0, str(rvc_root))

    import torch
    from lib.train.mel_processing import spectrogram_torch
    from lib.train.utils import load_wav_to_torch

    torch.set_num_threads(max(1, min(4, os.cpu_count() or 1)))
    paths = audio_paths(filelist)
    created = 0
    reused = 0
    total = len(paths)
    with torch.no_grad():
        for current, audio in enumerate(paths, 1):
            if not audio.is_file():
                raise FileNotFoundError(f"Training audio is missing: {audio}")
            target = audio.with_suffix(".spec.pt")
            if valid_cache(torch, audio, target):
                reused += 1
            else:
                target.unlink(missing_ok=True)
                temporary = target.with_name(f".{target.name}.{os.getpid()}.tmp")
                try:
                    waveform, sample_rate = load_wav_to_torch(str(audio))
                    if sample_rate != SAMPLE_RATE:
                        raise ValueError(
                            f"{audio} sample rate {sample_rate} does not match {SAMPLE_RATE}"
                        )
                    spectrogram = spectrogram_torch(
                        waveform.unsqueeze(0),
                        FILTER_LENGTH,
                        SAMPLE_RATE,
                        HOP_LENGTH,
                        WIN_LENGTH,
                        center=False,
                    ).squeeze(0)
                    torch.save(
                        spectrogram,
                        str(temporary),
                        _use_new_zipfile_serialization=False,
                    )
                    os.replace(temporary, target)
                    created += 1
                finally:
                    temporary.unlink(missing_ok=True)
            print(
                f"{PROGRESS_PREFIX}{current}|{total}|{created}|{reused}",
                flush=True,
            )


if __name__ == "__main__":
    main()
'''
