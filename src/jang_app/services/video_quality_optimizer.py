from __future__ import annotations

import re
from dataclasses import dataclass


ADAPTIVE_VIDEO_RESOLUTIONS = (
    (1920, 1080),
    (1706, 960),
    (1280, 720),
    (854, 480),
)

_VMAF_SCORE_PATTERN = re.compile(r"VMAF score:\s*([0-9]+(?:\.[0-9]+)?)", re.IGNORECASE)
_SSIM_SCORE_PATTERN = re.compile(r"All:\s*([0-9]+(?:\.[0-9]+)?)", re.IGNORECASE)


@dataclass(frozen=True)
class VideoSampleWindow:
    start_ms: int
    duration_ms: int


def representative_video_windows(duration_ms: int) -> tuple[VideoSampleWindow, ...]:
    if duration_ms <= 0:
        raise ValueError("Video duration must be greater than zero.")
    if duration_ms <= 18_000:
        return (VideoSampleWindow(0, duration_ms),)

    sample_duration = min(6_000, max(2_000, duration_ms // 12))
    windows: list[VideoSampleWindow] = []
    for position in (0.15, 0.50, 0.85):
        center = round(duration_ms * position)
        start = max(0, min(duration_ms - sample_duration, center - sample_duration // 2))
        window = VideoSampleWindow(start, sample_duration)
        if window not in windows:
            windows.append(window)
    return tuple(windows)


def adaptive_resolution_candidates(
    maximum: tuple[int, int],
    *,
    source_pixel_ceiling: int | None = None,
) -> tuple[tuple[int, int], ...]:
    maximum_width, maximum_height = maximum
    supported = tuple(
        resolution
        for resolution in ADAPTIVE_VIDEO_RESOLUTIONS
        if resolution[0] <= maximum_width and resolution[1] <= maximum_height
    )
    if maximum not in supported:
        supported = (maximum,) + supported
    if source_pixel_ceiling is None:
        return supported

    native = tuple(
        resolution
        for resolution in supported
        if resolution[0] * resolution[1] <= source_pixel_ceiling
    )
    return native or (supported[-1],)


def parse_vmaf_score(output: str) -> float | None:
    matches = _VMAF_SCORE_PATTERN.findall(output)
    return float(matches[-1]) if matches else None


def parse_ssim_score(output: str) -> float | None:
    matches = _SSIM_SCORE_PATTERN.findall(output)
    return float(matches[-1]) * 100 if matches else None


def best_scored_resolution(
    scores: dict[tuple[int, int], float],
) -> tuple[int, int]:
    if not scores:
        raise ValueError("At least one video quality score is required.")
    return max(
        scores,
        key=lambda resolution: (
            scores[resolution],
            resolution[0] * resolution[1],
        ),
    )
