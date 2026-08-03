from __future__ import annotations

import unittest

from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import QApplication, QWidget

from jang_app.qt_app.library_workspace import LibraryWorkspace
from jang_app.services.i18n import LANGUAGE_ENGLISH, LANGUAGE_KOREAN, set_language


class LibraryWorkspaceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def tearDown(self) -> None:
        set_language(LANGUAGE_ENGLISH)

    def test_tabs_switch_content_and_display_live_counts(self) -> None:
        workspace = LibraryWorkspace((("Songs", QWidget()), ("Models", QWidget())))
        changed = QSignalSpy(workspace.current_changed)

        workspace.set_section_count(0, 12)
        workspace.set_section_count(1, 4)
        workspace.section_buttons[1].click()

        self.assertEqual(workspace.section_buttons[0].text(), "Songs 12")
        self.assertEqual(workspace.section_buttons[1].text(), "Models 4")
        self.assertEqual(workspace.current_index(), 1)
        self.assertEqual(changed.at(0)[0], 1)
        self.assertEqual(workspace.section_buttons[1].objectName(), "LibrarySectionTab")
        workspace.close()

    def test_count_labels_follow_the_application_language(self) -> None:
        workspace = LibraryWorkspace((("Songs", QWidget()), ("Models", QWidget())))
        set_language(LANGUAGE_KOREAN)

        workspace.set_section_count(0, 3)
        workspace.set_section_count(1, 2)

        self.assertEqual(workspace.section_buttons[0].text(), "음원 3")
        self.assertEqual(workspace.section_buttons[1].text(), "모델 2")
        workspace.close()


if __name__ == "__main__":
    unittest.main()
