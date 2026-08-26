from __future__ import annotations

from contextlib import ExitStack
from dataclasses import dataclass, replace
from pathlib import Path

from jang_app.services.output_catalog import load_output_sound_set
from jang_app.services.managed_transaction import (
    ManagedPathTransaction,
    ManagedTransactionError,
)
from jang_app.services.managed_files import managed_path_lock
from jang_app.services.song_assets import (
    REMOVAL_FILE,
    REMOVAL_STUDIO_SESSION,
    REMOVAL_VIDEO,
    REMOVAL_VOCAL_OUTPUT,
    REMOVAL_VOCAL_TAKE,
    SongAsset,
    build_song_asset_details,
)
from jang_app.services.song_package import (
    SONG_MANIFEST_NAME,
    SongOutputReference,
    SongPackage,
    SongPackageStore,
    VOCAL_STAGE,
)
from jang_app.services.studio_project import (
    studio_project_paths,
)
from jang_app.services.video_source import (
    VideoSourceStore,
    video_source_state_path,
)
from jang_app.services.vocal_project_store import (
    VOCAL_PROJECT_MANIFEST,
    VocalProjectStore,
)


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
        manifest_path = package.folder / SONG_MANIFEST_NAME
        with managed_path_lock(manifest_path):
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
                self._remove_studio_session(package)
                return SongAssetRemovalResult(asset)
            if asset.removal_scope == REMOVAL_FILE:
                self._remove_managed_file(package, asset.path)
                return SongAssetRemovalResult(asset)
            raise SongAssetRemovalError(
                "This library item cannot be removed separately."
            )

    def remove_many(
        self,
        song_id: str,
        paths: tuple[Path, ...],
    ) -> tuple[SongAssetRemovalResult, ...]:
        package = self._packages.require(song_id)
        manifest_path = package.folder / SONG_MANIFEST_NAME
        with managed_path_lock(manifest_path):
            package = self._packages.require(song_id)
            return self._remove_many_locked(package, paths)

    def _remove_many_locked(
        self,
        package: SongPackage,
        paths: tuple[Path, ...],
    ) -> tuple[SongAssetRemovalResult, ...]:
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

        planned_assets = tuple(
            assets_by_path[path.expanduser().resolve()]
            for path in planned_paths
        )
        return self._remove_many_transactionally(package, planned_assets)

    def _remove_many_transactionally(
        self,
        package: SongPackage,
        assets: tuple[SongAsset, ...],
    ) -> tuple[SongAssetRemovalResult, ...]:
        transaction = ManagedPathTransaction(
            package.folder,
            "delete-song-assets",
            package.song_id,
        )
        updated_package = package
        updated_projects = {}
        stage_paths: list[tuple[Path, str]] = []
        metadata_targets: set[Path] = set()
        clear_video = False
        results: list[SongAssetRemovalResult] = []

        for index, asset in enumerate(assets):
            if asset.removal_scope == REMOVAL_VIDEO:
                target = self._require_managed_path(package, asset.path)
                stage_paths.append((target, f"video-{index}"))
                metadata_targets.add(video_source_state_path(package))
                clear_video = True
                results.append(SongAssetRemovalResult(asset))
                continue
            if asset.removal_scope == REMOVAL_VOCAL_OUTPUT:
                output = _output_for_asset(package, asset.path)
                if output is None:
                    raise SongAssetRemovalError(
                        "The vocal result is no longer registered."
                    )
                vocal_root = package.folder / VOCAL_STAGE
                is_managed = (
                    output.job_dir.expanduser().resolve()
                    != vocal_root.expanduser().resolve()
                    and _is_within(output.job_dir, vocal_root)
                )
                if is_managed:
                    stage_paths.append((output.job_dir, f"output-{index}"))
                updated_package = _package_without_output(
                    updated_package,
                    output,
                )
                metadata_targets.add(package.folder / SONG_MANIFEST_NAME)
                results.append(
                    SongAssetRemovalResult(
                        asset,
                        detached_only=not is_managed,
                        removed_output_dir=output.job_dir,
                    )
                )
                continue
            if asset.removal_scope == REMOVAL_VOCAL_TAKE:
                output = _output_for_asset(package, asset.path)
                if output is None or not _is_within(asset.path, output.job_dir):
                    raise SongAssetRemovalError(
                        "The converted vocal is no longer registered."
                    )
                project = updated_projects.get(output.job_dir)
                if project is None:
                    project = self._vocal_projects.open_or_create(
                        output.job_dir,
                        active_converted_path=asset.path,
                    )
                target = next(
                    (
                        take
                        for take in project.takes
                        if take.output_path.expanduser().resolve()
                        == asset.path.expanduser().resolve()
                    ),
                    None,
                )
                if target is None:
                    raise SongAssetRemovalError(
                        "The converted vocal is no longer registered."
                    )
                remaining = tuple(
                    take for take in project.takes if take.take_id != target.take_id
                )
                active_take_id = remaining[0].take_id if remaining else ""
                updated_projects[output.job_dir] = replace(
                    project,
                    takes=remaining,
                    active_take_id=active_take_id,
                )
                active_path = remaining[0].output_path if remaining else None
                updated_package = _package_with_active_converted(
                    updated_package,
                    output.job_dir,
                    active_path,
                )
                stage_paths.append((target.output_path, f"take-{index}"))
                metadata_targets.add(
                    output.job_dir / VOCAL_PROJECT_MANIFEST
                )
                metadata_targets.add(package.folder / SONG_MANIFEST_NAME)
                results.append(SongAssetRemovalResult(asset))
                continue
            if asset.removal_scope == REMOVAL_STUDIO_SESSION:
                paths = studio_project_paths(package)
                for label, path in (
                    ("studio-project", paths.root),
                    ("studio-legacy-session", paths.legacy_session),
                    ("studio-legacy-history", paths.legacy_history),
                    ("studio-legacy-backup", paths.legacy_backup),
                    ("studio-index", paths.index),
                ):
                    stage_paths.append((path, f"{label}-{index}"))
                results.append(SongAssetRemovalResult(asset))
                continue
            if asset.removal_scope == REMOVAL_FILE:
                target = self._require_managed_path(package, asset.path)
                stage_paths.append((target, f"file-{index}"))
                results.append(SongAssetRemovalResult(asset))
                continue
            raise SongAssetRemovalError(
                "This library item cannot be removed separately."
            )

        if updated_package.source_path is None and not updated_package.outputs:
            updated_package = replace(updated_package, removed=True)

        song_manifest = package.folder / SONG_MANIFEST_NAME
        lock_paths = sorted(
            {*metadata_targets, song_manifest},
            key=lambda path: str(path).casefold(),
        )
        with ExitStack() as locks:
            for path in lock_paths:
                locks.enter_context(managed_path_lock(path))
            try:
                for path in metadata_targets:
                    transaction.stage(path, f"metadata-{len(transaction.moves)}")
                for path, label in stage_paths:
                    transaction.stage(path, label)
                if updated_package != package:
                    self._packages.persist_asset_state(updated_package)
                if clear_video:
                    self._video_sources.clear(package)
                for job_dir, project in updated_projects.items():
                    self._vocal_projects.save(job_dir, project)
            except Exception as exc:
                for path in metadata_targets:
                    path.unlink(missing_ok=True)
                self._rollback_transaction(
                    transaction,
                    exc,
                    "Could not remove the selected library data",
                )
                self._packages._discard_cached_manifest(song_manifest)
                raise SongAssetRemovalError(
                    f"Could not remove the selected library data: {exc}"
                ) from exc

        self._commit_transaction(transaction)
        return tuple(results)

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
        target = self._require_managed_path(package, asset.path)
        transaction = ManagedPathTransaction(
            package.folder,
            "delete-video",
            package.song_id,
        )
        state_path = video_source_state_path(package)
        try:
            transaction.stage(state_path, "video-state")
            transaction.stage(target, "video")
            self._video_sources.clear(package)
        except Exception as exc:
            state_path.unlink(missing_ok=True)
            self._rollback_transaction(
                transaction,
                exc,
                "Could not remove the video",
            )
            raise SongAssetRemovalError(
                f"Could not remove the video: {exc}"
            ) from exc
        self._commit_transaction(transaction)
        _prune_empty_parents(asset.path.parent, package.folder)

    def _remove_vocal_output(
        self,
        package: SongPackage,
        asset: SongAsset,
    ) -> SongAssetRemovalResult:
        output = _output_for_asset(package, asset.path)
        if output is None:
            raise SongAssetRemovalError("The vocal result is no longer registered.")

        vocal_root = package.folder / VOCAL_STAGE
        is_managed = (
            output.job_dir.expanduser().resolve() != vocal_root.expanduser().resolve()
            and _is_within(output.job_dir, vocal_root)
        )
        transaction = (
            ManagedPathTransaction(
                package.folder,
                "delete-vocal-output",
                output.output_id,
            )
            if is_managed
            else None
        )
        manifest_path = package.folder / SONG_MANIFEST_NAME
        try:
            if transaction is not None:
                transaction.stage(manifest_path, "manifest")
                transaction.stage(output.job_dir, "output")
                updated = _package_without_output(package, output)
                if updated.source_path is None and not updated.outputs:
                    updated = replace(updated, removed=True)
                self._packages.persist_asset_state(updated)
            else:
                self._packages.detach_output(
                    package.song_id,
                    output.job_dir,
                    remove_if_empty=True,
                )
        except Exception as exc:
            if transaction is not None:
                manifest_path.unlink(missing_ok=True)
                self._rollback_transaction(
                    transaction,
                    exc,
                    "Could not remove the vocal result",
                )
                self._packages._discard_cached_manifest(manifest_path)
            if isinstance(exc, SongAssetRemovalError):
                raise
            raise SongAssetRemovalError(
                f"Could not remove the vocal result: {exc}"
            ) from exc
        if is_managed:
            self._commit_transaction(transaction)
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

        project = self._vocal_projects.open_or_create(
            output.job_dir,
            active_converted_path=asset.path,
        )
        target = next(
            (
                take
                for take in project.takes
                if take.output_path.expanduser().resolve()
                == asset.path.expanduser().resolve()
            ),
            None,
        )
        if target is None:
            raise SongAssetRemovalError(
                "The converted vocal is no longer registered."
            )
        remaining = tuple(
            take for take in project.takes if take.take_id != target.take_id
        )
        active_take_id = remaining[0].take_id if remaining else ""
        updated_project = replace(
            project,
            takes=remaining,
            active_take_id=active_take_id,
        )
        active_path = remaining[0].output_path if remaining else None
        updated_package = _package_with_active_converted(
            package,
            output.job_dir,
            active_path,
        )
        project_manifest = output.job_dir / VOCAL_PROJECT_MANIFEST
        song_manifest = package.folder / SONG_MANIFEST_NAME
        transaction = ManagedPathTransaction(
            package.folder,
            "delete-vocal-take",
            target.take_id,
        )
        try:
            transaction.stage(project_manifest, "vocal-project")
            transaction.stage(song_manifest, "song-manifest")
            transaction.stage(target.output_path, "take")
            self._vocal_projects.save(output.job_dir, updated_project)
            self._packages.persist_asset_state(updated_package)
        except Exception as exc:
            project_manifest.unlink(missing_ok=True)
            song_manifest.unlink(missing_ok=True)
            self._rollback_transaction(
                transaction,
                exc,
                "Could not remove the converted vocal",
            )
            self._packages._discard_cached_manifest(song_manifest)
            raise SongAssetRemovalError(
                f"Could not remove the converted vocal: {exc}"
            ) from exc
        self._commit_transaction(transaction)

    def _remove_studio_session(
        self,
        package: SongPackage,
    ) -> None:
        paths = studio_project_paths(package)
        transaction = ManagedPathTransaction(
            package.folder,
            "delete-studio-project",
            package.song_id,
        )
        try:
            for label, path in (
                ("project", paths.root),
                ("legacy-session", paths.legacy_session),
                ("legacy-history", paths.legacy_history),
                ("legacy-backup", paths.legacy_backup),
                ("index", paths.index),
            ):
                transaction.stage(path, label)
        except Exception as exc:
            self._rollback_transaction(
                transaction,
                exc,
                "Could not remove the Studio project",
            )
            raise SongAssetRemovalError(
                f"Could not remove the Studio project: {exc}"
            ) from exc
        self._commit_transaction(transaction)

    def _remove_managed_file(self, package: SongPackage, path: Path) -> None:
        target = self._require_managed_path(package, path)
        transaction = ManagedPathTransaction(
            package.folder,
            "delete-song-file",
            target.name,
        )
        try:
            transaction.stage(target, "file")
        except Exception as exc:
            self._rollback_transaction(
                transaction,
                exc,
                "Could not delete the file",
            )
            raise SongAssetRemovalError(
                f"Could not delete the file: {exc}"
            ) from exc
        self._commit_transaction(transaction)
        _prune_empty_parents(target.parent, package.folder)

    @staticmethod
    def _rollback_transaction(
        transaction: ManagedPathTransaction,
        original_error: Exception,
        message: str,
    ) -> None:
        try:
            transaction.rollback()
        except ManagedTransactionError as rollback_error:
            raise SongAssetRemovalError(
                f"{message}; rollback failed: {rollback_error}"
            ) from original_error

    @staticmethod
    def _commit_transaction(transaction: ManagedPathTransaction | None) -> None:
        if transaction is None:
            return
        try:
            transaction.mark_committed()
        except OSError:
            pass
        transaction.purge()

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


def _package_without_output(
    package: SongPackage,
    output: SongOutputReference,
) -> SongPackage:
    outputs = tuple(
        item for item in package.outputs if item.output_id != output.output_id
    )
    active_output_id = package.active_output_id
    if not any(item.output_id == active_output_id for item in outputs):
        active_output_id = outputs[0].output_id if outputs else ""
    return replace(
        package,
        outputs=outputs,
        active_output_id=active_output_id,
        detached_output_dirs=tuple(
            dict.fromkeys((*package.detached_output_dirs, output.job_dir))
        ),
    )


def _package_with_active_converted(
    package: SongPackage,
    job_dir: Path,
    active_path: Path | None,
) -> SongPackage:
    resolved_job = job_dir.expanduser().resolve()
    return replace(
        package,
        outputs=tuple(
            replace(output, active_converted_path=active_path)
            if output.job_dir.expanduser().resolve() == resolved_job
            else output
            for output in package.outputs
        ),
    )


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
