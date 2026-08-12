from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

from jang_app.services.output_catalog import load_output_sound_set
from jang_app.services.song_assets import (
    REMOVAL_FILE,
    REMOVAL_STUDIO_SESSION,
    REMOVAL_VIDEO,
    REMOVAL_VOCAL_OUTPUT,
    REMOVAL_VOCAL_TAKE,
    SongAsset,
    build_song_asset_details,
)
from jang_app.services.song_package import SongOutputReference, SongPackage, SongPackageStore, VOCAL_STAGE
from jang_app.services.video_source import VideoSourceStore
from jang_app.services.vocal_project_store import VocalProjectStore


class SongAssetRemovalError(RuntimeError):
    pass


@dataclass(frozen=True)
class SongAssetRemovalResult:
    asset: SongAsset
    detached_only: bool = False
    removed_output_dir: Path | None = None


class SongAssetRemovalService:
    def __init__(
        self,
        package_store: SongPackageStore,
        video_sources: VideoSourceStore,
        vocal_projects: VocalProjectStore | None = None,
    ) -> None:
        self._packages = package_store
        self._video_sources = video_sources
        self._vocal_projects = vocal_projects or VocalProjectStore()

    def remove(self, song_id: str, path: Path) -> SongAssetRemovalResult:
        package = self._packages.require(song_id)
        asset = self._require_removable_asset(package, path)

        if asset.removal_scope == REMOVAL_VIDEO:
            self._remove_video(package, asset)
            return SongAssetRemovalResult(asset)
        if asset.removal_scope == REMOVAL_VOCAL_OUTPUT:
            return self._remove_vocal_output(package, asset)
        if asset.removal_scope == REMOVAL_VOCAL_TAKE:
            self._remove_vocal_take(package, asset)
            return SongAssetRemovalResult(asset)
        if asset.removal_scope == REMOVAL_STUDIO_SESSION:
            self._remove_managed_file(package, asset.path)
            return SongAssetRemovalResult(asset)
        if asset.removal_scope == REMOVAL_FILE:
            self._remove_managed_file(package, asset.path)
            return SongAssetRemovalResult(asset)
        raise SongAssetRemovalError("This library item cannot be removed separately.")

    def remove_many(
        self,
        song_id: str,
        paths: tuple[Path, ...],
    ) -> tuple[SongAssetRemovalResult, ...]:
        package = self._packages.require(song_id)
        assets_by_path = {
            asset.path.expanduser().resolve(): asset
            for asset in build_song_asset_details(package).assets
            if asset.can_remove
        }
        selected: list[SongAsset] = []
        for path in paths:
            asset = assets_by_path.get(path.expanduser().resolve())
            if asset is None:
                raise SongAssetRemovalError("The selected library data is missing or protected.")
            if asset not in selected:
                selected.append(asset)

        selected_output_dirs = {
            output.job_dir.expanduser().resolve()
            for asset in selected
            if asset.removal_scope == REMOVAL_VOCAL_OUTPUT
            if (output := _output_for_asset(package, asset.path)) is not None
        }
        planned_paths: list[Path] = []
        seen_units: set[tuple[str, Path]] = set()
        for asset in selected:
            if asset.removal_scope != REMOVAL_VOCAL_OUTPUT and any(
                _is_within(asset.path, output_dir) for output_dir in selected_output_dirs
            ):
                continue
            output = (
                _output_for_asset(package, asset.path)
                if asset.removal_scope in {REMOVAL_VOCAL_OUTPUT, REMOVAL_VOCAL_TAKE}
                else None
            )
            output_dir = output.job_dir.expanduser().resolve() if output is not None else None
            unit = (
                (REMOVAL_VOCAL_OUTPUT, output_dir)
                if asset.removal_scope == REMOVAL_VOCAL_OUTPUT and output_dir is not None
                else (asset.removal_scope, asset.path.expanduser().resolve())
            )
            if unit in seen_units:
                continue
            seen_units.add(unit)
            planned_paths.append(asset.path)

        return tuple(self.remove(song_id, path) for path in planned_paths)

    def _require_removable_asset(self, package: SongPackage, path: Path) -> SongAsset:
        target = path.expanduser().resolve()
        asset = next(
            (
                item
                for item in build_song_asset_details(package).assets
                if item.path.expanduser().resolve() == target and item.can_remove
            ),
            None,
        )
        if asset is None:
            raise SongAssetRemovalError("The selected library data is missing or protected.")
        return asset

    def _remove_video(self, package: SongPackage, asset: SongAsset) -> None:
        self._require_managed_path(package, asset.path)
        try:
            asset.path.unlink()
        except OSError as exc:
            raise SongAssetRemovalError(f"Could not delete the video file: {exc}") from exc
        self._video_sources.clear(package)
        _prune_empty_parents(asset.path.parent, package.folder)

    def _remove_vocal_output(
        self,
        package: SongPackage,
        asset: SongAsset,
    ) -> SongAssetRemovalResult:
        output = _output_for_asset(package, asset.path)
        if output is None:
            raise SongAssetRemovalError("The vocal result is no longer registered.")

        updated = self._packages.detach_output(package.song_id, output.job_dir)
        if updated.source_path is None and not updated.outputs:
            self._packages.set_removed(package.song_id, True)
        vocal_root = package.folder / VOCAL_STAGE
        is_managed = (
            output.job_dir.expanduser().resolve() != vocal_root.expanduser().resolve()
            and _is_within(output.job_dir, vocal_root)
        )
        if is_managed:
            try:
                shutil.rmtree(output.job_dir)
            except OSError as exc:
                raise SongAssetRemovalError(
                    f"The vocal result was detached, but its files could not be deleted: {exc}"
                ) from exc
            _prune_empty_parents(output.job_dir.parent, vocal_root)
        return SongAssetRemovalResult(
            asset,
            detached_only=not is_managed,
            removed_output_dir=output.job_dir,
        )

    def _remove_vocal_take(self, package: SongPackage, asset: SongAsset) -> None:
        output = _output_for_asset(package, asset.path)
        if output is None:
            raise SongAssetRemovalError("The converted vocal is no longer registered.")
        if not _is_within(asset.path, output.job_dir):
            raise SongAssetRemovalError("Linked converted vocals cannot be deleted from JJZero Audio.")

        try:
            project = self._vocal_projects.remove_take(output.job_dir, asset.path)
        except Exception as exc:
            raise SongAssetRemovalError(f"Could not remove the converted vocal: {exc}") from exc
        active_path = next(
            (take.output_path for take in project.takes if take.take_id == project.active_take_id),
            None,
        )
        self._packages.activate_converted_output(package.song_id, output.job_dir, active_path)

    def _remove_managed_file(self, package: SongPackage, path: Path) -> None:
        target = self._require_managed_path(package, path)
        try:
            target.unlink()
        except OSError as exc:
            raise SongAssetRemovalError(f"Could not delete the file: {exc}") from exc
        _prune_empty_parents(target.parent, package.folder)

    @staticmethod
    def _require_managed_path(package: SongPackage, path: Path) -> Path:
        target = path.expanduser().resolve()
        if not _is_within(target, package.folder):
            raise SongAssetRemovalError("Linked files cannot be deleted from JJZero Audio.")
        if not target.is_file():
            raise SongAssetRemovalError("The selected file no longer exists.")
        return target


def _output_for_asset(package: SongPackage, path: Path) -> SongOutputReference | None:
    target = path.expanduser().resolve()
    for output in package.outputs:
        sound_set = load_output_sound_set(output.job_dir, package.folder / VOCAL_STAGE)
        if sound_set is None:
            continue
        paths = {
            sound_set.vocals_path.expanduser().resolve(),
            sound_set.instrumental_path.expanduser().resolve(),
            *(item.expanduser().resolve() for item in sound_set.converted_vocal_paths),
        }
        if target in paths:
            return output
    return None


def _prune_empty_parents(start: Path, boundary: Path) -> None:
    boundary = boundary.expanduser().resolve()
    current = start.expanduser().resolve()
    while current != boundary and _is_within(current, boundary):
        try:
            current.rmdir()
        except OSError:
            break
        current = current.parent


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.expanduser().resolve().relative_to(root.expanduser().resolve())
        return True
    except ValueError:
        return False
