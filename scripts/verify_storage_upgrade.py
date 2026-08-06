from __future__ import annotations

import argparse
from pathlib import Path

from jang_app.services.app_bootstrap import prepare_app_environment
from jang_app.services.app_paths import AppPaths, discover_app_paths
from jang_app.services.rvc_model_workspace import RvcModelWorkspace
from jang_app.services.song_library import SongLibrary
from jang_app.services.song_package import SongPackageStore
from jang_app.services.storage_migration import migrate_storage, plan_storage_migration


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PACKAGE_ROOT = PROJECT_ROOT / "src" / "jang_app"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify a legacy installed workspace migration."
    )
    parser.add_argument("install_root", type=Path)
    parser.add_argument("data_root", type=Path)
    parser.add_argument("target_root", type=Path)
    arguments = parser.parse_args()

    install_root = arguments.install_root.expanduser().resolve()
    data_root = arguments.data_root.expanduser().resolve()
    target_root = arguments.target_root.expanduser().resolve()
    current = _discover(install_root, data_root)
    if current.storage_version != 1:
        raise RuntimeError(
            f"Expected legacy storage version 1, found {current.storage_version}."
        )

    before_song_ids, before_model_ids = _library_ids(current)
    _require_expected_records(before_song_ids, before_model_ids, "before migration")

    configured = migrate_storage(plan_storage_migration(current, target_root))
    restarted = _discover(install_root, data_root)
    prepare_app_environment(restarted)

    if configured.storage_root != target_root or restarted.storage_root != target_root:
        raise RuntimeError("Restarted application did not select the migrated storage.")
    for actual, expected in (
        (restarted.workspace_root, target_root / "Data"),
        (restarted.output_root, target_root / "Output"),
        (restarted.runtime_root, target_root / "Runtime"),
        (restarted.cache_dir, target_root / "Cache"),
    ):
        if actual != expected.resolve():
            raise RuntimeError(f"Unexpected migrated path: {actual} != {expected}")

    after_song_ids, after_model_ids = _library_ids(restarted)
    _require_expected_records(after_song_ids, after_model_ids, "after migration")
    model = next(
        record
        for record in RvcModelWorkspace(
            restarted.workspace_root / "models",
            catalog_file=restarted.catalog_file,
        ).records()
        if record.model_id == "linked-upgrade-voice"
    )
    expected_runtime = target_root / "Runtime" / "rvc"
    if model.runtime_root.resolve() != expected_runtime.resolve():
        raise RuntimeError(
            f"Linked model runtime was not rebased: {model.runtime_root}"
        )
    if model.inference_model is None or not model.inference_model.is_file():
        raise RuntimeError("Linked inference model was not preserved.")

    expected_files = (
        target_root
        / "Data"
        / "library"
        / "songs"
        / "upgrade-song"
        / "01_source"
        / "audio"
        / "upgrade-song.wav",
        target_root
        / "Data"
        / "library"
        / "songs"
        / "upgrade-song"
        / "02_vocal"
        / "separations"
        / "run-upgrade"
        / "htdemucs"
        / "upgrade-song"
        / "vocals.wav",
        target_root / "Output" / "exports" / "upgrade-mix.wav",
        target_root / "Runtime" / "rvc" / "weights" / "preserve-runtime-model.pth",
        target_root / "Cache" / "upgrade-cache.bin",
        target_root / "Data" / "catalog.db",
    )
    missing = tuple(path for path in expected_files if not path.is_file())
    if missing:
        raise RuntimeError(f"Migrated file is missing: {missing[0]}")

    print(
        "Verified managed storage migration "
        f"{current.workspace_root} -> {restarted.workspace_root}"
    )
    return 0


def _discover(install_root: Path, data_root: Path) -> AppPaths:
    return discover_app_paths(
        PACKAGE_ROOT,
        environ={"JJZERO_DATA_ROOT": str(data_root)},
        frozen=True,
        executable=install_root / "JJZero Audio.exe",
        source_root=PROJECT_ROOT,
    )


def _library_ids(paths: AppPaths) -> tuple[set[str], set[str]]:
    song_store = SongPackageStore(
        paths.workspace_root / "library" / "songs",
        paths.workspace_anchor,
        catalog_file=paths.catalog_file,
    )
    songs = SongLibrary(
        paths.settings_dir / "song_library.json",
        song_store,
    ).items()
    models = RvcModelWorkspace(
        paths.workspace_root / "models",
        catalog_file=paths.catalog_file,
    ).records()
    return {song.id for song in songs}, {model.model_id for model in models}


def _require_expected_records(
    song_ids: set[str],
    model_ids: set[str],
    stage: str,
) -> None:
    if "upgrade-song" not in song_ids:
        raise RuntimeError(f"Upgrade song is unavailable {stage}.")
    if "linked-upgrade-voice" not in model_ids:
        raise RuntimeError(f"Linked upgrade model is unavailable {stage}.")


if __name__ == "__main__":
    raise SystemExit(main())
