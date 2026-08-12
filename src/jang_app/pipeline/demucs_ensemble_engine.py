from __future__ import annotations

import shutil
from dataclasses import replace

from jang_app.pipeline.demucs_engine import DemucsEngine, postprocess_stems
from jang_app.pipeline.separation_engine import (
    ProgressCallback,
    SeparationEngine,
    SeparationError,
    SeparationRequest,
    SeparationResult,
)
from jang_app.services.app_logging import get_logger
from jang_app.services.separation_ensemble import (
    SeparationEnsembleError,
    SeparationStemPair,
    blend_stem_pairs,
)
from jang_app.services.separation_recipe import save_separation_run


_MEMBER_PROGRESS_END = 90


class DemucsEnsembleEngine:
    engine_id = "demucs"

    def __init__(self, component_engine: SeparationEngine | None = None) -> None:
        self._component_engine = component_engine or DemucsEngine()

    def separate(
        self,
        request: SeparationRequest,
        progress_callback: ProgressCallback | None = None,
    ) -> SeparationResult:
        recipe = request.recipe
        if not recipe.is_ensemble:
            raise SeparationError("The Demucs ensemble engine requires an ensemble recipe.")

        logger = get_logger()
        report_progress = _monotonic_progress_callback(progress_callback)
        source = request.input_path.expanduser().resolve()
        output_root = request.output_root.expanduser().resolve()
        output_root.mkdir(parents=True, exist_ok=True)
        work_root = output_root / ".e"
        if work_root.exists():
            shutil.rmtree(work_root)
        job_dir = output_root
        completed = False
        stem_pairs: list[SeparationStemPair] = []
        logger.info(
            "Starting sequential Demucs ensemble: input=%s recipe=%s models=%s weights=%s shifts=%s",
            source,
            recipe.recipe_id,
            recipe.models,
            recipe.normalized_ensemble_weights,
            recipe.shifts,
        )
        try:
            for index, model in enumerate(recipe.models):
                member_recipe = replace(
                    recipe,
                    recipe_id=f"{recipe.recipe_id}-member-{index + 1}",
                    label=f"{recipe.label} ({model})",
                    model=model,
                    mixture_consistency=False,
                    ensemble_models=(),
                    ensemble_weights=(),
                )
                logger.info(
                    "Running ensemble member %s/%s: model=%s",
                    index + 1,
                    len(recipe.models),
                    model,
                )
                result = self._component_engine.separate(
                    SeparationRequest(source, work_root / f"m{index + 1}", member_recipe),
                    _member_progress_callback(
                        report_progress,
                        index,
                        len(recipe.models),
                    ),
                )
                stem_pairs.append(
                    SeparationStemPair(result.vocals_path, result.accompaniment_path)
                )

            if report_progress is not None:
                report_progress(93)
            vocals_path = job_dir / "vocals.wav"
            accompaniment_path = job_dir / "no_vocals.wav"
            report = blend_stem_pairs(
                stem_pairs,
                vocals_path,
                accompaniment_path,
                weights=recipe.normalized_ensemble_weights,
            )
            logger.info(
                "Demucs ensemble blend complete: members=%s frames=%s rate=%s channels=%s peak=%.5f",
                report.members,
                report.frames,
                report.sample_rate,
                report.channels,
                report.peak,
            )
            if report_progress is not None:
                report_progress(95)
            postprocess_status, postprocess_detail = postprocess_stems(
                source,
                vocals_path,
                accompaniment_path,
                recipe,
                report_progress,
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
                "Sequential Demucs ensemble complete: job_dir=%s recipe=%s",
                result.job_dir,
                recipe.recipe_id,
            )
            if report_progress is not None:
                report_progress(100)
            completed = True
            return result
        except SeparationEnsembleError as exc:
            raise SeparationError(str(exc)) from exc
        finally:
            shutil.rmtree(work_root, ignore_errors=True)
            if not completed:
                shutil.rmtree(job_dir, ignore_errors=True)


def _member_progress_callback(
    progress_callback: ProgressCallback | None,
    member_index: int,
    member_count: int,
) -> ProgressCallback | None:
    if progress_callback is None:
        return None
    phase_size = _MEMBER_PROGRESS_END / member_count
    phase_start = member_index * phase_size
    last_progress = -1

    def update(member_progress: int) -> None:
        nonlocal last_progress
        value = round(
            phase_start + phase_size * max(0, min(100, member_progress)) / 100
        )
        if value <= last_progress:
            return
        last_progress = value
        progress_callback(value)

    return update


def _monotonic_progress_callback(
    progress_callback: ProgressCallback | None,
) -> ProgressCallback | None:
    if progress_callback is None:
        return None
    last_progress = -1

    def update(progress: int) -> None:
        nonlocal last_progress
        value = max(0, min(100, int(progress)))
        if value <= last_progress:
            return
        last_progress = value
        progress_callback(value)

    return update
