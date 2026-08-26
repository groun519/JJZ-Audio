from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from jang_app.services.google_drive import GoogleDriveFile
from jang_app.services.managed_files import managed_path_lock, write_json_atomic


SHARE_CATALOG_VERSION = 2
SHARE_CATALOG_PREVIOUS_VERSIONS = (1,)


@dataclass(frozen=True)
class DriveShareRecord:
    source_path: str
    source_size: int
    source_modified_ns: int
    category: str
    file_id: str
    file_name: str
    share_link: str
    shared_at: str

    def matches(self, source: Path, category: str) -> bool:
        resolved = source.expanduser().resolve()
        if not resolved.is_file():
            return False
        stat = resolved.stat()
        return (
            self.source_path.casefold() == str(resolved).casefold()
            and self.source_size == stat.st_size
            and self.source_modified_ns == stat.st_mtime_ns
            and self.category == category
            and bool(self.share_link)
        )


@dataclass(frozen=True)
class DrivePendingRemoteDelete:
    file_id: str
    file_name: str
    reason: str
    created_at: str


class DriveShareCatalog:
    def __init__(self, path: Path) -> None:
        self._path = path

    def find(self, source: Path, category: str) -> DriveShareRecord | None:
        return next(
            (
                record
                for record in self.records()
                if record.matches(source, category)
            ),
            None,
        )

    def find_target(self, source: Path, category: str) -> DriveShareRecord | None:
        source_path = str(source.expanduser().resolve()).casefold()
        return next(
            (
                record
                for record in self.records()
                if record.source_path.casefold() == source_path
                and record.category == category
            ),
            None,
        )

    def record(
        self,
        source: Path,
        category: str,
        remote: GoogleDriveFile,
    ) -> DriveShareRecord:
        resolved = source.expanduser().resolve()
        stat = resolved.stat()
        item = DriveShareRecord(
            source_path=str(resolved),
            source_size=stat.st_size,
            source_modified_ns=stat.st_mtime_ns,
            category=category,
            file_id=remote.file_id,
            file_name=remote.name,
            share_link=remote.share_link,
            shared_at=datetime.now(UTC).isoformat(),
        )
        with managed_path_lock(self._path):
            current, pending = self._state_unlocked()
            replaced = [
                record
                for record in current
                if record.source_path.casefold() == item.source_path.casefold()
                and record.category == category
            ]
            records = [
                record
                for record in current
                if not (
                    record.source_path.casefold() == item.source_path.casefold()
                    and record.category == category
                )
            ]
            records.append(item)
            pending_by_id = {entry.file_id: entry for entry in pending}
            pending_by_id.pop(item.file_id, None)
            for previous in replaced:
                if previous.file_id == item.file_id:
                    continue
                pending_by_id[previous.file_id] = DrivePendingRemoteDelete(
                    previous.file_id,
                    previous.file_name,
                    "replaced share",
                    datetime.now(UTC).isoformat(),
                )
            self._save(records, list(pending_by_id.values()))
        return item

    def remember_pending_remote(
        self,
        remote: GoogleDriveFile,
        reason: str,
    ) -> DrivePendingRemoteDelete:
        item = DrivePendingRemoteDelete(
            remote.file_id.strip(),
            remote.name,
            reason.strip() or "uncommitted upload",
            datetime.now(UTC).isoformat(),
        )
        if not item.file_id:
            raise ValueError("Google Drive file ID is missing.")
        with managed_path_lock(self._path):
            records, pending = self._state_unlocked()
            pending_by_id = {entry.file_id: entry for entry in pending}
            pending_by_id[item.file_id] = item
            self._save(list(records), list(pending_by_id.values()))
        return item

    def forget_pending_remote(self, file_id: str) -> bool:
        normalized_id = file_id.strip()
        if not normalized_id:
            return False
        with managed_path_lock(self._path):
            records, pending = self._state_unlocked()
            remaining = [entry for entry in pending if entry.file_id != normalized_id]
            if len(remaining) == len(pending):
                return False
            self._save(list(records), remaining)
            return True

    def pending_remote_deletes(self) -> tuple[DrivePendingRemoteDelete, ...]:
        with managed_path_lock(self._path):
            _records, pending = self._state_unlocked()
            return pending

    def has_file_id(self, file_id: str) -> bool:
        normalized_id = file_id.strip()
        if not normalized_id:
            return False
        with managed_path_lock(self._path):
            records, _pending = self._state_unlocked()
            return any(record.file_id == normalized_id for record in records)

    def remove(self, source: Path, category: str) -> bool:
        source_path = str(source.expanduser().resolve()).casefold()
        with managed_path_lock(self._path):
            records, pending = self._state_unlocked()
            remaining = [
                record
                for record in records
                if not (
                    record.source_path.casefold() == source_path
                    and record.category == category
                )
            ]
            if len(remaining) == len(records):
                return False
            self._save(remaining, list(pending))
            return True

    def move_source(self, source: Path, target: Path, category: str) -> bool:
        source_path = str(source.expanduser().resolve()).casefold()
        resolved_target = target.expanduser().resolve()
        if not resolved_target.is_file():
            return False
        target_stat = resolved_target.stat()
        with managed_path_lock(self._path):
            current, pending = self._state_unlocked()
            changed = False
            records: list[DriveShareRecord] = []
            for record in current:
                if record.source_path.casefold() == source_path and record.category == category:
                    record = DriveShareRecord(
                        source_path=str(resolved_target),
                        source_size=target_stat.st_size,
                        source_modified_ns=target_stat.st_mtime_ns,
                        category=record.category,
                        file_id=record.file_id,
                        file_name=record.file_name,
                        share_link=record.share_link,
                        shared_at=record.shared_at,
                    )
                    changed = True
                records.append(record)
            if changed:
                self._save(records, list(pending))
            return changed

    def records(self) -> tuple[DriveShareRecord, ...]:
        with managed_path_lock(self._path):
            records, _pending = self._state_unlocked()
            return records

    def _state_unlocked(
        self,
    ) -> tuple[tuple[DriveShareRecord, ...], tuple[DrivePendingRemoteDelete, ...]]:
        if not self._path.is_file():
            return (), ()
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return (), ()
        if not isinstance(data, dict):
            return (), ()
        if data.get("version") not in (
            *SHARE_CATALOG_PREVIOUS_VERSIONS,
            SHARE_CATALOG_VERSION,
        ):
            return (), ()
        values = data.get("shares")
        if not isinstance(values, list):
            values = []
        records: list[DriveShareRecord] = []
        for value in values:
            if not isinstance(value, dict):
                continue
            try:
                records.append(
                    DriveShareRecord(
                        source_path=str(value["source_path"]),
                        source_size=int(value["source_size"]),
                        source_modified_ns=int(value["source_modified_ns"]),
                        category=str(value["category"]),
                        file_id=str(value["file_id"]),
                        file_name=str(value["file_name"]),
                        share_link=str(value["share_link"]),
                        shared_at=str(value["shared_at"]),
                    )
                )
            except (KeyError, TypeError, ValueError):
                continue
        pending_values = data.get("pending_remote_deletes")
        if not isinstance(pending_values, list):
            pending_values = []
        pending: list[DrivePendingRemoteDelete] = []
        seen_pending: set[str] = set()
        for value in pending_values:
            if not isinstance(value, dict):
                continue
            file_id = str(value.get("file_id", "")).strip()
            if not file_id or file_id in seen_pending:
                continue
            seen_pending.add(file_id)
            pending.append(
                DrivePendingRemoteDelete(
                    file_id,
                    str(value.get("file_name", "")),
                    str(value.get("reason", "")),
                    str(value.get("created_at", "")),
                )
            )
        return tuple(records), tuple(pending)

    def _save(
        self,
        records: list[DriveShareRecord],
        pending: list[DrivePendingRemoteDelete],
    ) -> None:
        write_json_atomic(
            self._path,
            {
                "version": SHARE_CATALOG_VERSION,
                "shares": [asdict(record) for record in records],
                "pending_remote_deletes": [asdict(item) for item in pending],
            },
        )
