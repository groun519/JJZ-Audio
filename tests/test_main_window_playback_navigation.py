from __future__ import annotations

import unittest
from pathlib import Path
from types import SimpleNamespace

from PySide6.QtWidgets import QApplication

from jang_app.qt_app.main_window import (
    MainWindow,
    PAGE_CONVERSION,
    PAGE_LIBRARY,
    PAGE_MODELS,
    PAGE_STUDIO,
    PAGE_SEPARATION,
)
from jang_app.services.playback_queue import PlaybackQueue
from jang_app.services.workspace_playback import WorkspacePlaybackScope


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
        self.scope: WorkspacePlaybackScope | None = None

    def setVisible(self, is_visible: bool) -> None:  # noqa: N802
        self.visible = is_visible

    def set_playback_scope(self, scope: WorkspacePlaybackScope | None) -> None:
        self.scope = scope


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


class _PlayheadTarget:
    def __init__(self) -> None:
        self.ratios: list[float] = []

    def set_playhead_ratio(self, ratio: float) -> None:
        self.ratios.append(ratio)


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

        MainWindow._navigate_to_page(window, PAGE_SEPARATION)

        self.assertNotIn(("suspend", None), calls)
        self.assertIn(("queue-force", PAGE_SEPARATION), calls)

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
            _workspace_scope_for_page=lambda index: MainWindow._workspace_scope_for_page(
                None, index
            ),
            _position_processing_queue=lambda: None,
        )

        MainWindow._sync_playback_surfaces(window)

        self.assertTrue(workspace.visible)
        self.assertEqual(workspace.scope, WorkspacePlaybackScope.STUDIO)
        window.page_stack.setCurrentIndex(PAGE_LIBRARY)
        MainWindow._sync_playback_surfaces(window)

        self.assertFalse(workspace.visible)
        self.assertIsNone(workspace.scope)

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

    def test_workspace_scope_filters_the_shared_sound_pool(self) -> None:
        def track(path: str, volume: float = 1.0):
            return SimpleNamespace(
                current_path=lambda: Path(path),
                is_muted=lambda: False,
                volume=lambda: volume,
            )

        tracks = {
            "original": track("original.wav", 0.8),
            "instrumental": track("instrumental.wav", 0.7),
            "converted": track("converted.wav", 1.2),
        }
        window = SimpleNamespace(
            _output_track=lambda track_id: tracks.get(track_id),
        )

        separation = MainWindow._playback_track_paths(
            window,
            WorkspacePlaybackScope.SEPARATION,
        )
        conversion = MainWindow._playback_track_paths(
            window,
            WorkspacePlaybackScope.CONVERSION,
        )
        studio = MainWindow._playback_track_paths(window, WorkspacePlaybackScope.STUDIO)

        self.assertEqual(
            [path for path, _volume in separation],
            [Path("original.wav"), Path("instrumental.wav")],
        )
        self.assertEqual(
            [path for path, _volume in conversion],
            [Path("original.wav"), Path("converted.wav")],
        )
        self.assertEqual(
            [path for path, _volume in studio],
            [Path("original.wav"), Path("instrumental.wav"), Path("converted.wav")],
        )

    def test_workspace_queue_records_scope_and_uses_scope_tracks(self) -> None:
        def track(path: str):
            return SimpleNamespace(
                current_path=lambda: Path(path),
                is_muted=lambda: False,
                volume=lambda: 1.0,
            )

        tracks = {
            "original": track("original.wav"),
            "instrumental": track("instrumental.wav"),
            "converted": track("converted.wav"),
        }
        window = SimpleNamespace(
            _output_track=lambda track_id: tracks.get(track_id),
            _playback_track_paths=lambda scope: MainWindow._playback_track_paths(window, scope),
            _duration_ms_for_paths=lambda paths: 12_000,
            current_output_set=SimpleNamespace(job_dir=Path("output/run-1"), label="Run 1"),
        )

        queue = MainWindow._workspace_playback_queue(
            window,
            WorkspacePlaybackScope.CONVERSION,
        )

        self.assertEqual(queue.context, "output")
        self.assertEqual(queue.scope, "conversion")
        self.assertEqual(queue.title, "Conversion Compare")
        self.assertEqual(queue.paths, (Path("original.wav"), Path("converted.wav")))
        self.assertEqual(queue.duration_ms, 12_000)

    def test_workspace_queue_falls_back_to_assigned_source_without_outputs(self) -> None:
        source_path = Path("song.m4a")
        work_song = SimpleNamespace(
            id="song-1",
            title="Assigned Song",
            kind="source",
            path=source_path,
        )
        window = SimpleNamespace(
            _playback_track_paths=lambda _scope: [],
            _duration_ms_for_paths=lambda paths: 42_000 if paths == [source_path] else 0,
            current_output_set=None,
            current_work_item=work_song,
        )

        queue = MainWindow._workspace_playback_queue(
            window,
            WorkspacePlaybackScope.SEPARATION,
        )

        self.assertIsNotNone(queue)
        self.assertEqual(queue.context, "output")
        self.assertEqual(queue.source_id, "source:song-1")
        self.assertEqual(queue.title, "Assigned Song")
        self.assertEqual(queue.paths, (source_path,))
        self.assertEqual(queue.volumes, (1.0,))
        self.assertEqual(queue.duration_ms, 42_000)
        self.assertEqual(queue.scope, "separation")

    def test_workspace_pages_map_to_their_playback_scope(self) -> None:
        window = SimpleNamespace()

        self.assertEqual(
            MainWindow._workspace_scope_for_page(window, PAGE_SEPARATION),
            WorkspacePlaybackScope.SEPARATION,
        )
        self.assertEqual(
            MainWindow._workspace_scope_for_page(window, PAGE_CONVERSION),
            WorkspacePlaybackScope.CONVERSION,
        )
        self.assertEqual(
            MainWindow._workspace_scope_for_page(window, PAGE_STUDIO),
            WorkspacePlaybackScope.STUDIO,
        )
        self.assertIsNone(MainWindow._workspace_scope_for_page(window, PAGE_LIBRARY))

    def test_playing_workspace_switch_replaces_only_the_page_sound_pool(self) -> None:
        separation_queue = PlaybackQueue(
            context="output",
            source_id="run-1",
            title="Separation Preview",
            paths=(Path("original.wav"), Path("instrumental.wav")),
            volumes=(1.0, 1.0),
            duration_ms=12_000,
            scope="separation",
        )
        conversion_queue = PlaybackQueue(
            context="output",
            source_id="run-1",
            title="Conversion Compare",
            paths=(Path("original.wav"), Path("converted.wav")),
            volumes=(1.0, 1.0),
            duration_ms=12_000,
            scope="conversion",
        )
        calls: list[tuple[str, object]] = []
        window = SimpleNamespace(
            current_playback_queue=separation_queue,
            player=SimpleNamespace(is_playing=lambda: True, position_ms=lambda: 4_500),
            _playback_position_ms=0,
            _current_playback_context=lambda: "output",
            _workspace_playback_queue=lambda scope: conversion_queue,
            _refresh_playback_ui=lambda **kwargs: calls.append(("ui", kwargs["is_playing"])),
            _update_output_playheads=lambda position, duration: calls.append(
                ("playhead", (position, duration))
            ),
            _play_current_queue=lambda position: calls.append(("play", position)),
        )

        MainWindow._refresh_output_playback_queue(
            window,
            WorkspacePlaybackScope.CONVERSION,
        )

        self.assertIs(window.current_playback_queue, conversion_queue)
        self.assertIn(("play", 4_500), calls)
        self.assertIn(("playhead", (4_500, 12_000)), calls)

    def test_output_playheads_update_only_the_active_workspace_surface(self) -> None:
        separation = _PlayheadTarget()
        conversion = _PlayheadTarget()
        studio_tracks = (_PlayheadTarget(), _PlayheadTarget(), _PlayheadTarget())
        queue = PlaybackQueue(
            context="output",
            source_id="run-1",
            title="Conversion Compare",
            paths=(Path("original.wav"), Path("converted.wav")),
            volumes=(1.0, 1.0),
            duration_ms=12_000,
            scope="conversion",
        )
        window = SimpleNamespace(
            current_playback_queue=queue,
            _current_playback_context=lambda: "output",
            _workspace_scope_for_queue=MainWindow._workspace_scope_for_queue,
            separation_results_panel=separation,
            vocal_results_panel=conversion,
            output_tracks=studio_tracks,
        )

        MainWindow._update_output_playheads(window, 3_000)

        self.assertEqual(separation.ratios, [])
        self.assertEqual(conversion.ratios, [0.25])
        self.assertEqual([track.ratios for track in studio_tracks], [[], [], []])

    def test_cleared_output_queue_resets_every_workspace_playhead(self) -> None:
        separation = _PlayheadTarget()
        conversion = _PlayheadTarget()
        studio_tracks = (_PlayheadTarget(), _PlayheadTarget(), _PlayheadTarget())
        window = SimpleNamespace(
            current_playback_queue=None,
            _current_playback_context=lambda: "",
            _workspace_scope_for_queue=MainWindow._workspace_scope_for_queue,
            separation_results_panel=separation,
            vocal_results_panel=conversion,
            output_tracks=studio_tracks,
        )

        MainWindow._update_output_playheads(window, 0, 0)

        self.assertEqual(separation.ratios, [0.0])
        self.assertEqual(conversion.ratios, [0.0])
        self.assertEqual([track.ratios for track in studio_tracks], [[0.0], [0.0], [0.0]])


if __name__ == "__main__":
    unittest.main()
