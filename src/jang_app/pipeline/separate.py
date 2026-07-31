from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from jang_app.config import FFMPEG_BIN_DIR, SEPARATION_OUTPUT_DIR, SUPPORTED_AUDIO_EXTENSIONS, VENV_SCRIPTS_DIR
from jang_app.services.app_logging import get_logger
from jang_app.services.command import run_command
from jang_app.services.environment import MissingExecutableError, require_executable


class SeparationError(RuntimeError):
    """Raised when source separation cannot be completed."""


@dataclass(frozen=True)
class SeparationResult:
    input_path: Path
    job_dir: Path
    vocals_path: Path
    accompaniment_path: Path


ProgressCallback = Callable[[int], None]
_DEMUCS_PROGRESS_PATTERN = re.compile(r"(\d{1,3})%\|")


def separate_audio(
    input_path: Path,
    output_root: Path = SEPARATION_OUTPUT_DIR,
    model_name: str = "htdemucs",
    progress_callback: ProgressCallback | None = None,
) -> SeparationResult:
    logger = get_logger()
    source = input_path.expanduser().resolve()
    logger.info("Starting separation: input=%s output_root=%s model=%s", source, output_root, model_name)
    _validate_input_audio(source)
    _require_separation_tools()

    output_root = output_root.expanduser().resolve()
    output_root.mkdir(parents=True, exist_ok=True)

    completed = run_command(
        _build_demucs_command(source, output_root, model_name),
        output_callback=_build_demucs_progress_callback(progress_callback),
    )
    if completed.returncode != 0:
        logger.error("Demucs failed with exit code %s\n%s", completed.returncode, completed.output)
        raise SeparationError(f"Demucs failed with exit code {completed.returncode}. See logs for details.")

    stem_name = source.stem
    job_dir = output_root / model_name / stem_name
    vocals_path = job_dir / "vocals.wav"
    accompaniment_path = job_dir / "no_vocals.wav"

    if not vocals_path.exists() or not accompaniment_path.exists():
        job_dir = _find_demucs_job_dir(output_root / model_name, stem_name)
        vocals_path = job_dir / "vocals.wav"
        accompaniment_path = job_dir / "no_vocals.wav"

    result = SeparationResult(
        input_path=source,
        job_dir=job_dir,
        vocals_path=vocals_path,
        accompaniment_path=accompaniment_path,
    )
    logger.info("Separation complete: job_dir=%s", result.job_dir)
    if progress_callback is not None:
        progress_callback(100)
    return result


def _validate_input_audio(source: Path) -> None:
    if not source.exists():
        raise SeparationError(f"Input file does not exist: {source}")
    if source.suffix.lower() not in SUPPORTED_AUDIO_EXTENSIONS:
        supported = ", ".join(sorted(SUPPORTED_AUDIO_EXTENSIONS))
        raise SeparationError(f"Unsupported audio format: {source.suffix}. Supported: {supported}")


def _require_separation_tools() -> None:
    try:
        require_executable("demucs", "Install project requirements first.", [VENV_SCRIPTS_DIR])
        require_executable("ffmpeg", "Place FFmpeg under third_party/ffmpeg/bin or add it to PATH.", [FFMPEG_BIN_DIR])
        require_executable("ffprobe", "Place FFprobe under third_party/ffmpeg/bin or add it to PATH.", [FFMPEG_BIN_DIR])
    except MissingExecutableError as exc:
        raise SeparationError(str(exc)) from exc


def _build_demucs_command(source: Path, output_root: Path, model_name: str) -> list[str]:
    return [
        "demucs",
        "--two-stems=vocals",
        "-n",
        model_name,
        "-o",
        str(output_root),
        str(source),
    ]


def _build_demucs_progress_callback(progress_callback: ProgressCallback | None) -> Callable[[str], None] | None:
    if progress_callback is None:
        return None

    last_percent = -1

    def handle_output(output: str) -> None:
        nonlocal last_percent
        percent = _extract_demucs_percent(output)
        if percent is None or percent == last_percent:
            return

        last_percent = percent
        progress_callback(percent)

    return handle_output


def _extract_demucs_percent(output: str) -> int | None:
    matches = _DEMUCS_PROGRESS_PATTERN.findall(output)
    if not matches:
        return None
    return max(0, min(100, int(matches[-1])))


def _find_demucs_job_dir(model_output_dir: Path, source_stem: str) -> Path:
    if not model_output_dir.exists():
        raise SeparationError(f"Demucs output directory was not created: {model_output_dir}")

    normalized_target = _normalize_name(source_stem)
    candidates = [
        child
        for child in model_output_dir.iterdir()
        if child.is_dir() and _normalize_name(child.name) == normalized_target
    ]
    if not candidates:
        raise SeparationError(f"Could not find separated output for: {source_stem}")

    job_dir = max(candidates, key=lambda path: path.stat().st_mtime)
    if not (job_dir / "vocals.wav").exists() or not (job_dir / "no_vocals.wav").exists():
        raise SeparationError(f"Separated stems are missing in: {job_dir}")
    return job_dir


def _normalize_name(value: str) -> str:
    return re.sub(r"\W+", "", value, flags=re.UNICODE).casefold()
