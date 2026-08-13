from __future__ import annotations

import math
from dataclasses import dataclass


AUDIO_FORMAT_WAV = "wav"
AUDIO_FORMAT_FLAC = "flac"
AUDIO_FORMAT_MP3 = "mp3"
AUDIO_FORMAT_OPUS = "opus"

NORMALIZATION_OFF = "off"
NORMALIZATION_OVERLOAD = "overload"
NORMALIZATION_STREAMING = "streaming"

PRESET_MASTER_WAV = "master-wav"
PRESET_LOSSLESS_FLAC = "lossless-flac"
PRESET_SHARE_MP3 = "share-mp3"
PRESET_DISCORD_10MB = "discord-10mb"
PRESET_CUSTOM = "custom"

DISCORD_TARGET_BYTES = 9_500_000
OPUS_MIN_MUSIC_BITRATE_KBPS = 48
OPUS_MAX_BITRATE_KBPS = 320


@dataclass(frozen=True)
class AudioExportSettings:
    preset_id: str = PRESET_MASTER_WAV
    format: str = AUDIO_FORMAT_WAV
    sample_rate: int | None = None
    bit_depth: int = 24
    normalization: str = NORMALIZATION_OVERLOAD
    dither: bool = True
    mp3_bitrate_kbps: int = 320
    opus_bitrate_kbps: int | None = 192
    target_size_bytes: int | None = None

    def __post_init__(self) -> None:
        if self.preset_id not in {
            PRESET_MASTER_WAV,
            PRESET_LOSSLESS_FLAC,
            PRESET_SHARE_MP3,
            PRESET_DISCORD_10MB,
            PRESET_CUSTOM,
        }:
            raise ValueError(f"Unsupported audio export preset: {self.preset_id}")
        if self.format not in {
            AUDIO_FORMAT_WAV,
            AUDIO_FORMAT_FLAC,
            AUDIO_FORMAT_MP3,
            AUDIO_FORMAT_OPUS,
        }:
            raise ValueError(f"Unsupported audio export format: {self.format}")
        if self.sample_rate not in {None, 44_100, 48_000}:
            raise ValueError(f"Unsupported audio export sample rate: {self.sample_rate}")
        if self.normalization not in {
            NORMALIZATION_OFF,
            NORMALIZATION_OVERLOAD,
            NORMALIZATION_STREAMING,
        }:
            raise ValueError(f"Unsupported normalization mode: {self.normalization}")
        if self.format == AUDIO_FORMAT_FLAC and self.bit_depth not in {16, 24}:
            raise ValueError("FLAC export supports 16-bit or 24-bit output.")
        if self.format == AUDIO_FORMAT_WAV and self.bit_depth not in {16, 24, 32}:
            raise ValueError("WAV export supports 16-bit, 24-bit, or 32-bit float output.")
        if self.format == AUDIO_FORMAT_MP3 and self.mp3_bitrate_kbps not in {
            128,
            192,
            256,
            320,
        }:
            raise ValueError("MP3 export bitrate must be 128, 192, 256, or 320 kbps.")
        if self.format == AUDIO_FORMAT_OPUS and self.opus_bitrate_kbps not in {
            None,
            64,
            96,
            128,
            160,
            192,
            256,
            320,
        }:
            raise ValueError("Opus export bitrate is unsupported.")
        if self.target_size_bytes is not None:
            if self.format != AUDIO_FORMAT_OPUS:
                raise ValueError("Size-targeted export is only supported for Opus.")
            if self.target_size_bytes < 1_000_000:
                raise ValueError("Audio export target size is too small.")

    @property
    def extension(self) -> str:
        return ".ogg" if self.format == AUDIO_FORMAT_OPUS else f".{self.format}"

    @property
    def output_label(self) -> str:
        return {
            PRESET_MASTER_WAV: "Master WAV",
            PRESET_LOSSLESS_FLAC: "Lossless FLAC",
            PRESET_SHARE_MP3: "Share MP3",
            PRESET_DISCORD_10MB: "Discord 10MB",
        }.get(self.preset_id, f"Custom {self.format.upper()}")


def audio_export_preset(preset_id: str) -> AudioExportSettings:
    if preset_id == PRESET_MASTER_WAV:
        return AudioExportSettings()
    if preset_id == PRESET_LOSSLESS_FLAC:
        return AudioExportSettings(
            preset_id=PRESET_LOSSLESS_FLAC,
            format=AUDIO_FORMAT_FLAC,
        )
    if preset_id == PRESET_SHARE_MP3:
        return AudioExportSettings(
            preset_id=PRESET_SHARE_MP3,
            format=AUDIO_FORMAT_MP3,
            bit_depth=24,
            normalization=NORMALIZATION_STREAMING,
            dither=False,
        )
    if preset_id == PRESET_DISCORD_10MB:
        return AudioExportSettings(
            preset_id=PRESET_DISCORD_10MB,
            format=AUDIO_FORMAT_OPUS,
            sample_rate=48_000,
            bit_depth=24,
            normalization=NORMALIZATION_STREAMING,
            dither=False,
            opus_bitrate_kbps=None,
            target_size_bytes=DISCORD_TARGET_BYTES,
        )
    if preset_id == PRESET_CUSTOM:
        return AudioExportSettings(preset_id=PRESET_CUSTOM)
    raise ValueError(f"Unsupported audio export preset: {preset_id}")


def discord_opus_bitrate_kbps(
    duration_seconds: float,
    target_size_bytes: int = DISCORD_TARGET_BYTES,
) -> int:
    if duration_seconds <= 0:
        return OPUS_MAX_BITRATE_KBPS
    payload_bytes = max(0, target_size_bytes - 64_000)
    bitrate = math.floor(payload_bytes * 8 * 0.96 / duration_seconds / 1000)
    if bitrate < OPUS_MIN_MUSIC_BITRATE_KBPS:
        raise ValueError("The audio is too long to keep music quality within 10 MB.")
    return min(OPUS_MAX_BITRATE_KBPS, bitrate)


def estimated_opus_size_bytes(duration_seconds: float, bitrate_kbps: int) -> int:
    if duration_seconds <= 0:
        return 0
    payload = duration_seconds * bitrate_kbps * 1000 / 8
    return round(payload * 1.02 + 64_000)
