from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from jang_app.services.song_library import SongVocalVersion
from jang_app.services.vocal_split import VocalSplitRun, VocalSplitStem


@dataclass(frozen=True)
class VocalInputChoice:
    choice_id: str
    version: SongVocalVersion
    path: Path
    label: str
    kind: str = "original"
    split_run: VocalSplitRun | None = None
    split_stem: VocalSplitStem | None = None


def original_vocal_choice(version: SongVocalVersion) -> VocalInputChoice:
    return VocalInputChoice(
        choice_id=f"original:{version.version_id}",
        version=version,
        path=version.vocals_path,
        label=version.separation_recipe_label or version.label,
    )


def split_vocal_choice(
    version: SongVocalVersion,
    run: VocalSplitRun,
    stem: VocalSplitStem,
) -> VocalInputChoice:
    return VocalInputChoice(
        choice_id=f"split:{run.run_id}:{stem.stem_id}",
        version=version,
        path=stem.path,
        label=stem.label,
        kind=stem.role or "split",
        split_run=run,
        split_stem=stem,
    )
