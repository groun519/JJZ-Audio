from __future__ import annotations

import json
import math
import os
import re
import tempfile
import uuid
from collections.abc import Callable, Sequence
from pathlib import Path

import numpy as np
import soundfile as sf

from jang_app.config import FFMPEG_BIN_DIR
from jang_app.services.audio_export import (
    AudioExportError,
    AudioMixSource,
    render_audio_mix,
)
from jang_app.services.audio_export_settings import (
    AUDIO_FORMAT_FLAC,
    AUDIO_FORMAT_MP3,
    AUDIO_FORMAT_OPUS,
    AUDIO_FORMAT_WAV,
    NORMALIZATION_OVERLOAD,
    NORMALIZATION_STREAMING,
    OPUS_MIN_MUSIC_BITRATE_KBPS,
    AudioExportSettings,
    discord_opus_bitrate_kbps,
)
from jang_app.services.command import run_command
from jang_app.services.environment import MissingExecutableError, require_executable


_LOUDNESS_JSON = re.compile(r"\{\s*\"input_i\".*?\}", re.DOTALL)
_OVERLOAD_CEILING_DB = -1.0


def export_final_audio_mix(
    sources: Sequence[AudioMixSource],
    output_path: Path,
    settings: AudioExportSettings,
    progress: Callable[[int], None] | None = None,
) -> Path:
    _report(progress, 2)
    rendered = render_audio_mix(sources)
    samples = rendered.samples
    if settings.normalization == NORMALIZATION_OVERLOAD:
        samples = _protect_overload(samples, _OVERLOAD_CEILING_DB)
    _report(progress, 28)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_output = output_path.with_name(
        f"{output_path.stem}.{uuid.uuid4().hex}.rendering{output_path.suffix}"
    )
    target_rate = _target_sample_rate(settings, rendered.sample_rate)
    direct_pcm = (
        settings.normalization != NORMALIZATION_STREAMING
        and settings.format in {AUDIO_FORMAT_WAV, AUDIO_FORMAT_FLAC}
        and target_rate == rendered.sample_rate
    )

    try:
        if direct_pcm:
            _write_pcm(temporary_output, samples, rendered.sample_rate, settings)
        else:
            _encode_with_ffmpeg(
                temporary_output,
                samples,
                rendered.sample_rate,
                target_rate,
                settings,
                progress,
            )
        os.replace(temporary_output, output_path)
    finally:
        try:
            temporary_output.unlink(missing_ok=True)
        except OSError:
            pass
    _report(progress, 100)
    return output_path.resolve()


def _write_pcm(
    output_path: Path,
    samples: np.ndarray,
    sample_rate: int,
    settings: AudioExportSettings,
) -> None:
    subtype = _soundfile_subtype(settings)
    prepared = samples
    if settings.dither and settings.bit_depth < 32:
        prepared = _apply_tpdf_dither(prepared, settings.bit_depth)
    sf.write(output_path, np.clip(prepared, -1.0, 1.0), sample_rate, subtype=subtype)


def _encode_with_ffmpeg(
    output_path: Path,
    samples: np.ndarray,
    source_rate: int,
    target_rate: int,
    settings: AudioExportSettings,
    progress: Callable[[int], None] | None,
) -> None:
    try:
        executable = require_executable(
            "ffmpeg",
            "Install the JJZero Audio media runtime before exporting compressed audio.",
            [FFMPEG_BIN_DIR],
        )
    except MissingExecutableError as exc:
        raise AudioExportError(str(exc)) from exc

    with tempfile.TemporaryDirectory(prefix="audio-export-", dir=output_path.parent) as temporary:
        master_path = Path(temporary) / "master-float.wav"
        sf.write(master_path, samples, source_rate, subtype="FLOAT")
        _report(progress, 42)
        loudness = None
        if settings.normalization == NORMALIZATION_STREAMING:
            loudness = _measure_loudness(executable, master_path)
            _report(progress, 62)
        command = _encoding_command(
            executable,
            master_path,
            output_path,
            source_rate,
            target_rate,
            settings,
            loudness,
            duration_seconds=len(samples) / max(1, source_rate),
        )
        completed = run_command(command)
        if completed.returncode != 0 or not output_path.is_file():
            raise AudioExportError(f"FFmpeg audio export failed. {completed.output}")
        if settings.target_size_bytes is not None and output_path.stat().st_size > settings.target_size_bytes:
            _retry_size_targeted_opus(
                executable,
                master_path,
                output_path,
                source_rate,
                target_rate,
                settings,
                loudness,
                len(samples) / max(1, source_rate),
            )
        _report(progress, 92)


def _measure_loudness(executable: str, master_path: Path) -> dict[str, str]:
    completed = run_command(
        (
            executable,
            "-hide_banner",
            "-nostats",
            "-i",
            str(master_path),
            "-af",
            "loudnorm=I=-14:TP=-1:LRA=11:print_format=json",
            "-f",
            "null",
            "-",
        )
    )
    match = _LOUDNESS_JSON.search(completed.output)
    if completed.returncode != 0 or match is None:
        raise AudioExportError(f"FFmpeg loudness analysis failed. {completed.output}")
    try:
        values = json.loads(match.group(0))
    except json.JSONDecodeError as exc:
        raise AudioExportError("FFmpeg returned invalid loudness analysis data.") from exc
    return {str(key): str(value) for key, value in values.items()}


def _encoding_command(
    executable: str,
    master_path: Path,
    output_path: Path,
    source_rate: int,
    target_rate: int,
    settings: AudioExportSettings,
    loudness: dict[str, str] | None = None,
    duration_seconds: float = 0.0,
    bitrate_override_kbps: int | None = None,
) -> list[str]:
    filters: list[str] = []
    if loudness is not None:
        filters.append(
            "loudnorm=I=-14:TP=-1:LRA=11:"
            f"measured_I={loudness['input_i']}:"
            f"measured_TP={loudness['input_tp']}:"
            f"measured_LRA={loudness['input_lra']}:"
            f"measured_thresh={loudness['input_thresh']}:"
            f"offset={loudness['target_offset']}:linear=true"
        )
    if target_rate != source_rate or (
        settings.dither
        and settings.format not in {AUDIO_FORMAT_MP3, AUDIO_FORMAT_OPUS}
        and settings.bit_depth < 32
    ):
        dither = "triangular_hp" if settings.dither else "none"
        filters.append(
            f"aresample={target_rate}:filter_size=64:phase_shift=10:"
            f"exact_rational=1:dither_method={dither}"
        )

    command = [
        executable,
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(master_path),
        "-vn",
    ]
    if filters:
        command.extend(("-af", ",".join(filters)))
    command.extend(("-ar", str(target_rate)))
    try:
        command.extend(_codec_options(settings, duration_seconds, bitrate_override_kbps))
    except ValueError as exc:
        raise AudioExportError(str(exc)) from exc
    command.append(str(output_path))
    return command


def _codec_options(
    settings: AudioExportSettings,
    duration_seconds: float = 0.0,
    bitrate_override_kbps: int | None = None,
) -> list[str]:
    if settings.format == AUDIO_FORMAT_WAV:
        codec = {16: "pcm_s16le", 24: "pcm_s24le", 32: "pcm_f32le"}[settings.bit_depth]
        return ["-c:a", codec]
    if settings.format == AUDIO_FORMAT_FLAC:
        sample_format = "s16" if settings.bit_depth == 16 else "s32"
        options = ["-c:a", "flac", "-compression_level", "8", "-sample_fmt", sample_format]
        if settings.bit_depth == 24:
            options.extend(("-bits_per_raw_sample", "24"))
        return options
    if settings.format == AUDIO_FORMAT_OPUS:
        bitrate = _resolved_opus_bitrate(settings, duration_seconds, bitrate_override_kbps)
        return [
            "-c:a",
            "libopus",
            "-b:a",
            f"{bitrate}k",
            "-vbr",
            "constrained",
            "-compression_level",
            "10",
            "-application",
            "audio",
        ]
    return ["-c:a", "libmp3lame", "-b:a", f"{settings.mp3_bitrate_kbps}k"]


def _soundfile_subtype(settings: AudioExportSettings) -> str:
    if settings.format == AUDIO_FORMAT_FLAC:
        return "PCM_16" if settings.bit_depth == 16 else "PCM_24"
    return {16: "PCM_16", 24: "PCM_24", 32: "FLOAT"}[settings.bit_depth]


def _target_sample_rate(settings: AudioExportSettings, source_rate: int) -> int:
    if settings.format == AUDIO_FORMAT_OPUS:
        return 48_000
    if settings.sample_rate is not None:
        return settings.sample_rate
    if settings.format == AUDIO_FORMAT_MP3 and source_rate > 48_000:
        return 48_000
    return source_rate


def _resolved_opus_bitrate(
    settings: AudioExportSettings,
    duration_seconds: float,
    override_kbps: int | None = None,
) -> int:
    if override_kbps is not None:
        return override_kbps
    if settings.target_size_bytes is not None:
        return discord_opus_bitrate_kbps(duration_seconds, settings.target_size_bytes)
    return settings.opus_bitrate_kbps or 192


def _retry_size_targeted_opus(
    executable: str,
    master_path: Path,
    output_path: Path,
    source_rate: int,
    target_rate: int,
    settings: AudioExportSettings,
    loudness: dict[str, str] | None,
    duration_seconds: float,
) -> None:
    target_size = settings.target_size_bytes
    if target_size is None:
        return
    bitrate = _resolved_opus_bitrate(settings, duration_seconds)
    for _attempt in range(2):
        actual_size = output_path.stat().st_size
        if actual_size <= target_size:
            return
        bitrate = math.floor(bitrate * target_size / actual_size * 0.96)
        if bitrate < OPUS_MIN_MUSIC_BITRATE_KBPS:
            break
        output_path.unlink(missing_ok=True)
        completed = run_command(
            _encoding_command(
                executable,
                master_path,
                output_path,
                source_rate,
                target_rate,
                settings,
                loudness,
                duration_seconds,
                bitrate,
            )
        )
        if completed.returncode != 0 or not output_path.is_file():
            raise AudioExportError(f"FFmpeg audio export failed. {completed.output}")
    if not output_path.is_file() or output_path.stat().st_size > target_size:
        raise AudioExportError("Could not keep the Discord audio export under 10 MB.")


def _protect_overload(samples: np.ndarray, ceiling_db: float) -> np.ndarray:
    peak = float(np.max(np.abs(samples))) if samples.size else 0.0
    ceiling = math.pow(10.0, ceiling_db / 20.0)
    if peak <= ceiling or peak <= 0.0:
        return samples
    return np.asarray(samples * (ceiling / peak), dtype=np.float32)


def _apply_tpdf_dither(samples: np.ndarray, bit_depth: int) -> np.ndarray:
    step = 1.0 / math.pow(2.0, bit_depth - 1)
    generator = np.random.default_rng()
    noise = (generator.random(samples.shape) - generator.random(samples.shape)) * step
    return np.asarray(samples + noise, dtype=np.float32)


def _report(progress: Callable[[int], None] | None, value: int) -> None:
    if progress is not None:
        progress(max(0, min(100, value)))
