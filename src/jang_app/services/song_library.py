from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path

from jang_app.config import DOWNLOAD_OUTPUT_DIR, SONG_LIBRARY_FILE, SUPPORTED_AUDIO_EXTENSIONS
from jang_app.services.output_catalog import OutputSoundSet
from jang_app.services.song_package import SongPackage, SongPackageStore


@dataclass(frozen=True)
class SongItem:
    id: str
    path: Path
    kind: str = "source"
    output_job_dir: Path | None = None
    title_override: str = ""
    source_type: str = "local"
    package_dir: Path | None = None

    @property
    def title(self) -> str:
        if self.title_override:
            return self.title_override
        if self.output_job_dir is not None and self.kind == "output":
            return self.output_job_dir.name
        return self.path.stem

    @property
    def format_label(self) -> str:
        if self.kind == "output":
            return "OUTPUT"
        return self.path.suffix.removeprefix(".").upper() or "AUDIO"

    @property
    def size_label(self) -> str:
        try:
            size_mb = self.path.stat().st_size / (1024 * 1024)
        except OSError:
            return "Unknown size"
        return f"{size_mb:.1f} MB"


class SongLibrary:
    def __init__(
        self,
        library_file: Path = SONG_LIBRARY_FILE,
        package_store: SongPackageStore | None = None,
    ) -> None:
        self._library_file = library_file
        self._store = package_store or SongPackageStore()
        self._legacy_titles: dict[str, str] = {}
        self._legacy_hidden_outputs: set[Path] = set()
        self._legacy_paths: tuple[Path, ...] = ()
        self._load_legacy_index()
        self._migrate_legacy_sources()

    def add_paths(self, paths: list[Path]) -> list[SongItem]:
        added: list[SongItem] = []
        for path in paths:
            source = path.expanduser().resolve()
            if not _is_supported_audio(source):
                continue
            legacy_id = _legacy_song_id(source)
            package, was_added = self._store.import_audio(
                source,
                title=self._legacy_titles.get(legacy_id, "") or source.stem,
                source_type=_source_type_for_path(source),
            )
            if was_added:
                added.append(_item_from_package(package))
        return added

    def add_youtube_audio(self, path: Path, title: str, url: str) -> SongItem | None:
        source = path.expanduser().resolve()
        if not _is_supported_audio(source):
            return None
        package, _was_added = self._store.import_audio(
            source,
            title=title,
            source_type="youtube",
            source_url=url,
        )
        return _item_from_package(package)

    def add_output_sets(self, sound_sets: list[OutputSoundSet]) -> None:
        for sound_set in sound_sets:
            job_dir = sound_set.job_dir.expanduser().resolve()
            if job_dir in self._legacy_hidden_outputs:
                continue

            existing = self._store.find_by_output_job_dir(job_dir, include_removed=True)
            source_packages = [
                package
                for package in self._store.packages()
                if package.source_path is not None and (existing is None or package.song_id != existing.song_id)
            ]
            match = _best_output_match(sound_set, source_packages)
            if existing is not None and existing.source_path is not None:
                continue
            if match is not None:
                self._store.attach_output(match.song_id, job_dir, sound_set.label)
                if existing is not None:
                    self._store.set_removed(existing.song_id, True)
                continue

            legacy_id = _legacy_output_song_id(job_dir)
            self._store.create_output_recovery(
                self._legacy_titles.get(legacy_id, "") or job_dir.name,
                job_dir,
                sound_set.label,
            )

    def items(self) -> list[SongItem]:
        return [_item_from_package(package) for package in self._store.packages()]

    def rename_item(self, item_id: str, title: str) -> bool:
        try:
            self._store.rename(item_id, title)
        except (KeyError, ValueError):
            return False
        return True

    def remove_item(self, item_id: str) -> bool:
        try:
            self._store.set_removed(item_id, True)
        except KeyError:
            return False
        return True

    def _load_legacy_index(self) -> None:
        if not self._library_file.is_file():
            return
        try:
            data = json.loads(self._library_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        if not isinstance(data, dict):
            return

        titles = data.get("titles")
        if isinstance(titles, dict):
            self._legacy_titles = {
                str(key): str(value).strip()
                for key, value in titles.items()
                if isinstance(value, str) and value.strip()
            }
        hidden_outputs = data.get("hidden_outputs")
        if isinstance(hidden_outputs, list):
            self._legacy_hidden_outputs = {
                Path(value).expanduser().resolve()
                for value in hidden_outputs
                if isinstance(value, str) and value.strip()
            }
        paths = data.get("paths")
        if isinstance(paths, list):
            self._legacy_paths = tuple(
                Path(value).expanduser().resolve()
                for value in paths
                if isinstance(value, str) and value.strip()
            )

    def _migrate_legacy_sources(self) -> None:
        self.add_paths(list(self._legacy_paths))


def _item_from_package(package: SongPackage) -> SongItem:
    active_output = package.active_output
    if package.source_path is not None:
        return SongItem(
            id=package.song_id,
            path=package.source_path,
            kind="source",
            output_job_dir=active_output.job_dir if active_output is not None else None,
            title_override=package.title,
            source_type=package.source_type,
            package_dir=package.folder,
        )
    if active_output is None:
        raise ValueError(f"Song package has neither source nor output: {package.song_id}")
    return SongItem(
        id=package.song_id,
        path=active_output.job_dir / "vocals.wav",
        kind="output",
        output_job_dir=active_output.job_dir,
        title_override=package.title,
        source_type="output",
        package_dir=package.folder,
    )


def _best_output_match(sound_set: OutputSoundSet, packages: list[SongPackage]) -> SongPackage | None:
    output_keys = {_normalize_name(sound_set.job_dir.name), _normalize_name(sound_set.label)}
    scored: list[tuple[int, SongPackage]] = []
    for package in packages:
        source_keys = {
            _normalize_name(package.title),
            _normalize_name(Path(package.original_name).stem),
        }
        score = max((_match_score(source, output) for source in source_keys for output in output_keys), default=0)
        if score > 0:
            scored.append((score, package))
    if not scored:
        return None
    scored.sort(key=lambda item: item[0], reverse=True)
    if len(scored) > 1 and scored[0][0] == scored[1][0]:
        return None
    return scored[0][1]


def _match_score(source: str, output: str) -> int:
    if not source or not output:
        return 0
    if source == output:
        return 1000 + len(source)
    shortest = min(len(source), len(output))
    if shortest >= 6 and (source in output or output in source):
        return 500 + shortest
    return 0


def _normalize_name(value: str) -> str:
    return re.sub(r"[\W_]+", "", value, flags=re.UNICODE).casefold()


def _is_supported_audio(path: Path) -> bool:
    return path.is_file() and path.suffix.lower() in SUPPORTED_AUDIO_EXTENSIONS


def _source_type_for_path(path: Path) -> str:
    try:
        if DOWNLOAD_OUTPUT_DIR.expanduser().resolve() in path.parents:
            return "youtube"
    except OSError:
        pass
    return "local"


def _legacy_song_id(path: Path) -> str:
    return hashlib.sha1(str(path).casefold().encode("utf-8")).hexdigest()[:12]


def _legacy_output_song_id(job_dir: Path) -> str:
    return f"out-{hashlib.sha1(str(job_dir).casefold().encode('utf-8')).hexdigest()[:12]}"
