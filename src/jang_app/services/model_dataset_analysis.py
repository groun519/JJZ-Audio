from __future__ import annotations

import json
import math
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import soundfile as sf

from jang_app.services.audio_preview import prepare_preview_audio
from jang_app.services.clip_edit_history import REVIEW_READY, TRAINING_MODE_CLIPS
from jang_app.services.managed_files import file_sha256, write_json_atomic
from jang_app.services.model_dataset import (
    ModelDatasetClip,
    ModelDatasetItem,
    ModelDatasetStore,
)


ANALYSIS_SCHEMA_VERSION = 4
ANALYSIS_FILE_NAME = "dataset-analysis.json"
_FRAME_MS = 50
_SILENCE_FLOOR_DB = -55.0
_MAX_PITCH_SAMPLES = 3000


class ModelDatasetAnalysisError(RuntimeError):
    """Raised when training material statistics cannot be calculated."""


@dataclass(frozen=True)
class DatasetAnalysisIssue:
    code: str
    severity: str
    message: str
    item_id: str = ""
    clip_id: str = ""
    source_name: str = ""
    start_ms: int = 0
    end_ms: int = 0


@dataclass(frozen=True)
class DatasetAssetAnalysis:
    asset_id: str
    item_id: str
    clip_id: str
    source_name: str
    start_ms: int
    end_ms: int
    duration_ms: int
    active_ratio: float
    rms_db: float
    peak_db: float
    clipping_ratio: float
    noise_floor_db: float | None
    signal_contrast_db: float | None
    pitch_midi_samples: tuple[float, ...]


@dataclass(frozen=True)
class PitchHistogramBin:
    midi_note: int
    note_name: str
    count: int


@dataclass(frozen=True)
class PitchCoverageRange:
    low_midi: int
    high_midi: int
    sample_ratio: float


@dataclass(frozen=True)
class ModelDatasetAnalysis:
    model_id: str
    generated_at: str
    selected_item_count: int
    ready_item_count: int
    asset_count: int
    cached_asset_count: int
    duration_ms: int
    active_ratio: float
    rms_db: float
    peak_db: float
    clipping_ratio: float
    noise_floor_db: float | None
    signal_contrast_db: float | None
    pitch_low_midi: float | None
    pitch_median_midi: float | None
    pitch_high_midi: float | None
    pitch_center_midi: float | None
    pitch_histogram: tuple[PitchHistogramBin, ...]
    pitch_coverage_ranges: tuple[PitchCoverageRange, ...]
    issues: tuple[DatasetAnalysisIssue, ...]
    assets: tuple[DatasetAssetAnalysis, ...]

    @property
    def attention_count(self) -> int:
        return sum(issue.severity == "attention" for issue in self.issues)


@dataclass(frozen=True)
class _TrainingAsset:
    asset_id: str
    item_id: str
    clip_id: str
    source_name: str
    path: Path
    start_ms: int
    end_ms: int


def analyze_model_dataset(
    store: ModelDatasetStore,
    model_id: str,
    *,
    progress: Callable[[int], None] | None = None,
) -> ModelDatasetAnalysis:
    dataset = store.load(model_id)
    assets = _training_assets(dataset.training_items)
    cache_path = _cache_path(store, model_id)
    cached = _load_cache_entries(cache_path)
    analyzed: list[DatasetAssetAnalysis] = []
    cache_entries: dict[str, dict[str, object]] = {}
    cached_count = 0

    _report(progress, 0)
    for index, asset in enumerate(assets):
        fingerprint = _asset_fingerprint(asset)
        entry = cached.get(asset.asset_id)
        analysis = _analysis_from_cache(entry, fingerprint)
        if analysis is None:
            analysis = _analyze_asset(asset)
        else:
            cached_count += 1
        analyzed.append(analysis)
        cache_entries[asset.asset_id] = {
            "fingerprint": fingerprint,
            "analysis": _asset_to_data(analysis),
        }
        _report(progress, round((index + 1) * 92 / max(1, len(assets))))

    report = _aggregate_analysis(
        model_id,
        dataset.training_items,
        tuple(analyzed),
        cached_count,
    )
    write_json_atomic(
        cache_path,
        {
            "schema_version": ANALYSIS_SCHEMA_VERSION,
            "model_id": model_id,
            "generated_at": report.generated_at,
            "entries": cache_entries,
            "report": _report_to_data(report),
        },
    )
    _report(progress, 100)
    return report


def load_cached_model_dataset_analysis(
    store: ModelDatasetStore,
    model_id: str,
) -> ModelDatasetAnalysis | None:
    path = _cache_path(store, model_id)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if (
            data.get("schema_version") != ANALYSIS_SCHEMA_VERSION
            or data.get("model_id") != model_id
            or not isinstance(data.get("report"), dict)
        ):
            return None
        return _report_from_data(data["report"])
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return None


def midi_note_name(value: float | int | None) -> str:
    if value is None or not math.isfinite(float(value)):
        return "-"
    midi = int(round(float(value)))
    names = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")
    return f"{names[midi % 12]}{midi // 12 - 1}"


def _training_assets(items: tuple[ModelDatasetItem, ...]) -> tuple[_TrainingAsset, ...]:
    assets: list[_TrainingAsset] = []
    for item in items:
        if item.training_mode == TRAINING_MODE_CLIPS:
            assets.extend(_clip_asset(item, clip) for clip in item.clips if clip.path.is_file())
            continue
        if item.active_audio_path.is_file():
            assets.append(
                _TrainingAsset(
                    asset_id=f"{item.item_id}:full",
                    item_id=item.item_id,
                    clip_id="",
                    source_name=item.source_name,
                    path=item.active_audio_path,
                    start_ms=0,
                    end_ms=item.duration_ms,
                )
            )
    return tuple(assets)


def _clip_asset(item: ModelDatasetItem, clip: ModelDatasetClip) -> _TrainingAsset:
    return _TrainingAsset(
        asset_id=f"{item.item_id}:{clip.clip_id}",
        item_id=item.item_id,
        clip_id=clip.clip_id,
        source_name=item.source_name,
        path=clip.path,
        start_ms=clip.start_ms,
        end_ms=clip.end_ms,
    )


def _asset_fingerprint(asset: _TrainingAsset) -> str:
    try:
        digest = file_sha256(asset.path)
    except OSError as exc:
        raise ModelDatasetAnalysisError(f"Training audio cannot be read: {asset.path}") from exc
    return ":".join(
        (
            str(ANALYSIS_SCHEMA_VERSION),
            digest,
            str(asset.start_ms),
            str(asset.end_ms),
        )
    )


def _analyze_asset(asset: _TrainingAsset) -> DatasetAssetAnalysis:
    try:
        preview = prepare_preview_audio(asset.path)
        with sf.SoundFile(preview) as audio:
            if audio.samplerate <= 0 or len(audio) <= 0:
                raise ModelDatasetAnalysisError(f"Training audio is empty: {asset.path}")
            metrics = _stream_audio_metrics(audio)
    except ModelDatasetAnalysisError:
        raise
    except Exception as exc:
        raise ModelDatasetAnalysisError(f"Training audio analysis failed: {asset.path}") from exc
    return DatasetAssetAnalysis(
        asset_id=asset.asset_id,
        item_id=asset.item_id,
        clip_id=asset.clip_id,
        source_name=asset.source_name,
        start_ms=asset.start_ms,
        end_ms=asset.end_ms,
        **metrics,
    )


def _stream_audio_metrics(audio: sf.SoundFile) -> dict[str, object]:
    sample_rate = audio.samplerate
    frame_size = max(1, round(sample_rate * _FRAME_MS / 1000))
    expected_frames = max(1, math.ceil(len(audio) / frame_size))
    pitch_stride = max(2, math.ceil(expected_frames / _MAX_PITCH_SAMPLES))
    carry = np.empty(0, dtype=np.float32)
    frame_levels: list[float] = []
    pitch_candidates: list[tuple[float, float]] = []
    sample_count = 0
    clipping_count = 0
    square_sum = 0.0
    peak = 0.0
    frame_index = 0
    previous_pitch_frame: np.ndarray | None = None

    while True:
        block = audio.read(frame_size * 256, always_2d=True, dtype="float32")
        if block.size == 0:
            break
        mono = np.mean(block, axis=1, dtype=np.float32)
        sample_count += len(mono)
        clipping_count += int(np.count_nonzero(np.abs(mono) >= 0.999))
        square_sum += float(np.sum(np.square(mono, dtype=np.float64)))
        peak = max(peak, float(np.max(np.abs(mono), initial=0.0)))
        if carry.size:
            mono = np.concatenate((carry, mono))
        complete = len(mono) // frame_size
        if complete:
            frames = mono[: complete * frame_size].reshape(complete, frame_size)
            rms = np.sqrt(np.mean(np.square(frames, dtype=np.float64), axis=1))
            levels = 20 * np.log10(np.maximum(rms, 1e-9))
            frame_levels.extend(float(level) for level in levels)
            for local_index, frame in enumerate(frames):
                absolute_index = frame_index + local_index
                pitch_frame = (
                    np.concatenate((previous_pitch_frame, frame))
                    if previous_pitch_frame is not None
                    else frame
                )
                previous_pitch_frame = frame.copy()
                if absolute_index % pitch_stride or levels[local_index] < _SILENCE_FLOOR_DB:
                    continue
                pitch = _estimate_pitch_midi(pitch_frame, sample_rate)
                if pitch is not None:
                    pitch_candidates.append((float(levels[local_index]), pitch))
            frame_index += complete
        carry = mono[complete * frame_size :].copy()

    if carry.size:
        padded = np.pad(carry, (0, frame_size - len(carry)))
        rms = float(np.sqrt(np.mean(np.square(padded, dtype=np.float64))))
        level = 20 * math.log10(max(rms, 1e-9))
        frame_levels.append(level)
        if frame_index % pitch_stride == 0 and level >= _SILENCE_FLOOR_DB:
            pitch_frame = (
                np.concatenate((previous_pitch_frame, padded))
                if previous_pitch_frame is not None
                else padded
            )
            pitch = _estimate_pitch_midi(pitch_frame, sample_rate)
            if pitch is not None:
                pitch_candidates.append((level, pitch))

    if sample_count <= 0 or not frame_levels:
        raise ModelDatasetAnalysisError("Training audio contains no readable samples.")
    levels = np.asarray(frame_levels, dtype=np.float64)
    upper_level = float(np.percentile(levels, 90))
    active_threshold = max(_SILENCE_FLOOR_DB, min(-35.0, upper_level - 25.0))
    active = levels >= active_threshold
    active_levels = levels[active]
    inactive_levels = levels[~active]
    has_quiet_reference = inactive_levels.size >= max(3, math.ceil(len(levels) * 0.05))
    noise_floor = max(-100.0, float(np.median(inactive_levels))) if has_quiet_reference else None
    signal_level = float(np.median(active_levels)) if active_levels.size else None
    signal_contrast = (
        min(80.0, max(0.0, signal_level - noise_floor))
        if signal_level is not None and noise_floor is not None
        else None
    )
    pitch_samples = _correct_isolated_octave_errors(
        tuple(
            pitch
            for level, pitch in pitch_candidates
            if level >= active_threshold
        )
    )
    rms = math.sqrt(square_sum / sample_count)
    return {
        "duration_ms": round(sample_count * 1000 / sample_rate),
        "active_ratio": float(np.count_nonzero(active) / len(levels)),
        "rms_db": 20 * math.log10(max(rms, 1e-9)),
        "peak_db": 20 * math.log10(max(peak, 1e-9)),
        "clipping_ratio": clipping_count / sample_count,
        "noise_floor_db": noise_floor,
        "signal_contrast_db": signal_contrast,
        "pitch_midi_samples": pitch_samples,
    }


def _estimate_pitch_midi(frame: np.ndarray, sample_rate: int) -> float | None:
    stride = max(1, round(sample_rate / 16000))
    signal = np.asarray(frame[::stride], dtype=np.float64)
    effective_rate = sample_rate / stride
    signal -= np.mean(signal)
    energy = float(np.dot(signal, signal))
    if energy <= 1e-8:
        return None
    signal *= np.hanning(len(signal))
    fft_size = 1 << max(1, (len(signal) * 2 - 1).bit_length())
    spectrum = np.fft.rfft(signal, fft_size)
    correlation = np.fft.irfft(spectrum * np.conjugate(spectrum), fft_size)[: len(signal)]
    if correlation[0] <= 0:
        return None
    min_lag = max(1, math.floor(effective_rate / 1100))
    max_lag = min(len(correlation) - 1, math.ceil(effective_rate / 65))
    if max_lag <= min_lag:
        return None
    search = correlation[min_lag : max_lag + 1]
    lag = min_lag + int(np.argmax(search))
    confidence = float(correlation[lag] / correlation[0])
    if confidence < 0.30:
        return None
    frequency = effective_rate / lag
    if not 65 <= frequency <= 1100:
        return None
    return 69.0 + 12.0 * math.log2(frequency / 440.0)


def _correct_isolated_octave_errors(values: tuple[float, ...]) -> tuple[float, ...]:
    if len(values) < 5:
        return values
    corrected = list(values)
    for index in range(2, len(values) - 2):
        neighbors = np.asarray(
            (*values[index - 2 : index], *values[index + 1 : index + 3]),
            dtype=np.float64,
        )
        if float(np.ptp(neighbors)) > 4.0:
            continue
        reference = float(np.median(neighbors))
        original = values[index]
        candidates = (original - 12.0, original + 12.0)
        replacement = min(candidates, key=lambda value: abs(value - reference))
        if 9.0 <= abs(original - reference) <= 15.0 and abs(replacement - reference) <= 2.5:
            corrected[index] = replacement
    return tuple(corrected)


def _aggregate_analysis(
    model_id: str,
    items: tuple[ModelDatasetItem, ...],
    assets: tuple[DatasetAssetAnalysis, ...],
    cached_count: int,
) -> ModelDatasetAnalysis:
    duration = sum(asset.duration_ms for asset in assets)
    weights = np.asarray([asset.duration_ms for asset in assets], dtype=np.float64)
    pitch = np.asarray(
        [value for asset in assets for value in asset.pitch_midi_samples],
        dtype=np.float64,
    )
    pitch_low = float(np.percentile(pitch, 5)) if pitch.size else None
    pitch_median = float(np.percentile(pitch, 50)) if pitch.size else None
    pitch_high = float(np.percentile(pitch, 95)) if pitch.size else None
    pitch_histogram = _pitch_histogram(pitch)
    coverage_ranges = pitch_coverage_ranges(pitch_histogram)
    pitch_center = _primary_pitch_center(pitch, coverage_ranges)
    if pitch_center is None:
        pitch_center = pitch_median
    issues = [issue for asset in assets for issue in _asset_issues(asset)]

    if not assets:
        issues.append(
            DatasetAnalysisIssue(
                "no_training_audio",
                "attention",
                "Add audio to the training set before analyzing it.",
            )
        )
    elif duration < 10 * 60 * 1000:
        issues.append(
            DatasetAnalysisIssue(
                "limited_duration",
                "info",
                "The selected material is under 10 minutes. More varied clean recordings may improve coverage.",
            )
        )
    if assets and pitch.size < 30:
        issues.append(
            DatasetAnalysisIssue(
                "limited_pitch_data",
                "info",
                "Not enough stable pitch frames were found to describe the vocal range.",
            )
        )
    elif coverage_ranges and coverage_ranges[0].high_midi - coverage_ranges[0].low_midi < 7:
        issues.append(
            DatasetAnalysisIssue(
                "narrow_pitch_coverage",
                "info",
                "Most detected pitch is concentrated inside a narrow range.",
            )
        )

    return ModelDatasetAnalysis(
        model_id=model_id,
        generated_at=datetime.now(UTC).isoformat(),
        selected_item_count=len(items),
        ready_item_count=sum(item.review_state == REVIEW_READY for item in items),
        asset_count=len(assets),
        cached_asset_count=cached_count,
        duration_ms=duration,
        active_ratio=_weighted_average(assets, weights, "active_ratio"),
        rms_db=_combined_rms_db(assets, weights),
        peak_db=max((asset.peak_db for asset in assets), default=-180.0),
        clipping_ratio=_weighted_average(assets, weights, "clipping_ratio"),
        noise_floor_db=_weighted_optional_average(assets, weights, "noise_floor_db"),
        signal_contrast_db=_weighted_optional_average(assets, weights, "signal_contrast_db"),
        pitch_low_midi=pitch_low,
        pitch_median_midi=pitch_median,
        pitch_high_midi=pitch_high,
        pitch_center_midi=pitch_center,
        pitch_histogram=pitch_histogram,
        pitch_coverage_ranges=coverage_ranges,
        issues=tuple(issues),
        assets=assets,
    )


def _asset_issues(asset: DatasetAssetAnalysis) -> tuple[DatasetAnalysisIssue, ...]:
    common = {
        "item_id": asset.item_id,
        "clip_id": asset.clip_id,
        "source_name": asset.source_name,
        "start_ms": asset.start_ms,
        "end_ms": asset.end_ms,
    }
    issues: list[DatasetAnalysisIssue] = []
    if asset.duration_ms < 1000:
        issues.append(DatasetAnalysisIssue("clip_too_short", "attention", "This clip is shorter than 1 second.", **common))
    if asset.duration_ms > 15_000 and asset.clip_id:
        issues.append(DatasetAnalysisIssue("clip_too_long", "info", "This clip is longer than 15 seconds.", **common))
    if asset.active_ratio < 0.65:
        issues.append(DatasetAnalysisIssue("excess_silence", "attention", "A large part of this material is silent.", **common))
    if asset.clipping_ratio > 0.001:
        issues.append(DatasetAnalysisIssue("clipping", "attention", "Clipped samples were detected.", **common))
    if asset.rms_db < -35:
        issues.append(DatasetAnalysisIssue("too_quiet", "info", "The average level is very low.", **common))
    if asset.rms_db > -6:
        issues.append(DatasetAnalysisIssue("too_loud", "info", "The average level is unusually high.", **common))
    if asset.signal_contrast_db is not None and asset.signal_contrast_db < 10:
        issues.append(DatasetAnalysisIssue("low_signal_contrast", "attention", "Voice and background level are not clearly separated.", **common))
    return tuple(issues)


def _weighted_average(
    assets: tuple[DatasetAssetAnalysis, ...],
    weights: np.ndarray,
    attribute: str,
    default: float = 0.0,
) -> float:
    if not assets or not np.sum(weights):
        return default
    values = np.asarray([getattr(asset, attribute) for asset in assets], dtype=np.float64)
    return float(np.average(values, weights=weights))


def _combined_rms_db(
    assets: tuple[DatasetAssetAnalysis, ...],
    weights: np.ndarray,
) -> float:
    if not assets or not np.sum(weights):
        return -180.0
    powers = np.asarray([10 ** (asset.rms_db / 10) for asset in assets], dtype=np.float64)
    return 10 * math.log10(max(float(np.average(powers, weights=weights)), 1e-18))


def _weighted_optional_average(
    assets: tuple[DatasetAssetAnalysis, ...],
    weights: np.ndarray,
    attribute: str,
) -> float | None:
    available = tuple(
        (index, float(value))
        for index, asset in enumerate(assets)
        if (value := getattr(asset, attribute)) is not None
    )
    if not available:
        return None
    indexes = np.asarray([index for index, _value in available], dtype=np.int64)
    values = np.asarray([value for _index, value in available], dtype=np.float64)
    selected_weights = weights[indexes]
    if not np.sum(selected_weights):
        return float(np.mean(values))
    return float(np.average(values, weights=selected_weights))


def _pitch_histogram(pitch: np.ndarray) -> tuple[PitchHistogramBin, ...]:
    if not pitch.size:
        return ()
    low = max(0, math.floor(float(np.percentile(pitch, 1))))
    high = min(127, math.ceil(float(np.percentile(pitch, 99))))
    rounded = np.rint(pitch).astype(np.int16)
    return tuple(
        PitchHistogramBin(note, midi_note_name(note), int(np.count_nonzero(rounded == note)))
        for note in range(low, high + 1)
    )


def pitch_coverage_ranges(
    histogram: tuple[PitchHistogramBin, ...],
) -> tuple[PitchCoverageRange, ...]:
    if not histogram:
        return ()
    counts = np.asarray([item.count for item in histogram], dtype=np.float64)
    total = float(np.sum(counts))
    if total <= 0:
        return ()
    smoothed = np.convolve(
        np.pad(counts, (1, 1)),
        np.asarray((0.25, 0.5, 0.25)),
        mode="valid",
    )
    threshold = max(1.0, float(np.max(smoothed)) * 0.15)
    covered = smoothed >= threshold
    _bridge_short_pitch_gaps(covered, max_gap=2)

    ranges: list[PitchCoverageRange] = []
    start: int | None = None
    for index, is_covered in enumerate((*covered, False)):
        if is_covered and start is None:
            start = index
            continue
        if is_covered or start is None:
            continue
        end = index - 1
        dense = np.flatnonzero(
            counts[start : end + 1] >= max(1.0, threshold * 0.5)
        )
        if dense.size:
            low_index = start + int(dense[0])
            high_index = start + int(dense[-1])
            sample_count = float(np.sum(counts[low_index : high_index + 1]))
            sample_ratio = sample_count / total
            if sample_ratio >= 0.03:
                ranges.append(
                    PitchCoverageRange(
                        histogram[low_index].midi_note,
                        histogram[high_index].midi_note,
                        sample_ratio,
                    )
                )
        start = None
    return tuple(
        sorted(
            ranges,
            key=lambda item: (
                -item.sample_ratio,
                item.low_midi,
            ),
        )[:3]
    )


def _bridge_short_pitch_gaps(covered: np.ndarray, *, max_gap: int) -> None:
    index = 1
    while index < len(covered) - 1:
        if covered[index]:
            index += 1
            continue
        start = index
        while index < len(covered) and not covered[index]:
            index += 1
        if (
            start > 0
            and index < len(covered)
            and covered[start - 1]
            and covered[index]
            and index - start <= max_gap
        ):
            covered[start:index] = True


def recommended_pitch_shift(model_center_midi: float, source_center_midi: float) -> int:
    return round(model_center_midi - source_center_midi)


def _primary_pitch_center(
    pitch: np.ndarray,
    ranges: tuple[PitchCoverageRange, ...],
) -> float | None:
    if not pitch.size or not ranges:
        return None
    primary = ranges[0]
    selected = pitch[
        (pitch >= primary.low_midi - 0.5)
        & (pitch <= primary.high_midi + 0.5)
    ]
    return float(np.median(selected)) if selected.size else None


def _load_cache_entries(path: Path) -> dict[str, object]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    entries = data.get("entries")
    if data.get("schema_version") != ANALYSIS_SCHEMA_VERSION or not isinstance(entries, dict):
        return {}
    return entries


def _analysis_from_cache(
    entry: object,
    fingerprint: str,
) -> DatasetAssetAnalysis | None:
    if not isinstance(entry, dict) or entry.get("fingerprint") != fingerprint:
        return None
    analysis = entry.get("analysis")
    if not isinstance(analysis, dict):
        return None
    try:
        return _asset_from_data(analysis)
    except (KeyError, TypeError, ValueError):
        return None


def _cache_path(store: ModelDatasetStore, model_id: str) -> Path:
    return store.root / model_id / "analysis" / ANALYSIS_FILE_NAME


def _asset_to_data(asset: DatasetAssetAnalysis) -> dict[str, object]:
    data = asdict(asset)
    data["pitch_midi_samples"] = list(asset.pitch_midi_samples)
    return data


def _asset_from_data(data: dict[str, object]) -> DatasetAssetAnalysis:
    return DatasetAssetAnalysis(
        asset_id=str(data["asset_id"]),
        item_id=str(data["item_id"]),
        clip_id=str(data.get("clip_id", "")),
        source_name=str(data["source_name"]),
        start_ms=int(data.get("start_ms", 0)),
        end_ms=int(data.get("end_ms", 0)),
        duration_ms=int(data["duration_ms"]),
        active_ratio=float(data["active_ratio"]),
        rms_db=float(data["rms_db"]),
        peak_db=float(data["peak_db"]),
        clipping_ratio=float(data["clipping_ratio"]),
        noise_floor_db=_optional_float(data.get("noise_floor_db")),
        signal_contrast_db=_optional_float(data.get("signal_contrast_db")),
        pitch_midi_samples=tuple(float(value) for value in data.get("pitch_midi_samples", ())),
    )


def _report_to_data(report: ModelDatasetAnalysis) -> dict[str, object]:
    data = asdict(report)
    data["pitch_histogram"] = [asdict(item) for item in report.pitch_histogram]
    data["pitch_coverage_ranges"] = [
        asdict(item) for item in report.pitch_coverage_ranges
    ]
    data["issues"] = [asdict(item) for item in report.issues]
    data["assets"] = [_asset_to_data(item) for item in report.assets]
    return data


def _report_from_data(data: dict[str, object]) -> ModelDatasetAnalysis:
    pitch_histogram = tuple(
        PitchHistogramBin(
            int(item["midi_note"]),
            str(item["note_name"]),
            int(item["count"]),
        )
        for item in data.get("pitch_histogram", ())
        if isinstance(item, dict)
    )
    coverage_ranges = tuple(
        PitchCoverageRange(
            int(item["low_midi"]),
            int(item["high_midi"]),
            float(item["sample_ratio"]),
        )
        for item in data.get("pitch_coverage_ranges", ())
        if isinstance(item, dict)
    ) or pitch_coverage_ranges(pitch_histogram)
    pitch_median = _optional_float(data.get("pitch_median_midi"))
    return ModelDatasetAnalysis(
        model_id=str(data["model_id"]),
        generated_at=str(data["generated_at"]),
        selected_item_count=int(data["selected_item_count"]),
        ready_item_count=int(data["ready_item_count"]),
        asset_count=int(data["asset_count"]),
        cached_asset_count=int(data.get("cached_asset_count", 0)),
        duration_ms=int(data["duration_ms"]),
        active_ratio=float(data["active_ratio"]),
        rms_db=float(data["rms_db"]),
        peak_db=float(data["peak_db"]),
        clipping_ratio=float(data["clipping_ratio"]),
        noise_floor_db=_optional_float(data.get("noise_floor_db")),
        signal_contrast_db=_optional_float(data.get("signal_contrast_db")),
        pitch_low_midi=_optional_float(data.get("pitch_low_midi")),
        pitch_median_midi=pitch_median,
        pitch_high_midi=_optional_float(data.get("pitch_high_midi")),
        pitch_center_midi=(
            _optional_float(data.get("pitch_center_midi"))
            if data.get("pitch_center_midi") is not None
            else pitch_median
        ),
        pitch_histogram=pitch_histogram,
        pitch_coverage_ranges=coverage_ranges,
        issues=tuple(
            DatasetAnalysisIssue(
                code=str(item["code"]),
                severity=str(item["severity"]),
                message=str(item["message"]),
                item_id=str(item.get("item_id", "")),
                clip_id=str(item.get("clip_id", "")),
                source_name=str(item.get("source_name", "")),
                start_ms=int(item.get("start_ms", 0)),
                end_ms=int(item.get("end_ms", 0)),
            )
            for item in data.get("issues", ())
            if isinstance(item, dict)
        ),
        assets=tuple(
            _asset_from_data(item)
            for item in data.get("assets", ())
            if isinstance(item, dict)
        ),
    )


def _optional_float(value: object) -> float | None:
    return None if value is None else float(value)


def _report(progress: Callable[[int], None] | None, value: int) -> None:
    if progress is not None:
        progress(max(0, min(100, int(value))))
