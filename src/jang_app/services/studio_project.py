from __future__ import annotations

import gzip
import hashlib
import json
import os
import shutil
import threading
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Mapping

from jang_app.services.managed_files import (
    copy_file_atomic,
    write_json_atomic,
    write_text_atomic,
)
from jang_app.services.song_package import STUDIO_STAGE, SongPackage

if TYPE_CHECKING:
    from jang_app.services.studio_assets import StudioSoundAsset


STUDIO_PROJECT_SCHEMA_VERSION = 1
STUDIO_PROJECT_INDEX_VERSION = 1
STUDIO_PROJECT_JOURNAL_VERSION = 1
DEFAULT_STUDIO_PROJECT_ID = "p_default"
STUDIO_PROJECTS_DIR = "projects"
STUDIO_PROJECT_INDEX_NAME = "project-index.json"
STUDIO_PROJECT_METADATA_NAME = "project.json"
STUDIO_PROJECT_SESSION_NAME = "session.json"
STUDIO_PROJECT_VIEW_STATE_NAME = "ui-state.json"
STUDIO_PROJECT_ASSETS_NAME = "assets.json"
STUDIO_PROJECT_JOURNAL_NAME = "journal.ndjson"
STUDIO_PROJECT_RECOVERY_NAME = "recovery.json"
STUDIO_PROJECT_CHECKPOINTS_DIR = "checkpoints"
STUDIO_PROJECT_HISTORY_DIR = ".history"
STUDIO_PROJECT_LEGACY_BACKUP_DIR = "legacy-backup"
STUDIO_PROJECT_JOURNAL_LIMIT = 250
STUDIO_PROJECT_CHECKPOINT_INTERVAL = 25
STUDIO_PROJECT_CHECKPOINT_LIMIT = 40

_PROJECT_LOCK = threading.RLock()


class StudioProjectError(RuntimeError):
    pass


@dataclass(frozen=True)
class StudioProjectPaths:
    stage: Path
    index: Path
    root: Path
    metadata: Path
    session: Path
    view_state: Path
    assets: Path
    journal: Path
    recovery: Path
    checkpoints: Path
    history: Path
    legacy_session: Path
    legacy_history: Path
    legacy_backup: Path


@dataclass(frozen=True)
class StudioProjectViewState:
    playhead_ms: int = 0
    horizontal_scroll: int = 0
    vertical_scroll: int = 0
    zoom: int = 7
    selected_clip_id: str = ""
    selected_track_id: str = ""
    selected_clip_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class StudioProjectRecoveryNotice:
    recovered: bool = False
    revision: int = 0
    recovered_at: str = ""
    reason: str = ""


@dataclass(frozen=True)
class StudioProjectRevision:
    revision: int
    created_at: str
    track_count: int
    clip_count: int
    checkpoint: bool = False


def studio_project_paths(package: SongPackage) -> StudioProjectPaths:
    stage = package.folder / STUDIO_STAGE
    root = stage / STUDIO_PROJECTS_DIR / DEFAULT_STUDIO_PROJECT_ID
    return StudioProjectPaths(
        stage=stage,
        index=stage / STUDIO_PROJECT_INDEX_NAME,
        root=root,
        metadata=root / STUDIO_PROJECT_METADATA_NAME,
        session=root / STUDIO_PROJECT_SESSION_NAME,
        view_state=root / STUDIO_PROJECT_VIEW_STATE_NAME,
        assets=root / STUDIO_PROJECT_ASSETS_NAME,
        journal=root / STUDIO_PROJECT_JOURNAL_NAME,
        recovery=root / STUDIO_PROJECT_RECOVERY_NAME,
        checkpoints=root / STUDIO_PROJECT_CHECKPOINTS_DIR,
        history=root / STUDIO_PROJECT_HISTORY_DIR,
        legacy_session=stage / STUDIO_PROJECT_SESSION_NAME,
        legacy_history=stage / STUDIO_PROJECT_HISTORY_DIR,
        legacy_backup=stage / STUDIO_PROJECT_LEGACY_BACKUP_DIR,
    )


def ensure_studio_project(package: SongPackage) -> StudioProjectPaths:
    paths = studio_project_paths(package)
    with _PROJECT_LOCK:
        paths.root.mkdir(parents=True, exist_ok=True)
        migrated = _migrate_legacy_session(paths)
        metadata = _read_json(paths.metadata)
        if metadata is not None:
            _validate_project_identity(metadata, package)
        else:
            created_at = _timestamp_for(paths.session) if paths.session.is_file() else _now()
            session = _read_json(paths.session)
            session_revision = 1 if session is not None else 0
            write_json_atomic(
                paths.metadata,
                _metadata_payload(
                    package,
                    revision=session_revision,
                    created_at=created_at,
                    updated_at=created_at,
                    session_checksum=_payload_checksum(session) if session is not None else "",
                    migrated_from_legacy=migrated,
                ),
            )
            if session is not None:
                _seed_project_journal(
                    package,
                    paths,
                    session,
                    revision=session_revision,
                    created_at=created_at,
                )
        _ensure_project_index(package, paths)
    return paths


def existing_studio_session_path(package: SongPackage) -> Path | None:
    paths = studio_project_paths(package)
    if paths.session.is_file():
        return paths.session
    if paths.legacy_session.is_file():
        return paths.legacy_session
    return None


def commit_studio_project_session(
    package: SongPackage,
    payload: Mapping[str, object],
) -> Path:
    paths = ensure_studio_project(package)
    with _PROJECT_LOCK:
        metadata = _project_metadata(package, paths)
        current_revision = max(
            _non_negative_int(metadata.get("revision")),
            _latest_journal_revision(paths, package.song_id),
        )
        revision = current_revision + 1
        encoded_payload = dict(payload)
        checksum = _payload_checksum(encoded_payload)
        record = {
            "version": STUDIO_PROJECT_JOURNAL_VERSION,
            "project_id": DEFAULT_STUDIO_PROJECT_ID,
            "song_id": package.song_id,
            "base_revision": current_revision,
            "revision": revision,
            "created_at": _now(),
            "checksum": checksum,
            "session": encoded_payload,
        }
        write_json_atomic(
            paths.recovery,
            {
                "version": 1,
                "project_id": DEFAULT_STUDIO_PROJECT_ID,
                "song_id": package.song_id,
                "state": "saving",
                "pending_revision": revision,
                "updated_at": _now(),
            },
        )
        _append_journal_record(paths.journal, record)
        write_json_atomic(paths.session, encoded_payload)
        write_json_atomic(
            paths.metadata,
            _metadata_payload(
                package,
                revision=revision,
                created_at=str(metadata.get("created_at", "")) or _now(),
                updated_at=str(encoded_payload.get("updated_at", "")) or _now(),
                session_checksum=checksum,
                migrated_from_legacy=metadata.get("migrated_from_legacy") is True,
            ),
        )
        if revision % STUDIO_PROJECT_CHECKPOINT_INTERVAL == 0:
            _write_checkpoint(paths, revision, encoded_payload)
        _prune_journal(paths.journal)
        _write_recovery_state(paths, package, revision, state="saved")
        _touch_project_index(package, paths, revision)
    return paths.session


def recover_studio_project_session(
    package: SongPackage,
    current: dict[str, object] | None,
) -> tuple[dict[str, object] | None, StudioProjectRecoveryNotice]:
    paths = ensure_studio_project(package)
    with _PROJECT_LOCK:
        metadata = _project_metadata(package, paths)
        expected_checksum = str(metadata.get("session_checksum", ""))
        current_checksum = _payload_checksum(current) if current is not None else ""
        latest = _latest_recovery_record(paths, package.song_id)
        reason = ""
        recovered_payload: dict[str, object] | None = None
        recovered_revision = 0
        if latest is not None:
            latest_revision = _non_negative_int(latest.get("revision"))
            metadata_revision = _non_negative_int(metadata.get("revision"))
            latest_session = latest.get("session")
            if current is None:
                reason = "current session is missing or invalid"
            elif latest_revision > metadata_revision:
                reason = "a newer autosave revision was found"
            elif (
                expected_checksum
                and current_checksum != expected_checksum
                and isinstance(latest_session, dict)
                and not _has_timeline_content(current)
                and _has_timeline_content(latest_session)
            ):
                reason = "the current session was unexpectedly emptied"
            if reason:
                recovered_payload = dict(latest["session"])
                recovered_revision = latest_revision
        if recovered_payload is None:
            return current, StudioProjectRecoveryNotice()

        checksum = _payload_checksum(recovered_payload)
        write_json_atomic(paths.session, recovered_payload)
        write_json_atomic(
            paths.metadata,
            _metadata_payload(
                package,
                revision=recovered_revision,
                created_at=str(metadata.get("created_at", "")) or _now(),
                updated_at=str(recovered_payload.get("updated_at", "")) or _now(),
                session_checksum=checksum,
                migrated_from_legacy=metadata.get("migrated_from_legacy") is True,
            ),
        )
        recovered_at = _now()
        write_json_atomic(
            paths.recovery,
            {
                "version": 1,
                "project_id": DEFAULT_STUDIO_PROJECT_ID,
                "song_id": package.song_id,
                "state": "recovered",
                "revision": recovered_revision,
                "recovered_at": recovered_at,
                "reason": reason,
            },
        )
        return recovered_payload, StudioProjectRecoveryNotice(
            True,
            recovered_revision,
            recovered_at,
            reason,
        )


def studio_project_recovery_notice(package: SongPackage) -> StudioProjectRecoveryNotice:
    data = _read_json(studio_project_paths(package).recovery)
    if data is None or data.get("state") != "recovered":
        return StudioProjectRecoveryNotice()
    return StudioProjectRecoveryNotice(
        True,
        _non_negative_int(data.get("revision")),
        str(data.get("recovered_at", "")),
        str(data.get("reason", "")),
    )


def consume_studio_project_recovery_notice(
    package: SongPackage,
) -> StudioProjectRecoveryNotice:
    paths = studio_project_paths(package)
    notice = studio_project_recovery_notice(package)
    if not notice.recovered:
        return notice
    write_json_atomic(
        paths.recovery,
        {
            "version": 1,
            "project_id": DEFAULT_STUDIO_PROJECT_ID,
            "song_id": package.song_id,
            "state": "acknowledged",
            "revision": notice.revision,
            "recovered_at": notice.recovered_at,
            "reason": notice.reason,
            "updated_at": _now(),
        },
    )
    return notice


def studio_project_revisions(package: SongPackage) -> tuple[StudioProjectRevision, ...]:
    paths = studio_project_paths(package)
    revisions: dict[int, StudioProjectRevision] = {}
    for record in _valid_journal_records(paths, package.song_id):
        revision = _non_negative_int(record.get("revision"))
        session = record["session"]
        revisions[revision] = StudioProjectRevision(
            revision=revision,
            created_at=str(record.get("created_at", "")),
            track_count=_timeline_track_count(session),
            clip_count=_timeline_clip_count(session),
        )
    for checkpoint in paths.checkpoints.glob("rev-*.json.gz") if paths.checkpoints.is_dir() else ():
        revision = _checkpoint_revision(checkpoint)
        if revision <= 0 or revision in revisions:
            continue
        session = _read_checkpoint(checkpoint)
        if session is None:
            continue
        revisions[revision] = StudioProjectRevision(
            revision=revision,
            created_at=_timestamp_for(checkpoint),
            track_count=_timeline_track_count(session),
            clip_count=_timeline_clip_count(session),
            checkpoint=True,
        )
    return tuple(sorted(revisions.values(), key=lambda item: item.revision, reverse=True))


def restore_studio_project_revision(package: SongPackage, revision: int) -> Path:
    paths = ensure_studio_project(package)
    target_revision = max(0, int(revision))
    payload = next(
        (
            dict(record["session"])
            for record in _valid_journal_records(paths, package.song_id)
            if _non_negative_int(record.get("revision")) == target_revision
        ),
        None,
    )
    if payload is None:
        payload = _read_checkpoint(paths.checkpoints / f"rev-{target_revision:08d}.json.gz")
    if payload is None:
        raise StudioProjectError(f"Studio project revision {target_revision} is unavailable.")
    payload["updated_at"] = _now()
    return commit_studio_project_session(package, payload)


def load_studio_project_view_state(package: SongPackage) -> StudioProjectViewState:
    data = _read_json(studio_project_paths(package).view_state)
    if data is None or data.get("song_id") not in (None, "", package.song_id):
        return StudioProjectViewState()
    selected_clip_id = str(data.get("selected_clip_id", ""))
    raw_selected_ids = data.get("selected_clip_ids", ())
    selected_clip_ids = tuple(
        dict.fromkeys(
            str(clip_id)
            for clip_id in raw_selected_ids
            if isinstance(clip_id, str) and clip_id
        )
    ) if isinstance(raw_selected_ids, (list, tuple)) else ()
    if "selected_clip_ids" not in data and selected_clip_id:
        selected_clip_ids = (selected_clip_id,)
    return StudioProjectViewState(
        playhead_ms=_non_negative_int(data.get("playhead_ms")),
        horizontal_scroll=_non_negative_int(data.get("horizontal_scroll")),
        vertical_scroll=_non_negative_int(data.get("vertical_scroll")),
        zoom=max(1, _non_negative_int(data.get("zoom")) or 7),
        selected_clip_id=selected_clip_id,
        selected_track_id=str(data.get("selected_track_id", "")),
        selected_clip_ids=selected_clip_ids,
    )


def save_studio_project_view_state(
    package: SongPackage,
    state: StudioProjectViewState,
) -> Path:
    paths = ensure_studio_project(package)
    payload = {
        "version": 1,
        "project_id": DEFAULT_STUDIO_PROJECT_ID,
        "song_id": package.song_id,
        **asdict(state),
        "updated_at": _now(),
    }
    write_json_atomic(paths.view_state, payload)
    return paths.view_state


def save_studio_project_assets(
    package: SongPackage,
    assets: tuple[StudioSoundAsset, ...],
    session: Mapping[str, object] | None = None,
) -> Path:
    paths = ensure_studio_project(package)
    rows = []
    for asset in assets:
        resolved = asset.path.expanduser().resolve()
        try:
            relative_path = str(resolved.relative_to(package.folder.resolve()))
        except ValueError:
            relative_path = ""
        try:
            stat = resolved.stat()
            size = stat.st_size
            modified_ns = stat.st_mtime_ns
            available = resolved.is_file()
        except OSError:
            size = 0
            modified_ns = 0
            available = False
        rows.append(
            {
                "asset_id": asset.asset_id,
                "output_id": asset.reference.output_id,
                "role": asset.reference.role,
                "filename": asset.reference.filename,
                "label": asset.label,
                "relative_path": relative_path,
                "last_known_path": str(resolved),
                "size": size,
                "modified_ns": modified_ns,
                "available": available,
                "media_kind": asset.media_kind,
            }
        )
    referenced = _session_asset_references(session)
    previous = _read_json(paths.assets)
    previous_assets = (
        previous.get("assets", [])
        if previous is not None and isinstance(previous.get("assets"), list)
        else []
    )
    previous_rows = {
        str(row.get("asset_id", "")): row
        for row in previous_assets
        if isinstance(row, dict) and row.get("asset_id")
    }
    current_ids = {str(row["asset_id"]) for row in rows}
    for asset_id, reference in referenced.items():
        if asset_id in current_ids:
            continue
        previous_row = previous_rows.get(asset_id, {})
        rows.append(
            {
                **previous_row,
                "asset_id": asset_id,
                "output_id": reference["output_id"],
                "role": reference["role"],
                "filename": reference["filename"],
                "label": previous_row.get("label") or reference["filename"] or reference["role"],
                "relative_path": previous_row.get("relative_path", ""),
                "last_known_path": previous_row.get("last_known_path", ""),
                "size": previous_row.get("size", 0),
                "modified_ns": previous_row.get("modified_ns", 0),
                "available": False,
                "media_kind": previous_row.get("media_kind", "audio"),
            }
        )
    rows.sort(key=lambda row: str(row["asset_id"]))
    payload = {
        "version": 1,
        "project_id": DEFAULT_STUDIO_PROJECT_ID,
        "song_id": package.song_id,
        "updated_at": _now(),
        "assets": rows,
    }
    if previous is None or previous.get("assets") != rows:
        write_json_atomic(paths.assets, payload)
    return paths.assets


def studio_project_missing_asset_ids(package: SongPackage) -> tuple[str, ...]:
    data = _read_json(studio_project_paths(package).assets)
    if data is None or not isinstance(data.get("assets"), list):
        return ()
    return tuple(
        str(row.get("asset_id"))
        for row in data["assets"]
        if isinstance(row, dict) and row.get("asset_id") and row.get("available") is not True
    )


def studio_project_history_paths(package: SongPackage) -> tuple[Path, ...]:
    paths = studio_project_paths(package)
    if not paths.history.is_dir():
        return ()
    return tuple(sorted(paths.history.glob("session-*.json"), reverse=True))


def remove_studio_project(package: SongPackage) -> None:
    paths = studio_project_paths(package)
    with _PROJECT_LOCK:
        if paths.root.is_dir():
            shutil.rmtree(paths.root)
        paths.legacy_session.unlink(missing_ok=True)
        if paths.legacy_history.is_dir():
            shutil.rmtree(paths.legacy_history)
        if paths.legacy_backup.is_dir():
            shutil.rmtree(paths.legacy_backup)
        paths.index.unlink(missing_ok=True)
        projects_root = paths.stage / STUDIO_PROJECTS_DIR
        try:
            projects_root.rmdir()
        except OSError:
            pass


def _migrate_legacy_session(paths: StudioProjectPaths) -> bool:
    if paths.session.is_file() or not paths.legacy_session.is_file():
        return False
    copy_file_atomic(paths.legacy_session, paths.session)
    paths.legacy_backup.mkdir(parents=True, exist_ok=True)
    backup = paths.legacy_backup / STUDIO_PROJECT_SESSION_NAME
    if not backup.is_file():
        copy_file_atomic(paths.legacy_session, backup)
    if paths.legacy_history.is_dir():
        paths.history.mkdir(parents=True, exist_ok=True)
        for source in paths.legacy_history.glob("session-*.json"):
            target = paths.history / source.name
            if not target.is_file():
                copy_file_atomic(source, target)
    return True


def _ensure_project_index(package: SongPackage, paths: StudioProjectPaths) -> None:
    data = _read_json(paths.index)
    if data is not None and data.get("song_id") not in (None, "", package.song_id):
        raise StudioProjectError("Studio project index belongs to another song.")
    if data is not None:
        return
    metadata = _read_json(paths.metadata) or {}
    write_json_atomic(
        paths.index,
        {
            "version": STUDIO_PROJECT_INDEX_VERSION,
            "song_id": package.song_id,
            "active_project_id": DEFAULT_STUDIO_PROJECT_ID,
            "projects": [
                {
                    "project_id": DEFAULT_STUDIO_PROJECT_ID,
                    "name": "Main",
                    "revision": _non_negative_int(metadata.get("revision")),
                    "updated_at": _now(),
                }
            ],
        },
    )


def _touch_project_index(package: SongPackage, paths: StudioProjectPaths, revision: int) -> None:
    data = _read_json(paths.index) or {}
    projects = data.get("projects") if isinstance(data.get("projects"), list) else []
    updated = []
    found = False
    for project in projects:
        if not isinstance(project, dict) or project.get("project_id") != DEFAULT_STUDIO_PROJECT_ID:
            updated.append(project)
            continue
        updated.append(
            {
                **project,
                "revision": revision,
                "updated_at": _now(),
            }
        )
        found = True
    if not found:
        updated.append(
            {
                "project_id": DEFAULT_STUDIO_PROJECT_ID,
                "name": "Main",
                "revision": revision,
                "updated_at": _now(),
            }
        )
    write_json_atomic(
        paths.index,
        {
            "version": STUDIO_PROJECT_INDEX_VERSION,
            "song_id": package.song_id,
            "active_project_id": DEFAULT_STUDIO_PROJECT_ID,
            "projects": updated,
        },
    )


def _project_metadata(package: SongPackage, paths: StudioProjectPaths) -> dict[str, object]:
    metadata = _read_json(paths.metadata)
    if metadata is None:
        raise StudioProjectError("Studio project metadata is missing.")
    _validate_project_identity(metadata, package)
    return metadata


def _validate_project_identity(data: Mapping[str, object], package: SongPackage) -> None:
    if data.get("project_id") not in (None, "", DEFAULT_STUDIO_PROJECT_ID):
        raise StudioProjectError("Studio project identity is invalid.")
    if data.get("song_id") not in (None, "", package.song_id):
        raise StudioProjectError("Studio project belongs to another song.")


def _metadata_payload(
    package: SongPackage,
    *,
    revision: int,
    created_at: str,
    updated_at: str,
    session_checksum: str,
    migrated_from_legacy: bool,
) -> dict[str, object]:
    return {
        "version": STUDIO_PROJECT_SCHEMA_VERSION,
        "project_id": DEFAULT_STUDIO_PROJECT_ID,
        "song_id": package.song_id,
        "name": "Main",
        "revision": revision,
        "timeline_schema": 11,
        "created_at": created_at,
        "updated_at": updated_at,
        "session_checksum": session_checksum,
        "migrated_from_legacy": migrated_from_legacy,
    }


def _append_journal_record(path: Path, record: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")))
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())


def _seed_project_journal(
    package: SongPackage,
    paths: StudioProjectPaths,
    session: Mapping[str, object],
    *,
    revision: int,
    created_at: str,
) -> None:
    if _latest_valid_journal_record(paths, package.song_id) is not None:
        return
    _append_journal_record(
        paths.journal,
        {
            "version": STUDIO_PROJECT_JOURNAL_VERSION,
            "project_id": DEFAULT_STUDIO_PROJECT_ID,
            "song_id": package.song_id,
            "base_revision": 0,
            "revision": revision,
            "created_at": created_at,
            "checksum": _payload_checksum(session),
            "session": dict(session),
        },
    )
    _write_recovery_state(paths, package, revision, state="saved")


def _journal_records(path: Path) -> tuple[dict[str, object], ...]:
    if not path.is_file():
        return ()
    records = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return ()
    for line in lines:
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(record, dict):
            records.append(record)
    return tuple(records)


def _latest_valid_journal_record(
    paths: StudioProjectPaths,
    song_id: str,
) -> dict[str, object] | None:
    valid = _valid_journal_records(paths, song_id)
    if not valid:
        return None
    return max(valid, key=lambda item: _non_negative_int(item.get("revision")))


def _valid_journal_records(
    paths: StudioProjectPaths,
    song_id: str,
) -> tuple[dict[str, object], ...]:
    valid = []
    for record in _journal_records(paths.journal):
        session = record.get("session")
        if (
            record.get("song_id") != song_id
            or record.get("project_id") != DEFAULT_STUDIO_PROJECT_ID
            or not isinstance(session, dict)
            or record.get("checksum") != _payload_checksum(session)
        ):
            continue
        valid.append(record)
    return tuple(valid)


def _latest_recovery_record(
    paths: StudioProjectPaths,
    song_id: str,
) -> dict[str, object] | None:
    journal = _latest_valid_journal_record(paths, song_id)
    checkpoint = _latest_valid_checkpoint_record(paths, song_id)
    candidates = [record for record in (journal, checkpoint) if record is not None]
    if not candidates:
        return None
    return max(candidates, key=lambda item: _non_negative_int(item.get("revision")))


def _latest_valid_checkpoint_record(
    paths: StudioProjectPaths,
    song_id: str,
) -> dict[str, object] | None:
    if not paths.checkpoints.is_dir():
        return None
    for checkpoint in sorted(paths.checkpoints.glob("rev-*.json.gz"), reverse=True):
        revision = _checkpoint_revision(checkpoint)
        session = _read_checkpoint(checkpoint)
        if revision <= 0 or session is None or session.get("song_id") != song_id:
            continue
        return {
            "version": STUDIO_PROJECT_JOURNAL_VERSION,
            "project_id": DEFAULT_STUDIO_PROJECT_ID,
            "song_id": song_id,
            "revision": revision,
            "created_at": _timestamp_for(checkpoint),
            "checksum": _payload_checksum(session),
            "session": session,
        }
    return None


def _latest_journal_revision(paths: StudioProjectPaths, song_id: str) -> int:
    record = _latest_valid_journal_record(paths, song_id)
    return _non_negative_int(record.get("revision")) if record is not None else 0


def _prune_journal(path: Path) -> None:
    records = _journal_records(path)
    if len(records) <= STUDIO_PROJECT_JOURNAL_LIMIT:
        return
    text = "".join(
        f"{json.dumps(record, ensure_ascii=False, separators=(',', ':'))}\n"
        for record in records[-STUDIO_PROJECT_JOURNAL_LIMIT:]
    )
    write_text_atomic(path, text)


def _write_checkpoint(
    paths: StudioProjectPaths,
    revision: int,
    payload: Mapping[str, object],
) -> None:
    paths.checkpoints.mkdir(parents=True, exist_ok=True)
    target = paths.checkpoints / f"rev-{revision:08d}.json.gz"
    temporary = target.with_suffix(".json.gz.tmp")
    try:
        with gzip.open(temporary, "wt", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, separators=(",", ":"))
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    checkpoints = sorted(paths.checkpoints.glob("rev-*.json.gz"), reverse=True)
    for stale in checkpoints[STUDIO_PROJECT_CHECKPOINT_LIMIT:]:
        stale.unlink(missing_ok=True)


def _read_checkpoint(path: Path) -> dict[str, object] | None:
    try:
        with gzip.open(path, "rt", encoding="utf-8") as stream:
            payload = json.load(stream)
    except (OSError, EOFError, json.JSONDecodeError, UnicodeDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _checkpoint_revision(path: Path) -> int:
    try:
        return max(0, int(path.name.removeprefix("rev-").removesuffix(".json.gz")))
    except ValueError:
        return 0


def _write_recovery_state(
    paths: StudioProjectPaths,
    package: SongPackage,
    revision: int,
    *,
    state: str,
) -> None:
    write_json_atomic(
        paths.recovery,
        {
            "version": 1,
            "project_id": DEFAULT_STUDIO_PROJECT_ID,
            "song_id": package.song_id,
            "state": state,
            "revision": revision,
            "updated_at": _now(),
        },
    )


def _read_json(path: Path) -> dict[str, object] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _payload_checksum(payload: Mapping[str, object] | None) -> str:
    if payload is None:
        return ""
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _has_timeline_content(payload: Mapping[str, object]) -> bool:
    tracks = payload.get("tracks")
    if not isinstance(tracks, list) or not tracks:
        return False
    return any(
        isinstance(track, dict)
        and isinstance(track.get("clips"), list)
        and bool(track["clips"])
        for track in tracks
    )


def _timeline_track_count(payload: Mapping[str, object]) -> int:
    tracks = payload.get("tracks")
    return len(tracks) if isinstance(tracks, list) else 0


def _timeline_clip_count(payload: Mapping[str, object]) -> int:
    tracks = payload.get("tracks")
    if not isinstance(tracks, list):
        return 0
    return sum(
        len(clips)
        for track in tracks
        if isinstance(track, dict) and isinstance((clips := track.get("clips")), list)
    )


def _session_asset_references(
    payload: Mapping[str, object] | None,
) -> dict[str, dict[str, str]]:
    if payload is None or not isinstance(payload.get("tracks"), list):
        return {}
    references: dict[str, dict[str, str]] = {}
    for track in payload["tracks"]:
        if not isinstance(track, dict) or not isinstance(track.get("clips"), list):
            continue
        for clip in track["clips"]:
            if not isinstance(clip, dict) or not isinstance(clip.get("asset"), dict):
                continue
            raw = clip["asset"]
            output_id = str(raw.get("output_id", ""))
            role = str(raw.get("role", ""))
            filename = Path(str(raw.get("filename", ""))).name
            if not output_id or not role:
                continue
            asset_id = ":".join((output_id, role, filename))
            references[asset_id] = {
                "output_id": output_id,
                "role": role,
                "filename": filename,
            }
    return references


def _timestamp_for(path: Path) -> str:
    try:
        return datetime.fromtimestamp(path.stat().st_mtime, UTC).isoformat()
    except OSError:
        return _now()


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _non_negative_int(value: object) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0
