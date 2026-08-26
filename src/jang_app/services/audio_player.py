from __future__ import annotations

from collections import deque
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
import logging
from pathlib import Path
import time
from typing import Sequence

import numpy as np
import soundfile as sf
from PySide6.QtCore import QElapsedTimer, QTimer
from PySide6.QtMultimedia import QAudioFormat, QAudioSink

from jang_app.services.realtime_effects import RealtimeEffectChain
from jang_app.services.studio_audio_levels import clamp_studio_source_volume
from jang_app.services.studio_session import StudioEffect


class AudioPlaybackError(RuntimeError):
    """Raised when an audio preview cannot be played."""


_SAMPLE_RATE = 44100
_CHANNELS = 2
_CHUNK_FRAMES = 1024
_BUFFER_MS = 60
_REPLACE_CROSSFADE_MS = 45
_RENDER_LOOKAHEAD_CHUNKS = 4
_EFFECT_PREROLL_MS = 5_000

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class PreparedPlaybackAudio:
    tracks: tuple[np.ndarray, ...]
    duration_frames: int
    effect_chains: tuple[tuple[StudioEffect, ...], ...] = ()
    track_start_frames: tuple[int, ...] = ()
    track_effect_end_frames: tuple[int, ...] = ()

    @property
    def duration_ms(self) -> int:
        return int(self.duration_frames / _SAMPLE_RATE * 1000)


@dataclass
class _BufferTransition:
    tracks: tuple[np.ndarray, ...]
    track_start_frames: tuple[int, ...]
    track_effect_end_frames: tuple[int, ...]
    volumes: tuple[float, ...]
    effect_chains: tuple[RealtimeEffectChain, ...]
    start_frame: int
    end_frame: int


@dataclass(frozen=True)
class _RenderedAudioChunk:
    generation: int
    start_frame: int
    audio: np.ndarray


@dataclass
class _WorkerPlaybackState:
    tracks: tuple[np.ndarray, ...]
    track_start_frames: tuple[int, ...]
    track_effect_end_frames: tuple[int, ...]
    volumes: tuple[float, ...]
    effect_chains: list[RealtimeEffectChain]
    duration_frames: int
    frame_index: int
    transition: _BufferTransition | None = None


class _AsyncChunkRenderer:
    """Serializes stateful FX work away from the Qt UI thread."""

    def __init__(self) -> None:
        self._executor = ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix="jjzero-audio-render",
        )
        self._pending: deque[Future[_RenderedAudioChunk | None]] = deque()
        self._generation = 0
        self._state: _WorkerPlaybackState | None = None

    def configure(
        self,
        prepared: PreparedPlaybackAudio,
        volumes: Sequence[float],
        start_frame: int,
    ) -> None:
        self._generation += 1
        generation = self._generation
        self._cancel_waiting_chunks()
        self._executor.submit(
            self._configure_worker,
            generation,
            prepared,
            tuple(volumes),
            max(0, int(start_frame)),
        )
        self.ensure_lookahead()

    def replace(
        self,
        prepared: PreparedPlaybackAudio,
        volumes: Sequence[float],
        crossfade_ms: int,
    ) -> None:
        self._cancel_waiting_chunks()
        self._executor.submit(
            self._replace_worker,
            self._generation,
            prepared,
            tuple(volumes),
            max(0, int(crossfade_ms)),
        )
        self.ensure_lookahead()

    def update_effects(self, effects: tuple[tuple[StudioEffect, ...], ...]) -> None:
        self._cancel_waiting_chunks()
        self._executor.submit(
            self._update_effects_worker,
            self._generation,
            effects,
        )
        self.ensure_lookahead()

    def update_volumes(self, volumes: Sequence[float]) -> None:
        self._cancel_waiting_chunks()
        self._executor.submit(
            self._update_volumes_worker,
            self._generation,
            tuple(volumes),
        )
        self.ensure_lookahead()

    def suspend(self) -> None:
        self._generation += 1
        generation = self._generation
        self._cancel_waiting_chunks()
        self._executor.submit(self._clear_worker, generation)

    def ensure_lookahead(self) -> None:
        while len(self._pending) < _RENDER_LOOKAHEAD_CHUNKS:
            self._pending.append(
                self._executor.submit(self._render_worker, self._generation, _CHUNK_FRAMES)
            )

    def take_ready(self) -> _RenderedAudioChunk | None:
        while self._pending:
            future = self._pending[0]
            if not future.done():
                return None
            self._pending.popleft()
            if future.cancelled():
                continue
            try:
                rendered = future.result()
            except Exception:
                _LOGGER.exception("Background audio rendering failed")
                continue
            if rendered is not None and rendered.generation == self._generation:
                return rendered
        return None

    def pending_count(self) -> int:
        return len(self._pending)

    def _cancel_waiting_chunks(self) -> None:
        retained: deque[Future[_RenderedAudioChunk | None]] = deque()
        while self._pending:
            future = self._pending.popleft()
            if not future.cancel():
                retained.append(future)
        self._pending = retained

    def _configure_worker(
        self,
        generation: int,
        prepared: PreparedPlaybackAudio,
        volumes: tuple[float, ...],
        start_frame: int,
    ) -> None:
        if generation != self._generation:
            return
        target_frame = min(start_frame, prepared.duration_frames)
        preroll_frames = round(_EFFECT_PREROLL_MS * _SAMPLE_RATE / 1_000)
        state = _WorkerPlaybackState(
            tracks=prepared.tracks,
            track_start_frames=tuple(_resolve_track_start_frames(prepared)),
            track_effect_end_frames=tuple(_resolve_track_effect_end_frames(prepared)),
            volumes=tuple(_resolve_volumes(len(prepared.tracks), volumes)),
            effect_chains=_build_effect_chains(prepared),
            duration_frames=prepared.duration_frames,
            frame_index=max(0, target_frame - preroll_frames),
        )
        while state.frame_index < target_frame:
            frame_count = min(_CHUNK_FRAMES, target_frame - state.frame_index)
            _mix_effected_chunk(
                state.tracks,
                state.track_start_frames,
                state.track_effect_end_frames,
                state.volumes,
                state.effect_chains,
                state.frame_index,
                frame_count,
            )
            state.frame_index += frame_count
        self._state = state

    def _replace_worker(
        self,
        generation: int,
        prepared: PreparedPlaybackAudio,
        volumes: tuple[float, ...],
        crossfade_ms: int,
    ) -> None:
        state = self._state
        if generation != self._generation or state is None:
            return
        transition_frames = max(1, int(crossfade_ms * _SAMPLE_RATE / 1000))
        transition = _BufferTransition(
            tracks=state.tracks,
            track_start_frames=state.track_start_frames,
            track_effect_end_frames=state.track_effect_end_frames,
            volumes=state.volumes,
            effect_chains=tuple(state.effect_chains),
            start_frame=state.frame_index,
            end_frame=state.frame_index + transition_frames,
        )
        state.tracks = prepared.tracks
        state.track_start_frames = tuple(_resolve_track_start_frames(prepared))
        state.track_effect_end_frames = tuple(_resolve_track_effect_end_frames(prepared))
        state.volumes = tuple(_resolve_volumes(len(prepared.tracks), volumes))
        state.effect_chains = _build_effect_chains(prepared)
        state.duration_frames = prepared.duration_frames
        state.transition = transition

    def _update_effects_worker(
        self,
        generation: int,
        effects: tuple[tuple[StudioEffect, ...], ...],
    ) -> None:
        state = self._state
        if generation != self._generation or state is None or len(effects) != len(state.tracks):
            return
        if len(state.effect_chains) != len(effects):
            state.effect_chains = [
                RealtimeEffectChain(_SAMPLE_RATE, chain)
                for chain in effects
            ]
            return
        for processor, chain in zip(state.effect_chains, effects, strict=True):
            processor.update(chain)

    def _update_volumes_worker(
        self,
        generation: int,
        volumes: tuple[float, ...],
    ) -> None:
        state = self._state
        if generation != self._generation or state is None:
            return
        state.volumes = tuple(_resolve_volumes(len(state.tracks), volumes))

    def _clear_worker(self, generation: int) -> None:
        if generation == self._generation:
            self._state = None

    def _render_worker(
        self,
        generation: int,
        requested_frames: int,
    ) -> _RenderedAudioChunk | None:
        state = self._state
        if generation != self._generation or state is None:
            return None
        frame_count = min(requested_frames, state.duration_frames - state.frame_index)
        if frame_count <= 0:
            return None
        start_frame = state.frame_index
        chunk = _mix_effected_chunk(
            state.tracks,
            state.track_start_frames,
            state.track_effect_end_frames,
            state.volumes,
            state.effect_chains,
            start_frame,
            frame_count,
        )
        chunk = _crossfade_transition(chunk, state.transition, start_frame, frame_count)
        if state.transition is not None and start_frame + frame_count >= state.transition.end_frame:
            state.transition = None
        state.frame_index += frame_count
        return _RenderedAudioChunk(generation, start_frame, chunk)


class AudioPlayer:
    def __init__(self) -> None:
        self._audio_sink: QAudioSink | None = None
        self._audio_device = None
        self._feed_timer: QTimer | None = None
        self._elapsed_timer = QElapsedTimer()
        self._tracks: list[np.ndarray] = []
        self._track_start_frames: list[int] = []
        self._track_effect_end_frames: list[int] = []
        self._volumes: list[float] = []
        self._effect_chains: list[RealtimeEffectChain] = []
        self._frame_index = 0
        self._duration_frames = 0
        self._duration_ms = 0
        self._start_ms = 0
        self._last_position_ms = 0
        self._transition: _BufferTransition | None = None
        self._renderer = _AsyncChunkRenderer()
        self._pending_pcm = b""
        self._output_start_frame = 0
        self._written_audio_bytes = 0
        self._last_underrun_log_at = 0.0
        self._underrun_count = 0

    def play(self, paths: Sequence[Path], start_ms: int = 0, volumes: Sequence[float] | None = None) -> None:
        self.play_prepared(prepare_playback_audio(paths), start_ms=start_ms, volumes=volumes)

    def play_prepared(
        self,
        prepared: PreparedPlaybackAudio,
        start_ms: int = 0,
        volumes: Sequence[float] | None = None,
    ) -> None:
        self.stop()
        if not self.set_prepared(prepared, volumes):
            return
        self._start_ms = max(0, min(start_ms, self._duration_ms))
        self._last_position_ms = self._start_ms
        self._frame_index = int(self._start_ms * _SAMPLE_RATE / 1000)
        self._start_output()

    def set_prepared(
        self,
        prepared: PreparedPlaybackAudio,
        volumes: Sequence[float] | None = None,
    ) -> bool:
        if self.is_playing() or not prepared.tracks:
            return False
        self._stop_sink()
        self._tracks = list(prepared.tracks)
        self._track_start_frames = _resolve_track_start_frames(prepared)
        self._track_effect_end_frames = _resolve_track_effect_end_frames(prepared)
        self._volumes = _resolve_volumes(len(prepared.tracks), volumes)
        self._effect_chains = _build_effect_chains(prepared)
        self._duration_frames = prepared.duration_frames
        self._duration_ms = prepared.duration_ms
        self._frame_index = 0
        self._transition = None
        return True

    def resume(
        self,
        start_ms: int,
        volumes: Sequence[float] | None = None,
    ) -> bool:
        if not self._tracks:
            return False
        self._volumes = _resolve_volumes(len(self._tracks), volumes)
        self._effect_chains = [
            RealtimeEffectChain(_SAMPLE_RATE, chain.effects)
            for chain in self._effect_chains
        ]
        self._start_ms = max(0, min(start_ms, self._duration_ms))
        self._last_position_ms = self._start_ms
        self._frame_index = int(self._start_ms * _SAMPLE_RATE / 1000)
        self._transition = None
        self._start_output()
        return True

    def has_prepared_audio(self) -> bool:
        return bool(self._tracks)

    def _start_output(self) -> None:
        self._stop_sink()

        self._pending_pcm = b""
        self._output_start_frame = self._frame_index
        self._written_audio_bytes = 0
        self._renderer.configure(
            self._prepared_snapshot(),
            self._volumes,
            self._frame_index,
        )

        self._audio_sink = QAudioSink(_audio_format())
        self._audio_sink.setBufferSize(_frames_to_bytes(int(_SAMPLE_RATE * _BUFFER_MS / 1000)))
        self._audio_device = self._audio_sink.start()
        if self._audio_device is None:
            self.stop()
            raise AudioPlaybackError("Could not open audio output device.")

        self._elapsed_timer.restart()
        self._feed_audio()
        self._ensure_feed_timer().start()

    def replace_prepared(
        self,
        prepared: PreparedPlaybackAudio,
        volumes: Sequence[float] | None = None,
        *,
        crossfade_ms: int = _REPLACE_CROSSFADE_MS,
    ) -> bool:
        if not self.is_playing() or not prepared.tracks:
            return False
        transition_frames = max(1, int(max(0, crossfade_ms) * _SAMPLE_RATE / 1000))
        self._transition = _BufferTransition(
            tracks=tuple(self._tracks),
            track_start_frames=tuple(self._track_start_frames),
            track_effect_end_frames=tuple(self._track_effect_end_frames),
            volumes=tuple(self._volumes),
            effect_chains=tuple(self._effect_chains),
            start_frame=self._frame_index,
            end_frame=self._frame_index + transition_frames,
        )
        self._tracks = list(prepared.tracks)
        self._track_start_frames = _resolve_track_start_frames(prepared)
        self._track_effect_end_frames = _resolve_track_effect_end_frames(prepared)
        self._volumes = _resolve_volumes(len(prepared.tracks), volumes)
        self._effect_chains = _build_effect_chains(prepared)
        self._duration_frames = prepared.duration_frames
        self._duration_ms = prepared.duration_ms
        self._renderer.replace(prepared, self._volumes, crossfade_ms)
        return True

    def set_effect_chains(self, effects: tuple[tuple[StudioEffect, ...], ...]) -> bool:
        if len(effects) != len(self._tracks):
            return False
        if len(self._effect_chains) != len(effects):
            self._effect_chains = [RealtimeEffectChain(_SAMPLE_RATE, chain) for chain in effects]
            if self.is_playing():
                self._renderer.update_effects(effects)
            return True
        for processor, chain in zip(self._effect_chains, effects, strict=True):
            processor.update(chain)
        if self.is_playing():
            self._renderer.update_effects(effects)
        return True

    def set_volumes(self, volumes: Sequence[float]) -> None:
        if not self._tracks:
            return
        self._volumes = _resolve_volumes(len(self._tracks), volumes)
        if self.is_playing():
            self._renderer.update_volumes(self._volumes)

    def pause(self) -> None:
        if not self.is_playing():
            return
        self._last_position_ms = self.position_ms()
        self._stop_sink()

    def stop(self) -> None:
        self._last_position_ms = self.position_ms() if self.is_playing() else 0
        self._stop_sink()
        self._tracks.clear()
        self._track_start_frames.clear()
        self._track_effect_end_frames.clear()
        self._volumes.clear()
        self._effect_chains.clear()
        self._frame_index = 0
        self._duration_frames = 0
        self._duration_ms = 0
        self._start_ms = 0
        self._last_position_ms = 0
        self._transition = None

    def is_playing(self) -> bool:
        return self._audio_sink is not None and self.position_ms() < self._duration_ms

    def position_ms(self) -> int:
        if self._audio_sink is not None:
            processed_us = _processed_audio_microseconds(self._audio_sink)
            if processed_us is not None:
                elapsed_ms = processed_us // 1_000
            elif self._elapsed_timer.isValid():
                elapsed_ms = self._elapsed_timer.elapsed()
            else:
                elapsed_ms = 0
            self._last_position_ms = min(self._duration_ms, self._start_ms + elapsed_ms)
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
        if self._frame_index < self._duration_frames:
            self._renderer.ensure_lookahead()
        while self._audio_sink is not None and self._audio_sink.bytesFree() >= bytes_per_frame:
            if not self._pending_pcm:
                rendered = self._renderer.take_ready()
                if rendered is None:
                    self._record_underrun_if_needed()
                    return
                self._pending_pcm = _float_to_pcm16(rendered.audio)
            available_bytes = self._audio_sink.bytesFree()
            writable_bytes = min(len(self._pending_pcm), available_bytes)
            writable_bytes -= writable_bytes % bytes_per_frame
            if writable_bytes <= 0:
                return
            written_bytes = int(self._audio_device.write(self._pending_pcm[:writable_bytes]))
            if written_bytes <= 0:
                return
            self._pending_pcm = self._pending_pcm[written_bytes:]
            self._written_audio_bytes += written_bytes
            self._frame_index = min(
                self._duration_frames,
                self._output_start_frame + self._written_audio_bytes // bytes_per_frame,
            )
            if self._frame_index < self._duration_frames:
                self._renderer.ensure_lookahead()

    def _mix_live_chunk(self, frame_index: int, frame_count: int) -> np.ndarray:
        return _mix_effected_chunk(
            self._tracks,
            self._track_start_frames,
            self._track_effect_end_frames,
            self._volumes,
            self._effect_chains,
            frame_index,
            frame_count,
        )

    def _crossfade_replacement(
        self,
        new_chunk: np.ndarray,
        frame_index: int,
        frame_count: int,
    ) -> np.ndarray:
        transition = self._transition
        if transition is None or frame_index >= transition.end_frame:
            self._transition = None
            return new_chunk
        blended = _crossfade_transition(new_chunk, transition, frame_index, frame_count)
        if frame_index + frame_count >= transition.end_frame:
            self._transition = None
        return blended

    def _stop_sink(self) -> None:
        if self._feed_timer is not None:
            self._feed_timer.stop()
        if self._audio_sink is not None:
            self._audio_sink.stop()
            self._audio_sink.deleteLater()
        self._audio_sink = None
        self._audio_device = None
        self._pending_pcm = b""
        self._renderer.suspend()

    def _prepared_snapshot(self) -> PreparedPlaybackAudio:
        return PreparedPlaybackAudio(
            tracks=tuple(self._tracks),
            duration_frames=self._duration_frames,
            effect_chains=tuple(chain.effects for chain in self._effect_chains),
            track_start_frames=tuple(self._track_start_frames),
            track_effect_end_frames=tuple(self._track_effect_end_frames),
        )

    def _record_underrun_if_needed(self) -> None:
        sink = self._audio_sink
        if sink is None or self._elapsed_timer.elapsed() < 100:
            return
        if sink.bytesFree() < sink.bufferSize():
            return
        self._underrun_count += 1
        now = time.monotonic()
        if now - self._last_underrun_log_at < 5.0:
            return
        self._last_underrun_log_at = now
        _LOGGER.warning(
            "Audio renderer underrun | count=%s frame=%s pending=%s",
            self._underrun_count,
            self._frame_index,
            self._renderer.pending_count(),
        )

    def _validate_source(self, source: Path) -> None:
        _validate_playback_source(source)


def _audio_format() -> QAudioFormat:
    audio_format = QAudioFormat()
    audio_format.setSampleRate(_SAMPLE_RATE)
    audio_format.setChannelCount(_CHANNELS)
    audio_format.setSampleFormat(QAudioFormat.SampleFormat.Int16)
    return audio_format


def prepare_playback_audio(paths: Sequence[Path]) -> PreparedPlaybackAudio:
    sources = tuple(path.expanduser().resolve() for path in paths)
    for source in sources:
        _validate_playback_source(source)
    tracks = tuple(read_playback_audio(source) for source in sources)
    return PreparedPlaybackAudio(
        tracks=tracks,
        duration_frames=max((track.shape[0] for track in tracks), default=0),
    )


def _validate_playback_source(source: Path) -> None:
    if not source.exists():
        raise AudioPlaybackError(f"Audio file does not exist: {source}")
    if source.suffix.lower() != ".wav":
        raise AudioPlaybackError("Audio preview currently supports WAV files only.")


def read_playback_audio(path: Path) -> np.ndarray:
    try:
        audio, sample_rate = sf.read(path, always_2d=True, dtype="float32")
    except Exception as exc:
        raise AudioPlaybackError(f"Could not read audio file: {path}") from exc

    audio = _resample_audio(audio, sample_rate, _SAMPLE_RATE)
    return _match_channels(audio, _CHANNELS)


def _track_chunk(track: np.ndarray, frame_index: int, frame_count: int) -> np.ndarray:
    chunk = np.zeros((frame_count, _CHANNELS), dtype=np.float32)
    if frame_index >= track.shape[0]:
        return chunk
    end_index = min(frame_index + frame_count, track.shape[0])
    chunk[: end_index - frame_index] = track[frame_index:end_index]
    return chunk


def _mix_effected_chunk(
    tracks: Sequence[np.ndarray],
    track_start_frames: Sequence[int],
    track_effect_end_frames: Sequence[int],
    volumes: Sequence[float],
    effect_chains: Sequence[RealtimeEffectChain],
    frame_index: int,
    frame_count: int,
) -> np.ndarray:
    mix = np.zeros((frame_count, _CHANNELS), dtype=np.float32)
    for index, (track, volume) in enumerate(zip(tracks, volumes, strict=True)):
        start_frame = track_start_frames[index] if index < len(track_start_frames) else 0
        effect_end_frame = (
            track_effect_end_frames[index]
            if index < len(track_effect_end_frames)
            else start_frame + track.shape[0]
        )
        if frame_index + frame_count <= start_frame or frame_index >= effect_end_frame:
            continue
        chunk = _offset_track_chunk(track, start_frame, frame_index, frame_count)
        if index < len(effect_chains):
            chunk = effect_chains[index].process(chunk)
        if volume > 0.0:
            mix += chunk * volume
    return mix


def _crossfade_transition(
    new_chunk: np.ndarray,
    transition: _BufferTransition | None,
    frame_index: int,
    frame_count: int,
) -> np.ndarray:
    if transition is None or frame_index >= transition.end_frame:
        return new_chunk
    old_chunk = _mix_effected_chunk(
        transition.tracks,
        transition.track_start_frames,
        transition.track_effect_end_frames,
        transition.volumes,
        transition.effect_chains,
        frame_index,
        frame_count,
    )
    denominator = max(1, transition.end_frame - transition.start_frame)
    fade = np.clip(
        (np.arange(frame_count, dtype=np.float32) + frame_index - transition.start_frame)
        / denominator,
        0.0,
        1.0,
    )[:, None]
    return old_chunk * (1.0 - fade) + new_chunk * fade


def _offset_track_chunk(
    track: np.ndarray,
    track_start_frame: int,
    frame_index: int,
    frame_count: int,
) -> np.ndarray:
    relative_frame = frame_index - max(0, int(track_start_frame))
    chunk = np.zeros((frame_count, _CHANNELS), dtype=np.float32)
    source_start = max(0, relative_frame)
    output_start = max(0, -relative_frame)
    if source_start >= track.shape[0] or output_start >= frame_count:
        return chunk
    count = min(frame_count - output_start, track.shape[0] - source_start)
    chunk[output_start : output_start + count] = track[source_start : source_start + count]
    return chunk


def _build_effect_chains(prepared: PreparedPlaybackAudio) -> list[RealtimeEffectChain]:
    chains = prepared.effect_chains
    return [
        RealtimeEffectChain(_SAMPLE_RATE, chains[index] if index < len(chains) else ())
        for index in range(len(prepared.tracks))
    ]


def _resolve_track_start_frames(prepared: PreparedPlaybackAudio) -> list[int]:
    return [
        max(0, int(prepared.track_start_frames[index]))
        if index < len(prepared.track_start_frames)
        else 0
        for index in range(len(prepared.tracks))
    ]


def _resolve_track_effect_end_frames(prepared: PreparedPlaybackAudio) -> list[int]:
    starts = _resolve_track_start_frames(prepared)
    return [
        max(
            starts[index] + prepared.tracks[index].shape[0],
            int(prepared.track_effect_end_frames[index]),
        )
        if index < len(prepared.track_effect_end_frames)
        else starts[index] + prepared.tracks[index].shape[0]
        for index in range(len(prepared.tracks))
    ]


def _float_to_pcm16(audio: np.ndarray) -> bytes:
    return (np.clip(audio, -1.0, 1.0) * 32767).astype("<i2", copy=False).tobytes()


def _processed_audio_microseconds(audio_sink: QAudioSink) -> int | None:
    processed = getattr(audio_sink, "processedUSecs", None)
    if not callable(processed):
        return None
    try:
        value = int(processed())
    except (TypeError, ValueError, RuntimeError):
        return None
    return max(0, value)


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
    return clamp_studio_source_volume(volume)


def _frames_to_bytes(frame_count: int) -> int:
    return frame_count * _CHANNELS * 2
