from __future__ import annotations

from pathlib import Path

from jang_app.pipeline.separation_engine import ProgressCallback
from jang_app.services.app_logging import get_logger
from jang_app.services.separation_postprocess import (
    SeparationPostprocessError,
    enforce_mixture_consistency,
)
from jang_app.services.separation_recipe import SeparationRecipe


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
        "Separation quality normalization complete: policy=vocal-preserving frames=%s rate=%s channels=%s residual_before=%.8f residual_after=%.8f peak=%.5f",
        report.frames,
        report.sample_rate,
        report.channels,
        report.residual_rms_before,
        report.residual_rms_after,
        report.peak,
    )
    return (
        "applied",
        f"vocal-preserving; residual {report.residual_rms_before:.8f} -> "
        f"{report.residual_rms_after:.8f}; peak {report.peak:.5f}",
    )
