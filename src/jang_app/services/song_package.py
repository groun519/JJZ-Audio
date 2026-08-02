from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path

from jang_app.config import PROJECT_ROOT, SONG_WORKSPACE_DIR
from jang_app.services.file_names import safe_filename_stem
from jang_app.services.managed_files import copy_file_atomic, file_sha256, write_json_atomic


SONG_MANIFEST_VERSION = 1
SONG_MANIFEST_NAME = "song.json"
SOURCE_STAGE = "01_source"
VOCAL_STAGE = "02_vocal"
STUDIO_STAGE = "03_studio"
EXPORT_STAGE = "04_exports"


@dataclass(frozen=True)
class SongOutputReference:
    output_id: str
    label: str
    job_dir: Path
    added_at: str


@dataclass(frozen=True)
class SongPackage:
    song_id: str
    title: str
    folder: Path
    source_path: Path | None
    source_type: str
    source_url: str
    source_hash: str
    original_name: str
    outputs: tuple[SongOutputReference, ...]
    active_output_id: str
    created_at: str
    removed: bool = False

    @property
    def active_output(self) -> SongOutputReference | None:
        if self.active_output_id:
            selected = next((item for item in self.outputs if item.output_id == self.active_output_id), None)
            if selected is not None:
                return selected
        return self.outputs[0] if self.outputs else None


class SongPackageStore:
    def __init__(self, root: Path = SONG_WORKSPACE_DIR, project_root: Path = PROJECT_ROOT) -> None:
        self.root = root.expanduser().resolve()
        self.project_root = project_root.expanduser().resolve()

    def packages(self, *, include_removed: bool = False) -> list[SongPackage]:
        if not self.root.is_dir():
            return []
        packages: list[SongPackage] = []
        for manifest_path in self.root.glob(f"*/{SONG_MANIFEST_NAME}"):
            try:
                package = self._load_manifest(manifest_path)
            except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError):
                continue
            if include_removed or not package.removed:
                packages.append(package)
        return sorted(packages, key=lambda item: item.title.casefold())

    def import_audio(
        self,
        source: Path,
        *,
        title: str = "",
        source_type: str = "local",
        source_url: str = "",
    ) -> tuple[SongPackage, bool]:
        source = source.expanduser().resolve()
        content_hash = file_sha256(source)
        existing = next(
            (item for item in self.packages(include_removed=True) if item.source_hash == content_hash),
            None,
        )
        if existing is not None:
            if existing.removed:
                existing = replace(existing, removed=False)
                self._save(existing)
                return existing, True
            return existing, False

        display_title = title.strip() or source.stem
        song_id = f"song-{content_hash[:16]}"
        folder_name = f"{safe_filename_stem(display_title, fallback='song', max_length=56)}__{song_id[-8:]}"
        folder = self.root / folder_name
        self._create_stage_directories(folder)
        managed_source = folder / SOURCE_STAGE / "audio" / _managed_source_name(source, song_id)
        copy_file_atomic(source, managed_source)
        package = SongPackage(
            song_id=song_id,
            title=display_title,
            folder=folder,
            source_path=managed_source,
            source_type=source_type if source_type in {"local", "youtube"} else "local",
            source_url=source_url.strip(),
            source_hash=content_hash,
            original_name=source.name,
            outputs=(),
            active_output_id="",
            created_at=_now(),
        )
        self._save(package)
        return package, True

    def create_output_recovery(self, title: str, job_dir: Path, label: str) -> SongPackage:
        resolved_job = job_dir.expanduser().resolve()
        existing = self.find_by_output_job_dir(resolved_job, include_removed=True)
        if existing is not None:
            if existing.removed:
                existing = replace(existing, removed=False)
                self._save(existing)
            return existing

        output_id = _output_id(resolved_job)
        song_id = f"song-{output_id.removeprefix('output-')}"
        display_title = title.strip() or resolved_job.name
        folder_name = f"{safe_filename_stem(display_title, fallback='recovered', max_length=56)}__{song_id[-8:]}"
        folder = self.root / folder_name
        self._create_stage_directories(folder)
        output = SongOutputReference(output_id, label, resolved_job, _now())
        package = SongPackage(
            song_id=song_id,
            title=display_title,
            folder=folder,
            source_path=None,
            source_type="output",
            source_url="",
            source_hash="",
            original_name="",
            outputs=(output,),
            active_output_id=output_id,
            created_at=_now(),
        )
        self._save(package)
        return package

    def attach_output(self, song_id: str, job_dir: Path, label: str) -> SongPackage:
        package = self.require(song_id)
        resolved_job = job_dir.expanduser().resolve()
        output_id = _output_id(resolved_job)
        outputs = tuple(item for item in package.outputs if item.output_id != output_id)
        outputs = (SongOutputReference(output_id, label, resolved_job, _now()), *outputs)
        updated = replace(package, outputs=outputs, active_output_id=output_id)
        self._save(updated)
        return updated

    def rename(self, song_id: str, title: str) -> SongPackage:
        value = title.strip()
        if not value:
            raise ValueError("Song title is required")
        updated = replace(self.require(song_id), title=value)
        self._save(updated)
        return updated

    def set_removed(self, song_id: str, removed: bool) -> SongPackage:
        updated = replace(self.require(song_id, include_removed=True), removed=removed)
        self._save(updated)
        return updated

    def require(self, song_id: str, *, include_removed: bool = False) -> SongPackage:
        package = next(
            (item for item in self.packages(include_removed=include_removed) if item.song_id == song_id),
            None,
        )
        if package is None:
            raise KeyError(f"Song package does not exist: {song_id}")
        return package

    def find_by_output_job_dir(self, job_dir: Path, *, include_removed: bool = False) -> SongPackage | None:
        target = job_dir.expanduser().resolve()
        return next(
            (
                package
                for package in self.packages(include_removed=include_removed)
                if any(item.job_dir == target for item in package.outputs)
            ),
            None,
        )

    def _save(self, package: SongPackage) -> None:
        self._create_stage_directories(package.folder)
        source = None
        if package.source_path is not None:
            source = {
                "audio": _relative_path(package.folder, package.source_path),
                "type": package.source_type,
                "url": package.source_url,
                "sha256": package.source_hash,
                "original_name": package.original_name,
            }
        data = {
            "version": SONG_MANIFEST_VERSION,
            "id": package.song_id,
            "title": package.title,
            "created_at": package.created_at,
            "removed": package.removed,
            "source": source,
            "vocal": {
                "active_output_id": package.active_output_id,
                "outputs": [
                    {
                        "id": item.output_id,
                        "label": item.label,
                        "job_dir": self._workspace_path(item.job_dir),
                        "added_at": item.added_at,
                    }
                    for item in package.outputs
                ],
            },
        }
        write_json_atomic(package.folder / SONG_MANIFEST_NAME, data)

    def _load_manifest(self, manifest_path: Path) -> SongPackage:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        if data.get("version") != SONG_MANIFEST_VERSION:
            raise ValueError("Unsupported song manifest version")
        folder = manifest_path.parent.resolve()
        source_data = data.get("source")
        source_path = None
        source_type = "output"
        source_url = ""
        source_hash = ""
        original_name = ""
        if isinstance(source_data, dict):
            source_path = _resolve_relative_path(folder, source_data.get("audio"))
            source_type = str(source_data.get("type", "local"))
            source_url = str(source_data.get("url", ""))
            source_hash = str(source_data.get("sha256", ""))
            original_name = str(source_data.get("original_name", ""))

        vocal_data = data.get("vocal") if isinstance(data.get("vocal"), dict) else {}
        outputs = tuple(
            SongOutputReference(
                output_id=str(item["id"]),
                label=str(item.get("label", "")),
                job_dir=self._resolve_workspace_path(item.get("job_dir")),
                added_at=str(item.get("added_at", "")),
            )
            for item in vocal_data.get("outputs", [])
            if isinstance(item, dict)
        )
        package = SongPackage(
            song_id=str(data["id"]),
            title=str(data["title"]),
            folder=folder,
            source_path=source_path,
            source_type=source_type,
            source_url=source_url,
            source_hash=source_hash,
            original_name=original_name,
            outputs=outputs,
            active_output_id=str(vocal_data.get("active_output_id", "")),
            created_at=str(data["created_at"]),
            removed=bool(data.get("removed", False)),
        )
        return self._migrate_managed_source_name(package)

    def _migrate_managed_source_name(self, package: SongPackage) -> SongPackage:
        source = package.source_path
        if source is None or source.stem != "source" or not source.is_file():
            return package
        original = Path(package.original_name) if package.original_name else source
        target = source.with_name(_managed_source_name(original, package.song_id))
        if not target.exists():
            source.replace(target)
        updated = replace(package, source_path=target)
        self._save(updated)
        return updated

    def _workspace_path(self, path: Path) -> str:
        resolved = path.expanduser().resolve()
        try:
            return f"@project/{resolved.relative_to(self.project_root).as_posix()}"
        except ValueError:
            return str(resolved)

    def _resolve_workspace_path(self, value: object) -> Path:
        if not isinstance(value, str) or not value:
            raise ValueError("Output path is missing")
        if value.startswith("@project/"):
            resolved = (self.project_root / Path(value.removeprefix("@project/"))).resolve()
            if not _is_within(resolved, self.project_root):
                raise ValueError("Output path leaves the project workspace")
            return resolved
        return Path(value).expanduser().resolve()

    @staticmethod
    def _create_stage_directories(folder: Path) -> None:
        for relative in (
            Path(SOURCE_STAGE) / "audio",
            Path(SOURCE_STAGE) / "video",
            Path(VOCAL_STAGE),
            Path(STUDIO_STAGE),
            Path(EXPORT_STAGE),
        ):
            (folder / relative).mkdir(parents=True, exist_ok=True)


def _output_id(job_dir: Path) -> str:
    digest = hashlib.sha256(str(job_dir.resolve()).casefold().encode("utf-8")).hexdigest()[:16]
    return f"output-{digest}"


def _managed_source_name(source: Path, song_id: str) -> str:
    stem = safe_filename_stem(source.stem, fallback="audio", max_length=48)
    return f"{stem}__{song_id[-8:]}{source.suffix.lower()}"


def _relative_path(folder: Path, path: Path) -> str:
    resolved = path.resolve()
    if not _is_within(resolved, folder):
        raise ValueError("Song source path leaves its package")
    return resolved.relative_to(folder.resolve()).as_posix()


def _resolve_relative_path(folder: Path, value: object) -> Path:
    if not isinstance(value, str) or not value:
        raise ValueError("Song source path is missing")
    resolved = (folder / Path(value)).resolve()
    if not _is_within(resolved, folder):
        raise ValueError("Song source path leaves its package")
    return resolved


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _now() -> str:
    return datetime.now(UTC).isoformat()
