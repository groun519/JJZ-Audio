from __future__ import annotations

import math
from dataclasses import dataclass


PRESET_YOUTUBE_1080P = "youtube-1080p"
PRESET_HIGH_QUALITY = "high-quality"
PRESET_COMPACT_720P = "compact-720p"
PRESET_DISCORD_10MB = "discord-10mb"
PRESET_CUSTOM = "custom"

VIDEO_TARGET_10MB_BYTES = 9_500_000
VIDEO_TARGET_RESERVE_BYTES = 250_000
MIN_TARGET_VIDEO_BITRATE_KBPS = 96
MAX_TARGET_VIDEO_BITRATE_KBPS = 2_500

ENCODING_FAST = "fast"
ENCODING_STANDARD = "medium"
ENCODING_SLOW = "slow"


@dataclass(frozen=True)
class VideoExportSettings:
    preset_id: str = PRESET_YOUTUBE_1080P
    width: int = 1920
    height: int = 1080
    frame_rate: int = 30
    quality_crf: int = 18
    encoding_preset: str = ENCODING_STANDARD
    audio_bitrate_kbps: int = 320
    target_size_bytes: int | None = None

    def __post_init__(self) -> None:
        if self.preset_id not in {
            PRESET_YOUTUBE_1080P,
            PRESET_HIGH_QUALITY,
            PRESET_COMPACT_720P,
            PRESET_DISCORD_10MB,
            PRESET_CUSTOM,
        }:
            raise ValueError(f"Unsupported video export preset: {self.preset_id}")
        if (self.width, self.height) not in {
            (640, 360),
            (854, 480),
            (1280, 720),
            (1706, 960),
            (1920, 1080),
        }:
            raise ValueError("Video export resolution is unsupported.")
        if self.frame_rate not in {24, 30, 60}:
            raise ValueError("Video export frame rate must be 24, 30, or 60 fps.")
        if self.quality_crf not in {16, 18, 21, 24}:
            raise ValueError("Video export CRF must be 16, 18, 21, or 24.")
        if self.encoding_preset not in {
            ENCODING_FAST,
            ENCODING_STANDARD,
            ENCODING_SLOW,
        }:
            raise ValueError(f"Unsupported video encoding preset: {self.encoding_preset}")
        if self.audio_bitrate_kbps not in {64, 96, 128, 192, 256, 320}:
            raise ValueError("Video audio bitrate is unsupported.")
        if self.target_size_bytes is not None and self.target_size_bytes < 1_000_000:
            raise ValueError("Video export target size is too small.")

    @property
    def resolution_label(self) -> str:
        return f"{self.width}x{self.height}"

    @property
    def output_label(self) -> str:
        return {
            PRESET_YOUTUBE_1080P: "YouTube 1080p",
            PRESET_HIGH_QUALITY: "High Quality Video",
            PRESET_COMPACT_720P: "Compact 720p",
            PRESET_DISCORD_10MB: "Discord 10MB Video",
        }.get(self.preset_id, f"Custom {self.height}p")


@dataclass(frozen=True)
class VideoEncodingPlan:
    settings: VideoExportSettings
    video_bitrate_kbps: int | None = None

    @property
    def is_size_targeted(self) -> bool:
        return self.settings.target_size_bytes is not None


def video_export_preset(preset_id: str) -> VideoExportSettings:
    if preset_id == PRESET_YOUTUBE_1080P:
        return VideoExportSettings()
    if preset_id == PRESET_HIGH_QUALITY:
        return VideoExportSettings(
            preset_id=PRESET_HIGH_QUALITY,
            quality_crf=16,
            encoding_preset=ENCODING_SLOW,
        )
    if preset_id == PRESET_COMPACT_720P:
        return VideoExportSettings(
            preset_id=PRESET_COMPACT_720P,
            width=1280,
            height=720,
            quality_crf=24,
            audio_bitrate_kbps=192,
        )
    if preset_id == PRESET_DISCORD_10MB:
        return VideoExportSettings(
            preset_id=PRESET_DISCORD_10MB,
            width=1920,
            height=1080,
            frame_rate=24,
            quality_crf=24,
            encoding_preset=ENCODING_SLOW,
            audio_bitrate_kbps=96,
            target_size_bytes=VIDEO_TARGET_10MB_BYTES,
        )
    if preset_id == PRESET_CUSTOM:
        return VideoExportSettings(preset_id=PRESET_CUSTOM)
    raise ValueError(f"Unsupported video export preset: {preset_id}")


def video_encoding_plan(
    settings: VideoExportSettings,
    duration_seconds: float,
) -> VideoEncodingPlan:
    target_size = settings.target_size_bytes
    if target_size is None:
        return VideoEncodingPlan(settings)
    if duration_seconds <= 0:
        raise ValueError("Video duration must be greater than zero.")

    payload_bytes = max(0, target_size - VIDEO_TARGET_RESERVE_BYTES)
    total_bitrate = math.floor(payload_bytes * 8 * 0.95 / duration_seconds / 1000)
    audio_bitrate = _target_audio_bitrate(total_bitrate)
    video_bitrate = min(
        MAX_TARGET_VIDEO_BITRATE_KBPS,
        total_bitrate - audio_bitrate,
    )
    if video_bitrate < MIN_TARGET_VIDEO_BITRATE_KBPS:
        raise ValueError("The video is too long to keep usable quality within 10 MB.")

    resolved = VideoExportSettings(
        preset_id=settings.preset_id,
        width=settings.width,
        height=settings.height,
        frame_rate=24,
        quality_crf=settings.quality_crf,
        encoding_preset=settings.encoding_preset,
        audio_bitrate_kbps=audio_bitrate,
        target_size_bytes=target_size,
    )
    return VideoEncodingPlan(resolved, video_bitrate)


def _target_audio_bitrate(total_bitrate_kbps: int) -> int:
    if total_bitrate_kbps >= 700:
        return 128
    if total_bitrate_kbps >= 350:
        return 96
    return 64
