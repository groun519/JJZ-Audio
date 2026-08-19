from __future__ import annotations


STUDIO_BASE_PIXELS_PER_SECOND = 7
STUDIO_MIN_PIXELS_PER_SECOND = 2
STUDIO_MAX_ZOOM_FACTOR = 20
STUDIO_MAX_PIXELS_PER_SECOND = (
    STUDIO_BASE_PIXELS_PER_SECOND * STUDIO_MAX_ZOOM_FACTOR
)


def studio_zoom_label(pixels_per_second: int) -> str:
    factor = max(0, int(pixels_per_second)) / STUDIO_BASE_PIXELS_PER_SECOND
    if factor.is_integer():
        return f"{int(factor)}x"
    return f"{factor:.1f}x"
