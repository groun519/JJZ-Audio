from __future__ import annotations

import unittest

from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import QApplication

from jang_app.qt_app.library_group_panel import LibraryGroupPanel
from jang_app.services.library_groups import (
    ALL_SONGS_GROUP_ID,
    UNGROUPED_SONGS_GROUP_ID,
    LibraryGroup,
)


class LibraryGroupPanelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_renders_hierarchy_counts_and_restores_selection(self) -> None:
        panel = LibraryGroupPanel()
        parent = LibraryGroup("parent", "Cover Work")
        child = LibraryGroup("child", "Vocaloid", parent.group_id)

        panel.set_groups(
            (parent, child),
            {
                ALL_SONGS_GROUP_ID: 12,
                parent.group_id: 7,
                child.group_id: 3,
                UNGROUPED_SONGS_GROUP_ID: 5,
            },
            child.group_id,
            (parent.group_id,),
        )

        self.assertEqual(panel.tree.topLevelItemCount(), 3)
        parent_item = panel.tree.topLevelItem(1)
        self.assertEqual(parent_item.text(0), "Cover Work")
        self.assertEqual(parent_item.text(1), "7")
        self.assertEqual(parent_item.childCount(), 1)
        self.assertEqual(parent_item.child(0).text(0), "Vocaloid")
        self.assertTrue(parent_item.isExpanded())
        self.assertEqual(panel.selected_group_id(), child.group_id)
        panel.close()

    def test_emits_selection_and_expanded_group_state(self) -> None:
        panel = LibraryGroupPanel()
        parent = LibraryGroup("parent", "Parent")
        child = LibraryGroup("child", "Child", parent.group_id)
        panel.set_groups(
            (parent, child),
            {ALL_SONGS_GROUP_ID: 2, parent.group_id: 1, child.group_id: 1},
            ALL_SONGS_GROUP_ID,
            (),
        )
        selected = QSignalSpy(panel.group_selected)
        expanded = QSignalSpy(panel.expanded_groups_changed)
        parent_item = panel.tree.topLevelItem(1)

        panel.tree.setCurrentItem(parent_item.child(0))
        parent_item.setExpanded(True)
        self.app.processEvents()

        self.assertEqual(selected.count(), 1)
        self.assertEqual(selected.at(0)[0], child.group_id)
        self.assertGreaterEqual(expanded.count(), 1)
        self.assertIn(parent.group_id, expanded.at(expanded.count() - 1)[0])
        panel.close()


if __name__ == "__main__":
    unittest.main()
