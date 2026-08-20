from __future__ import annotations

import shutil
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

import numpy as np
import soundfile as sf

from jang_app.config import ROFORMER_MODEL_DIR, TOOL_WORKSPACE_DIR
from jang_app.pipeline.roformer_engine import (
    build_roformer_command,
    build_roformer_environment,
    build_roformer_progress_callback,
    normalize_deecho_outputs,
    normalize_roformer_effect_outputs,
    require_roformer_tools,
)
from jang_app.pipeline.separation_engine import SeparationError
from jang_app.services.audio_denoise import AudioDenoiseError, render_denoised_audio
from jang_app.services.command import run_command
from jang_app.services.roformer_model_assets import (
    RoFormerModelAssetError,
    prepare_roformer_model_assets,
)
from jang_app.services.separation_recipe import EFFECT_REMOVAL_RECIPE
from jang_app.services.tool_workspace import ToolWorkspace
from jang_app.services.vocal_cleanup import (
    VOCAL_CLEANUP_DEECHO_MODEL,
    VOCAL_CLEANUP_EFFECT_DEECHO,
    VOCAL_CLEANUP_EFFECT_DENOISE,
    VOCAL_CLEANUP_EFFECT_DEREVERB,
    VOCAL_CLEANUP_EFFECTS,
    VocalCleanupProject,
    VocalCleanupRegion,
)
from jang_app.services.vocal_effect_protection import (
    VocalEffectProtectionError,
    protect_effect_removed_vocals,
)


ProgressCallback = Callable[[int], None]
_CONTEXT_MS = 3_000
_EDGE_FADE_MS = 90
_STRENGTH_MIX = {
    "conservative": 0.45,
    "standard": 0.72,
    "strong": 1.0,
}
_DENOISE_STRENGTH = {
    "conservative": 30,
    "standard": 50,
    "strong": 70,
}


class VocalCleanupError(RuntimeError):
    pass


@dataclass(frozen=True)
class VocalCleanupPreview:
    preview_id: str
    start_ms: int
    end_ms: int
    effect: str
    strength: str
    processed_segment_path: Path
    removed_segment_path: Path
    preview_path: Path
    removed_preview_path: Path


def preview_vocal_cleanup(
    source_path: Path,
    job_dir: Path,
    existing_regions: tuple[VocalCleanupRegion, ...],
    *,
    start_ms: int,
    end_ms: int,
    effect: str = VOCAL_CLEANUP_EFFECT_DEREVERB,
    strength: str = "standard",
    progress_callback: ProgressCallback | None = None,
) -> VocalCleanupPreview:
    source = _require_audio(source_path)
    _validate_request(start_ms, end_ms, effect, strength)
    _ensure_no_overlap(existing_regions, start_ms, end_ms)
    preview_id = f"preview-{uuid4().hex[:12]}"
    preview_root = job_dir.expanduser().resolve() / "cleanup" / ".preview" / preview_id
    preview_root.mkdir(parents=True, exist_ok=False)
    processed_segment = preview_root / "processed-segment.wav"
    removed_segment = preview_root / "removed-segment.wav"
    try:
        renderers = {
            VOCAL_CLEANUP_EFFECT_DEREVERB: _render_dereverb_segment,
            VOCAL_CLEANUP_EFFECT_DEECHO: _render_deecho_segment,
            VOCAL_CLEANUP_EFFECT_DENOISE: _render_denoise_segment,
        }
        renderer = renderers[effect]
        renderer(
            source,
            processed_segment,
            removed_segment,
            start_ms=start_ms,
            end_ms=end_ms,
            strength=strength,
            progress_callback=_scaled_progress(progress_callback, 0, 82),
        )
        pending = VocalCleanupRegion(
            region_id=preview_id,
            start_ms=start_ms,
            end_ms=end_ms,
            effect=effect,
            strength=strength,
            processed_segment_path=processed_segment,
            removed_segment_path=removed_segment,
            created_at="",
        )
        preview_path = preview_root / "preview.wav"
        removed_preview_path = preview_root / "removed.wav"
        _compose_audio(
            source,
            (*existing_regions, pending),
            preview_path,
            removed_preview_path,
            progress_callback=_scaled_progress(progress_callback, 82, 100),
        )
    except Exception:
        shutil.rmtree(preview_root, ignore_errors=True)
        raise
    _report(progress_callback, 100)
    return VocalCleanupPreview(
        preview_id=preview_id,
        start_ms=start_ms,
        end_ms=end_ms,
        effect=effect,
        strength=strength,
        processed_segment_path=processed_segment,
        removed_segment_path=removed_segment,
        preview_path=preview_path,
        removed_preview_path=removed_preview_path,
    )


def render_vocal_cleanup(
    project: VocalCleanupProject,
    target_path: Path,
    progress_callback: ProgressCallback | None = None,
) -> Path:
    if not project.regions:
        raise VocalCleanupError("Add at least one cleanup region before creating a result.")
    target = target_path.expanduser().resolve()
    removed_target = target.with_name(f"{target.stem}-removed.wav")
    _compose_audio(
        _require_audio(project.source_path),
        project.regions,
        target,
        removed_target,
        progress_callback=progress_callback,
    )
    removed_target.unlink(missing_ok=True)
    return target


def discard_vocal_cleanup_preview(preview: VocalCleanupPreview | None) -> None:
    if preview is None:
        return
    root = preview.preview_path.parent
    if root.name != preview.preview_id or root.parent.name != ".preview":
        return
    shutil.rmtree(root, ignore_errors=True)


def _render_dereverb_segment(
    source_path: Path,
    processed_target: Path,
    removed_target: Path,
    *,
    start_ms: int,
    end_ms: int,
    strength: str,
    progress_callback: ProgressCallback | None,
) -> None:
    require_roformer_tools()
    source_audio, source_rate = _read_audio(source_path)
    start_frame = _ms_to_frame(start_ms, source_rate)
    end_frame = _ms_to_frame(end_ms, source_rate)
    context_frames = _ms_to_frame(_CONTEXT_MS, source_rate)
    padded_start = max(0, start_frame - context_frames)
    padded_end = min(len(source_audio), end_frame + context_frames)
    padded_audio = source_audio[padded_start:padded_end]
    if padded_audio.size == 0:
        raise VocalCleanupError("The selected vocal range is empty.")

    model = EFFECT_REMOVAL_RECIPE.effect_model
    try:
        prepare_roformer_model_assets(
            model,
            ROFORMER_MODEL_DIR,
            _scaled_progress(progress_callback, 0, 24),
        )
    except RoFormerModelAssetError as exc:
        raise VocalCleanupError(str(exc)) from exc

    with ToolWorkspace(TOOL_WORKSPACE_DIR, "vocalcleanup") as workspace:
        staged_source = workspace.root / "i.wav"
        sf.write(staged_source, padded_audio, source_rate, subtype="FLOAT")
        completed = run_command(
            build_roformer_command(
                staged_source,
                workspace.output_dir,
                EFFECT_REMOVAL_RECIPE,
                model=model,
                model_dir=ROFORMER_MODEL_DIR,
            ),
            env=build_roformer_environment(),
            output_callback=build_roformer_progress_callback(
                _scaled_progress(progress_callback, 24, 82),
                minimum_percent=5,
                maximum_percent=92,
            ),
        )
        if completed.returncode != 0:
            raise VocalCleanupError(
                f"Vocal dereverb failed with exit code {completed.returncode}. See logs for details."
            )
        try:
            dry_path, _effect_path = normalize_roformer_effect_outputs(
                workspace.output_dir
            )
        except SeparationError as exc:
            raise VocalCleanupError(str(exc)) from exc
        dry_audio, dry_rate = _read_audio(dry_path)
        dry_audio = _match_audio_format(
            dry_audio,
            dry_rate,
            source_rate,
            padded_audio.shape[1],
            len(padded_audio),
        )
        aligned_dry_path = workspace.root / "dry-aligned.wav"
        sf.write(aligned_dry_path, dry_audio, source_rate, subtype="FLOAT")
        protected_path = workspace.root / "protected.wav"
        try:
            protect_effect_removed_vocals(
                staged_source,
                aligned_dry_path,
                protected_path,
            )
        except VocalEffectProtectionError as exc:
            raise VocalCleanupError(str(exc)) from exc
        processed_audio, processed_rate = _read_audio(protected_path)

    processed_audio = _match_audio_format(
        processed_audio,
        processed_rate,
        source_rate,
        padded_audio.shape[1],
        len(padded_audio),
    )
    mix = _STRENGTH_MIX[strength]
    processed_audio = padded_audio + (processed_audio - padded_audio) * mix
    core_start = start_frame - padded_start
    core_length = end_frame - start_frame
    processed_core = _match_frame_count(
        processed_audio[core_start : core_start + core_length],
        core_length,
    )
    source_core = source_audio[start_frame:end_frame]
    removed_core = source_core - processed_core
    processed_target.parent.mkdir(parents=True, exist_ok=True)
    sf.write(processed_target, processed_core, source_rate, subtype="FLOAT")
    sf.write(removed_target, removed_core, source_rate, subtype="FLOAT")


def _render_denoise_segment(
    source_path: Path,
    processed_target: Path,
    removed_target: Path,
    *,
    start_ms: int,
    end_ms: int,
    strength: str,
    progress_callback: ProgressCallback | None,
) -> None:
    source_audio, source_rate = _read_audio(source_path)
    start_frame = _ms_to_frame(start_ms, source_rate)
    end_frame = _ms_to_frame(end_ms, source_rate)
    context_frames = _ms_to_frame(_CONTEXT_MS, source_rate)
    padded_start = max(0, start_frame - context_frames)
    padded_end = min(len(source_audio), end_frame + context_frames)
    padded_audio = source_audio[padded_start:padded_end]
    if padded_audio.size == 0:
        raise VocalCleanupError("The selected vocal range is empty.")

    with ToolWorkspace(TOOL_WORKSPACE_DIR, "vocaldenoise") as workspace:
        staged_source = workspace.root / "i.wav"
        denoised_path = workspace.root / "o.wav"
        sf.write(staged_source, padded_audio, source_rate, subtype="FLOAT")
        try:
            render_denoised_audio(
                staged_source,
                denoised_path,
                _DENOISE_STRENGTH[strength],
                progress=_scaled_progress(progress_callback, 4, 94),
            )
        except AudioDenoiseError as exc:
            raise VocalCleanupError(str(exc)) from exc
        denoised_audio, denoised_rate = _read_audio(denoised_path)

    denoised_audio = _match_audio_format(
        denoised_audio,
        denoised_rate,
        source_rate,
        padded_audio.shape[1],
        len(padded_audio),
    )
    core_start = start_frame - padded_start
    core_length = end_frame - start_frame
    processed_core = _match_frame_count(
        denoised_audio[core_start : core_start + core_length],
        core_length,
    )
    source_core = source_audio[start_frame:end_frame]
    removed_core = source_core - processed_core
    processed_target.parent.mkdir(parents=True, exist_ok=True)
    sf.write(processed_target, processed_core, source_rate, subtype="FLOAT")
    sf.write(removed_target, removed_core, source_rate, subtype="FLOAT")
    _report(progress_callback, 100)


def _render_deecho_segment(
    source_path: Path,
    processed_target: Path,
    removed_target: Path,
    *,
    start_ms: int,
    end_ms: int,
    strength: str,
    progress_callback: ProgressCallback | None,
) -> None:
    require_roformer_tools()
    source_audio, source_rate = _read_audio(source_path)
    start_frame = _ms_to_frame(start_ms, source_rate)
    end_frame = _ms_to_frame(end_ms, source_rate)
    context_frames = _ms_to_frame(_CONTEXT_MS, source_rate)
    padded_start = max(0, start_frame - context_frames)
    padded_end = min(len(source_audio), end_frame + context_frames)
    padded_audio = source_audio[padded_start:padded_end]
    if padded_audio.size == 0:
        raise VocalCleanupError("The selected vocal range is empty.")

    try:
        prepare_roformer_model_assets(
            VOCAL_CLEANUP_DEECHO_MODEL,
            ROFORMER_MODEL_DIR,
            _scaled_progress(progress_callback, 0, 24),
        )
    except RoFormerModelAssetError as exc:
        raise VocalCleanupError(str(exc)) from exc

    with ToolWorkspace(TOOL_WORKSPACE_DIR, "vocaldeecho") as workspace:
        staged_source = workspace.root / "i.wav"
        sf.write(staged_source, padded_audio, source_rate, subtype="FLOAT")
        completed = run_command(
            build_roformer_command(
                staged_source,
                workspace.output_dir,
                EFFECT_REMOVAL_RECIPE,
                model=VOCAL_CLEANUP_DEECHO_MODEL,
                model_dir=ROFORMER_MODEL_DIR,
            ),
            env=build_roformer_environment(),
            output_callback=build_roformer_progress_callback(
                _scaled_progress(progress_callback, 24, 82),
                minimum_percent=5,
                maximum_percent=92,
            ),
        )
        if completed.returncode != 0:
            raise VocalCleanupError(
                f"Vocal de-echo failed with exit code {completed.returncode}. "
                "See logs for details."
            )
        try:
            no_echo_path, _echo_path = normalize_deecho_outputs(workspace.output_dir)
        except SeparationError as exc:
            raise VocalCleanupError(str(exc)) from exc
        no_echo_audio, no_echo_rate = _read_audio(no_echo_path)

    no_echo_audio = _match_audio_format(
        no_echo_audio,
        no_echo_rate,
        source_rate,
        padded_audio.shape[1],
        len(padded_audio),
    )
    mix = _STRENGTH_MIX[strength]
    processed_audio = padded_audio + (no_echo_audio - padded_audio) * mix
    core_start = start_frame - padded_start
    core_length = end_frame - start_frame
    processed_core = _match_frame_count(
        processed_audio[core_start : core_start + core_length],
        core_length,
    )
    source_core = source_audio[start_frame:end_frame]
    removed_core = source_core - processed_core
    processed_target.parent.mkdir(parents=True, exist_ok=True)
    sf.write(processed_target, processed_core, source_rate, subtype="FLOAT")
    sf.write(removed_target, removed_core, source_rate, subtype="FLOAT")
    _report(progress_callback, 100)


def _compose_audio(
    source_path: Path,
    regions: Iterable[VocalCleanupRegion],
    processed_target: Path,
    removed_target: Path,
    *,
    progress_callback: ProgressCallback | None,
) -> None:
    source, sample_rate = _read_audio(source_path)
    processed = source.copy()
    removed = np.zeros_like(source)
    ordered = tuple(sorted(regions, key=lambda item: item.start_ms))
    for index, region in enumerate(ordered):
        start = _ms_to_frame(region.start_ms, sample_rate)
        end = min(len(source), _ms_to_frame(region.end_ms, sample_rate))
        frames = max(0, end - start)
        if frames <= 0:
            continue
        segment, segment_rate = _read_audio(region.processed_segment_path)
        segment = _match_audio_format(
            segment,
            segment_rate,
            sample_rate,
            source.shape[1],
            frames,
        )
        weights = _region_weights(frames, sample_rate)[:, None]
        original = source[start:end]
        processed[start:end] = original * (1.0 - weights) + segment * weights
        removed[start:end] = (original - segment) * weights
        _report(progress_callback, round((index + 1) * 90 / max(1, len(ordered))))
    processed_target.parent.mkdir(parents=True, exist_ok=True)
    temporary = processed_target.with_suffix(".rendering.wav")
    removed_temporary = removed_target.with_suffix(".rendering.wav")
    try:
        sf.write(temporary, processed, sample_rate, subtype="FLOAT")
        sf.write(removed_temporary, removed, sample_rate, subtype="FLOAT")
        temporary.replace(processed_target)
        removed_temporary.replace(removed_target)
    finally:
        temporary.unlink(missing_ok=True)
        removed_temporary.unlink(missing_ok=True)
    _report(progress_callback, 100)


def _read_audio(path: Path) -> tuple[np.ndarray, int]:
    try:
        audio, sample_rate = sf.read(
            path.expanduser().resolve(),
            dtype="float32",
            always_2d=True,
        )
    except (OSError, RuntimeError) as exc:
        raise VocalCleanupError(f"Could not read vocal audio: {path}") from exc
    return audio, int(sample_rate)


def _match_audio_format(
    audio: np.ndarray,
    source_rate: int,
    target_rate: int,
    target_channels: int,
    target_frames: int,
) -> np.ndarray:
    if source_rate != target_rate:
        try:
            import torch
            import torchaudio.functional as audio_functional

            tensor = torch.from_numpy(audio.T.copy())
            audio = audio_functional.resample(tensor, source_rate, target_rate).T.numpy()
        except Exception as exc:
            raise VocalCleanupError("Could not restore the vocal sample rate after cleanup.") from exc
    if audio.shape[1] != target_channels:
        if audio.shape[1] == 1:
            audio = np.repeat(audio, target_channels, axis=1)
        elif target_channels == 1:
            audio = np.mean(audio, axis=1, keepdims=True)
        else:
            audio = audio[:, :target_channels]
    return _match_frame_count(audio, target_frames)


def _match_frame_count(audio: np.ndarray, frames: int) -> np.ndarray:
    if len(audio) == frames:
        return audio
    if len(audio) > frames:
        return audio[:frames]
    padding = np.zeros((frames - len(audio), audio.shape[1]), dtype=audio.dtype)
    return np.concatenate((audio, padding), axis=0)


def _region_weights(frames: int, sample_rate: int) -> np.ndarray:
    weights = np.ones(frames, dtype=np.float32)
    fade_frames = min(frames // 2, _ms_to_frame(_EDGE_FADE_MS, sample_rate))
    if fade_frames <= 1:
        return weights
    phase = np.linspace(0.0, np.pi / 2.0, fade_frames, dtype=np.float32)
    fade = np.square(np.sin(phase))
    weights[:fade_frames] = fade
    weights[-fade_frames:] = fade[::-1]
    return weights


def _validate_request(start_ms: int, end_ms: int, effect: str, strength: str) -> None:
    if end_ms - start_ms < 250:
        raise VocalCleanupError("Select at least 0.25 seconds of vocal audio.")
    if effect not in VOCAL_CLEANUP_EFFECTS:
        raise VocalCleanupError(f"Unsupported vocal cleanup effect: {effect}")
    if strength not in _STRENGTH_MIX:
        raise VocalCleanupError(f"Unsupported vocal cleanup strength: {strength}")


def _ensure_no_overlap(
    regions: tuple[VocalCleanupRegion, ...],
    start_ms: int,
    end_ms: int,
) -> None:
    if any(start_ms < region.end_ms and region.start_ms < end_ms for region in regions):
        raise VocalCleanupError("The selected range overlaps another cleanup region.")


def _require_audio(path: Path) -> Path:
    source = path.expanduser().resolve()
    if not source.is_file():
        raise VocalCleanupError("The selected vocal file does not exist.")
    return source


def _ms_to_frame(milliseconds: int, sample_rate: int) -> int:
    return max(0, round(milliseconds * sample_rate / 1_000))


def _scaled_progress(
    callback: ProgressCallback | None,
    minimum: int,
    maximum: int,
) -> ProgressCallback | None:
    if callback is None:
        return None
    span = max(0, maximum - minimum)
    return lambda value: callback(minimum + round(max(0, min(100, value)) * span / 100))


def _report(callback: ProgressCallback | None, value: int) -> None:
    if callback is not None:
        callback(max(0, min(100, int(value))))
