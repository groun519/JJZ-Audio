from __future__ import annotations

import unittest
from pathlib import Path
from types import SimpleNamespace

from PySide6.QtWidgets import QApplication

from jang_app.qt_app.main_window import MainWindow, PAGE_LIBRARY, PAGE_MODELS, PAGE_STUDIO
from jang_app.services.playback_queue import PlaybackQueue


class _PageStack:
    def __init__(self, index: int) -> None:
        self.index = index

    def currentIndex(self) -> int:  # noqa: N802
        return self.index

    def setCurrentIndex(self, index: int) -> None:  # noqa: N802
        self.index = index


class _VisibilityTarget:
    def __init__(self) -> None:
        self.visible = False

    def setVisible(self, is_visible: bool) -> None:  # noqa: N802
        self.visible = is_visible


class _FloatingPlaybackTarget(_VisibilityTarget):
    def __init__(self) -> None:
        super().__init__()
        self.queue: tuple[str, int] | None = None
        self.position: tuple[int, int] | None = None
        self.is_playing = False

    def set_queue(self, title: str, duration_ms: int) -> None:
        self.queue = (title, duration_ms)

    def set_position(self, position_ms: int, duration_ms: int) -> None:
        self.position = (position_ms, duration_ms)

    def set_playing(self, is_playing: bool) -> None:
        self.is_playing = is_playing

    def clear(self) -> None:
        self.queue = None
        self.position = None
        self.is_playing = False


class _WorkspacePlaybackTarget(_VisibilityTarget):
    def __init__(self) -> None:
        super().__init__()
        self.duration_ms = 0
        self.position: tuple[int, int] | None = None
        self.is_playing = False

    def set_queue(self, duration_ms: int) -> None:
        self.duration_ms = duration_ms

    def set_position(self, position_ms: int, duration_ms: int) -> None:
        self.position = (position_ms, duration_ms)

    def set_playing(self, is_playing: bool) -> None:
        self.is_playing = is_playing

    def clear(self) -> None:
        self.duration_ms = 0
        self.position = None
        self.is_playing = False


class MainWindowPlaybackNavigationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_navigation_does_not_suspend_the_active_queue(self) -> None:
        calls: list[tuple[str, int | None]] = []
        window = SimpleNamespace(
            page_stack=_PageStack(PAGE_LIBRARY),
            studio_session_autosave=SimpleNamespace(flush=lambda: calls.append(("flush", None))),
            model_workspace_page=SimpleNamespace(stop_preview=lambda: calls.append(("model", None))),
            primary_navigation=SimpleNamespace(
                set_current_page=lambda index: calls.append(("navigation", index))
            ),
            _refresh_export_page=lambda: calls.append(("export", None)),
            _sync_playback_queue_for_page=lambda index: calls.append(("queue", index)),
            _sync_playback_surfaces=lambda: calls.append(("surface", None)),
            _sync_video_workspace=lambda: calls.append(("video", None)),
        )

        MainWindow._navigate_to_page(window, PAGE_MODELS)

        self.assertEqual(window.page_stack.currentIndex(), PAGE_MODELS)
        self.assertIn(("queue", PAGE_MODELS), calls)
        self.assertIn(("surface", None), calls)

    def test_existing_queue_is_not_replaced_on_page_change(self) -> None:
        queue = PlaybackQueue(
            context="library",
            source_id="song-1",
            title="Song",
            paths=(Path("song.wav"),),
            volumes=(1.0,),
            duration_ms=1_000,
        )
        window = SimpleNamespace(
            current_playback_queue=queue,
            _library_preview_song_id="song-1",
            _song_items_by_id={},
            _load_library_playback_queue=lambda _song: self.fail("queue was replaced"),
            _refresh_output_playback_queue=lambda: self.fail("output queue was loaded"),
        )

        MainWindow._sync_playback_queue_for_page(window, PAGE_STUDIO)

        self.assertIs(window.current_playback_queue, queue)

    def test_library_preview_remains_floating_inside_workspace_pages(self) -> None:
        workspace = _VisibilityTarget()
        floating = _VisibilityTarget()
        queue = PlaybackQueue(
            context="library",
            source_id="song-1",
            title="Song",
            paths=(Path("song.wav"),),
            volumes=(1.0,),
            duration_ms=1_000,
        )
        window = SimpleNamespace(
            page_stack=_PageStack(PAGE_STUDIO),
            current_playback_queue=queue,
            workspace_dock=workspace,
            floating_playback_panel=floating,
            _position_floating_playback=lambda: None,
            _position_processing_queue=lambda: None,
        )

        MainWindow._sync_playback_surfaces(window)

        self.assertTrue(workspace.visible)
        self.assertTrue(floating.visible)

        window.current_playback_queue = PlaybackQueue(
            context="output",
            source_id="output-1",
            title="Output",
            paths=(Path("mix.wav"),),
            volumes=(1.0,),
            duration_ms=1_000,
        )
        MainWindow._sync_playback_surfaces(window)

        self.assertTrue(workspace.visible)
        self.assertFalse(floating.visible)

    def test_library_queue_state_is_mirrored_to_workspace_transport(self) -> None:
        workspace = _WorkspacePlaybackTarget()
        floating = _FloatingPlaybackTarget()
        queue = PlaybackQueue(
            context="library",
            source_id="song-1",
            title="Song",
            paths=(Path("song.wav"),),
            volumes=(1.0,),
            duration_ms=90_000,
        )
        window = SimpleNamespace(
            current_playback_queue=queue,
            workspace_dock=workspace,
            floating_playback_panel=floating,
            _playback_position_ms=15_000,
            _sync_playback_surfaces=lambda: None,
            _sync_video_playback=lambda _is_playing: None,
        )

        MainWindow._refresh_playback_ui(window, is_playing=True)

        self.assertEqual(floating.position, (15_000, 90_000))
        self.assertEqual(workspace.position, floating.position)
        self.assertEqual(workspace.duration_ms, 90_000)
        self.assertTrue(floating.is_playing)
        self.assertTrue(workspace.is_playing)


if __name__ == "__main__":
    unittest.main()
