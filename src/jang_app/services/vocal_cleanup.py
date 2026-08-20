from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


VOCAL_CLEANUP_EFFECT_DEREVERB = "dereverb"
VOCAL_CLEANUP_STRENGTHS = ("conservative", "standard", "strong")


@dataclass(frozen=True)
class VocalCleanupRegion:
    region_id: str
    start_ms: int
    end_ms: int
    effect: str
    strength: str
    processed_segment_path: Path
    removed_segment_path: Path
    created_at: str

    @property
    def duration_ms(self) -> int:
        return max(0, self.end_ms - self.start_ms)


@dataclass(frozen=True)
class VocalCleanupResult:
    result_id: str
    label: str
    path: Path
    created_at: str


@dataclass(frozen=True)
class VocalCleanupProject:
    source_path: Path
    source_fingerprint: str
    regions: tuple[VocalCleanupRegion, ...] = ()
    results: tuple[VocalCleanupResult, ...] = ()

    def region(self, region_id: str) -> VocalCleanupRegion | None:
        return next((item for item in self.regions if item.region_id == region_id), None)
