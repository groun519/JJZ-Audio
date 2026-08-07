from __future__ import annotations

import unittest
from pathlib import Path
from types import SimpleNamespace

from PySide6.QtWidgets import QApplication

from jang_app.qt_app.main_window import (
    MainWindow,
    PAGE_LIBRARY,
    PAGE_MODELS,
    PAGE_STUDIO,
    PAGE_VOCAL,
)
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


class _LibraryPlaybackTarget:
    def __init__(self) -> None:
        self.duration_ms = 0
        self.position: tuple[int, int] | None = None
        self.is_playing = False

    def set_preview_queue(self, duration_ms: int) -> None:
        self.duration_ms = duration_ms

    def set_preview_position(self, position_ms: int, duration_ms: int) -> None:
        self.position = (position_ms, duration_ms)

    def set_preview_playing(self, is_playing: bool) -> None:
        self.is_playing = is_playing


class MainWindowPlaybackNavigationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_navigation_suspends_playback_across_context_boundaries(self) -> None:
        calls: list[tuple[str, int | None]] = []
        window = SimpleNamespace(
            page_stack=_PageStack(PAGE_LIBRARY),
            studio_session_autosave=SimpleNamespace(flush=lambda: calls.append(("flush", None))),
            model_workspace_page=SimpleNamespace(stop_preview=lambda: calls.append(("model", None))),
            primary_navigation=SimpleNamespace(
                set_current_page=lambda index: calls.append(("navigation", index))
            ),
            _suspend_playback=lambda: calls.append(("suspend", None)),
            _refresh_export_page=lambda: calls.append(("export", None)),
            _sync_playback_queue_for_page=lambda index: calls.append(("queue", index)),
            _sync_playback_surfaces=lambda: calls.append(("surface", None)),
            _sync_video_workspace=lambda: calls.append(("video", None)),
        )

        MainWindow._navigate_to_page(window, PAGE_MODELS)

        self.assertEqual(window.page_stack.currentIndex(), PAGE_MODELS)
        self.assertIn(("suspend", None), calls)
        self.assertIn(("queue", PAGE_MODELS), calls)
        self.assertIn(("surface", None), calls)

    def test_navigation_keeps_playback_between_vocal_and_studio(self) -> None:
        calls: list[tuple[str, int | None]] = []
        window = SimpleNamespace(
            page_stack=_PageStack(PAGE_STUDIO),
            studio_session_autosave=SimpleNamespace(flush=lambda: calls.append(("flush", None))),
            model_workspace_page=SimpleNamespace(stop_preview=lambda: calls.append(("model", None))),
            primary_navigation=SimpleNamespace(
                set_current_page=lambda index: calls.append(("navigation", index))
            ),
            _suspend_playback=lambda: calls.append(("suspend", None)),
            _refresh_export_page=lambda: calls.append(("export", None)),
            _sync_playback_queue_for_page=lambda index, **kwargs: calls.append(
                ("queue-force" if kwargs.get("force") else "queue", index)
            ),
            _sync_playback_surfaces=lambda: calls.append(("surface", None)),
            _sync_video_workspace=lambda: calls.append(("video", None)),
        )

        MainWindow._navigate_to_page(window, PAGE_VOCAL)

        self.assertNotIn(("suspend", None), calls)
        self.assertIn(("queue-force", PAGE_VOCAL), calls)

    def test_suspending_library_preview_collapses_and_remembers_position(self) -> None:
        queue = PlaybackQueue(
            context="library",
            source_id="song-1",
            title="Song",
            paths=(Path("song.wav"),),
            volumes=(1.0,),
            duration_ms=90_000,
        )
        calls: list[tuple[str, object]] = []
        window = SimpleNamespace(
            current_playback_queue=queue,
            player=SimpleNamespace(is_playing=lambda: True, position_ms=lambda: 15_000),
            _playback_position_ms=0,
            _playback_resume_positions={},
            _set_library_preview_expanded=lambda song_id, expanded: calls.append(
                (song_id, expanded)
            ),
            _stop_playback=lambda **kwargs: calls.append(("stop", kwargs)),
        )

        MainWindow._suspend_playback(window)

        self.assertEqual(window._playback_resume_positions[("library", "song-1")], 15_000)
        self.assertIn(("song-1", False), calls)
        self.assertIn(("stop", {"clear_queue": True}), calls)

    def test_playing_workspace_queue_is_not_replaced_inside_workspace(self) -> None:
        queue = PlaybackQueue(
            context="output",
            source_id="output-1",
            title="Output",
            paths=(Path("mix.wav"),),
            volumes=(1.0,),
            duration_ms=1_000,
        )
        window = SimpleNamespace(
            current_playback_queue=queue,
            player=SimpleNamespace(is_playing=lambda: True),
            _load_library_playback_queue=lambda _song: self.fail("queue was replaced"),
            _refresh_output_playback_queue=lambda: self.fail("output queue was loaded"),
        )

        MainWindow._sync_playback_queue_for_page(window, PAGE_STUDIO)

        self.assertIs(window.current_playback_queue, queue)

    def test_workspace_transport_is_visible_only_on_workspace_pages(self) -> None:
        workspace = _VisibilityTarget()
        window = SimpleNamespace(
            page_stack=_PageStack(PAGE_STUDIO),
            workspace_dock=workspace,
            _position_processing_queue=lambda: None,
        )

        MainWindow._sync_playback_surfaces(window)

        self.assertTrue(workspace.visible)
        window.page_stack.setCurrentIndex(PAGE_LIBRARY)
        MainWindow._sync_playback_surfaces(window)

        self.assertFalse(workspace.visible)

    def test_library_queue_state_updates_only_the_expanded_row(self) -> None:
        workspace = _WorkspacePlaybackTarget()
        preview = _LibraryPlaybackTarget()
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
            _playback_position_ms=15_000,
            _library_row=lambda _song_id: (None, preview),
            _sync_playback_surfaces=lambda: None,
            _sync_video_playback=lambda _is_playing: None,
        )

        MainWindow._refresh_playback_ui(window, is_playing=True)

        self.assertEqual(preview.position, (15_000, 90_000))
        self.assertEqual(workspace.duration_ms, 0)
        self.assertIsNone(workspace.position)
        self.assertTrue(preview.is_playing)
        self.assertFalse(workspace.is_playing)

    def test_vocal_playback_uses_shared_track_mute_and_volume_settings(self) -> None:
        def track(path: str, volume: float, muted: bool = False):
            return SimpleNamespace(
                current_path=lambda: Path(path),
                is_muted=lambda: muted,
                volume=lambda: volume,
            )

        original = track("original.wav", 0.8)
        instrumental = track("instrumental.wav", 0.4, muted=True)
        converted = track("converted.wav", 1.2)
        window = SimpleNamespace(
            output_tracks=(original, instrumental, converted),
        )

        tracks = MainWindow._playback_track_paths(window)

        self.assertEqual(
            [path for path, _volume in tracks],
            [Path("original.wav"), Path("instrumental.wav"), Path("converted.wav")],
        )
        self.assertEqual([volume for _path, volume in tracks], [0.8, 0.0, 1.2])


if __name__ == "__main__":
    unittest.main()
