from __future__ import annotations

import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from PySide6.QtWidgets import QApplication, QLineEdit, QPushButton

from jang_app.qt_app.main_window import (
    MainWindow,
    PAGE_CONVERSION,
    PAGE_EXPORT,
    PAGE_LIBRARY,
    PAGE_MODELS,
    PAGE_STUDIO,
    PAGE_SEPARATION,
)
from jang_app.services.audio_export import AudioMixSource
from jang_app.services.playback_queue import PlaybackQueue
from jang_app.services.settings import AppSettings, StudioLayoutSettings
from jang_app.services.song_assets import SongAsset
from jang_app.services.workspace_playback import WorkspacePlaybackScope
from jang_app.services.video_source import VideoSource


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


class _LibraryAssetPlaybackTarget:
    def __init__(self) -> None:
        self.path: Path | None = None
        self.duration_ms = 0
        self.position: tuple[int, int] | None = None
        self.is_playing = False

    def set_preview_queue(self, path: Path, duration_ms: int) -> None:
        self.path = path
        self.duration_ms = duration_ms

    def set_preview_position(self, path: Path, position_ms: int, duration_ms: int) -> None:
        self.path = path
        self.position = (position_ms, duration_ms)

    def set_preview_playing(self, path: Path, is_playing: bool) -> None:
        self.path = path
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

    def test_space_shortcut_is_reserved_for_workspace_playback(self) -> None:
        button = QPushButton()
        line_edit = QLineEdit()

        self.assertTrue(
            MainWindow._workspace_space_shortcut_allowed(
                PAGE_CONVERSION,
                button,
                has_modal=False,
                has_popup=False,
            )
        )
        self.assertFalse(
            MainWindow._workspace_space_shortcut_allowed(
                PAGE_LIBRARY,
                button,
                has_modal=False,
                has_popup=False,
            )
        )
        self.assertFalse(
            MainWindow._workspace_space_shortcut_allowed(
                PAGE_STUDIO,
                line_edit,
                has_modal=False,
                has_popup=False,
            )
        )
        self.assertFalse(
            MainWindow._workspace_space_shortcut_allowed(
                PAGE_SEPARATION,
                button,
                has_modal=True,
                has_popup=False,
            )
        )
        button.close()
        line_edit.close()

    def test_studio_history_shortcuts_do_not_capture_input_fields(self) -> None:
        button = QPushButton()
        line_edit = QLineEdit()

        self.assertTrue(
            MainWindow._studio_history_shortcut_allowed(
                PAGE_STUDIO,
                button,
                has_modal=False,
                has_popup=False,
            )
        )
        self.assertFalse(
            MainWindow._studio_history_shortcut_allowed(
                PAGE_STUDIO,
                line_edit,
                has_modal=False,
                has_popup=False,
            )
        )
        self.assertFalse(
            MainWindow._studio_history_shortcut_allowed(
                PAGE_LIBRARY,
                button,
                has_modal=False,
                has_popup=False,
            )
        )
        button.close()
        line_edit.close()

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

    def test_navigation_rejects_workflow_page_without_a_work_song(self) -> None:
        calls: list[int] = []
        window = SimpleNamespace(
            current_work_item=None,
            page_stack=_PageStack(PAGE_LIBRARY),
            primary_navigation=SimpleNamespace(
                set_current_page=lambda index: calls.append(index)
            ),
        )

        MainWindow._navigate_to_page(window, PAGE_STUDIO)

        self.assertEqual(window.page_stack.currentIndex(), PAGE_LIBRARY)
        self.assertEqual(calls, [PAGE_LIBRARY])

    def test_navigation_allows_export_without_a_work_song(self) -> None:
        calls: list[tuple[str, int | None]] = []
        window = SimpleNamespace(
            current_work_item=None,
            page_stack=_PageStack(PAGE_LIBRARY),
            studio_session_autosave=SimpleNamespace(flush=lambda: None),
            model_workspace_page=SimpleNamespace(stop_preview=lambda: None),
            primary_navigation=SimpleNamespace(
                set_current_page=lambda index: calls.append(("navigation", index))
            ),
            _suspend_playback=lambda: calls.append(("suspend", None)),
            _refresh_export_page=lambda: calls.append(("export", None)),
            _sync_playback_queue_for_page=lambda index: calls.append(("queue", index)),
            _sync_playback_surfaces=lambda: None,
            _sync_video_workspace=lambda: None,
        )

        MainWindow._navigate_to_page(window, PAGE_EXPORT)

        self.assertEqual(window.page_stack.currentIndex(), PAGE_EXPORT)
        self.assertIn(("export", None), calls)

    def test_work_song_navigation_locks_pages_and_returns_to_library(self) -> None:
        states: list[tuple[int, bool, str]] = []
        navigated: list[int] = []
        window = SimpleNamespace(
            current_work_item=None,
            page_stack=_PageStack(PAGE_CONVERSION),
            primary_navigation=SimpleNamespace(
                set_page_enabled=lambda page_id, enabled, **kwargs: states.append(
                    (page_id, enabled, kwargs.get("disabled_tooltip", ""))
                )
            ),
            _navigate_to_page=lambda page_id: navigated.append(page_id),
        )

        MainWindow._sync_work_song_navigation(window)

        self.assertEqual(
            {page_id for page_id, enabled, _tooltip in states if not enabled},
            {PAGE_SEPARATION, PAGE_CONVERSION, PAGE_STUDIO},
        )
        self.assertIn((PAGE_EXPORT, True, ""), states)
        self.assertTrue(
            all(tooltip for page_id, enabled, tooltip in states if page_id != PAGE_EXPORT and not enabled)
        )
        self.assertEqual(navigated, [PAGE_LIBRARY])

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

    def test_each_vocal_page_resolves_its_own_result_transport(self) -> None:
        separation = object()
        conversion = object()
        window = SimpleNamespace(
            separation_transport_bar=separation,
            conversion_transport_bar=conversion,
        )

        self.assertIs(
            MainWindow._result_transport_for_scope(
                window, WorkspacePlaybackScope.SEPARATION
            ),
            separation,
        )
        self.assertIs(
            MainWindow._result_transport_for_scope(
                window, WorkspacePlaybackScope.CONVERSION
            ),
            conversion,
        )
        self.assertIsNone(
            MainWindow._result_transport_for_scope(
                window, WorkspacePlaybackScope.STUDIO
            )
        )

    def test_work_song_title_is_sent_to_both_result_headers(self) -> None:
        separation_titles: list[str] = []
        conversion_titles: list[str] = []
        window = SimpleNamespace(
            current_work_item=SimpleNamespace(title="Current Song"),
            separation_results_panel=SimpleNamespace(
                set_song_title=separation_titles.append
            ),
            vocal_results_panel=SimpleNamespace(
                set_song_title=conversion_titles.append
            ),
        )

        MainWindow._sync_result_song_titles(window)

        self.assertEqual(separation_titles, ["Current Song"])
        self.assertEqual(conversion_titles, ["Current Song"])

    def test_navigation_work_song_selection_uses_the_global_work_song_path(self) -> None:
        song = SimpleNamespace(id="song-1")
        selected: list[object] = []
        cleared: list[object] = []
        window = SimpleNamespace(
            _song_items_by_id={"song-1": song},
            _select_work_song=selected.append,
            _set_current_song=cleared.append,
            _sync_navigation_work_song_selector=lambda: self.fail(
                "known songs should not reset the selector"
            ),
        )

        MainWindow._on_navigation_work_song_changed(window, "song-1")
        MainWindow._on_navigation_work_song_changed(window, "")

        self.assertEqual(selected, [song])
        self.assertEqual(cleared, [None])

    def test_navigation_output_song_selection_uses_async_loading(self) -> None:
        song = SimpleNamespace(id="song-1", output_job_dir="output-job")
        started: list[object] = []
        window = SimpleNamespace(
            _song_items_by_id={"song-1": song},
            _work_song_load_worker=None,
            _start_library_work_song_load=started.append,
            _select_work_song=lambda _song: self.fail(
                "output songs should not load synchronously"
            ),
            _sync_navigation_work_song_selector=lambda: None,
        )

        MainWindow._on_navigation_work_song_changed(window, "song-1")

        self.assertEqual(started, [song])

    def test_entering_studio_prepares_surface_without_building_playback_queue(self) -> None:
        calls: list[tuple[str, int | None]] = []
        page_stack = _PageStack(PAGE_SEPARATION)
        window = SimpleNamespace(
            page_stack=page_stack,
            studio_session_autosave=SimpleNamespace(flush=lambda: None),
            model_workspace_page=SimpleNamespace(stop_preview=lambda: None),
            primary_navigation=SimpleNamespace(set_current_page=lambda _index: None),
            _suspend_playback=lambda: None,
            _refresh_export_page=lambda: None,
            _sync_playback_queue_for_page=lambda _index, **_kwargs: self.fail(
                "Studio navigation rendered a playback queue"
            ),
            _prepare_studio_playback_surface=lambda: calls.append(
                ("prepare", page_stack.currentIndex())
            ),
            _restore_current_studio_session=lambda: calls.append(
                ("restore", page_stack.currentIndex())
            ),
            _sync_playback_surfaces=lambda: None,
            _sync_video_workspace=lambda: None,
        )

        MainWindow._navigate_to_page(window, PAGE_STUDIO)

        self.assertEqual(
            calls,
            [("restore", PAGE_SEPARATION), ("prepare", PAGE_STUDIO)],
        )

    def test_video_source_defers_studio_session_loading_until_studio_is_visible(self) -> None:
        restored: list[bool] = []
        page_stack = _PageStack(PAGE_LIBRARY)
        window = SimpleNamespace(
            current_work_item=SimpleNamespace(
                id="song-1",
                source_url="",
                source_type="local",
            ),
            library=SimpleNamespace(managed_video_sources=lambda _song_id: ()),
            video_preview_panel=SimpleNamespace(set_source=lambda *_args, **_kwargs: None),
            page_stack=page_stack,
            studio_editor=object(),
            _is_loading_studio_session=False,
            _restore_current_studio_session=lambda: restored.append(True),
            _sync_video_workspace=lambda: None,
        )

        MainWindow._set_video_source(window, VideoSource(), enabled=True)
        self.assertEqual(restored, [])

        page_stack.setCurrentIndex(PAGE_STUDIO)
        MainWindow._set_video_source(window, VideoSource(), enabled=True)
        self.assertEqual(restored, [True])

    def test_studio_splitter_sizes_are_saved_as_layout_settings(self) -> None:
        window = SimpleNamespace(
            studio_workspace_splitter=SimpleNamespace(sizes=lambda: [220, 1_050, 310]),
            studio_center_splitter=SimpleNamespace(sizes=lambda: [410, 590]),
            settings=AppSettings(),
        )
        with patch("jang_app.qt_app.main_window.save_app_settings") as save:
            MainWindow._save_studio_layout(window)

        expected = StudioLayoutSettings(
            workspace_sizes=(220, 1_050, 310),
            center_sizes=(410, 590),
        )
        self.assertEqual(window.settings.studio_layout, expected)
        save.assert_called_once_with(window.settings)

    def test_library_queue_state_updates_only_the_expanded_row(self) -> None:
        separation = _WorkspacePlaybackTarget()
        conversion = _WorkspacePlaybackTarget()
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
            separation_transport_bar=separation,
            conversion_transport_bar=conversion,
            _playback_position_ms=15_000,
            _library_row=lambda _song_id: (None, preview),
            _sync_playback_surfaces=lambda: None,
            _sync_video_playback=lambda _is_playing: None,
        )

        MainWindow._refresh_playback_ui(window, is_playing=True)

        self.assertEqual(preview.position, (15_000, 90_000))
        self.assertEqual(separation.duration_ms, 0)
        self.assertIsNone(separation.position)
        self.assertTrue(preview.is_playing)
        self.assertFalse(separation.is_playing)

    def test_library_asset_queue_previews_only_the_selected_audio_file(self) -> None:
        source = Path(__file__).resolve()
        audio_path = source.with_suffix(".wav")
        window = SimpleNamespace(
            _duration_ms_for_paths=lambda paths: 42_000 if paths == [audio_path] else 0,
            library_status_label=None,
        )
        with patch.object(Path, "is_file", return_value=True):
            queue = MainWindow._library_asset_playback_queue(window, audio_path)

        self.assertIsNotNone(queue)
        self.assertEqual(queue.context, "library_asset")
        self.assertEqual(queue.source_id, str(audio_path))
        self.assertEqual(queue.paths, (audio_path,))
        self.assertEqual(queue.duration_ms, 42_000)

    def test_library_asset_queue_state_updates_the_inline_detail_player(self) -> None:
        separation = _WorkspacePlaybackTarget()
        conversion = _WorkspacePlaybackTarget()
        preview = _LibraryAssetPlaybackTarget()
        path = Path("mix.wav")
        queue = PlaybackQueue(
            context="library_asset",
            source_id=str(path),
            title="mix.wav",
            paths=(path,),
            volumes=(1.0,),
            duration_ms=90_000,
        )
        window = SimpleNamespace(
            current_playback_queue=queue,
            separation_transport_bar=separation,
            conversion_transport_bar=conversion,
            library_details_panel=preview,
            _playback_position_ms=15_000,
            _sync_playback_surfaces=lambda: None,
            _sync_video_playback=lambda _is_playing: None,
        )

        MainWindow._refresh_playback_ui(window, is_playing=True)

        self.assertEqual(preview.path, path)
        self.assertEqual(preview.position, (15_000, 90_000))
        self.assertTrue(preview.is_playing)
        self.assertEqual(separation.duration_ms, 0)

    def test_output_queue_updates_only_its_page_result_transport(self) -> None:
        separation = _WorkspacePlaybackTarget()
        conversion = _WorkspacePlaybackTarget()
        queue = PlaybackQueue(
            context="output",
            source_id="separation:run-1",
            title="Separation",
            paths=(Path("vocals.wav"),),
            volumes=(1.0,),
            duration_ms=90_000,
            scope=WorkspacePlaybackScope.SEPARATION.value,
        )
        window = SimpleNamespace(
            current_playback_queue=queue,
            separation_transport_bar=separation,
            conversion_transport_bar=conversion,
            _playback_position_ms=15_000,
            _workspace_scope_for_queue=MainWindow._workspace_scope_for_queue,
            _sync_playback_surfaces=lambda: None,
            _sync_video_playback=lambda _is_playing: None,
        )

        MainWindow._refresh_playback_ui(window, is_playing=True)

        self.assertEqual(separation.duration_ms, 90_000)
        self.assertEqual(separation.position, (15_000, 90_000))
        self.assertTrue(separation.is_playing)
        self.assertEqual(conversion.duration_ms, 0)

    def test_switching_output_scope_clears_the_previous_result_transport(self) -> None:
        separation = _WorkspacePlaybackTarget()
        conversion = _WorkspacePlaybackTarget()
        separation.set_queue(90_000)
        separation.set_position(15_000, 90_000)
        separation.set_playing(True)
        queue = PlaybackQueue(
            context="output",
            source_id="conversion:run-2",
            title="Conversion",
            paths=(Path("converted.wav"),),
            volumes=(1.0,),
            duration_ms=75_000,
            scope=WorkspacePlaybackScope.CONVERSION.value,
        )
        window = SimpleNamespace(
            current_playback_queue=queue,
            separation_transport_bar=separation,
            conversion_transport_bar=conversion,
            _playback_position_ms=8_000,
            _workspace_scope_for_queue=MainWindow._workspace_scope_for_queue,
            _sync_playback_surfaces=lambda: None,
            _sync_video_playback=lambda _is_playing: None,
        )

        MainWindow._refresh_playback_ui(window, is_playing=True)

        self.assertEqual(separation.duration_ms, 0)
        self.assertIsNone(separation.position)
        self.assertFalse(separation.is_playing)
        self.assertEqual(conversion.position, (8_000, 75_000))
        self.assertTrue(conversion.is_playing)

    def test_bulk_library_removal_uses_one_confirmation_and_one_execution(self) -> None:
        first = SongAsset(
            "export",
            "Exported Asset",
            Path("first.wav"),
            removal_scope="file",
        )
        second = SongAsset(
            "export",
            "Exported Asset",
            Path("second.wav"),
            removal_scope="file",
        )
        calls: list[tuple[str, tuple[SongAsset, ...]]] = []
        window = SimpleNamespace(
            _song_items_by_id={"song-1": object()},
            settings=AppSettings(),
            _execute_library_asset_removal=lambda song_id, assets: calls.append(
                (song_id, assets)
            ),
        )

        with patch(
            "jang_app.qt_app.main_window.ConfirmationDialog.confirm",
            return_value=True,
        ) as confirm:
            MainWindow._remove_library_assets(window, "song-1", (first, second))

        confirm.assert_called_once()
        self.assertEqual(calls, [("song-1", (first, second))])

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
            [Path("original.wav"), Path("instrumental.wav"), Path("converted.wav")],
        )
        self.assertEqual(
            [path for path, _volume in studio],
            [Path("original.wav"), Path("instrumental.wav"), Path("converted.wav")],
        )

    def test_separation_scope_uses_independently_selected_stem_paths(self) -> None:
        def track(path: str, volume: float):
            return SimpleNamespace(
                current_path=lambda: Path(path),
                is_muted=lambda: False,
                volume=lambda: volume,
            )

        tracks = {
            "original": track("active-vocal.wav", 0.8),
            "instrumental": track("active-instrumental.wav", 0.7),
            "converted": track("converted.wav", 1.0),
        }
        window = SimpleNamespace(
            _output_track=lambda track_id: tracks.get(track_id),
            _separation_preview_paths={
                "original": Path("precision-vocal.wav"),
                "instrumental": Path("fast-instrumental.wav"),
            },
        )

        separation = MainWindow._playback_track_paths(
            window,
            WorkspacePlaybackScope.SEPARATION,
        )
        conversion = MainWindow._playback_track_paths(
            window,
            WorkspacePlaybackScope.CONVERSION,
        )

        self.assertEqual(
            separation,
            [
                (Path("precision-vocal.wav"), 0.8),
                (Path("fast-instrumental.wav"), 0.7),
            ],
        )
        self.assertEqual(
            conversion,
            [
                (Path("active-vocal.wav"), 0.8),
                (Path("active-instrumental.wav"), 0.7),
                (Path("converted.wav"), 1.0),
            ],
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
        self.assertEqual(
            queue.paths,
            (Path("original.wav"), Path("instrumental.wav"), Path("converted.wav")),
        )
        self.assertEqual(queue.duration_ms, 12_000)

    def test_conversion_scope_uses_the_three_visible_result_tracks(self) -> None:
        visible_tracks = (
            (Path("original.wav"), 0.0),
            (Path("instrumental.wav"), 0.8),
            (Path("converted.wav"), 1.0),
        )
        window = SimpleNamespace(
            vocal_results_panel=SimpleNamespace(playback_tracks=lambda: visible_tracks),
        )

        conversion = MainWindow._playback_track_paths(
            window,
            WorkspacePlaybackScope.CONVERSION,
        )

        self.assertEqual(conversion, list(visible_tracks))

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

    def test_unedited_studio_sources_can_play_without_rendering_a_preview(self) -> None:
        sources = (
            AudioMixSource("Vocal", Path("vocal.wav"), 1.0, source_end_ms=12_000),
            AudioMixSource("Music", Path("music.wav"), 0.8, source_end_ms=12_000),
        )

        with patch(
            "jang_app.qt_app.main_window.read_audio_metadata",
            return_value=SimpleNamespace(duration_ms=12_000),
        ):
            duration = MainWindow._direct_studio_preview_duration(sources)

        self.assertEqual(duration, 12_000)

    def test_edited_studio_sources_require_a_rendered_preview(self) -> None:
        moved = (
            AudioMixSource(
                "Vocal",
                Path("vocal.wav"),
                1.0,
                timeline_start_ms=500,
                source_end_ms=12_000,
            ),
        )
        trimmed = (
            AudioMixSource(
                "Vocal",
                Path("vocal.wav"),
                1.0,
                source_start_ms=250,
                source_end_ms=11_000,
            ),
        )

        self.assertEqual(MainWindow._direct_studio_preview_duration(moved), 0)
        self.assertEqual(MainWindow._direct_studio_preview_duration(trimmed), 0)

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

    def test_studio_volume_refresh_updates_live_player_without_stopping(self) -> None:
        current_queue = PlaybackQueue(
            context="output",
            source_id="studio:song-1",
            title="Studio Mix",
            paths=(Path("vocal.wav"), Path("music.wav")),
            volumes=(1.0, 1.0),
            duration_ms=12_000,
            scope="studio",
        )
        refreshed_queue = PlaybackQueue(
            context="output",
            source_id="studio:song-1",
            title="Studio Mix",
            paths=current_queue.paths,
            volumes=(0.4, 1.0),
            duration_ms=12_000,
            scope="studio",
        )
        calls: list[tuple[str, object]] = []
        window = SimpleNamespace(
            current_playback_queue=current_queue,
            player=SimpleNamespace(
                is_playing=lambda: True,
                position_ms=lambda: 4_500,
                set_volumes=lambda volumes: calls.append(("volumes", volumes)),
            ),
            _playback_position_ms=0,
            _current_playback_context=lambda: "output",
            _workspace_playback_queue=lambda _scope: refreshed_queue,
            _refresh_playback_ui=lambda **_kwargs: None,
            _update_output_playheads=lambda _position, _duration: None,
            _play_current_queue=lambda position: calls.append(("play", position)),
        )

        MainWindow._refresh_output_playback_queue(window, WorkspacePlaybackScope.STUDIO)

        self.assertEqual(calls, [("volumes", (0.4, 1.0))])
        self.assertIs(window.current_playback_queue, refreshed_queue)
        self.assertEqual(window._playback_position_ms, 4_500)

    def test_rendered_studio_refresh_reloads_audio_at_current_position(self) -> None:
        current_queue = PlaybackQueue(
            context="output",
            source_id="studio:song-1",
            title="Studio Mix",
            paths=(Path("studio-preview.wav"),),
            volumes=(1.0,),
            duration_ms=12_000,
            scope="studio",
            reload_on_refresh=True,
        )
        refreshed_queue = current_queue.with_duration(12_500)
        calls: list[tuple[str, object]] = []
        window = SimpleNamespace(
            current_playback_queue=current_queue,
            player=SimpleNamespace(
                is_playing=lambda: True,
                position_ms=lambda: 4_500,
                set_volumes=lambda _volumes: self.fail("rendered audio must be reloaded"),
            ),
            _playback_position_ms=0,
            _current_playback_context=lambda: "output",
            _workspace_playback_queue=lambda _scope: refreshed_queue,
            _refresh_playback_ui=lambda **_kwargs: None,
            _update_output_playheads=lambda _position, _duration: None,
            _play_current_queue=lambda position: calls.append(("play", position)),
        )

        MainWindow._refresh_output_playback_queue(window, WorkspacePlaybackScope.STUDIO)

        self.assertEqual(calls, [("play", 4_500)])
        self.assertTrue(window.current_playback_queue.reload_on_refresh)

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
