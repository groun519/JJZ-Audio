from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import soundfile as sf

from jang_app.services.audio_pitch_analysis import analyze_audio_signal
from jang_app.services.managed_files import write_json_atomic
from jang_app.services.model_dataset import DATASET_MANIFEST_NAME, ModelDatasetStore
from jang_app.services.model_dataset_analysis import (
    ANALYSIS_FILE_NAME,
    ModelDatasetAnalysis,
)
from jang_app.services.model_precision_benchmark import (
    REFERENCE_CENTER_MIDI,
    ModelPrecisionBenchmark,
)
from jang_app.services.pitch_profile import (
    pitch_coverage_ranges,
    pitch_histogram,
    recommended_pitch_shift,
)


PITCH_CACHE_SCHEMA_VERSION = 2
MINIMUM_PITCH_SAMPLES = 12
LARGE_PITCH_SHIFT = 12
PITCH_RANGE_LOW_PERCENTILE = 5
PITCH_RANGE_HIGH_PERCENTILE = 95


class PitchRecommendationError(RuntimeError):
    """Raised when an audio file cannot produce a trustworthy pitch profile."""


@dataclass(frozen=True)
class PitchRangeProfile:
    low_midi: float
    center_midi: float
    high_midi: float
    sample_count: int = 0


@dataclass(frozen=True)
class VocalPitchAnalysis:
    source_path: Path
    source_size: int
    source_mtime_ns: int
    generated_at: str
    profile: PitchRangeProfile


@dataclass(frozen=True)
class PitchRecommendation:
    source: PitchRangeProfile
    model: PitchRangeProfile
    pitch: int
    overlap_ratio: float
    is_large_shift: bool
    recommended_low_pitch: int | None = None
    recommended_high_pitch: int | None = None

    @property
    def has_recommended_range(self) -> bool:
        return (
            self.recommended_low_pitch is not None
            and self.recommended_high_pitch is not None
        )

    def contains_pitch(self, pitch: int) -> bool:
        if not self.has_recommended_range:
            return False
        assert self.recommended_low_pitch is not None
        assert self.recommended_high_pitch is not None
        return self.recommended_low_pitch <= pitch <= self.recommended_high_pitch

    @property
    def shifted_source_low_midi(self) -> float:
        return self.source.low_midi + self.pitch

    @property
    def shifted_source_high_midi(self) -> float:
        return self.source.high_midi + self.pitch


@dataclass(frozen=True)
class PitchRecommendationResult:
    recommendation: PitchRecommendation | None
    message_key: str = ""


class VocalPitchAnalysisCache:
    def __init__(self, root: Path, *, maximum_entries: int = 128) -> None:
        self.root = root.expanduser().resolve()
        self.maximum_entries = max(8, int(maximum_entries))

    def get_or_analyze(self, source_path: Path) -> VocalPitchAnalysis:
        source = source_path.expanduser().resolve()
        try:
            stat = source.stat()
        except OSError as exc:
            raise PitchRecommendationError(f"Vocal input cannot be read: {source}") from exc
        if not source.is_file():
            raise PitchRecommendationError(f"Vocal input does not exist: {source}")

        cache_path = self._cache_path(source)
        cached = _load_cached_analysis(cache_path, source, stat.st_size, stat.st_mtime_ns)
        if cached is not None:
            return cached

        analysis = analyze_vocal_pitch(source)
        self.root.mkdir(parents=True, exist_ok=True)
        write_json_atomic(cache_path, _analysis_to_data(analysis))
        self._prune()
        return analysis

    def _cache_path(self, source: Path) -> Path:
        key = hashlib.sha256(str(source).casefold().encode("utf-8")).hexdigest()
        return self.root / f"{key}.json"

    def _prune(self) -> None:
        try:
            entries = sorted(
                self.root.glob("*.json"),
                key=lambda path: path.stat().st_mtime_ns,
                reverse=True,
            )
        except OSError:
            return
        for path in entries[self.maximum_entries :]:
            try:
                path.unlink()
            except OSError:
                continue


def analyze_vocal_pitch(source_path: Path) -> VocalPitchAnalysis:
    source = source_path.expanduser().resolve()
    try:
        stat = source.stat()
        with sf.SoundFile(str(source)) as audio:
            metrics = analyze_audio_signal(audio)
    except (OSError, RuntimeError, sf.SoundFileRuntimeError) as exc:
        raise PitchRecommendationError(f"Vocal pitch analysis failed: {source.name}") from exc

    samples = np.asarray(
        tuple(value for value in metrics.pitch_midi_samples if math.isfinite(value)),
        dtype=np.float64,
    )
    if samples.size < MINIMUM_PITCH_SAMPLES:
        raise PitchRecommendationError(
            "Not enough stable vocal pitch was detected for a recommendation."
        )
    histogram = pitch_histogram(samples)
    ranges = pitch_coverage_ranges(histogram)
    if not ranges:
        raise PitchRecommendationError(
            "Not enough stable vocal pitch was detected for a recommendation."
        )
    return VocalPitchAnalysis(
        source_path=source,
        source_size=stat.st_size,
        source_mtime_ns=stat.st_mtime_ns,
        generated_at=datetime.now(UTC).isoformat(),
        profile=PitchRangeProfile(
            low_midi=float(np.percentile(samples, PITCH_RANGE_LOW_PERCENTILE)),
            center_midi=float(np.median(samples)),
            high_midi=float(np.percentile(samples, PITCH_RANGE_HIGH_PERCENTILE)),
            sample_count=int(samples.size),
        ),
    )


def model_pitch_profile(
    report: ModelDatasetAnalysis | None,
) -> PitchRangeProfile | None:
    if report is None:
        return None
    if report.pitch_low_midi is not None and report.pitch_high_midi is not None:
        low = float(report.pitch_low_midi)
        high = float(report.pitch_high_midi)
    elif report.pitch_coverage_ranges:
        primary = report.pitch_coverage_ranges[0]
        low = float(primary.low_midi)
        high = float(primary.high_midi)
    else:
        return None
    center_value = (
        report.pitch_median_midi
        if report.pitch_median_midi is not None
        else report.pitch_center_midi
    )
    if center_value is None:
        return None
    center = float(center_value)
    if not all(math.isfinite(value) for value in (low, center, high)):
        return None
    if low > center or center > high:
        return None
    return PitchRangeProfile(
        low_midi=low,
        center_midi=center,
        high_midi=high,
        sample_count=sum(item.count for item in report.pitch_histogram),
    )


def precision_benchmark_pitch_profile(
    report: ModelPrecisionBenchmark | None,
) -> PitchRangeProfile | None:
    if report is None:
        return None
    low_shift = report.recommended_low_shift
    high_shift = report.recommended_high_shift
    if low_shift is None or high_shift is None:
        low_shift = report.usable_low_shift
        high_shift = report.usable_high_shift
    if low_shift is None or high_shift is None or low_shift > high_shift:
        return None

    center_shift = report.best_shift_semitones
    if center_shift is None or not low_shift <= center_shift <= high_shift:
        center_shift = round((low_shift + high_shift) / 2)
    evidence_count = sum(
        point.successful_references
        for point in report.points
        if low_shift <= point.shift_semitones <= high_shift
    )
    return PitchRangeProfile(
        low_midi=REFERENCE_CENTER_MIDI + low_shift,
        center_midi=REFERENCE_CENTER_MIDI + center_shift,
        high_midi=REFERENCE_CENTER_MIDI + high_shift,
        sample_count=evidence_count,
    )


def recommend_conversion_pitch(
    source: PitchRangeProfile,
    model: PitchRangeProfile,
) -> PitchRecommendation:
    recommended_low = math.ceil(model.low_midi - source.low_midi)
    recommended_high = math.floor(model.high_midi - source.high_midi)
    has_full_range = recommended_low <= recommended_high
    if has_full_range:
        pitch = _closest_to_zero(recommended_low, recommended_high)
    else:
        pitch = recommended_pitch_shift(model.center_midi, source.center_midi)
    shifted_low = source.low_midi + pitch
    shifted_high = source.high_midi + pitch
    intersection = max(
        0.0,
        min(shifted_high, model.high_midi) - max(shifted_low, model.low_midi) + 1.0,
    )
    source_width = max(1.0, shifted_high - shifted_low + 1.0)
    return PitchRecommendation(
        source=source,
        model=model,
        pitch=pitch,
        overlap_ratio=min(1.0, intersection / source_width),
        is_large_shift=abs(pitch) > LARGE_PITCH_SHIFT,
        recommended_low_pitch=recommended_low if has_full_range else None,
        recommended_high_pitch=recommended_high if has_full_range else None,
    )


def _closest_to_zero(low: int, high: int) -> int:
    if low <= 0 <= high:
        return 0
    return high if high < 0 else low


def analyze_conversion_pitch(
    cache: VocalPitchAnalysisCache,
    source_path: Path,
    model: PitchRangeProfile,
) -> PitchRecommendationResult:
    try:
        source = cache.get_or_analyze(source_path).profile
    except PitchRecommendationError as exc:
        message = str(exc)
        if message != "Not enough stable vocal pitch was detected for a recommendation.":
            message = "Could not analyze the selected vocal."
        return PitchRecommendationResult(None, message)
    return PitchRecommendationResult(recommend_conversion_pitch(source, model))


def cached_model_analysis_is_current(store: ModelDatasetStore, model_id: str) -> bool:
    model_root = store.root / model_id
    manifest = model_root / DATASET_MANIFEST_NAME
    analysis = model_root / "analysis" / ANALYSIS_FILE_NAME
    try:
        return manifest.is_file() and analysis.is_file() and (
            analysis.stat().st_mtime_ns >= manifest.stat().st_mtime_ns
        )
    except OSError:
        return False


def _analysis_to_data(analysis: VocalPitchAnalysis) -> dict[str, object]:
    return {
        "schema_version": PITCH_CACHE_SCHEMA_VERSION,
        "source_path": str(analysis.source_path),
        "source_size": analysis.source_size,
        "source_mtime_ns": analysis.source_mtime_ns,
        "generated_at": analysis.generated_at,
        "profile": asdict(analysis.profile),
    }


def _load_cached_analysis(
    cache_path: Path,
    source: Path,
    source_size: int,
    source_mtime_ns: int,
) -> VocalPitchAnalysis | None:
    try:
        data = json.loads(cache_path.read_text(encoding="utf-8"))
        profile = data["profile"]
        if (
            data.get("schema_version") != PITCH_CACHE_SCHEMA_VERSION
            or Path(str(data["source_path"])).expanduser().resolve() != source
            or int(data["source_size"]) != source_size
            or int(data["source_mtime_ns"]) != source_mtime_ns
            or not isinstance(profile, dict)
        ):
            return None
        parsed = PitchRangeProfile(
            low_midi=float(profile["low_midi"]),
            center_midi=float(profile["center_midi"]),
            high_midi=float(profile["high_midi"]),
            sample_count=int(profile.get("sample_count", 0)),
        )
        if not all(
            math.isfinite(value)
            for value in (parsed.low_midi, parsed.center_midi, parsed.high_midi)
        ):
            return None
        return VocalPitchAnalysis(
            source_path=source,
            source_size=source_size,
            source_mtime_ns=source_mtime_ns,
            generated_at=str(data["generated_at"]),
            profile=parsed,
        )
    except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError):
        return None
