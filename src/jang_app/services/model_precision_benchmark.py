from __future__ import annotations

import json
import math
import tempfile
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import soundfile as sf

from jang_app.services.audio_pitch_analysis import AudioPitchMetrics, analyze_audio_signal
from jang_app.services.managed_files import write_json_atomic
from jang_app.services.pitch_profile import midi_note_name
from jang_app.services.rvc_inference_settings import RvcInferenceSettings
from jang_app.services.rvc_model_workspace import RvcModelRecord
from jang_app.services.settings import RVC_DEVICE_AUTO, RvcSettings
from jang_app.pipeline.rvc_convert import RvcConversionError, convert_vocal_with_rvc


PRECISION_BENCHMARK_SCHEMA_VERSION = 1
PRECISION_BENCHMARK_VERSION = "precision-v1"
PRECISION_BENCHMARK_FILE_NAME = "precision-benchmark.json"
REFERENCE_CENTER_MIDI = 60.0
BENCHMARK_SHIFTS = tuple(range(-24, 25))
STABLE_SCORE_THRESHOLD = 82
USABLE_SCORE_THRESHOLD = 58


class ModelPrecisionBenchmarkError(RuntimeError):
    """Raised when the model precision benchmark cannot be completed."""


@dataclass(frozen=True)
class ModelPrecisionBenchmarkPoint:
    shift_semitones: int
    score: int
    status: str
    pitch_error: float | None
    pitch_bias: float | None
    active_ratio: float
    clipping_ratio: float
    successful_references: int
    total_references: int


@dataclass(frozen=True)
class ModelPrecisionBenchmark:
    model_id: str
    generated_at: str
    benchmark_version: str
    reference_count: int
    total_jobs: int
    successful_jobs: int
    failed_jobs: int
    best_shift_semitones: int | None
    recommended_low_shift: int | None
    recommended_high_shift: int | None
    usable_low_shift: int | None
    usable_high_shift: int | None
    stable_point_count: int
    caution_point_count: int
    avoid_point_count: int
    points: tuple[ModelPrecisionBenchmarkPoint, ...]
    notes: tuple[str, ...]


@dataclass(frozen=True)
class _BenchmarkReference:
    key: str
    label: str
    breath_amount: float
    pulse_depth: float
    pulse_rate: float


@dataclass(frozen=True)
class _ReferenceResult:
    success: bool
    metrics: AudioPitchMetrics | None
    pitch_error: float | None
    pitch_bias: float | None


_REFERENCES = (
    _BenchmarkReference("steady", "steady", 0.010, 0.00, 0.0),
    _BenchmarkReference("pulse", "pulse", 0.015, 0.28, 2.2),
    _BenchmarkReference("airy", "airy", 0.040, 0.08, 0.8),
)


def run_model_precision_benchmark(
    workspace_root: Path,
    record: RvcModelRecord,
    *,
    progress: Callable[[int, int, str], None] | None = None,
    execution_runtime_root: Path | None = None,
) -> ModelPrecisionBenchmark:
    if not record.can_convert or record.inference_model is None:
        raise ModelPrecisionBenchmarkError("This model does not have an inference checkpoint.")
    runtime_root = (
        execution_runtime_root.expanduser().resolve()
        if execution_runtime_root is not None
        else record.runtime_root.expanduser().resolve()
    )
    if not runtime_root.is_dir():
        raise ModelPrecisionBenchmarkError("The selected RVC runtime root does not exist.")

    root = workspace_root.expanduser().resolve()
    reference_paths = _ensure_reference_assets(root)
    total_jobs = len(reference_paths) * len(BENCHMARK_SHIFTS)
    ordered_shifts = _benchmark_shift_order()
    completed_jobs = 0
    successful_jobs = 0
    failed_jobs = 0
    had_success = False
    early_failures = 0
    point_map: dict[int, list[_ReferenceResult]] = {shift: [] for shift in BENCHMARK_SHIFTS}

    cache_dir = _benchmark_cache_dir(root, record.model_id)
    cache_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix="jjzero-model-benchmark-",
        dir=str(cache_dir),
    ) as temporary:
        output_dir = Path(temporary)
        for shift in ordered_shifts:
            for reference in _REFERENCES:
                note = midi_note_name(REFERENCE_CENTER_MIDI + shift)
                label = f"{note} ({shift:+d})  /  {reference.label}"
                result = _run_reference_job(
                    reference_paths[reference.key],
                    reference,
                    output_dir,
                    record,
                    runtime_root,
                    shift,
                )
                point_map[shift].append(result)
                completed_jobs += 1
                if result.success:
                    successful_jobs += 1
                    had_success = True
                else:
                    failed_jobs += 1
                    if not had_success:
                        early_failures += 1
                if progress is not None:
                    progress(completed_jobs, total_jobs, label)
                if not had_success and early_failures >= len(_REFERENCES) * 2:
                    raise ModelPrecisionBenchmarkError(
                        "The selected model could not complete the benchmark conversion."
                    )

    if not had_success:
        raise ModelPrecisionBenchmarkError(
            "The selected model did not produce a usable benchmark render."
        )

    ordered_points = tuple(
        _aggregate_shift_point(shift, tuple(point_map[shift]))
        for shift in BENCHMARK_SHIFTS
    )
    display_best_shift, recommended_range, usable_range = _summary_ranges(ordered_points)
    result = ModelPrecisionBenchmark(
        model_id=record.model_id,
        generated_at=datetime.now(UTC).isoformat(),
        benchmark_version=PRECISION_BENCHMARK_VERSION,
        reference_count=len(_REFERENCES),
        total_jobs=total_jobs,
        successful_jobs=successful_jobs,
        failed_jobs=failed_jobs,
        best_shift_semitones=display_best_shift,
        recommended_low_shift=recommended_range[0],
        recommended_high_shift=recommended_range[1],
        usable_low_shift=usable_range[0],
        usable_high_shift=usable_range[1],
        stable_point_count=sum(point.status == "stable" for point in ordered_points),
        caution_point_count=sum(point.status == "caution" for point in ordered_points),
        avoid_point_count=sum(point.status == "avoid" for point in ordered_points),
        points=ordered_points,
        notes=_build_notes(display_best_shift, recommended_range, usable_range, failed_jobs),
    )
    _write_cache(root, record, result)
    if progress is not None:
        progress(total_jobs, total_jobs, "complete")
    return result


def load_cached_model_precision_benchmark(
    workspace_root: Path,
    record: RvcModelRecord,
) -> ModelPrecisionBenchmark | None:
    cache_path = _cache_path(workspace_root.expanduser().resolve(), record.model_id)
    try:
        data = json.loads(cache_path.read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return None
    if data.get("schema_version") != PRECISION_BENCHMARK_SCHEMA_VERSION:
        return None
    if data.get("benchmark_version") != PRECISION_BENCHMARK_VERSION:
        return None
    if data.get("model_id") != record.model_id:
        return None
    if data.get("model_signature") != _artifact_signature(record.inference_model):
        return None
    if data.get("index_signature") != _artifact_signature(record.index_file):
        return None
    result = data.get("result")
    if not isinstance(result, dict):
        return None
    try:
        return _result_from_data(result)
    except (KeyError, TypeError, ValueError):
        return None


def _run_reference_job(
    reference_path: Path,
    reference: _BenchmarkReference,
    output_dir: Path,
    record: RvcModelRecord,
    runtime_root: Path,
    shift: int,
) -> _ReferenceResult:
    try:
        result = convert_vocal_with_rvc(
            reference_path,
            output_dir,
            RvcSettings(
                root=runtime_root,
                voice_model=str(record.inference_model or ""),
                index_file=str(record.index_file) if record.index_file is not None else "",
                pitch=shift,
                device=record.default_device or RVC_DEVICE_AUTO,
                f0_method="rmvpe",
                inference=RvcInferenceSettings(),
            ),
        )
    except RvcConversionError:
        return _ReferenceResult(False, None, None, None)

    try:
        with sf.SoundFile(result.output_path) as rendered_audio:
            metrics = analyze_audio_signal(rendered_audio)
    except Exception:
        return _ReferenceResult(False, None, None, None)
    pitch_samples = np.asarray(metrics.pitch_midi_samples, dtype=np.float64)
    if pitch_samples.size:
        pitch_center = float(np.median(pitch_samples))
        expected_center = REFERENCE_CENTER_MIDI + shift
        pitch_bias = pitch_center - expected_center
        pitch_error = abs(pitch_bias)
    else:
        pitch_bias = None
        pitch_error = None
    return _ReferenceResult(True, metrics, pitch_error, pitch_bias)


def _aggregate_shift_point(
    shift: int,
    results: tuple[_ReferenceResult, ...],
) -> ModelPrecisionBenchmarkPoint:
    successful = tuple(
        result
        for result in results
        if result.success and result.metrics is not None
    )
    if not successful:
        return ModelPrecisionBenchmarkPoint(
            shift_semitones=shift,
            score=0,
            status="avoid",
            pitch_error=None,
            pitch_bias=None,
            active_ratio=0.0,
            clipping_ratio=0.0,
            successful_references=0,
            total_references=len(results),
        )
    pitch_errors = tuple(
        result.pitch_error
        for result in successful
        if result.pitch_error is not None
    )
    pitch_biases = tuple(
        result.pitch_bias
        for result in successful
        if result.pitch_bias is not None
    )
    active_ratio = float(np.mean([result.metrics.active_ratio for result in successful]))
    clipping_ratio = float(np.mean([result.metrics.clipping_ratio for result in successful]))
    pitch_error = float(np.mean(pitch_errors)) if pitch_errors else None
    pitch_bias = float(np.mean(pitch_biases)) if pitch_biases else None
    score = _score_point(
        pitch_error,
        active_ratio,
        clipping_ratio,
        len(successful),
        len(results),
    )
    if score >= STABLE_SCORE_THRESHOLD:
        status = "stable"
    elif score >= USABLE_SCORE_THRESHOLD:
        status = "caution"
    else:
        status = "avoid"
    return ModelPrecisionBenchmarkPoint(
        shift_semitones=shift,
        score=score,
        status=status,
        pitch_error=pitch_error,
        pitch_bias=pitch_bias,
        active_ratio=active_ratio,
        clipping_ratio=clipping_ratio,
        successful_references=len(successful),
        total_references=len(results),
    )


def _score_point(
    pitch_error: float | None,
    active_ratio: float,
    clipping_ratio: float,
    successful_references: int,
    total_references: int,
) -> int:
    pitch_score = 0.0 if pitch_error is None else max(0.0, 1.0 - (pitch_error / 3.0))
    activity_score = max(0.0, min(1.0, (active_ratio - 0.45) / 0.45))
    clipping_score = max(0.0, 1.0 - min(1.0, clipping_ratio / 0.003))
    completion_score = successful_references / max(1, total_references)
    total = (
        pitch_score * 0.55
        + activity_score * 0.20
        + clipping_score * 0.15
        + completion_score * 0.10
    )
    return max(0, min(100, round(total * 100)))


def _best_point(
    points: tuple[ModelPrecisionBenchmarkPoint, ...],
) -> ModelPrecisionBenchmarkPoint | None:
    if not points:
        return None
    max_score = max(point.score for point in points)
    tied = tuple(point for point in points if point.score >= max_score - 1)
    return min(
        tied,
        key=lambda item: (
            abs(item.shift_semitones),
            -item.score,
            -item.successful_references,
            abs(item.pitch_bias or 0.0),
            item.shift_semitones,
        ),
    )


def _summary_ranges(
    points: tuple[ModelPrecisionBenchmarkPoint, ...],
) -> tuple[int | None, tuple[int | None, int | None], tuple[int | None, int | None]]:
    best_point = _best_point(points)
    anchor = best_point.shift_semitones if best_point is not None else None
    stable_range = _contiguous_range(
        points,
        lambda item: (
            item.score >= STABLE_SCORE_THRESHOLD
            and item.successful_references >= 2
        ),
        anchor=anchor,
    )
    usable_range = _contiguous_range(
        points,
        lambda item: (
            item.score >= USABLE_SCORE_THRESHOLD
            and item.successful_references >= 1
        ),
        anchor=anchor,
    )
    center_shift = _range_center(stable_range)
    if center_shift is None:
        center_shift = anchor
    return center_shift, stable_range, usable_range


def _contiguous_range(
    points: tuple[ModelPrecisionBenchmarkPoint, ...],
    predicate: Callable[[ModelPrecisionBenchmarkPoint], bool],
    *,
    anchor: int | None,
) -> tuple[int | None, int | None]:
    qualifying = {point.shift_semitones for point in points if predicate(point)}
    if not qualifying:
        return (None, None)
    current = anchor if anchor in qualifying else min(qualifying, key=abs)
    low = current
    high = current
    while low - 1 in qualifying:
        low -= 1
    while high + 1 in qualifying:
        high += 1
    return (low, high)


def _build_notes(
    best_shift: int | None,
    recommended_range: tuple[int | None, int | None],
    usable_range: tuple[int | None, int | None],
    failed_jobs: int,
) -> tuple[str, ...]:
    notes: list[str] = [
        "This score uses the same built-in reference vocal for every model.",
        "This benchmark measures pitch-shift stability, not the recorded training range.",
        "Compare this with training material analysis to see the model's recorded range.",
    ]
    if best_shift is None:
        return tuple(notes)
    if best_shift <= -4:
        notes.append("The model stays cleaner when the source is lowered before conversion.")
    elif best_shift >= 4:
        notes.append("The model stays cleaner when the source is raised before conversion.")
    else:
        notes.append("The model is most stable near the original source pitch.")
    if recommended_range[0] is not None and recommended_range[1] is not None:
        width = recommended_range[1] - recommended_range[0] + 1
        if width <= 5:
            notes.append(
                "The recommended pitch window is narrow, so large shifts may lose "
                "quality quickly."
            )
        elif width >= 12:
            notes.append("The model keeps a wide usable shift window in this benchmark.")
    if usable_range[0] is None:
        notes.append("No reliable shift window was detected in the precise benchmark.")
    if failed_jobs:
        notes.append("Some shifts failed to render and were treated as unstable.")
    return tuple(notes)


def _write_cache(
    workspace_root: Path,
    record: RvcModelRecord,
    result: ModelPrecisionBenchmark,
) -> None:
    write_json_atomic(
        _cache_path(workspace_root, record.model_id),
        {
            "schema_version": PRECISION_BENCHMARK_SCHEMA_VERSION,
            "benchmark_version": PRECISION_BENCHMARK_VERSION,
            "model_id": record.model_id,
            "model_signature": _artifact_signature(record.inference_model),
            "index_signature": _artifact_signature(record.index_file),
            "result": _result_to_data(result),
        },
    )


def _result_to_data(result: ModelPrecisionBenchmark) -> dict[str, object]:
    data = asdict(result)
    data["points"] = [asdict(point) for point in result.points]
    data["notes"] = list(result.notes)
    return data


def _result_from_data(data: dict[str, object]) -> ModelPrecisionBenchmark:
    points = tuple(
        ModelPrecisionBenchmarkPoint(
            shift_semitones=int(item["shift_semitones"]),
            score=int(item["score"]),
            status=str(item["status"]),
            pitch_error=_float_or_none(item.get("pitch_error")),
            pitch_bias=_float_or_none(item.get("pitch_bias")),
            active_ratio=float(item["active_ratio"]),
            clipping_ratio=float(item["clipping_ratio"]),
            successful_references=int(item["successful_references"]),
            total_references=int(item["total_references"]),
        )
        for item in data.get("points", ())
        if isinstance(item, dict)
    )
    center_shift, stable_range, usable_range = _summary_ranges(points)
    return ModelPrecisionBenchmark(
        model_id=str(data["model_id"]),
        generated_at=str(data["generated_at"]),
        benchmark_version=str(data["benchmark_version"]),
        reference_count=int(data["reference_count"]),
        total_jobs=int(data["total_jobs"]),
        successful_jobs=int(data["successful_jobs"]),
        failed_jobs=int(data["failed_jobs"]),
        best_shift_semitones=center_shift,
        recommended_low_shift=stable_range[0],
        recommended_high_shift=stable_range[1],
        usable_low_shift=usable_range[0],
        usable_high_shift=usable_range[1],
        stable_point_count=sum(point.status == "stable" for point in points),
        caution_point_count=sum(point.status == "caution" for point in points),
        avoid_point_count=sum(point.status == "avoid" for point in points),
        points=points,
        notes=tuple(str(item) for item in data.get("notes", ()) if isinstance(item, str)),
    )


def _artifact_signature(path: Path | None) -> str:
    if path is None:
        return ""
    resolved = path.expanduser().resolve()
    try:
        stat = resolved.stat()
    except OSError:
        return f"missing:{resolved}"
    return ":".join(
        (
            str(resolved),
            str(stat.st_size),
            str(stat.st_mtime_ns),
        )
    )


def _cache_path(workspace_root: Path, model_id: str) -> Path:
    return _benchmark_cache_dir(workspace_root, model_id) / PRECISION_BENCHMARK_FILE_NAME


def _benchmark_cache_dir(workspace_root: Path, model_id: str) -> Path:
    return workspace_root / model_id / "analysis"


def _reference_asset_dir(workspace_root: Path) -> Path:
    return workspace_root / "_benchmark_assets" / PRECISION_BENCHMARK_VERSION


def _ensure_reference_assets(workspace_root: Path) -> dict[str, Path]:
    asset_dir = _reference_asset_dir(workspace_root)
    asset_dir.mkdir(parents=True, exist_ok=True)
    paths: dict[str, Path] = {}
    for reference in _REFERENCES:
        path = asset_dir / f"{reference.key}.wav"
        if not path.is_file():
            _write_reference_audio(path, reference)
        paths[reference.key] = path
    return paths


def _write_reference_audio(path: Path, reference: _BenchmarkReference) -> None:
    sample_rate = 40_000
    segments = []
    for index in range(3):
        duration = 0.38 if index == 1 else 0.34
        segments.append(
            _synthesize_reference_note(
                sample_rate,
                duration,
                REFERENCE_CENTER_MIDI,
                breath_amount=reference.breath_amount,
                pulse_depth=reference.pulse_depth,
                pulse_rate=reference.pulse_rate,
                seed=index + len(reference.key),
            )
        )
        if index < 2:
            segments.append(np.zeros(round(sample_rate * 0.05), dtype=np.float32))
    audio = np.concatenate(segments)
    peak = float(np.max(np.abs(audio), initial=1e-6))
    normalized = np.clip(audio * (0.68 / peak), -0.95, 0.95)
    path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(path, normalized.astype(np.float32), sample_rate, subtype="PCM_16")


def _synthesize_reference_note(
    sample_rate: int,
    duration: float,
    midi_note: float,
    *,
    breath_amount: float,
    pulse_depth: float,
    pulse_rate: float,
    seed: int,
) -> np.ndarray:
    total = round(sample_rate * duration)
    time = np.arange(total, dtype=np.float64) / sample_rate
    frequency = 440.0 * (2.0 ** ((midi_note - 69.0) / 12.0))
    vibrato = 2.0 ** ((0.14 * np.sin(2 * math.pi * 5.2 * time)) / 12.0)
    phase = 2 * math.pi * np.cumsum(frequency * vibrato) / sample_rate

    formants = (
        (700.0, 140.0, 1.00),
        (1220.0, 180.0, 0.80),
        (2580.0, 260.0, 0.45),
    )
    harmonic_sum = np.zeros(total, dtype=np.float64)
    max_harmonics = max(8, int((sample_rate * 0.45) // frequency))
    for harmonic in range(1, min(max_harmonics, 32) + 1):
        harmonic_frequency = frequency * harmonic
        formant_weight = 0.0
        for center, width, amount in formants:
            distance = (harmonic_frequency - center) / width
            formant_weight += amount * math.exp(-0.5 * (distance**2))
        harmonic_sum += (formant_weight + 0.08) * np.sin(phase * harmonic) / harmonic

    envelope = _adsr_envelope(total, attack=0.06, decay=0.12, sustain=0.82, release=0.10)
    if pulse_depth > 0.0 and pulse_rate > 0.0:
        pulse = 1.0 - (pulse_depth * 0.5) + (
            pulse_depth * 0.5 * np.sin(2 * math.pi * pulse_rate * time)
        )
    else:
        pulse = np.ones_like(time)
    rng = np.random.default_rng(seed)
    breath = rng.normal(0.0, 1.0, total)
    breath = np.convolve(breath, np.ones(11, dtype=np.float64) / 11.0, mode="same")
    audio = (harmonic_sum * pulse + breath * breath_amount) * envelope
    return audio.astype(np.float32)


def _adsr_envelope(
    total: int,
    *,
    attack: float,
    decay: float,
    sustain: float,
    release: float,
) -> np.ndarray:
    attack_count = max(1, round(total * attack))
    decay_count = max(1, round(total * decay))
    release_count = max(1, round(total * release))
    sustain_count = max(1, total - attack_count - decay_count - release_count)
    attack_curve = np.linspace(0.0, 1.0, attack_count, endpoint=False)
    decay_curve = np.linspace(1.0, sustain, decay_count, endpoint=False)
    sustain_curve = np.full(sustain_count, sustain, dtype=np.float64)
    release_curve = np.linspace(sustain, 0.0, release_count)
    envelope = np.concatenate((attack_curve, decay_curve, sustain_curve, release_curve))
    if len(envelope) < total:
        envelope = np.pad(envelope, (0, total - len(envelope)), constant_values=0.0)
    return envelope[:total]


def _benchmark_shift_order() -> tuple[int, ...]:
    ordered = [0]
    for offset in range(1, 25):
        ordered.append(-offset)
        ordered.append(offset)
    return tuple(ordered)


def _range_center(value: tuple[int | None, int | None]) -> int | None:
    low, high = value
    if low is None or high is None:
        return None
    return round((low + high) / 2)


def _float_or_none(value: object) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None
