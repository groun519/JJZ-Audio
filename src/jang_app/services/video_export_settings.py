from __future__ import annotations

from dataclasses import dataclass


PRESET_YOUTUBE_1080P = "youtube-1080p"
PRESET_HIGH_QUALITY = "high-quality"
PRESET_COMPACT_720P = "compact-720p"
PRESET_CUSTOM = "custom"

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

    def __post_init__(self) -> None:
        if self.preset_id not in {
            PRESET_YOUTUBE_1080P,
            PRESET_HIGH_QUALITY,
            PRESET_COMPACT_720P,
            PRESET_CUSTOM,
        }:
            raise ValueError(f"Unsupported video export preset: {self.preset_id}")
        if (self.width, self.height) not in {(1280, 720), (1920, 1080)}:
            raise ValueError("Video export resolution must be 1280x720 or 1920x1080.")
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
        if self.audio_bitrate_kbps not in {192, 256, 320}:
            raise ValueError("Video audio bitrate must be 192, 256, or 320 kbps.")

    @property
    def resolution_label(self) -> str:
        return f"{self.width}x{self.height}"

    @property
    def output_label(self) -> str:
        return {
            PRESET_YOUTUBE_1080P: "YouTube 1080p",
            PRESET_HIGH_QUALITY: "High Quality Video",
            PRESET_COMPACT_720P: "Compact 720p",
        }.get(self.preset_id, f"Custom {self.height}p")


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
    if preset_id == PRESET_CUSTOM:
        return VideoExportSettings(preset_id=PRESET_CUSTOM)
    raise ValueError(f"Unsupported video export preset: {preset_id}")
