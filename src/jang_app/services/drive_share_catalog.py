from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from jang_app.services.google_drive import GoogleDriveFile
from jang_app.services.managed_files import write_json_atomic


SHARE_CATALOG_VERSION = 1


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
        records = [
            record
            for record in self.records()
            if not (
                record.source_path.casefold() == item.source_path.casefold()
                and record.category == category
            )
        ]
        records.append(item)
        self._save(records)
        return item

    def remove(self, source: Path, category: str) -> bool:
        source_path = str(source.expanduser().resolve()).casefold()
        records = self.records()
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
        self._save(remaining)
        return True

    def records(self) -> tuple[DriveShareRecord, ...]:
        if not self._path.is_file():
            return ()
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return ()
        if data.get("version") != SHARE_CATALOG_VERSION:
            return ()
        values = data.get("shares")
        if not isinstance(values, list):
            return ()
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
        return tuple(records)

    def _save(self, records: list[DriveShareRecord]) -> None:
        write_json_atomic(
            self._path,
            {
                "version": SHARE_CATALOG_VERSION,
                "shares": [asdict(record) for record in records],
            },
        )
