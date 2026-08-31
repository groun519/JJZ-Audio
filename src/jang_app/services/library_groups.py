from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Iterator
from uuid import uuid4

from jang_app.services.library_catalog import LibraryCatalog
from jang_app.services.managed_files import managed_path_lock


ALL_SONGS_GROUP_ID = "__all__"
UNGROUPED_SONGS_GROUP_ID = "__ungrouped__"
_SELECTED_GROUP_KEY = "library.selected_group"
_EXPANDED_GROUPS_KEY = "library.expanded_groups"
_GROUP_PANEL_WIDTH_KEY = "library.group_panel_width"


class LibraryGroupError(ValueError):
    pass


@dataclass(frozen=True)
class LibraryGroup:
    group_id: str
    name: str
    parent_group_id: str | None = None
    position: int = 0


class LibraryGroupStore:
    """Persistent virtual folders for songs without moving managed media files."""

    def __init__(self, catalog_file: Path) -> None:
        self.path = catalog_file.expanduser().resolve()
        self._catalog = LibraryCatalog(self.path)
        self._catalog.ensure_schema()

    def groups(self) -> tuple[LibraryGroup, ...]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT group_id, name, parent_group_id, position
                FROM song_groups
                ORDER BY parent_group_id IS NOT NULL, position, normalized_name, group_id
                """
            ).fetchall()
        return tuple(
            LibraryGroup(
                group_id=str(row[0]),
                name=str(row[1]),
                parent_group_id=str(row[2]) if row[2] is not None else None,
                position=int(row[3]),
            )
            for row in rows
        )

    def create_group(self, name: str, parent_group_id: str | None = None) -> LibraryGroup:
        cleaned = _clean_group_name(name)
        parent_id = _optional_group_id(parent_group_id)
        with self._connect() as connection:
            if parent_id is not None:
                parent = connection.execute(
                    "SELECT parent_group_id FROM song_groups WHERE group_id = ?",
                    (parent_id,),
                ).fetchone()
                if parent is None:
                    raise LibraryGroupError("The parent group no longer exists.")
                if parent[0] is not None:
                    raise LibraryGroupError("Groups can be nested by one level only.")
            position = int(
                connection.execute(
                    """
                    SELECT COALESCE(MAX(position), -1) + 1
                    FROM song_groups
                    WHERE parent_group_id IS ?
                    """,
                    (parent_id,),
                ).fetchone()[0]
            )
            now = _utc_timestamp()
            group = LibraryGroup(uuid4().hex, cleaned, parent_id, position)
            try:
                connection.execute(
                    """
                    INSERT INTO song_groups(
                        group_id, name, normalized_name, parent_group_id,
                        position, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        group.group_id,
                        group.name,
                        group.name.casefold(),
                        group.parent_group_id,
                        group.position,
                        now,
                        now,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise LibraryGroupError("A group with this name already exists here.") from exc
        return group

    def rename_group(self, group_id: str, name: str) -> LibraryGroup:
        cleaned = _clean_group_name(name)
        with self._connect() as connection:
            row = connection.execute(
                "SELECT parent_group_id, position FROM song_groups WHERE group_id = ?",
                (group_id,),
            ).fetchone()
            if row is None:
                raise LibraryGroupError("The group no longer exists.")
            try:
                connection.execute(
                    """
                    UPDATE song_groups
                    SET name = ?, normalized_name = ?, updated_at = ?
                    WHERE group_id = ?
                    """,
                    (cleaned, cleaned.casefold(), _utc_timestamp(), group_id),
                )
            except sqlite3.IntegrityError as exc:
                raise LibraryGroupError("A group with this name already exists here.") from exc
        return LibraryGroup(
            group_id,
            cleaned,
            str(row[0]) if row[0] is not None else None,
            int(row[1]),
        )

    def delete_group(self, group_id: str) -> None:
        with self._connect() as connection:
            connection.execute("DELETE FROM song_groups WHERE group_id = ?", (group_id,))

    def assign_songs(self, song_ids: Iterable[str], group_id: str | None) -> None:
        normalized_ids = tuple(dict.fromkeys(str(song_id).strip() for song_id in song_ids if str(song_id).strip()))
        if not normalized_ids:
            return
        target_id = _optional_group_id(group_id)
        with self._connect() as connection:
            if target_id is None:
                connection.executemany(
                    "DELETE FROM song_group_memberships WHERE song_id = ?",
                    ((song_id,) for song_id in normalized_ids),
                )
                return
            exists = connection.execute(
                "SELECT 1 FROM song_groups WHERE group_id = ?",
                (target_id,),
            ).fetchone()
            if exists is None:
                raise LibraryGroupError("The target group no longer exists.")
            connection.executemany(
                """
                INSERT INTO song_group_memberships(song_id, group_id) VALUES (?, ?)
                ON CONFLICT(song_id) DO UPDATE SET group_id = excluded.group_id
                """,
                ((song_id, target_id) for song_id in normalized_ids),
            )

    def membership_map(self, song_ids: Iterable[str] = ()) -> dict[str, str]:
        normalized_ids = tuple(dict.fromkeys(str(song_id).strip() for song_id in song_ids if str(song_id).strip()))
        with self._connect() as connection:
            if not normalized_ids:
                rows = connection.execute(
                    "SELECT song_id, group_id FROM song_group_memberships"
                ).fetchall()
            else:
                placeholders = ",".join("?" for _ in normalized_ids)
                rows = connection.execute(
                    f"SELECT song_id, group_id FROM song_group_memberships WHERE song_id IN ({placeholders})",
                    normalized_ids,
                ).fetchall()
        return {str(row[0]): str(row[1]) for row in rows}

    def song_ids_for_group(
        self,
        selection_id: str,
        all_song_ids: Iterable[str],
    ) -> frozenset[str]:
        available = frozenset(str(song_id) for song_id in all_song_ids)
        if selection_id == ALL_SONGS_GROUP_ID:
            return available
        memberships = self.membership_map(available)
        if selection_id == UNGROUPED_SONGS_GROUP_ID:
            return frozenset(song_id for song_id in available if song_id not in memberships)
        descendants = self._descendant_ids(selection_id)
        descendants.add(selection_id)
        return frozenset(
            song_id
            for song_id, group_id in memberships.items()
            if song_id in available and group_id in descendants
        )

    def group_counts(
        self,
        all_song_ids: Iterable[str],
        groups: Iterable[LibraryGroup] | None = None,
    ) -> dict[str, int]:
        available = frozenset(str(song_id) for song_id in all_song_ids)
        group_list = tuple(groups) if groups is not None else self.groups()
        by_id = {group.group_id: group for group in group_list}
        memberships = self.membership_map(available)
        counts = {
            ALL_SONGS_GROUP_ID: len(available),
            UNGROUPED_SONGS_GROUP_ID: sum(
                1
                for song_id in available
                if memberships.get(song_id) not in by_id
            ),
        }
        counts.update((group.group_id, 0) for group in group_list)
        for song_id in available:
            group_id = memberships.get(song_id)
            visited: set[str] = set()
            while group_id in by_id and group_id not in visited:
                counts[group_id] += 1
                visited.add(group_id)
                group_id = by_id[group_id].parent_group_id
        return counts

    def selected_group_id(self) -> str:
        selected = self._catalog.metadata(_SELECTED_GROUP_KEY) or ALL_SONGS_GROUP_ID
        valid_ids = {group.group_id for group in self.groups()}
        if selected in {ALL_SONGS_GROUP_ID, UNGROUPED_SONGS_GROUP_ID} or selected in valid_ids:
            return selected
        return ALL_SONGS_GROUP_ID

    def set_selected_group_id(self, group_id: str) -> None:
        self._catalog.set_metadata(_SELECTED_GROUP_KEY, group_id)

    def expanded_group_ids(self) -> frozenset[str]:
        try:
            value = json.loads(self._catalog.metadata(_EXPANDED_GROUPS_KEY) or "[]")
        except (TypeError, ValueError, json.JSONDecodeError):
            return frozenset()
        return frozenset(str(item) for item in value if isinstance(item, str))

    def set_expanded_group_ids(self, group_ids: Iterable[str]) -> None:
        payload = sorted({str(group_id) for group_id in group_ids if str(group_id)})
        self._catalog.set_metadata(_EXPANDED_GROUPS_KEY, json.dumps(payload))

    def group_panel_width(self, default: int = 210) -> int:
        try:
            return max(0, min(420, int(self._catalog.metadata(_GROUP_PANEL_WIDTH_KEY))))
        except (TypeError, ValueError):
            return default

    def set_group_panel_width(self, width: int) -> None:
        self._catalog.set_metadata(_GROUP_PANEL_WIDTH_KEY, str(max(0, min(420, int(width)))))

    def display_path(self, group_id: str) -> str:
        return self.display_paths().get(group_id, "")

    def display_paths(
        self,
        groups: Iterable[LibraryGroup] | None = None,
    ) -> dict[str, str]:
        group_list = tuple(groups) if groups is not None else self.groups()
        by_id = {group.group_id: group for group in group_list}
        paths: dict[str, str] = {}
        for group in group_list:
            parent = by_id.get(group.parent_group_id or "")
            paths[group.group_id] = (
                f"{parent.name} / {group.name}" if parent is not None else group.name
            )
        return paths

    def _descendant_ids(self, group_id: str) -> set[str]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                WITH RECURSIVE descendants(group_id) AS (
                    SELECT group_id FROM song_groups WHERE parent_group_id = ?
                    UNION ALL
                    SELECT child.group_id
                    FROM song_groups AS child
                    JOIN descendants AS parent ON child.parent_group_id = parent.group_id
                )
                SELECT group_id FROM descendants
                """,
                (group_id,),
            ).fetchall()
        return {str(row[0]) for row in rows}

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        with managed_path_lock(self.path):
            connection = sqlite3.connect(self.path, timeout=5)
            try:
                connection.execute("PRAGMA foreign_keys = ON")
                connection.execute("PRAGMA busy_timeout = 5000")
                with connection:
                    yield connection
            finally:
                connection.close()


def _clean_group_name(name: str) -> str:
    cleaned = " ".join(str(name).split())
    if not cleaned:
        raise LibraryGroupError("Enter a group name.")
    if len(cleaned) > 80:
        raise LibraryGroupError("Group names can contain up to 80 characters.")
    return cleaned


def _optional_group_id(group_id: str | None) -> str | None:
    if group_id in {None, "", UNGROUPED_SONGS_GROUP_ID, ALL_SONGS_GROUP_ID}:
        return None
    return str(group_id)


def _utc_timestamp() -> str:
    return datetime.now(UTC).isoformat()
