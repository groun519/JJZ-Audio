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
    TOOL_WORKSPACE_DIR,
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
from jang_app.pipeline.separation_postprocessor import postprocess_stems
from jang_app.services.separation_assets import separation_model_component_count
from jang_app.services.separation_recipe import SeparationRecipe, save_separation_run
from jang_app.services.tool_workspace import ToolWorkspace


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
        job_dir = request.output_root.expanduser().resolve()
        job_dir.mkdir(parents=True, exist_ok=True)
        with ToolWorkspace(TOOL_WORKSPACE_DIR, "demucs") as workspace:
            staged_source = workspace.stage_input(source)
            completed = run_command(
                build_demucs_command(staged_source, workspace.output_dir, recipe=recipe),
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
                logger.error(
                    "Demucs failed with exit code %s\n%s",
                    completed.returncode,
                    completed.output,
                )
                raise SeparationError(
                    f"Demucs failed with exit code {completed.returncode}. See logs for details."
                )

            staged_job = find_demucs_job_dir(
                workspace.output_dir / recipe.model,
                staged_source.stem,
            )
            staged_vocals = staged_job / "vocals.wav"
            staged_accompaniment = staged_job / "no_vocals.wav"
            postprocess_status, postprocess_detail = postprocess_stems(
                staged_source,
                staged_vocals,
                staged_accompaniment,
                recipe,
                progress_callback,
            )
            vocals_path = workspace.publish_file(staged_vocals, job_dir / "vocals.wav")
            accompaniment_path = workspace.publish_file(
                staged_accompaniment,
                job_dir / "no_vocals.wav",
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


def _normalize_name(value: str) -> str:
    return re.sub(r"\W+", "", value, flags=re.UNICODE).casefold()
