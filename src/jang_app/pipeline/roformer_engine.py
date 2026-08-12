from __future__ import annotations

import importlib.util
import os
import re
import shutil
import sys
from collections.abc import Callable
from pathlib import Path

from jang_app.config import (
    APP_PATHS,
    FFMPEG_BIN_DIR,
    ROFORMER_MODEL_DIR,
    ROFORMER_PACKAGE_DIR,
    RVC_PYTHON_EXE,
    TOOL_WORKSPACE_DIR,
)
from jang_app.pipeline.separation_engine import (
    ProgressCallback,
    SeparationError,
    SeparationRequest,
    SeparationResult,
)
from jang_app.pipeline.separation_postprocessor import postprocess_stems
from jang_app.services.app_logging import get_logger
from jang_app.services.command import run_command
from jang_app.services.environment import MissingExecutableError, require_executable
from jang_app.services.roformer_model_assets import (
    RoFormerModelAssetError,
    prepare_roformer_model_assets,
)
from jang_app.services.separation_assets import roformer_model_assets
from jang_app.services.separation_recipe import SeparationRecipe, save_separation_run
from jang_app.services.tool_workspace import ToolWorkspace
from jang_app.services.vocal_effect_protection import (
    VocalEffectProtectionError,
    protect_effect_removed_vocals,
)


_ROFORMER_PROGRESS_PATTERN = re.compile(r"(?<!\d)(\d{1,3})%")
_CLI_ENTRYPOINT = "from audio_separator.utils.cli import main; main()"


class RoFormerEngine:
    engine_id = "roformer"

    def separate(
        self,
        request: SeparationRequest,
        progress_callback: ProgressCallback | None = None,
    ) -> SeparationResult:
        logger = get_logger()
        source = request.input_path.expanduser().resolve()
        recipe = request.recipe
        logger.info(
            "Starting RoFormer separation: input=%s output_root=%s recipe=%s model=%s",
            source,
            request.output_root,
            recipe.recipe_id,
            recipe.model,
        )
        require_roformer_tools()
        job_dir = request.output_root.expanduser().resolve()
        job_dir.mkdir(parents=True, exist_ok=True)
        ROFORMER_MODEL_DIR.mkdir(parents=True, exist_ok=True)
        if progress_callback is not None:
            progress_callback(2)
        prepared_files, prepared_registry = _prepare_recipe_model_assets(
            recipe,
            progress_callback,
        )
        with ToolWorkspace(TOOL_WORKSPACE_DIR, "roformer") as workspace:
            staged_source = workspace.stage_input(source)
            model_dir = ROFORMER_MODEL_DIR
            if prepared_files:
                for asset in prepared_files:
                    workspace.stage_file(asset, asset.name)
                if prepared_registry is not None:
                    workspace.stage_file(prepared_registry, prepared_registry.name)
                model_dir = workspace.root
            for model in recipe.required_models:
                model_source = ROFORMER_MODEL_DIR / model
                if model_source.is_file() and not (workspace.root / model).is_file():
                    workspace.stage_file(model_source, model)
                    model_dir = workspace.root
            first_stage_end = 62 if recipe.effect_model else 92
            completed = run_command(
                build_roformer_command(
                    staged_source,
                    workspace.output_dir,
                    recipe,
                    model_dir=model_dir,
                ),
                env=build_roformer_environment(),
                output_callback=build_roformer_progress_callback(
                    progress_callback,
                    minimum_percent=35 if prepared_files else 5,
                    maximum_percent=first_stage_end,
                ),
            )
            if completed.returncode != 0:
                logger.error(
                    "RoFormer failed with exit code %s\n%s",
                    completed.returncode,
                    completed.output,
                )
                raise SeparationError(
                    f"Precision separation failed with exit code {completed.returncode}. "
                    "See logs for details."
                )

            staged_vocals, staged_accompaniment = normalize_roformer_outputs(
                workspace.output_dir
            )
            protection_detail = ""
            if recipe.effect_model:
                effect_output_dir = workspace.root / "e"
                effect_output_dir.mkdir(parents=True, exist_ok=True)
                completed = run_command(
                    build_roformer_command(
                        staged_vocals,
                        effect_output_dir,
                        recipe,
                        model=recipe.effect_model,
                        model_dir=model_dir,
                    ),
                    env=build_roformer_environment(),
                    output_callback=build_roformer_progress_callback(
                        progress_callback,
                        minimum_percent=63,
                        maximum_percent=92,
                    ),
                )
                if completed.returncode != 0:
                    logger.error(
                        "RoFormer effect removal failed with exit code %s\n%s",
                        completed.returncode,
                        completed.output,
                    )
                    raise SeparationError(
                        "Effect removal failed with exit code "
                        f"{completed.returncode}. See logs for details."
                    )
                dry_vocals, _removed_effect = normalize_roformer_effect_outputs(
                    effect_output_dir
                )
                protected_vocals = effect_output_dir / "protected_vocals.wav"
                try:
                    protection_report = protect_effect_removed_vocals(
                        staged_vocals,
                        dry_vocals,
                        protected_vocals,
                    )
                except VocalEffectProtectionError as exc:
                    logger.warning(
                        "Vocal protection skipped; preserving the first-stage vocal: %s",
                        exc,
                    )
                    protection_detail = f"vocal protection skipped: {exc}"
                else:
                    logger.info("Vocal protection complete: %s", protection_report.detail)
                    protection_detail = protection_report.detail
                    _replace_output(protected_vocals, staged_vocals)
                if progress_callback is not None:
                    progress_callback(94)
            postprocess_status, postprocess_detail = postprocess_stems(
                staged_source,
                staged_vocals,
                staged_accompaniment,
                recipe,
                progress_callback,
            )
            if protection_detail:
                postprocess_detail = "; ".join(
                    detail for detail in (protection_detail, postprocess_detail) if detail
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
        logger.info(
            "RoFormer separation complete: job_dir=%s recipe=%s",
            result.job_dir,
            recipe.recipe_id,
        )
        if progress_callback is not None:
            progress_callback(100)
        return result


def build_roformer_command(
    source: Path,
    output_dir: Path,
    recipe: SeparationRecipe,
    *,
    model: str | None = None,
    model_dir: Path = ROFORMER_MODEL_DIR,
) -> list[str]:
    python = roformer_python_executable()
    return [
        str(python),
        "-c",
        _CLI_ENTRYPOINT,
        str(source),
        "--model_filename",
        model or recipe.model,
        "--model_file_dir",
        str(model_dir),
        "--output_dir",
        str(output_dir),
        "--output_format",
        "WAV",
        "--sample_rate",
        "44100",
        "--mdxc_segment_size",
        "256",
        "--mdxc_overlap",
        "8",
        "--mdxc_batch_size",
        "1",
    ]


def build_roformer_environment() -> dict[str, str]:
    environment = os.environ.copy()
    existing_path = environment.get("PATH", "")
    environment["PATH"] = os.pathsep.join(
        part for part in (str(FFMPEG_BIN_DIR), existing_path) if part
    )
    environment["AUDIO_SEPARATOR_MODEL_DIR"] = str(ROFORMER_MODEL_DIR)
    existing_python_path = environment.get("PYTHONPATH", "")
    environment["PYTHONPATH"] = os.pathsep.join(
        part for part in (str(ROFORMER_PACKAGE_DIR), existing_python_path) if part
    )
    environment["PYTHONUNBUFFERED"] = "1"
    return environment


def require_roformer_tools() -> None:
    try:
        python = roformer_python_executable()
        if python == RVC_PYTHON_EXE:
            if not RVC_PYTHON_EXE.is_file():
                raise MissingExecutableError(
                    f"Packaged AI runtime was not found: {RVC_PYTHON_EXE}"
                )
            package = ROFORMER_PACKAGE_DIR / "audio_separator"
            development_package = (
                RVC_PYTHON_EXE.parent / "Lib" / "site-packages" / "audio_separator"
            )
            if not package.is_dir() and not (
                not APP_PATHS.is_frozen and development_package.is_dir()
            ):
                raise MissingExecutableError(
                    "The precision separation component is not installed. "
                    "Update the JJZero Audio AI runtime."
                )
        elif importlib.util.find_spec("audio_separator") is None:
            raise MissingExecutableError(
                "The precision separation component is not installed. "
                "Install project requirements first."
            )
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


def roformer_python_executable() -> Path:
    if APP_PATHS.is_frozen or RVC_PYTHON_EXE.is_file():
        return RVC_PYTHON_EXE
    return Path(sys.executable)


def build_roformer_progress_callback(
    progress_callback: ProgressCallback | None,
    *,
    minimum_percent: int = 5,
    maximum_percent: int = 92,
) -> Callable[[str], None] | None:
    if progress_callback is None:
        return None
    minimum_percent = max(2, min(90, minimum_percent))
    maximum_percent = max(minimum_percent, min(92, maximum_percent))
    span = maximum_percent - minimum_percent
    model_end = minimum_percent + round(span * 30 / 87)
    separation_start = minimum_percent + round(span * 40 / 87)
    last_percent = minimum_percent - 1
    phase = "model"

    def handle_output(output: str) -> None:
        nonlocal last_percent, phase
        lowered = output.casefold()
        if "starting separation process" in lowered:
            phase = "separation"
            candidate = separation_start
        elif "loading model" in lowered:
            phase = "model"
            candidate = minimum_percent
        else:
            raw_percent = extract_roformer_percent(output)
            if raw_percent is None:
                return
            candidate = (
                minimum_percent
                + round(raw_percent * (model_end - minimum_percent) / 100)
                if phase == "model"
                else separation_start
                + round(raw_percent * (maximum_percent - separation_start) / 100)
            )
        candidate = max(last_percent, min(maximum_percent, candidate))
        if candidate == last_percent:
            return
        last_percent = candidate
        progress_callback(candidate)

    return handle_output


def _prepare_recipe_model_assets(
    recipe: SeparationRecipe,
    progress_callback: ProgressCallback | None,
) -> tuple[tuple[Path, ...], Path | None]:
    managed_models = tuple(
        model
        for model in recipe.required_models
        if (assets := roformer_model_assets(model)) is not None
        and assets.managed_download
    )
    if not managed_models:
        return (), None
    files: dict[str, Path] = {}
    registry: Path | None = None
    try:
        for index, model in enumerate(managed_models):
            prepared = prepare_roformer_model_assets(
                model,
                ROFORMER_MODEL_DIR,
                _asset_progress_callback(
                    progress_callback,
                    index=index,
                    count=len(managed_models),
                ),
            )
            files.update((path.name, path) for path in prepared.files)
            registry = prepared.registry
    except RoFormerModelAssetError as exc:
        raise SeparationError(str(exc)) from exc
    return tuple(files.values()), registry


def _asset_progress_callback(
    progress_callback: ProgressCallback | None,
    *,
    index: int = 0,
    count: int = 1,
) -> ProgressCallback | None:
    if progress_callback is None:
        return None
    count = max(1, count)

    def report(value: int) -> None:
        completed = index + max(0, min(100, value)) / 100
        progress_callback(2 + round(completed * 32 / count))

    return report


def extract_roformer_percent(output: str) -> int | None:
    matches = _ROFORMER_PROGRESS_PATTERN.findall(output)
    if not matches:
        return None
    return max(0, min(100, int(matches[-1])))


def normalize_roformer_outputs(job_dir: Path) -> tuple[Path, Path]:
    root = job_dir.expanduser().resolve()
    vocals_target = root / "vocals.wav"
    accompaniment_target = root / "no_vocals.wav"
    candidates = tuple(
        path
        for path in root.rglob("*.wav")
        if path not in {vocals_target, accompaniment_target}
    )
    vocals_source = _find_stem(candidates, "vocals")
    accompaniment_source = _find_stem(candidates, "instrumental")
    if vocals_source is None or accompaniment_source is None:
        names = ", ".join(path.name for path in candidates) or "none"
        raise SeparationError(
            "Precision separation did not produce both vocal and instrumental stems. "
            f"Outputs: {names}"
        )
    _replace_output(vocals_source, vocals_target)
    _replace_output(accompaniment_source, accompaniment_target)
    return vocals_target, accompaniment_target


def normalize_roformer_effect_outputs(job_dir: Path) -> tuple[Path, Path]:
    root = job_dir.expanduser().resolve()
    dry_target = root / "dry_vocals.wav"
    effect_target = root / "removed_effect.wav"
    candidates = tuple(
        path for path in root.rglob("*.wav") if path not in {dry_target, effect_target}
    )
    dry_source = _find_effect_stem(candidates, dry=True)
    effect_source = _find_effect_stem(candidates, dry=False)
    if dry_source is None or effect_source is None:
        names = ", ".join(path.name for path in candidates) or "none"
        raise SeparationError(
            "Effect removal did not produce both dry-vocal and ambience stems. "
            f"Outputs: {names}"
        )
    _replace_output(dry_source, dry_target)
    _replace_output(effect_source, effect_target)
    return dry_target, effect_target


def _find_stem(candidates: tuple[Path, ...], stem: str) -> Path | None:
    if stem == "vocals":
        patterns = ("(vocals)", "_vocals.", "-vocals.")
    else:
        patterns = (
            "(instrumental)",
            "(other)",
            "no_vocals",
            "_instrumental.",
            "-instrumental.",
        )
    matches = [
        path
        for path in candidates
        if any(pattern in path.name.casefold() for pattern in patterns)
    ]
    return max(matches, key=lambda path: path.stat().st_mtime) if matches else None


def _find_effect_stem(candidates: tuple[Path, ...], *, dry: bool) -> Path | None:
    patterns = (
        (
            "(no reverb)",
            "(noreverb)",
            "_no_reverb.",
            "-no_reverb.",
            "_noreverb.",
            "(vocals)",
        )
        if dry
        else ("(reverb)", "_reverb.", "-reverb.", "(instrumental)")
    )
    matches = [
        path
        for path in candidates
        if any(pattern in path.name.casefold() for pattern in patterns)
    ]
    return max(matches, key=lambda path: path.stat().st_mtime) if matches else None


def _replace_output(source: Path, target: Path) -> None:
    if source.resolve() == target.resolve():
        return
    target.unlink(missing_ok=True)
    shutil.move(str(source), str(target))
