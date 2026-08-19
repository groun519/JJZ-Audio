from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class VocalSplitStem:
    stem_id: str
    role: str
    label: str
    path: Path
    parent_stem_id: str = ""
    generation: int = 0
    active: bool = True
    origin: str = "vocal"


@dataclass(frozen=True)
class VocalReferenceRegion:
    region_id: str
    start_ms: int
    end_ms: int

    @property
    def duration_ms(self) -> int:
        return max(0, self.end_ms - self.start_ms)


@dataclass(frozen=True)
class VocalSplitOperation:
    operation_id: str
    input_stem_id: str
    output_stem_ids: tuple[str, str]
    reference_regions: tuple[VocalReferenceRegion, ...]
    model: str
    created_at: str

    @property
    def reference_start_ms(self) -> int:
        return min((region.start_ms for region in self.reference_regions), default=0)

    @property
    def reference_end_ms(self) -> int:
        return max((region.end_ms for region in self.reference_regions), default=0)


@dataclass(frozen=True)
class VocalSplitRun:
    run_id: str
    parent_job_dir: Path
    input_path: Path
    method_id: str
    method_label: str
    model: str
    created_at: str
    stems: tuple[VocalSplitStem, ...]
    nodes: tuple[VocalSplitStem, ...] = ()
    operations: tuple[VocalSplitOperation, ...] = ()

    @property
    def group_id(self) -> str:
        return self.run_id

    @property
    def all_stems(self) -> tuple[VocalSplitStem, ...]:
        return self.nodes or self.stems

    def stem(self, stem_id: str) -> VocalSplitStem | None:
        return next((stem for stem in self.stems if stem.stem_id == stem_id), None)

    def node(self, stem_id: str) -> VocalSplitStem | None:
        return next((stem for stem in self.all_stems if stem.stem_id == stem_id), None)
