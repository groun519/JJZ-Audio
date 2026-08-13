from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path

from jang_app.pipeline.rvc_convert import RvcConversionResult, convert_vocal_with_rvc
from jang_app.pipeline.separate import SeparationResult, separate_audio
from jang_app.services.output_catalog import OutputSoundSet
from jang_app.services.separation_recipe import FAST_RECIPE
from jang_app.services.settings import RvcSettings
from jang_app.services.song_library import SongVocalVersion


ProgressCallback = Callable[[int], None]
SEPARATION_PROGRESS_END = 45


@dataclass(frozen=True)
class QuickProductionResult:
    sound_set: OutputSoundSet
    conversion: RvcConversionResult
    separation: SeparationResult | None = None

    @property
    def reused_separation(self) -> bool:
        return self.separation is None


def reusable_fast_separation(
    versions: Iterable[SongVocalVersion],
) -> SongVocalVersion | None:
    candidates = tuple(
        version
        for version in versions
        if version.separation_recipe_id == FAST_RECIPE.recipe_id
        and version.vocals_path.is_file()
        and version.instrumental_path.is_file()
    )
    return max(candidates, key=lambda version: version.added_at, default=None)


def run_quick_production(
    *,
    source_path: Path | None,
    separation_output_root: Path | None,
    reusable_sound_set: OutputSoundSet | None,
    rvc_settings: RvcSettings,
    progress_callback: ProgressCallback | None = None,
) -> QuickProductionResult:
    separation: SeparationResult | None = None
    if reusable_sound_set is None:
        if source_path is None or separation_output_root is None:
            raise ValueError("Original audio is required when no fast separation result exists.")
        separation = separate_audio(
            source_path,
            output_root=separation_output_root,
            recipe=FAST_RECIPE,
            progress_callback=_mapped_progress(
                progress_callback,
                start=0,
                end=SEPARATION_PROGRESS_END,
            ),
        )
        sound_set = OutputSoundSet(
            label=separation.recipe.label,
            job_dir=separation.job_dir,
            vocals_path=separation.vocals_path,
            instrumental_path=separation.accompaniment_path,
            converted_vocal_paths=(),
        )
    else:
        sound_set = reusable_sound_set
        _report(progress_callback, SEPARATION_PROGRESS_END)

    conversion = convert_vocal_with_rvc(
        sound_set.vocals_path,
        sound_set.job_dir,
        rvc_settings,
        _mapped_progress(
            progress_callback,
            start=SEPARATION_PROGRESS_END,
            end=100,
        ),
    )
    _report(progress_callback, 100)
    return QuickProductionResult(sound_set, conversion, separation)


def _mapped_progress(
    callback: ProgressCallback | None,
    *,
    start: int,
    end: int,
) -> ProgressCallback:
    span = max(0, end - start)
    return lambda value: _report(
        callback,
        start + round(span * max(0, min(100, int(value))) / 100),
    )


def _report(callback: ProgressCallback | None, value: int) -> None:
    if callback is not None:
        callback(max(0, min(100, int(value))))
