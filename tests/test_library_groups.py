from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from jang_app.services.library_catalog import LibraryCatalog
from jang_app.services.library_groups import (
    ALL_SONGS_GROUP_ID,
    UNGROUPED_SONGS_GROUP_ID,
    LibraryGroupError,
    LibraryGroupStore,
)


class LibraryGroupStoreTests(unittest.TestCase):
    def test_groups_support_one_child_level_and_unique_sibling_names(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = LibraryGroupStore(Path(temporary) / "catalog.db")
            parent = store.create_group("Cover Work")
            child = store.create_group("Vocaloid", parent.group_id)

            self.assertEqual(store.display_path(child.group_id), "Cover Work / Vocaloid")
            with self.assertRaises(LibraryGroupError):
                store.create_group("Vocaloid", parent.group_id)
            with self.assertRaises(LibraryGroupError):
                store.create_group("Too Deep", child.group_id)

    def test_song_assignment_moves_between_groups_and_returns_to_ungrouped(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = LibraryGroupStore(Path(temporary) / "catalog.db")
            first = store.create_group("First")
            second = store.create_group("Second")
            store.assign_songs(("song-1", "song-2"), first.group_id)
            store.assign_songs(("song-1",), second.group_id)

            self.assertEqual(
                store.song_ids_for_group(first.group_id, ("song-1", "song-2", "song-3")),
                frozenset(("song-2",)),
            )
            self.assertEqual(
                store.song_ids_for_group(UNGROUPED_SONGS_GROUP_ID, ("song-1", "song-2", "song-3")),
                frozenset(("song-3",)),
            )
            store.assign_songs(("song-1",), None)
            self.assertEqual(
                store.song_ids_for_group(UNGROUPED_SONGS_GROUP_ID, ("song-1", "song-2", "song-3")),
                frozenset(("song-1", "song-3")),
            )

    def test_parent_selection_includes_child_group_songs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = LibraryGroupStore(Path(temporary) / "catalog.db")
            parent = store.create_group("Parent")
            child = store.create_group("Child", parent.group_id)
            store.assign_songs(("song-1",), child.group_id)

            self.assertEqual(
                store.song_ids_for_group(parent.group_id, ("song-1", "song-2")),
                frozenset(("song-1",)),
            )
            self.assertEqual(
                store.song_ids_for_group(ALL_SONGS_GROUP_ID, ("song-1", "song-2")),
                frozenset(("song-1", "song-2")),
            )

    def test_deleting_group_keeps_song_catalog_and_ungroups_members(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            catalog_path = Path(temporary) / "catalog.db"
            catalog = LibraryCatalog(catalog_path)
            catalog.ensure_schema()
            connection = sqlite3.connect(catalog_path)
            try:
                connection.execute(
                    """
                    INSERT INTO songs(
                        song_id, title, normalized_title, package_dir, source_path,
                        source_type, source_url, created_at, removed
                    ) VALUES ('song-1', 'Song', 'song', '', '', 'local', '', '', 0)
                    """
                )
                connection.commit()
            finally:
                connection.close()
            store = LibraryGroupStore(catalog_path)
            group = store.create_group("Temporary")
            store.assign_songs(("song-1",), group.group_id)

            store.delete_group(group.group_id)

            self.assertEqual(catalog.counts(), (1, 0))
            self.assertEqual(
                store.song_ids_for_group(UNGROUPED_SONGS_GROUP_ID, ("song-1",)),
                frozenset(("song-1",)),
            )

    def test_catalog_rebuild_preserves_virtual_groups(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            catalog_path = Path(temporary) / "catalog.db"
            store = LibraryGroupStore(catalog_path)
            group = store.create_group("Persistent")
            store.assign_songs(("song-1",), group.group_id)

            LibraryCatalog(catalog_path).rebuild((), ())

            self.assertEqual(store.groups(), (group,))
            self.assertEqual(store.membership_map(), {"song-1": group.group_id})

    def test_ui_state_round_trips(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = LibraryGroupStore(Path(temporary) / "catalog.db")
            group = store.create_group("Expanded")
            store.set_selected_group_id(group.group_id)
            store.set_expanded_group_ids((group.group_id,))
            store.set_group_panel_width(236)

            self.assertEqual(store.selected_group_id(), group.group_id)
            self.assertEqual(store.expanded_group_ids(), frozenset((group.group_id,)))
            self.assertEqual(store.group_panel_width(), 236)


if __name__ == "__main__":
    unittest.main()
