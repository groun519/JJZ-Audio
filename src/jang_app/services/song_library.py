from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from jang_app.config import DOWNLOAD_OUTPUT_DIR, SONG_LIBRARY_FILE, SUPPORTED_AUDIO_EXTENSIONS
from jang_app.services.audio_export import AudioMixSource
from jang_app.services.audio_export_settings import AudioExportSettings
from jang_app.services.export_catalog import rename_exported_file
from jang_app.services.output_catalog import OutputSoundSet, load_output_sound_set
from jang_app.services.song_asset_removal import SongAssetRemovalResult, SongAssetRemovalService
from jang_app.services.song_assets import SongAssetDetails, build_song_asset_details
from jang_app.services.song_package import (
    EXPORT_STAGE,
    VOCAL_STAGE,
    SongOutputReference,
    SongPackage,
    SongPackageStore,
)
from jang_app.services.separation_recipe import load_separation_run
from jang_app.services.song_video_export import (
    SongVideoExport,
    can_render_song_video,
    list_song_video_exports,
    render_song_video,
    song_video_export_dir,
)
from jang_app.services.song_export import (
    SongAudioExport,
    build_song_mix_sources,
    export_song_mix,
    list_song_audio_exports,
    render_studio_preview,
    song_audio_export_dir,
)
from jang_app.services.studio_assets import StudioSoundAsset, studio_sound_pool
from jang_app.services.studio_project import (
    StudioProjectRecoveryNotice,
    StudioProjectRevision,
    StudioProjectViewState,
    consume_studio_project_recovery_notice,
    load_studio_project_view_state,
    save_studio_project_view_state,
    restore_studio_project_revision,
    studio_project_missing_asset_ids,
    studio_project_revisions,
)
from jang_app.services.studio_session import (
    StudioSession,
    load_studio_session as load_package_studio_session,
    save_studio_session as save_package_studio_session,
)
from jang_app.services.video_source import VideoSource, VideoSourceStore
from jang_app.services.video_export_settings import VideoExportSettings


@dataclass(frozen=True)
class SongItem:
    id: str
    path: Path
    kind: str = "source"
    output_job_dir: Path | None = None
    title_override: str = ""
    source_type: str = "local"
    source_url: str = ""
    package_dir: Path | None = None
    created_at: str = ""

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


def sort_song_items(items: list[SongItem], sort_mode: str) -> list[SongItem]:
    if sort_mode == "oldest":
        return sorted(items, key=lambda item: (_created_timestamp(item), item.title.casefold(), item.id))
    if sort_mode == "name_asc":
        return sorted(items, key=lambda item: (item.title.casefold(), -_created_timestamp(item), item.id))
    if sort_mode == "name_desc":
        return sorted(
            items,
            key=lambda item: (item.title.casefold(), _created_timestamp(item), item.id),
            reverse=True,
        )
    return sorted(items, key=lambda item: (-_created_timestamp(item), item.title.casefold(), item.id))


@dataclass(frozen=True)
class SongVocalVersion:
    version_id: str
    label: str
    job_dir: Path
    added_at: str
    vocals_path: Path
    instrumental_path: Path
    converted_vocal_paths: tuple[Path, ...]
    active_converted_path: Path | None = None
    separation_recipe_id: str = ""
    separation_recipe_label: str = "Legacy"
    separation_recipe_summary: str = ""
    separation_postprocess_status: str = "not_requested"


@dataclass(frozen=True)
class StudioWorkspaceSnapshot:
    session: StudioSession
    assets: tuple[StudioSoundAsset, ...]
    missing_asset_ids: tuple[str, ...] = ()


class SongLibrary:
    def __init__(
        self,
        library_file: Path = SONG_LIBRARY_FILE,
        package_store: SongPackageStore | None = None,
    ) -> None:
        self._library_file = library_file
        self._store = package_store or SongPackageStore()
        self._video_sources = VideoSourceStore()
        self._asset_removal = SongAssetRemovalService(self._store, self._video_sources)
        self._legacy_titles: dict[str, str] = {}
        self._legacy_hidden_outputs: set[Path] = set()
        self._legacy_paths: tuple[Path, ...] = ()
        self._output_sound_sets_by_job_dir: dict[Path, OutputSoundSet] = {}
        self._store.purge_legacy_removed_data()
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

    def attach_source(self, item_id: str, path: Path) -> SongItem:
        source = path.expanduser().resolve()
        if not _is_supported_audio(source):
            raise ValueError("Select a supported audio file")
        return _item_from_package(self._store.attach_source(item_id, source))

    def add_output_sets(self, sound_sets: list[OutputSoundSet]) -> None:
        packages = self._store.packages(include_removed=True)
        detached_output_dirs = {
            job_dir
            for package in packages
            for job_dir in package.detached_output_dirs
        }
        source_packages = [
            package
            for package in packages
            if not package.removed and package.source_path is not None
        ]
        for sound_set in sound_sets:
            job_dir = sound_set.job_dir.expanduser().resolve()
            if job_dir in self._legacy_hidden_outputs or job_dir in detached_output_dirs:
                continue
            self._remember_output_sound_set(sound_set)

            existing = next(
                (
                    package
                    for package in packages
                    if any(output.job_dir == job_dir for output in package.outputs)
                ),
                None,
            )
            match = _best_output_match(
                sound_set,
                [
                    package
                    for package in source_packages
                    if existing is None or package.song_id != existing.song_id
                ],
            )
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

    def asset_details(self, item_id: str) -> SongAssetDetails:
        return build_song_asset_details(self._store.require(item_id))

    def remove_asset(self, item_id: str, path: Path) -> SongAssetRemovalResult:
        return self._asset_removal.remove(item_id, path)

    def remove_assets(
        self,
        item_id: str,
        paths: tuple[Path, ...],
    ) -> tuple[SongAssetRemovalResult, ...]:
        return self._asset_removal.remove_many(item_id, paths)

    def studio_session(self, item_id: str) -> StudioSession:
        return load_package_studio_session(self._store.require(item_id))

    def save_studio_session(
        self,
        item_id: str,
        session: StudioSession,
        assets: tuple[StudioSoundAsset, ...] | None = None,
    ) -> Path:
        return save_package_studio_session(
            self._store.require(item_id),
            session,
            assets=assets,
        )

    def studio_assets(self, item_id: str) -> tuple[StudioSoundAsset, ...]:
        return studio_sound_pool(self._store.require(item_id))

    def studio_view_state(self, item_id: str) -> StudioProjectViewState:
        return load_studio_project_view_state(self._store.require(item_id))

    def save_studio_view_state(
        self,
        item_id: str,
        state: StudioProjectViewState,
    ) -> Path:
        return save_studio_project_view_state(self._store.require(item_id), state)

    def consume_studio_recovery_notice(
        self,
        item_id: str,
    ) -> StudioProjectRecoveryNotice:
        return consume_studio_project_recovery_notice(self._store.require(item_id))

    def studio_revisions(self, item_id: str) -> tuple[StudioProjectRevision, ...]:
        return studio_project_revisions(self._store.require(item_id))

    def restore_studio_revision(self, item_id: str, revision: int) -> StudioSession:
        package = self._store.require(item_id)
        restore_studio_project_revision(package, revision)
        return load_package_studio_session(package)

    def studio_workspace(self, item_id: str) -> StudioWorkspaceSnapshot:
        package = self._store.require(item_id)
        assets = studio_sound_pool(package)
        return StudioWorkspaceSnapshot(
            load_package_studio_session(package, assets=assets),
            assets,
            studio_project_missing_asset_ids(package),
        )

    def studio_mix_sources(
        self,
        item_id: str,
        session: StudioSession,
        assets: tuple[StudioSoundAsset, ...] | None = None,
    ) -> tuple[AudioMixSource, ...]:
        return build_song_mix_sources(
            self._store.require(item_id),
            session,
            assets,
        )

    def render_studio_preview(self, item_id: str, session: StudioSession) -> Path:
        return render_studio_preview(self._store.require(item_id), session)

    def video_source(self, item_id: str) -> VideoSource:
        return self._video_sources.resolve(self._store.require(item_id))

    def managed_video_sources(self, item_id: str) -> tuple[VideoSource, ...]:
        return self._video_sources.managed_sources(self._store.require(item_id))

    def select_managed_video(self, item_id: str, path: Path) -> VideoSource:
        return self._video_sources.select_managed(self._store.require(item_id), path)

    def set_video_file(
        self,
        item_id: str,
        source: Path,
        progress: Callable[[int], None] | None = None,
    ) -> VideoSource:
        return self._video_sources.import_file(self._store.require(item_id), source, progress)

    def set_video_url(self, item_id: str, url: str) -> VideoSource:
        return self._video_sources.set_url(self._store.require(item_id), url)

    def download_video_source(
        self,
        item_id: str,
        progress: Callable[[int], None] | None = None,
    ) -> VideoSource:
        return self._video_sources.materialize(self._store.require(item_id), progress)

    def clear_video_source(self, item_id: str) -> VideoSource:
        package = self._store.require(item_id)
        self._video_sources.clear(package)
        return self._video_sources.resolve(package)

    def export_audio_mix(
        self,
        item_id: str,
        settings: AudioExportSettings | None = None,
        progress: Callable[[int], None] | None = None,
    ) -> Path:
        package = self._store.require(item_id)
        return export_song_mix(
            package,
            load_package_studio_session(package),
            settings,
            progress,
        )

    def audio_exports(self, item_id: str) -> tuple[SongAudioExport, ...]:
        return list_song_audio_exports(self._store.require(item_id))

    def audio_export_dir(self, item_id: str) -> Path:
        return song_audio_export_dir(self._store.require(item_id))

    def render_video(
        self,
        item_id: str,
        settings: VideoExportSettings | None = None,
        progress: Callable[[int], None] | None = None,
    ) -> Path:
        package = self._store.require(item_id)
        return render_song_video(
            package,
            self._video_sources.resolve(package),
            load_package_studio_session(package),
            progress=progress,
            settings=settings,
        )

    def can_render_video(self, item_id: str) -> bool:
        package = self._store.require(item_id)
        return can_render_song_video(
            package,
            self._video_sources.resolve(package),
            load_package_studio_session(package),
        )

    def video_export_dir(self, item_id: str) -> Path:
        return song_video_export_dir(self._store.require(item_id))

    def video_exports(self, item_id: str) -> tuple[SongVideoExport, ...]:
        return list_song_video_exports(self._store.require(item_id))

    def rename_export(self, item_id: str, source: Path, name: str) -> Path:
        package = self._store.require(item_id)
        export_root = (package.folder / EXPORT_STAGE).resolve()
        resolved = source.expanduser().resolve()
        try:
            resolved.relative_to(export_root)
        except ValueError as exc:
            raise ValueError("Exported file is outside the selected song package.") from exc
        return rename_exported_file(resolved, name)

    def vocal_separation_root(self, item_id: str) -> Path:
        return self._store.vocal_separation_root(item_id)

    def create_vocal_separation_run(self, item_id: str) -> Path:
        return self._store.create_vocal_separation_run(item_id)

    def register_output(self, item_id: str, job_dir: Path, label: str) -> SongItem:
        package = self._store.attach_output(item_id, job_dir, label)
        self._cache_output_sound_set(package.folder / VOCAL_STAGE, job_dir)
        return _item_from_package(package)

    def activate_output(self, job_dir: Path) -> SongItem | None:
        package = self._store.find_by_output_job_dir(job_dir)
        if package is None:
            return None
        return _item_from_package(self._store.activate_output(package.song_id, job_dir))

    def activate_converted_output(self, job_dir: Path, converted_path: Path | None) -> SongItem | None:
        package = self._store.find_by_output_job_dir(job_dir)
        if package is None:
            return None
        updated = self._store.activate_converted_output(package.song_id, job_dir, converted_path)
        return _item_from_package(updated)

    def detach_output(self, job_dir: Path) -> SongItem | None:
        package = self._store.find_by_output_job_dir(job_dir)
        if package is None:
            return None
        detached = self._store.detach_output(package.song_id, job_dir)
        self._output_sound_sets_by_job_dir.pop(job_dir.expanduser().resolve(), None)
        return _item_from_package(detached)

    def vocal_versions(self, item_id: str) -> tuple[SongVocalVersion, ...]:
        package = self._store.require(item_id)
        versions: list[SongVocalVersion] = []
        for output in package.outputs:
            job_dir = output.job_dir.expanduser().resolve()
            sound_set = self._output_sound_sets_by_job_dir.get(job_dir)
            if sound_set is None:
                sound_set = self._cache_output_sound_set(package.folder / VOCAL_STAGE, job_dir)
            if sound_set is None:
                continue
            versions.append(_vocal_version_from_output(output, sound_set))
        return tuple(versions)

    def output_sound_sets(self) -> list[OutputSoundSet]:
        sound_sets: list[tuple[str, OutputSoundSet]] = []
        seen_job_dirs: set[Path] = set()
        for package in self._store.packages():
            for output in package.outputs:
                job_dir = output.job_dir.expanduser().resolve()
                if job_dir in seen_job_dirs:
                    continue
                sound_set = self._output_sound_sets_by_job_dir.get(job_dir)
                if sound_set is None:
                    sound_set = self._cache_output_sound_set(
                        package.folder / VOCAL_STAGE,
                        job_dir,
                    )
                if sound_set is None:
                    continue
                seen_job_dirs.add(job_dir)
                display_label = f"{package.title} / {output.label or sound_set.label}"
                sound_sets.append(
                    (
                        output.added_at,
                        OutputSoundSet(
                            label=display_label,
                            job_dir=sound_set.job_dir,
                            vocals_path=sound_set.vocals_path,
                            instrumental_path=sound_set.instrumental_path,
                            converted_vocal_paths=sound_set.converted_vocal_paths,
                        ),
                    )
                )
        sound_sets.sort(key=lambda item: item[0], reverse=True)
        return [sound_set for _added_at, sound_set in sound_sets]

    def refresh_output_sound_sets(self) -> list[OutputSoundSet]:
        """Reload registered output folders before returning the catalog."""
        for package in self._store.packages():
            for output in package.outputs:
                self._cache_output_sound_set(
                    package.folder / VOCAL_STAGE,
                    output.job_dir,
                )
        return self.output_sound_sets()

    def _cache_output_sound_set(
        self,
        output_root: Path,
        job_dir: Path,
    ) -> OutputSoundSet | None:
        sound_set = load_output_sound_set(job_dir, output_root)
        if sound_set is None:
            self._output_sound_sets_by_job_dir.pop(job_dir.expanduser().resolve(), None)
            return None
        return self._remember_output_sound_set(sound_set)

    def _remember_output_sound_set(self, sound_set: OutputSoundSet) -> OutputSoundSet:
        self._output_sound_sets_by_job_dir[sound_set.job_dir.expanduser().resolve()] = sound_set
        return sound_set

    def rename_item(self, item_id: str, title: str) -> bool:
        try:
            self._store.rename(item_id, title)
        except (KeyError, ValueError):
            return False
        return True

    def remove_item(self, item_id: str) -> bool:
        try:
            self._store.remove_managed_data(item_id)
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
            source_url=package.source_url,
            package_dir=package.folder,
            created_at=package.created_at,
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
        source_url="",
        package_dir=package.folder,
        created_at=package.created_at,
    )


def _created_timestamp(item: SongItem) -> float:
    if item.created_at:
        try:
            return datetime.fromisoformat(item.created_at.replace("Z", "+00:00")).timestamp()
        except ValueError:
            pass
    try:
        return item.path.stat().st_mtime
    except OSError:
        return 0.0


def _vocal_version_from_output(
    output: SongOutputReference,
    sound_set: OutputSoundSet,
) -> SongVocalVersion:
    active_converted = output.active_converted_path
    if active_converted not in sound_set.converted_vocal_paths:
        active_converted = sound_set.converted_vocal_paths[0] if sound_set.converted_vocal_paths else None
    run = load_separation_run(sound_set.job_dir)
    return SongVocalVersion(
        version_id=output.output_id,
        label=output.label or sound_set.label,
        job_dir=sound_set.job_dir,
        added_at=output.added_at,
        vocals_path=sound_set.vocals_path,
        instrumental_path=sound_set.instrumental_path,
        converted_vocal_paths=sound_set.converted_vocal_paths,
        active_converted_path=active_converted,
        separation_recipe_id=run.recipe.recipe_id,
        separation_recipe_label=run.recipe.label,
        separation_recipe_summary=run.recipe.summary,
        separation_postprocess_status=run.postprocess_status,
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
