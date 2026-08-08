from __future__ import annotations

from pathlib import Path
from typing import Sequence

import numpy as np
import soundfile as sf
from PySide6.QtCore import QElapsedTimer, QTimer
from PySide6.QtMultimedia import QAudioFormat, QAudioSink

class AudioPlaybackError(RuntimeError):
    """Raised when an audio preview cannot be played."""


_SAMPLE_RATE = 44100
_CHANNELS = 2
_CHUNK_FRAMES = 1024
_BUFFER_MS = 90


class AudioPlayer:
    def __init__(self) -> None:
        self._audio_sink: QAudioSink | None = None
        self._audio_device = None
        self._feed_timer: QTimer | None = None
        self._elapsed_timer = QElapsedTimer()
        self._tracks: list[np.ndarray] = []
        self._volumes: list[float] = []
        self._frame_index = 0
        self._duration_frames = 0
        self._duration_ms = 0
        self._start_ms = 0
        self._last_position_ms = 0

    def play(self, paths: Sequence[Path], start_ms: int = 0, volumes: Sequence[float] | None = None) -> None:
        sources = [path.expanduser().resolve() for path in paths]
        for source in sources:
            self._validate_source(source)
        resolved_volumes = _resolve_volumes(len(sources), volumes)

        self.stop()
        if not sources:
            return

        self._tracks = [_read_playback_audio(source) for source in sources]
        self._volumes = resolved_volumes
        self._duration_frames = max((track.shape[0] for track in self._tracks), default=0)
        self._duration_ms = int(self._duration_frames / _SAMPLE_RATE * 1000)
        self._start_ms = max(0, min(start_ms, self._duration_ms))
        self._last_position_ms = self._start_ms
        self._frame_index = int(self._start_ms * _SAMPLE_RATE / 1000)

        self._audio_sink = QAudioSink(_audio_format())
        self._audio_sink.setBufferSize(_frames_to_bytes(int(_SAMPLE_RATE * _BUFFER_MS / 1000)))
        self._audio_device = self._audio_sink.start()
        if self._audio_device is None:
            self.stop()
            raise AudioPlaybackError("Could not open audio output device.")

        self._elapsed_timer.restart()
        self._feed_audio()
        self._ensure_feed_timer().start()

    def set_volumes(self, volumes: Sequence[float]) -> None:
        if not self._tracks:
            return
        self._volumes = _resolve_volumes(len(self._tracks), volumes)

    def pause(self) -> None:
        if not self.is_playing():
            return
        self._last_position_ms = self.position_ms()
        self._stop_sink()

    def stop(self) -> None:
        self._last_position_ms = self.position_ms() if self.is_playing() else 0
        self._stop_sink()
        self._tracks.clear()
        self._volumes.clear()
        self._frame_index = 0
        self._duration_frames = 0
        self._duration_ms = 0
        self._start_ms = 0
        self._last_position_ms = 0

    def is_playing(self) -> bool:
        return self._audio_sink is not None and self.position_ms() < self._duration_ms

    def position_ms(self) -> int:
        if self._audio_sink is not None and self._elapsed_timer.isValid():
            self._last_position_ms = min(self._duration_ms, self._start_ms + self._elapsed_timer.elapsed())
        return self._last_position_ms

    def duration_ms(self, path: Path) -> int:
        source = path.expanduser().resolve()
        self._validate_source(source)
        try:
            info = sf.info(source)
        except Exception as exc:
            raise AudioPlaybackError(f"Could not read audio file: {source}") from exc
        if info.samplerate <= 0:
            return 0
        return int(info.frames / info.samplerate * 1000)

    def _ensure_feed_timer(self) -> QTimer:
        if self._feed_timer is None:
            self._feed_timer = QTimer()
            self._feed_timer.setInterval(12)
            self._feed_timer.timeout.connect(self._feed_audio)
        return self._feed_timer

    def _feed_audio(self) -> None:
        if self._audio_sink is None or self._audio_device is None:
            return

        if self.position_ms() >= self._duration_ms:
            self._stop_sink()
            return

        bytes_per_frame = _frames_to_bytes(1)
        while self._audio_sink is not None and self._audio_sink.bytesFree() >= bytes_per_frame:
            available_frames = self._audio_sink.bytesFree() // bytes_per_frame
            frame_count = min(_CHUNK_FRAMES, available_frames, self._duration_frames - self._frame_index)
            if frame_count <= 0:
                return
            chunk = _mix_chunk(self._tracks, self._volumes, self._frame_index, frame_count)
            self._audio_device.write(_float_to_pcm16(chunk))
            self._frame_index += frame_count

    def _stop_sink(self) -> None:
        if self._feed_timer is not None:
            self._feed_timer.stop()
        if self._audio_sink is not None:
            self._audio_sink.stop()
            self._audio_sink.deleteLater()
        self._audio_sink = None
        self._audio_device = None

    def _validate_source(self, source: Path) -> None:
        if not source.exists():
            raise AudioPlaybackError(f"Audio file does not exist: {source}")
        if source.suffix.lower() != ".wav":
            raise AudioPlaybackError("Audio preview currently supports WAV files only.")


def _audio_format() -> QAudioFormat:
    audio_format = QAudioFormat()
    audio_format.setSampleRate(_SAMPLE_RATE)
    audio_format.setChannelCount(_CHANNELS)
    audio_format.setSampleFormat(QAudioFormat.SampleFormat.Int16)
    return audio_format


def _read_playback_audio(path: Path) -> np.ndarray:
    try:
        audio, sample_rate = sf.read(path, always_2d=True, dtype="float32")
    except Exception as exc:
        raise AudioPlaybackError(f"Could not read audio file: {path}") from exc

    audio = _resample_audio(audio, sample_rate, _SAMPLE_RATE)
    return _match_channels(audio, _CHANNELS)


def _mix_chunk(tracks: Sequence[np.ndarray], volumes: Sequence[float], frame_index: int, frame_count: int) -> np.ndarray:
    mix = np.zeros((frame_count, _CHANNELS), dtype=np.float32)
    for track, volume in zip(tracks, volumes, strict=True):
        if frame_index >= track.shape[0] or volume <= 0:
            continue
        end_index = min(frame_index + frame_count, track.shape[0])
        mix[: end_index - frame_index] += track[frame_index:end_index] * volume
    return mix


def _float_to_pcm16(audio: np.ndarray) -> bytes:
    return (np.clip(audio, -1.0, 1.0) * 32767).astype("<i2", copy=False).tobytes()


def _match_channels(audio: np.ndarray, target_channels: int) -> np.ndarray:
    if audio.shape[1] == target_channels:
        return audio
    if audio.shape[1] == 1:
        return np.repeat(audio, target_channels, axis=1)

    matched = np.zeros((audio.shape[0], target_channels), dtype=np.float32)
    channels_to_copy = min(audio.shape[1], target_channels)
    matched[:, :channels_to_copy] = audio[:, :channels_to_copy]
    return matched


def _resample_audio(audio: np.ndarray, source_sample_rate: int, target_sample_rate: int) -> np.ndarray:
    if source_sample_rate == target_sample_rate:
        return audio
    if source_sample_rate <= 0 or target_sample_rate <= 0:
        raise AudioPlaybackError("Cannot play tracks with invalid sample rates.")
    if audio.shape[0] == 0:
        return audio

    target_frames = max(1, round(audio.shape[0] * target_sample_rate / source_sample_rate))
    if audio.shape[0] == 1:
        return np.repeat(audio, target_frames, axis=0)

    source_positions = np.arange(audio.shape[0], dtype=np.float32)
    target_positions = np.linspace(0, audio.shape[0] - 1, target_frames, dtype=np.float32)
    resampled = np.empty((target_frames, audio.shape[1]), dtype=np.float32)
    for channel in range(audio.shape[1]):
        resampled[:, channel] = np.interp(target_positions, source_positions, audio[:, channel])
    return resampled


def _resolve_volumes(source_count: int, volumes: Sequence[float] | None) -> list[float]:
    if volumes is None:
        return [1.0] * source_count
    return [_clamp_volume(volumes[index] if index < len(volumes) else 1.0) for index in range(source_count)]


def _clamp_volume(volume: float) -> float:
    return max(0.0, min(2.0, volume))


def _frames_to_bytes(frame_count: int) -> int:
    return frame_count * _CHANNELS * 2
