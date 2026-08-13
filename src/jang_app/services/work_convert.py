from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from jang_app.services.output_catalog import OutputSoundSet, load_output_sound_set
from jang_app.services.song_library import SongVocalVersion
from jang_app.services.vocal_project import VocalProject


@dataclass(frozen=True)
class WorkConvertContext:
    input_version: SongVocalVersion | None
    result_version: SongVocalVersion | None
    selected_converted_path: Path | None


class WorkConvertSession:
    def __init__(
        self,
        selected_input_job_dir: Path | None = None,
        selected_converted_path: Path | None = None,
        *,
        versions: Sequence[SongVocalVersion] = (),
    ) -> None:
        self._selected_input_job_dir = selected_input_job_dir
        self._selected_converted_path = selected_converted_path
        self._versions: tuple[SongVocalVersion, ...] = ()
        self._versions_by_job_dir: dict[Path, SongVocalVersion] = {}
        self._owners_by_path: dict[Path, SongVocalVersion] = {}
        self._projects_by_job_dir: dict[Path, VocalProject] = {}
        self._cache_versions(versions)

    @property
    def selected_input_job_dir(self) -> Path | None:
        return self._selected_input_job_dir

    @property
    def selected_converted_path(self) -> Path | None:
        return self._selected_converted_path

    def refresh(
        self,
        versions: Sequence[SongVocalVersion],
        *,
        current_output_job_dir: Path | None = None,
        preferred_converted_path: Path | None = None,
    ) -> WorkConvertContext:
        self._cache_versions(versions)
        if not self._versions:
            self._selected_input_job_dir = None
            self._selected_converted_path = None
            return self.context()

        selected_input = self._selected_input_job_dir
        current_output = current_output_job_dir
        if not self._has_input_job_dir(selected_input):
            if self._has_input_job_dir(current_output):
                selected_input = current_output
            else:
                selected_input = self._versions[0].job_dir
        self._selected_input_job_dir = selected_input

        requested_converted = preferred_converted_path
        selected_converted = self._selected_converted_path
        if self._has_converted_path(requested_converted):
            selected_converted = requested_converted
        elif not self._has_converted_path(selected_converted):
            selected_converted = self._default_converted_path()
        self._selected_converted_path = selected_converted
        return self.context()

    def select_input_job_dir(
        self,
        job_dir: Path | None,
        *,
        clear_selected_converted: bool = False,
    ) -> WorkConvertContext:
        if self._has_input_job_dir(job_dir) or not self._versions_by_job_dir:
            self._selected_input_job_dir = job_dir
        elif job_dir is None:
            self._selected_input_job_dir = None
        if clear_selected_converted:
            self._selected_converted_path = None
        return self.context()

    def select_converted_path(self, path: Path | None) -> WorkConvertContext:
        if self._has_converted_path(path) or not self._owners_by_path:
            self._selected_converted_path = path
        elif path is None:
            self._selected_converted_path = None
        return self.context()

    def remember_converted_owner(
        self,
        version: SongVocalVersion | None,
        path: Path | None,
    ) -> WorkConvertContext:
        resolved = _optional_resolved(path)
        if version is not None:
            job_dir = version.job_dir.expanduser().resolve()
            if job_dir not in self._versions_by_job_dir:
                self._versions = (*self._versions, version)
                self._versions_by_job_dir[job_dir] = version
            if resolved is not None:
                self._owners_by_path[resolved] = version
            if not self._has_input_job_dir(self._selected_input_job_dir):
                self._selected_input_job_dir = version.job_dir
        self._selected_converted_path = path
        return self.context()

    def input_version(self) -> SongVocalVersion | None:
        if self._selected_input_job_dir is None:
            return None
        return self._versions_by_job_dir.get(
            _optional_resolved(self._selected_input_job_dir)
        )

    def result_version(self) -> SongVocalVersion | None:
        owner = self.version_for_converted_path(self._selected_converted_path)
        if owner is not None:
            return owner
        return self.input_version()

    def version_for_converted_path(
        self,
        path: Path | None,
    ) -> SongVocalVersion | None:
        resolved = _optional_resolved(path)
        if resolved is None:
            return None
        return self._owners_by_path.get(resolved)

    def job_dir_for_converted_path(
        self,
        path: Path | None,
        *,
        fallback_job_dir: Path | None = None,
    ) -> Path | None:
        owner = self.version_for_converted_path(path)
        if owner is not None:
            return owner.job_dir
        fallback = _optional_resolved(fallback_job_dir)
        if fallback is not None:
            return fallback
        return self._selected_input_job_dir

    def input_sound_set(self, output_root: Path) -> OutputSoundSet | None:
        version = self.input_version()
        if version is not None:
            return load_output_sound_set(version.job_dir, output_root)
        if self._selected_input_job_dir is None:
            return None
        return load_output_sound_set(self._selected_input_job_dir, output_root)

    def projects(
        self,
        load_project: Callable[[Path], VocalProject | None],
        *,
        on_error: Callable[[Path, Exception], None] | None = None,
    ) -> dict[Path, VocalProject]:
        current_projects: dict[Path, VocalProject] = {}
        for version in self._versions:
            job_dir = version.job_dir
            job_key = _optional_resolved(job_dir)
            if job_key is None or not version.converted_vocal_paths:
                if job_key is not None:
                    self._projects_by_job_dir.pop(job_key, None)
                continue
            project = self._projects_by_job_dir.get(job_key)
            if project is None:
                try:
                    project = load_project(job_dir)
                except Exception as exc:
                    if on_error is not None:
                        on_error(job_dir, exc)
                    continue
                if project is not None:
                    self._projects_by_job_dir[job_key] = project
            if project is not None:
                current_projects[job_dir] = project
        return current_projects

    def remember_project(self, job_dir: Path, project: VocalProject | None) -> None:
        resolved = _optional_resolved(job_dir)
        if resolved is None:
            return
        if project is None:
            self._projects_by_job_dir.pop(resolved, None)
            return
        self._projects_by_job_dir[resolved] = project

    def context(self) -> WorkConvertContext:
        return WorkConvertContext(
            input_version=self.input_version(),
            result_version=self.result_version(),
            selected_converted_path=self._selected_converted_path,
        )

    def _cache_versions(self, versions: Sequence[SongVocalVersion]) -> None:
        self._versions = tuple(versions)
        self._versions_by_job_dir = {
            version.job_dir.expanduser().resolve(): version
            for version in self._versions
        }
        self._owners_by_path = {
            path.expanduser().resolve(): version
            for version in self._versions
            for path in version.converted_vocal_paths
        }
        self._projects_by_job_dir = {
            job_key: project
            for job_key, project in self._projects_by_job_dir.items()
            if job_key in self._versions_by_job_dir
        }

    def _default_converted_path(self) -> Path | None:
        for version in self._versions:
            if self._has_converted_path(version.active_converted_path):
                return version.active_converted_path
        for version in self._versions:
            if version.converted_vocal_paths:
                return version.converted_vocal_paths[0]
        return None

    def _has_input_job_dir(self, job_dir: Path | None) -> bool:
        resolved = _optional_resolved(job_dir)
        return resolved in self._versions_by_job_dir if resolved is not None else False

    def _has_converted_path(self, path: Path | None) -> bool:
        resolved = _optional_resolved(path)
        return resolved in self._owners_by_path if resolved is not None else False


def _optional_resolved(path: Path | None) -> Path | None:
    return path.expanduser().resolve() if path is not None else None
