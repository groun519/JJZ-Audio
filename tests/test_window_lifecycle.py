from __future__ import annotations

import unittest
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QLabel, QMenu, QVBoxLayout, QWidget

from jang_app.qt_app.library_details_panel import LibraryDetailsPanel
from jang_app.qt_app.share_progress_action import ShareProgressAction
from jang_app.qt_app.vocal_results_panel import VocalResultsPanel
from jang_app.qt_app.window_lifecycle import (
    WindowLifecycleGuard,
    install_window_lifecycle_guard,
)
from jang_app.qt_app.widgets import DangerIconButton, TrackRow
from jang_app.services.song_assets import SongAsset, SongAssetDetails


class WindowLifecycleGuardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        existing = getattr(self.app, "_jjzero_window_lifecycle_guard", None)
        if isinstance(existing, WindowLifecycleGuard):
            self.app.removeEventFilter(existing)
            delattr(self.app, "_jjzero_window_lifecycle_guard")

    def tearDown(self) -> None:
        existing = getattr(self.app, "_jjzero_window_lifecycle_guard", None)
        if isinstance(existing, WindowLifecycleGuard):
            self.app.removeEventFilter(existing)
            delattr(self.app, "_jjzero_window_lifecycle_guard")

    def test_parentless_label_is_blocked_before_it_can_remain_visible(self) -> None:
        guard = install_window_lifecycle_guard(self.app)
        label = QLabel("Accidental window")
        label.setObjectName("TransientLabel")

        with self.assertLogs("jang_app", level="ERROR") as captured:
            label.show()
            QTest.qWait(260)

        self.assertFalse(label.isVisible())
        self.assertEqual(guard.blocked_count, 1)
        self.assertIn("TransientLabel", guard.last_blocked)
        self.assertIn("Blocked unexpected top-level widget", captured.output[0])
        label.close()

    def test_normal_application_windows_and_framework_popups_are_allowed(self) -> None:
        guard = WindowLifecycleGuard(self.app)
        dialog = QDialog()
        menu = QMenu()
        splash = QWidget(
            None,
            Qt.WindowType.SplashScreen | Qt.WindowType.FramelessWindowHint,
        )

        self.assertTrue(guard.is_expected_window(dialog))
        self.assertTrue(guard.is_expected_window(menu))
        self.assertTrue(guard.is_expected_window(splash))

    def test_explicit_custom_window_opt_in_is_allowed(self) -> None:
        guard = WindowLifecycleGuard(self.app)
        custom_window = QWidget()
        custom_window.setProperty("allowTopLevelWindow", True)

        self.assertTrue(guard.is_expected_window(custom_window))

    def test_installation_is_idempotent(self) -> None:
        first = install_window_lifecycle_guard(self.app)
        second = install_window_lifecycle_guard(self.app)

        self.assertIs(first, second)

    def test_composite_widgets_do_not_show_children_before_parenting(self) -> None:
        guard = install_window_lifecycle_guard(self.app)
        host = QWidget()
        host.setProperty("allowTopLevelWindow", True)
        layout = QVBoxLayout(host)

        result_panel = VocalResultsPanel(mode="separation")
        track_row = TrackRow("Converted Vocal", allow_selection=True)
        share_action = ShareProgressAction(parent=host)
        self.app.processEvents()

        self.assertIsInstance(share_action.delete_button, DangerIconButton)
        self.assertEqual(guard.blocked_count, 0)
        layout.addWidget(result_panel)
        layout.addWidget(track_row)
        layout.addWidget(share_action)
        host.show()
        self.app.processEvents()

        self.assertFalse(result_panel.result_combo.isVisible())
        self.assertTrue(result_panel.original_waveform.isVisible())
        self.assertTrue(result_panel.instrumental_waveform.isVisible())
        self.assertTrue(track_row.path_combo.isVisible())
        self.assertTrue(share_action.isVisible())
        self.assertEqual(guard.blocked_count, 0)
        host.close()

    def test_temporarily_top_level_children_are_restored_after_layout_parenting(self) -> None:
        guard = install_window_lifecycle_guard(self.app)
        host = QWidget()
        host.setProperty("allowTopLevelWindow", True)
        layout = QVBoxLayout(host)
        host.show()

        child = QLabel("Deferred child")
        child.show()
        layout.addWidget(child)
        self.app.processEvents()

        self.assertTrue(child.isVisible())
        self.assertFalse(child.isWindow())
        self.assertEqual(guard.blocked_count, 0)
        host.close()

    def test_slowly_parented_child_is_not_reported_as_an_unexpected_window(self) -> None:
        guard = install_window_lifecycle_guard(self.app)
        host = QWidget()
        host.setProperty("allowTopLevelWindow", True)
        layout = QVBoxLayout(host)
        host.show()

        child = QLabel("Slow child")
        child.setObjectName("SlowChild")
        child.show()
        QTimer.singleShot(120, lambda: layout.addWidget(child))
        QTest.qWait(260)

        self.assertTrue(child.isVisible())
        self.assertFalse(child.isWindow())
        self.assertEqual(guard.blocked_count, 0)
        host.close()

    def test_library_asset_actions_are_not_blocked_as_top_level_windows(self) -> None:
        guard = install_window_lifecycle_guard(self.app)
        host = QWidget()
        host.setProperty("allowTopLevelWindow", True)
        layout = QVBoxLayout(host)
        panel = LibraryDetailsPanel()
        layout.addWidget(panel)
        host.show()
        panel.set_details(
            SongAssetDetails(
                song_id="song-1",
                title="Song One",
                source_type="local",
                source_url="",
                original_name="source.wav",
                package_dir=Path("song-package"),
                created_at="",
                assets=(
                    SongAsset(
                        "vocal",
                        "Original Vocal",
                        Path("vocals.wav"),
                        removal_scope="vocal_output",
                    ),
                ),
            )
        )
        panel.stage_stack.set_current_index(1)
        self.app.processEvents()

        row = panel.vocal_page.asset_rows[0]
        self.assertTrue(row.remove_slot.isVisible())
        self.assertFalse(row.remove_button.isVisible())
        row._set_remove_emphasis(True)
        self.assertTrue(row.remove_button.isVisible())
        self.assertEqual(guard.blocked_count, 0)
        host.close()
