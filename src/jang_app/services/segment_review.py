from __future__ import annotations

import uuid
from collections.abc import Iterable
from dataclasses import dataclass, replace


SEGMENT_PENDING = "pending"
SEGMENT_HELD = "held"
SEGMENT_REJECTED = "rejected"
SEGMENT_STATUSES = frozenset({SEGMENT_PENDING, SEGMENT_HELD, SEGMENT_REJECTED})


@dataclass(frozen=True)
class SegmentCandidate:
    candidate_id: str
    start_ms: int
    end_ms: int
    status: str = SEGMENT_PENDING

    @property
    def duration_ms(self) -> int:
        return max(0, self.end_ms - self.start_ms)


def split_review_regions(
    ranges: Iterable[tuple[int, int]],
    max_duration_ms: int,
) -> tuple[tuple[int, int], ...]:
    maximum = max(100, int(max_duration_ms))
    result: list[tuple[int, int]] = []
    seen: set[tuple[int, int]] = set()
    for raw_start, raw_end in ranges:
        start = max(0, int(raw_start))
        end = max(start, int(raw_end))
        duration = end - start
        if duration < 100:
            continue
        segment_count = max(1, (duration + maximum - 1) // maximum)
        for index in range(segment_count):
            segment_start = start + round(duration * index / segment_count)
            segment_end = start + round(duration * (index + 1) / segment_count)
            segment = (segment_start, segment_end)
            if segment_end - segment_start >= 100 and segment not in seen:
                seen.add(segment)
                result.append(segment)
    return tuple(result)


def build_segment_candidates(
    ranges: Iterable[tuple[int, int]],
    existing: Iterable[SegmentCandidate] = (),
) -> tuple[SegmentCandidate, ...]:
    previous = {(item.start_ms, item.end_ms): item for item in existing}
    candidates: list[SegmentCandidate] = []
    for start_ms, end_ms in ranges:
        candidate = previous.get((start_ms, end_ms))
        candidates.append(
            candidate
            if candidate is not None
            else SegmentCandidate(uuid.uuid4().hex[:12], start_ms, end_ms)
        )
    return tuple(candidates)


def update_candidate_status(
    candidates: Iterable[SegmentCandidate],
    candidate_id: str,
    status: str,
) -> tuple[SegmentCandidate, ...]:
    normalized = normalize_segment_status(status)
    return tuple(
        replace(candidate, status=normalized) if candidate.candidate_id == candidate_id else candidate
        for candidate in candidates
    )


def normalize_segment_status(value: object) -> str:
    status = str(value)
    return status if status in SEGMENT_STATUSES else SEGMENT_PENDING
