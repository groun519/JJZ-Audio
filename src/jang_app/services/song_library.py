from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, replace
from pathlib import Path

from jang_app.config import DOWNLOAD_OUTPUT_DIR, SONG_LIBRARY_FILE, SUPPORTED_AUDIO_EXTENSIONS
from jang_app.services.file_names import safe_filename_stem, unique_path
from jang_app.services.output_catalog import OutputSoundSet


@dataclass(frozen=True)
class SongItem:
    id: str
    path: Path
    kind: str = "source"
    output_job_dir: Path | None = None
    title_override: str = ""

    @property
    def title(self) -> str:
        if self.title_override:
            return self.title_override
        if self.output_job_dir is not None:
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
    def __init__(self, library_file: Path = SONG_LIBRARY_FILE) -> None:
        self._library_file = library_file
        self._source_items_by_path: dict[Path, SongItem] = {}
        self._output_items_by_job_dir: dict[Path, SongItem] = {}
        self._title_overrides_by_id: dict[str, str] = {}
        self._hidden_output_job_dirs: set[Path] = set()
        self._load()

    def add_paths(self, paths: list[Path]) -> list[SongItem]:
        added: list[SongItem] = []
        for path in paths:
            resolved = _normalize_project_download_path(path.expanduser().resolve())
            if not _is_supported_audio(resolved) or resolved in self._source_items_by_path:
                continue
            song_id = _song_id(resolved)
            item = SongItem(song_id, resolved, title_override=self._title_overrides_by_id.get(song_id, ""))
            self._source_items_by_path[resolved] = item
            added.append(item)
        if added:
            self._save()
        return added

    def add_output_sets(self, sound_sets: list[OutputSoundSet]) -> None:
        self._output_items_by_job_dir = {}
        for sound_set in sound_sets:
            job_dir = sound_set.job_dir.expanduser().resolve()
            if job_dir in self._hidden_output_job_dirs:
                continue
            song_id = _output_song_id(job_dir)
            self._output_items_by_job_dir[job_dir] = SongItem(
                id=song_id,
                path=sound_set.vocals_path.expanduser().resolve(),
                kind="output",
                output_job_dir=job_dir,
                title_override=self._title_overrides_by_id.get(song_id, ""),
            )

    def items(self) -> list[SongItem]:
        return sorted(
            [*self._source_items_by_path.values(), *self._output_items_by_job_dir.values()],
            key=lambda item: (item.kind != "source", item.title.casefold()),
        )

    def rename_item(self, item_id: str, title: str) -> bool:
        next_title = title.strip()
        if not next_title:
            return False

        for path, item in list(self._source_items_by_path.items()):
            if item.id == item_id:
                self._title_overrides_by_id[item_id] = next_title
                self._source_items_by_path[path] = replace(item, title_override=next_title)
                self._save()
                return True

        for job_dir, item in list(self._output_items_by_job_dir.items()):
            if item.id == item_id:
                self._title_overrides_by_id[item_id] = next_title
                self._output_items_by_job_dir[job_dir] = replace(item, title_override=next_title)
                self._save()
                return True
        return False

    def remove_item(self, item_id: str) -> bool:
        for path, item in list(self._source_items_by_path.items()):
            if item.id == item_id:
                del self._source_items_by_path[path]
                self._title_overrides_by_id.pop(item_id, None)
                self._save()
                return True

        for job_dir, item in list(self._output_items_by_job_dir.items()):
            if item.id == item_id:
                self._hidden_output_job_dirs.add(job_dir)
                del self._output_items_by_job_dir[job_dir]
                self._save()
                return True
        return False

    def _load(self) -> None:
        if not self._library_file.exists():
            return

        try:
            data = json.loads(self._library_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return

        titles = data.get("titles") if isinstance(data, dict) else None
        if isinstance(titles, dict):
            self._title_overrides_by_id = {
                str(key): str(value).strip()
                for key, value in titles.items()
                if isinstance(value, str) and value.strip()
            }

        hidden_outputs = data.get("hidden_outputs") if isinstance(data, dict) else None
        if isinstance(hidden_outputs, list):
            self._hidden_output_job_dirs = {
                Path(value).expanduser().resolve()
                for value in hidden_outputs
                if isinstance(value, str) and value.strip()
            }

        paths = data.get("paths") if isinstance(data, dict) else None
        if not isinstance(paths, list):
            return

        did_normalize = False
        for value in paths:
            if not isinstance(value, str):
                continue
            path = Path(value).expanduser().resolve()
            normalized = _normalize_project_download_path(path)
            did_normalize = did_normalize or normalized != path
            if _is_supported_audio(normalized):
                song_id = _song_id(normalized)
                self._source_items_by_path[normalized] = SongItem(
                    song_id,
                    normalized,
                    title_override=self._title_overrides_by_id.get(song_id, ""),
                )
        if did_normalize:
            self._save()

    def _save(self) -> None:
        self._library_file.parent.mkdir(parents=True, exist_ok=True)
        paths = [str(path) for path in sorted(self._source_items_by_path)]
        data = {
            "paths": paths,
            "titles": dict(sorted(self._title_overrides_by_id.items())),
            "hidden_outputs": [str(path) for path in sorted(self._hidden_output_job_dirs)],
        }
        self._library_file.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _is_supported_audio(path: Path) -> bool:
    return path.is_file() and path.suffix.lower() in SUPPORTED_AUDIO_EXTENSIONS


def _normalize_project_download_path(path: Path) -> Path:
    download_root = DOWNLOAD_OUTPUT_DIR.expanduser().resolve()
    if not path.is_file() or download_root not in path.parents:
        return path

    safe_stem = safe_filename_stem(path.stem, fallback="downloaded_audio", max_length=92)
    target = path.with_name(f"{safe_stem}{path.suffix.lower()}")
    if target == path:
        return path
    try:
        target = unique_path(target)
        path.rename(target)
    except OSError:
        return path
    return target.expanduser().resolve()


def _song_id(path: Path) -> str:
    return hashlib.sha1(str(path).casefold().encode("utf-8")).hexdigest()[:12]


def _output_song_id(job_dir: Path) -> str:
    return f"out-{hashlib.sha1(str(job_dir).casefold().encode('utf-8')).hexdigest()[:12]}"
