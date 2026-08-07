from __future__ import annotations

import unittest

from PySide6.QtWidgets import QApplication

from jang_app.qt_app.library_source_filter import LibrarySourceFilter


class LibrarySourceFilterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_all_sources_is_the_default(self) -> None:
        source_filter = LibrarySourceFilter()

        self.assertTrue(source_filter.buttons["all"].isChecked())
        self.assertEqual(source_filter.selected_sources(), frozenset())
        source_filter.close()

    def test_source_flags_support_multiple_selection(self) -> None:
        source_filter = LibrarySourceFilter()

        source_filter.buttons["local"].click()
        source_filter.buttons["youtube"].click()

        self.assertFalse(source_filter.buttons["all"].isChecked())
        self.assertEqual(source_filter.selected_sources(), frozenset(("local", "youtube")))
        source_filter.close()

    def test_empty_source_selection_returns_to_all(self) -> None:
        source_filter = LibrarySourceFilter()
        source_filter.buttons["output"].click()

        source_filter.buttons["output"].click()

        self.assertTrue(source_filter.buttons["all"].isChecked())
        self.assertEqual(source_filter.selected_sources(), frozenset())
        source_filter.close()

    def test_all_flag_clears_individual_sources(self) -> None:
        source_filter = LibrarySourceFilter()
        source_filter.buttons["local"].click()
        source_filter.buttons["youtube"].click()

        source_filter.buttons["all"].click()

        self.assertTrue(source_filter.buttons["all"].isChecked())
        self.assertEqual(source_filter.selected_sources(), frozenset())
        source_filter.close()


if __name__ == "__main__":
    unittest.main()
