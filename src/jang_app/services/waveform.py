from __future__ import annotations

from collections import OrderedDict
from pathlib import Path

import numpy as np
import soundfile as sf

from jang_app.config import FFMPEG_BIN_DIR
from jang_app.services.command import run_binary_command
from jang_app.services.environment import require_executable
from jang_app.services.studio_session import StudioLevelMatchSettings


_FFMPEG_WAVEFORM_SAMPLE_RATE = 800
_WAVEFORM_CACHE_LIMIT = 384

WaveformCacheKey = tuple[str, int, int, int]


class WaveformPeakCache:
    """Owns bounded waveform results shared by every audio workspace."""

    def __init__(self, max_entries: int = _WAVEFORM_CACHE_LIMIT) -> None:
        self._max_entries = max(1, int(max_entries))
        self._entries: OrderedDict[tuple[str, object], list[float]] = OrderedDict()

    def normalized(self, key: WaveformCacheKey) -> list[float] | None:
        return self._get("normalized", key)

    def store_normalized(self, key: WaveformCacheKey, peaks: list[float]) -> None:
        self._store("normalized", key, peaks)

    def amplitude(self, key: WaveformCacheKey) -> list[float] | None:
        return self._get("amplitude", key)

    def store_amplitude(self, key: WaveformCacheKey, peaks: list[float]) -> None:
        self._store("amplitude", key, peaks)

    def level_matched(self, key: tuple[object, ...]) -> list[float] | None:
        return self._get("level_matched", key)

    def store_level_matched(self, key: tuple[object, ...], peaks: list[float]) -> None:
        self._store("level_matched", key, peaks)

    def discard_normalized(self, key: WaveformCacheKey) -> None:
        self._entries.pop(("normalized", key), None)

    def clear(self) -> None:
        self._entries.clear()

    def _get(self, kind: str, key: object) -> list[float] | None:
        entry_key = kind, key
        peaks = self._entries.pop(entry_key, None)
        if peaks is not None:
            self._entries[entry_key] = peaks
        return peaks

    def _store(self, kind: str, key: object, peaks: list[float]) -> None:
        entry_key = kind, key
        self._entries.pop(entry_key, None)
        if not peaks:
            return
        self._entries[entry_key] = peaks
        while len(self._entries) > self._max_entries:
            self._entries.popitem(last=False)


waveform_peak_cache = WaveformPeakCache()


class WaveformDecodeError(RuntimeError):
    """Raised when neither SoundFile nor FFmpeg can decode an audio source."""


def waveform_cache_key(path: Path, point_count: int) -> WaveformCacheKey:
    resolved = path.expanduser().resolve()
    stat = resolved.stat()
    return (str(resolved), stat.st_mtime_ns, stat.st_size, point_count)


def build_waveform_peaks(path: Path, point_count: int) -> list[float]:
    if point_count <= 0:
        return []

    try:
        peaks = _read_soundfile_peaks(path, point_count)
    except (OSError, RuntimeError):
        samples = _decode_with_ffmpeg(path)
        peaks = _sample_peaks(samples, point_count)

    max_peak = float(np.max(peaks)) if peaks.size else 0.0
    if max_peak <= 0:
        return [0.0 for _ in range(len(peaks))]
    return (peaks / max_peak).tolist()


def build_waveform_amplitude_peaks(path: Path, point_count: int) -> list[float]:
    """Build non-normalized peaks so a shared timeline can display actual levels."""
    if point_count <= 0:
        return []
    try:
        peaks = _read_soundfile_peaks(path, point_count)
    except (OSError, RuntimeError):
        peaks = _sample_peaks(_decode_with_ffmpeg(path), point_count)
    return peaks.tolist()


def build_level_matched_waveform_peaks(
    path: Path,
    reference_path: Path,
    point_count: int,
    settings: StudioLevelMatchSettings,
) -> list[float]:
    """Build peaks from the same level-matched signal used by playback and export."""
    if point_count <= 0:
        return []
    try:
        peaks = _read_soundfile_peaks(path, point_count)
    except (OSError, RuntimeError):
        peaks = _sample_peaks(_decode_with_ffmpeg(path), point_count)
    source_rms = _read_rms_envelope(path)
    reference_rms = _read_rms_envelope(reference_path)
    shared_points = min(source_rms.size, reference_rms.size)
    if shared_points <= 0 or settings.strength_percent <= 0:
        return peaks.tolist()
    source_rms = _windowed_rms(source_rms[:shared_points], settings.response_ms)
    reference_rms = _windowed_rms(reference_rms[:shared_points], settings.response_ms)
    floor = 10.0 ** (settings.silence_threshold_db / 20.0)
    valid = (source_rms >= floor) & (reference_rms >= floor)
    gain_db = np.zeros(shared_points, dtype=np.float64)
    gain_db[valid] = 20.0 * np.log10(
        np.maximum(reference_rms[valid], 1e-8)
        / np.maximum(source_rms[valid], 1e-8)
    )
    gain_db *= settings.strength_percent / 100.0
    gain_db = np.clip(gain_db, -settings.max_correction_db, settings.max_correction_db)
    gain_db = _smooth_envelope(gain_db, settings.response_ms)
    visual_positions = np.linspace(0, shared_points - 1, len(peaks))
    visual_gain = np.power(
        10.0,
        np.interp(visual_positions, np.arange(shared_points), gain_db) / 20.0,
    )
    return (peaks * visual_gain).tolist()


def _read_soundfile_peaks(path: Path, point_count: int) -> np.ndarray:
    with sf.SoundFile(path) as audio:
        frame_count = len(audio)
        if frame_count <= 0:
            return np.zeros(0, dtype=np.float32)
        bucket_count = min(point_count, frame_count)
        bucket_size = max(1, frame_count // bucket_count)
        return _stream_peaks(audio, bucket_count, bucket_size)


def _decode_with_ffmpeg(path: Path) -> np.ndarray:
    executable = require_executable(
        "ffmpeg",
        "Place FFmpeg under third_party/ffmpeg/bin or add it to PATH.",
        [FFMPEG_BIN_DIR],
    )
    completed = run_binary_command(
        [
            executable,
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(path.expanduser().resolve()),
            "-map",
            "0:a:0",
            "-vn",
            "-ac",
            "1",
            "-ar",
            str(_FFMPEG_WAVEFORM_SAMPLE_RATE),
            "-f",
            "f32le",
            "-acodec",
            "pcm_f32le",
            "pipe:1",
        ],
    )
    if completed.returncode != 0:
        detail = completed.stderr.decode("utf-8", errors="replace").strip()
        raise WaveformDecodeError(detail or f"FFmpeg could not decode {path.name}.")
    if not completed.stdout:
        return np.zeros(0, dtype=np.float32)
    return np.frombuffer(completed.stdout, dtype="<f4")


def _sample_peaks(samples: np.ndarray, point_count: int) -> np.ndarray:
    if samples.size == 0:
        return np.zeros(0, dtype=np.float32)
    bucket_count = min(point_count, len(samples))
    starts = np.arange(bucket_count, dtype=np.int64) * len(samples) // bucket_count
    peaks = np.maximum.reduceat(np.abs(samples), starts)
    return peaks.astype(np.float32, copy=False)


def _stream_peaks(audio: sf.SoundFile, bucket_count: int, bucket_size: int) -> np.ndarray:
    peaks = np.zeros(bucket_count, dtype=np.float32)
    usable_frames = bucket_count * bucket_size
    cursor = 0
    while cursor < usable_frames:
        block = audio.read(min(65536, usable_frames - cursor), always_2d=True, dtype="float32")
        if block.size == 0:
            break
        mono = np.mean(block, axis=1)
        block_cursor = 0
        while block_cursor < len(mono):
            bucket_index = cursor // bucket_size
            bucket_end = (bucket_index + 1) * bucket_size
            take = min(len(mono) - block_cursor, bucket_end - cursor)
            peaks[bucket_index] = max(
                peaks[bucket_index],
                float(np.max(np.abs(mono[block_cursor : block_cursor + take]))),
            )
            block_cursor += take
            cursor += take
    return peaks


def _read_rms_envelope(path: Path, hop_ms: int = 10) -> np.ndarray:
    with sf.SoundFile(path) as audio:
        hop_frames = max(1, round(audio.samplerate * hop_ms / 1_000))
        values: list[np.ndarray] = []
        carry = np.zeros((0, audio.channels), dtype=np.float32)
        while True:
            block = audio.read(65_536, always_2d=True, dtype="float32")
            if block.size == 0:
                break
            if carry.size:
                block = np.concatenate((carry, block), axis=0)
            groups = block.shape[0] // hop_frames
            usable = groups * hop_frames
            if groups:
                frames = block[:usable].reshape(groups, hop_frames, audio.channels)
                values.append(np.sqrt(np.mean(np.square(frames, dtype=np.float64), axis=(1, 2))))
            carry = block[usable:]
        if carry.size:
            values.append(
                np.asarray(
                    [np.sqrt(np.mean(np.square(carry, dtype=np.float64)))],
                    dtype=np.float64,
                )
            )
    return np.concatenate(values) if values else np.zeros(0, dtype=np.float64)


def _windowed_rms(rms: np.ndarray, response_ms: int, hop_ms: int = 10) -> np.ndarray:
    points = max(1, round(response_ms / hop_ms))
    if points <= 1 or rms.size <= 1:
        return rms
    points = min(points, rms.size)
    kernel = np.ones(points, dtype=np.float64) / points
    power = np.square(rms, dtype=np.float64)
    return np.sqrt(np.convolve(power, kernel, mode="same"))


def _smooth_envelope(gain_db: np.ndarray, response_ms: int, hop_ms: int = 10) -> np.ndarray:
    radius = max(1, round(response_ms / hop_ms / 3.0))
    radius = min(radius, max(0, (gain_db.size - 1) // 2))
    if radius <= 0:
        return gain_db
    kernel = np.hanning(radius * 2 + 1)
    kernel /= np.sum(kernel)
    return np.convolve(np.pad(gain_db, radius, mode="edge"), kernel, mode="valid")
