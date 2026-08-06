from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from jang_app.services.output_catalog import load_output_sound_set
from jang_app.services.song_package import EXPORT_STAGE, SOURCE_STAGE, STUDIO_STAGE, VOCAL_STAGE, SongPackage
from jang_app.services.video_source import VideoSourceStore


STAGE_SOURCE = "source"
STAGE_VOCAL = "vocal"
STAGE_STUDIO = "studio"
STAGE_EXPORT = "export"
SONG_ASSET_STAGES = (STAGE_SOURCE, STAGE_VOCAL, STAGE_STUDIO, STAGE_EXPORT)

REMOVAL_FILE = "file"
REMOVAL_VIDEO = "video"
REMOVAL_VOCAL_OUTPUT = "vocal_output"
REMOVAL_VOCAL_TAKE = "vocal_take"

_INTERNAL_STATE_FILES = {"session.json", "video.json", "vocal_project.json"}


@dataclass(frozen=True)
class SongAsset:
    stage: str
    role: str
    path: Path
    version_label: str = ""
    is_active: bool = False
    is_managed: bool = True
    size_bytes: int = 0
    removal_scope: str = ""

    @property
    def can_remove(self) -> bool:
        return bool(self.removal_scope)


@dataclass(frozen=True)
class SongAssetDetails:
    song_id: str
    title: str
    source_type: str
    source_url: str
    original_name: str
    package_dir: Path
    created_at: str
    assets: tuple[SongAsset, ...]

    def assets_for(self, stage: str) -> tuple[SongAsset, ...]:
        return tuple(asset for asset in self.assets if asset.stage == stage)


def build_song_asset_details(package: SongPackage) -> SongAssetDetails:
    assets: list[SongAsset] = []
    known_paths: set[Path] = set()

    if package.source_path is not None and package.source_path.is_file():
        assets.append(_asset(package, STAGE_SOURCE, "Source", package.source_path, is_active=True))
        known_paths.add(package.source_path.resolve())

    video_source = VideoSourceStore().load(package)
    if video_source.path is not None and video_source.path.is_file():
        assets.append(
            _asset(
                package,
                STAGE_SOURCE,
                "Source Video",
                video_source.path,
                is_active=True,
                removal_scope=REMOVAL_VIDEO,
            )
        )
        known_paths.add(video_source.path.resolve())

    for output in package.outputs:
        sound_set = load_output_sound_set(output.job_dir, package.folder / VOCAL_STAGE)
        if sound_set is None:
            continue
        output_active = output.output_id == package.active_output_id
        for role, path in (
            ("Original Vocal", sound_set.vocals_path),
            ("Instrumental", sound_set.instrumental_path),
        ):
            assets.append(
                _asset(
                    package,
                    STAGE_VOCAL,
                    role,
                    path,
                    version_label=output.label or sound_set.label,
                    is_active=output_active,
                    removal_scope=REMOVAL_VOCAL_OUTPUT,
                )
            )
            known_paths.add(path.resolve())
        active_converted = output.active_converted_path
        if active_converted not in sound_set.converted_vocal_paths:
            active_converted = sound_set.converted_vocal_paths[0] if sound_set.converted_vocal_paths else None
        for path in sound_set.converted_vocal_paths:
            assets.append(
                _asset(
                    package,
                    STAGE_VOCAL,
                    "Converted Vocal",
                    path,
                    version_label=output.label or sound_set.label,
                    is_active=output_active and path == active_converted,
                    removal_scope=(
                        REMOVAL_VOCAL_TAKE
                        if _is_within(path.expanduser().resolve(), package.folder)
                        else ""
                    ),
                )
            )
            known_paths.add(path.resolve())

    for stage, folder, role in (
        (STAGE_SOURCE, package.folder / SOURCE_STAGE, "Source Asset"),
        (STAGE_VOCAL, package.folder / VOCAL_STAGE, "Vocal Asset"),
        (STAGE_STUDIO, package.folder / STUDIO_STAGE, "Studio Asset"),
        (STAGE_EXPORT, package.folder / EXPORT_STAGE, "Exported Asset"),
    ):
        assets.extend(_untracked_assets(package, stage, folder, role, known_paths))

    return SongAssetDetails(
        song_id=package.song_id,
        title=package.title,
        source_type=package.source_type,
        source_url=package.source_url,
        original_name=package.original_name,
        package_dir=package.folder,
        created_at=package.created_at,
        assets=tuple(assets),
    )


def _untracked_assets(
    package: SongPackage,
    stage: str,
    folder: Path,
    role: str,
    known_paths: set[Path],
) -> list[SongAsset]:
    if not folder.is_dir():
        return []
    assets = []
    for path in sorted((item for item in folder.rglob("*") if item.is_file()), key=lambda item: str(item).casefold()):
        resolved = path.resolve()
        if resolved in known_paths or path.name.casefold() in _INTERNAL_STATE_FILES:
            continue
        known_paths.add(resolved)
        assets.append(_asset(package, stage, role, resolved, removal_scope=REMOVAL_FILE))
    return assets


def _asset(
    package: SongPackage,
    stage: str,
    role: str,
    path: Path,
    *,
    version_label: str = "",
    is_active: bool = False,
    removal_scope: str = "",
) -> SongAsset:
    resolved = path.expanduser().resolve()
    return SongAsset(
        stage=stage,
        role=role,
        path=resolved,
        version_label=version_label,
        is_active=is_active,
        is_managed=_is_within(resolved, package.folder),
        size_bytes=_file_size(resolved),
        removal_scope=removal_scope,
    )


def _file_size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root.resolve())
        return True
    except ValueError:
        return False
