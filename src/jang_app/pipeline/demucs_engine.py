from __future__ import annotations

import os
import re
from collections.abc import Callable
from pathlib import Path

from jang_app.config import (
    APP_PATHS,
    DEMUCS_RUNTIME_DIR,
    FFMPEG_BIN_DIR,
    RVC_PYTHON_EXE,
    VENV_SCRIPTS_DIR,
)
from jang_app.pipeline.separation_engine import (
    ProgressCallback,
    SeparationError,
    SeparationRequest,
    SeparationResult,
)
from jang_app.services.app_logging import get_logger
from jang_app.services.command import run_command
from jang_app.services.environment import MissingExecutableError, require_executable
from jang_app.services.separation_postprocess import (
    SeparationPostprocessError,
    enforce_mixture_consistency,
)
from jang_app.services.separation_assets import separation_model_component_count
from jang_app.services.separation_recipe import SeparationRecipe, save_separation_run


_DEMUCS_PROGRESS_PATTERN = re.compile(r"(\d{1,3})%\|")


class DemucsEngine:
    engine_id = "demucs"

    def separate(
        self,
        request: SeparationRequest,
        progress_callback: ProgressCallback | None = None,
    ) -> SeparationResult:
        logger = get_logger()
        source = request.input_path.expanduser().resolve()
        recipe = request.recipe
        logger.info(
            "Starting separation: input=%s output_root=%s recipe=%s model=%s shifts=%s overlap=%s float32=%s",
            source,
            request.output_root,
            recipe.recipe_id,
            recipe.model,
            recipe.shifts,
            recipe.overlap,
            recipe.float32,
        )
        require_demucs_tools()
        output_root = request.output_root.expanduser().resolve()
        output_root.mkdir(parents=True, exist_ok=True)
        completed = run_command(
            build_demucs_command(source, output_root, recipe=recipe),
            env=build_demucs_environment(),
            output_callback=build_demucs_progress_callback(
                progress_callback,
                expected_cycles=(
                    separation_model_component_count(recipe.model)
                    * max(1, recipe.shifts)
                ),
            ),
        )
        if completed.returncode != 0:
            logger.error("Demucs failed with exit code %s\n%s", completed.returncode, completed.output)
            raise SeparationError(
                f"Demucs failed with exit code {completed.returncode}. See logs for details."
            )

        job_dir = output_root / recipe.model / source.stem
        vocals_path = job_dir / "vocals.wav"
        accompaniment_path = job_dir / "no_vocals.wav"
        if not vocals_path.exists() or not accompaniment_path.exists():
            job_dir = find_demucs_job_dir(output_root / recipe.model, source.stem)
            vocals_path = job_dir / "vocals.wav"
            accompaniment_path = job_dir / "no_vocals.wav"

        postprocess_status, postprocess_detail = postprocess_stems(
            source,
            vocals_path,
            accompaniment_path,
            recipe,
            progress_callback,
        )
        save_separation_run(
            job_dir,
            recipe,
            source.name,
            postprocess_status=postprocess_status,
            postprocess_detail=postprocess_detail,
        )
        result = SeparationResult(
            input_path=source,
            job_dir=job_dir,
            vocals_path=vocals_path,
            accompaniment_path=accompaniment_path,
            recipe=recipe,
        )
        logger.info("Separation complete: job_dir=%s recipe=%s", result.job_dir, recipe.recipe_id)
        if progress_callback is not None:
            progress_callback(100)
        return result


def require_demucs_tools() -> None:
    try:
        if not APP_PATHS.is_frozen:
            require_executable("demucs", "Install project requirements first.", [VENV_SCRIPTS_DIR])
        elif not RVC_PYTHON_EXE.is_file():
            raise MissingExecutableError(f"Packaged AI runtime was not found: {RVC_PYTHON_EXE}")
        require_executable(
            "ffmpeg",
            "Place FFmpeg under third_party/ffmpeg/bin or add it to PATH.",
            [FFMPEG_BIN_DIR],
        )
        require_executable(
            "ffprobe",
            "Place FFprobe under third_party/ffmpeg/bin or add it to PATH.",
            [FFMPEG_BIN_DIR],
        )
    except MissingExecutableError as exc:
        raise SeparationError(str(exc)) from exc


def build_demucs_command(
    source: Path,
    output_root: Path,
    model_name: str = "htdemucs",
    *,
    recipe: SeparationRecipe | None = None,
) -> list[str]:
    selected = recipe or SeparationRecipe(
        recipe_id=f"demucs-{model_name}",
        label=model_name,
        engine="demucs",
        model=model_name,
    )
    command = [str(RVC_PYTHON_EXE), "-m", "demucs"] if APP_PATHS.is_frozen else ["demucs"]
    return [
        *command,
        "--two-stems=vocals",
        "-n",
        selected.model,
        "--shifts",
        str(selected.shifts),
        "--overlap",
        str(selected.overlap),
        "--clip-mode",
        selected.clip_mode,
        *(["--float32"] if selected.float32 else []),
        "-o",
        str(output_root),
        str(source),
    ]


def build_demucs_environment() -> dict[str, str]:
    environment = os.environ.copy()
    environment["TORCH_HOME"] = str(DEMUCS_RUNTIME_DIR / "torch")
    return environment


def build_demucs_progress_callback(
    progress_callback: ProgressCallback | None,
    *,
    expected_cycles: int = 1,
) -> Callable[[str], None] | None:
    if progress_callback is None:
        return None
    cycle_count = max(1, expected_cycles)
    cycle_index = 0
    last_raw_percent = -1
    last_percent = -1

    def handle_output(output: str) -> None:
        nonlocal cycle_index, last_percent, last_raw_percent
        raw_percent = extract_demucs_percent(output)
        if raw_percent is None:
            return
        if raw_percent < last_raw_percent:
            cycle_index = min(cycle_count - 1, cycle_index + 1)
        last_raw_percent = raw_percent
        percent = round((cycle_index * 100 + raw_percent) / cycle_count)
        if percent <= last_percent:
            return
        last_percent = percent
        progress_callback(percent)

    return handle_output


def extract_demucs_percent(output: str) -> int | None:
    matches = _DEMUCS_PROGRESS_PATTERN.findall(output)
    if not matches:
        return None
    return max(0, min(100, int(matches[-1])))


def find_demucs_job_dir(model_output_dir: Path, source_stem: str) -> Path:
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


def postprocess_stems(
    source: Path,
    vocals_path: Path,
    accompaniment_path: Path,
    recipe: SeparationRecipe,
    progress_callback: ProgressCallback | None,
) -> tuple[str, str]:
    if not recipe.mixture_consistency:
        return "not_requested", ""
    if progress_callback is not None:
        progress_callback(96)
    logger = get_logger()
    try:
        report = enforce_mixture_consistency(source, vocals_path, accompaniment_path)
    except SeparationPostprocessError as exc:
        logger.warning("Separation quality normalization skipped: %s", exc)
        return "skipped", str(exc)
    logger.info(
        "Separation quality normalization complete: frames=%s rate=%s channels=%s residual_before=%.8f residual_after=%.8f peak=%.5f",
        report.frames,
        report.sample_rate,
        report.channels,
        report.residual_rms_before,
        report.residual_rms_after,
        report.peak,
    )
    return (
        "applied",
        f"residual {report.residual_rms_before:.8f} -> {report.residual_rms_after:.8f}; "
        f"peak {report.peak:.5f}",
    )


def _normalize_name(value: str) -> str:
    return re.sub(r"\W+", "", value, flags=re.UNICODE).casefold()
