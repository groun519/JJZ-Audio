from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import numpy as np
import soundfile as sf
from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QApplication, QVBoxLayout, QWidget

from jang_app.qt_app.studio_editor import StudioEditor, StudioTimelineView, _WAVEFORM_EXECUTOR
from jang_app.qt_app.waveform_thumbnail import (
    _WAVEFORM_EXECUTOR as _THUMBNAIL_WAVEFORM_EXECUTOR,
)
from jang_app.services.studio_assets import StudioSoundAsset
from jang_app.services.studio_session import (
    TRACK_ORIGINAL_VOCAL,
    TRACK_VIDEO,
    StudioAssetRef,
    StudioClip,
    StudioEffect,
    StudioSession,
    StudioTrack,
)


class StudioEditorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_sound_pool_drop_adds_non_destructive_clip_at_target_position(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            asset = _asset(Path(temporary))
            editor = StudioEditor()
            editor.set_context(_session(), (asset,))
            changed = QSignalSpy(editor.session_changed)
            source_before = asset.path.read_bytes()

            editor._drop_asset(asset.asset_id, "track-original-vocal", 2_500)

            self.assertEqual(changed.count(), 1)
            clips = editor.session().tracks[0].clips
            self.assertEqual(len(clips), 2)
            self.assertEqual(clips[-1].timeline_start_ms, 2_500)
            self.assertEqual(asset.path.read_bytes(), source_before)

    def test_committed_session_marks_only_rendering_changes_as_structural(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            asset = _asset(Path(temporary))
            editor = StudioEditor()
            editor.set_context(_session(), (asset,))
            committed = QSignalSpy(editor.session_committed)

            editor._set_track_mix("track-original-vocal", False, False, 72)
            editor._move_clip("clip-1", "track-original-vocal", 500)

            self.assertEqual(committed.count(), 2)
            self.assertFalse(committed.at(0)[1])
            self.assertTrue(committed.at(1)[1])
            editor.close()

    def test_reverb_changes_use_the_realtime_playback_path(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            asset = _asset(Path(temporary))
            editor = StudioEditor()
            editor.set_context(_session(), (asset,))
            editor._drop_effect("reverb", "clip-1")
            committed = QSignalSpy(editor.session_committed)
            effect = editor.session().tracks[0].clips[0].effects[0]

            editor._update_effect(
                "clip-1",
                replace(
                    effect,
                    reverb=replace(effect.reverb, dry_wet_percent=64),
                ),
            )

            self.assertEqual(committed.count(), 1)
            self.assertFalse(committed.at(0)[1])
            editor.close()

    def test_reverb_drop_targets_one_clip_and_is_undoable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            asset = _asset(Path(temporary))
            editor = StudioEditor()
            editor.set_context(_session(), (asset,))
            changed = QSignalSpy(editor.session_changed)

            editor._drop_effect("reverb", "clip-1")

            effect = editor.session().tracks[0].clips[0].effects[0]
            self.assertEqual(effect.kind, "reverb")
            self.assertEqual(changed.count(), 1)
            self.assertTrue(editor.undo())
            self.assertEqual(editor.session().tracks[0].clips[0].effects, ())
            self.assertTrue(editor.redo())
            self.assertEqual(editor.session().tracks[0].clips[0].effects, (effect,))
            editor.close()

    def test_inspector_updates_and_removes_reverb_as_undoable_edits(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            asset = _asset(Path(temporary))
            editor = StudioEditor()
            editor.set_context(_session(), (asset,))
            editor._drop_effect("reverb", "clip-1")
            effect = editor.session().tracks[0].clips[0].effects[0]
            updated = replace(
                effect,
                reverb=replace(effect.reverb, dry_wet_percent=62),
            )

            editor._update_effect("clip-1", updated)
            editor._remove_effect("clip-1", updated.effect_id)

            self.assertEqual(editor.session().tracks[0].clips[0].effects, ())
            self.assertTrue(editor.undo())
            self.assertEqual(editor.session().tracks[0].clips[0].effects, (updated,))
            self.assertTrue(editor.undo())
            self.assertEqual(editor.session().tracks[0].clips[0].effects, (effect,))
            editor.close()

    def test_studio_left_sidebar_contains_sound_and_fx_pools(self) -> None:
        editor = StudioEditor(include_sidebars=False)

        self.assertEqual(editor.left_sidebar.count(), 2)
        self.assertIs(editor.left_sidebar.widget(0), editor.sound_pool)
        self.assertIs(editor.left_sidebar.widget(1), editor.fx_pool)
        self.assertFalse(editor.fx_pool.isHidden())
        editor.close()

    def test_timeline_effect_chip_remains_addressable_on_short_clips(self) -> None:
        effect = StudioEffect("fx-reverb", "reverb")
        clip = StudioClip(
            "clip-short",
            StudioAssetRef("output-1", TRACK_ORIGINAL_VOCAL),
            0,
            0,
            100,
            effects=(effect,),
        )
        track = StudioTrack(
            "track-original-vocal",
            "Original Vocal",
            TRACK_ORIGINAL_VOCAL,
            clips=(clip,),
        )
        timeline = StudioTimelineView()
        timeline.set_context(StudioSession(tracks=(track,)), ())

        regions = timeline._effect_chip_rects(clip, 0)

        self.assertEqual(len(regions), 1)
        self.assertEqual(regions[0][0].effect_id, effect.effect_id)
        self.assertTrue(timeline._clip_rect(clip, 0).contains(regions[0][1].center()))

    def test_clip_follows_pointer_before_release_and_commits_once(self) -> None:
        timeline = StudioTimelineView()
        timeline.set_zoom(24)
        timeline.set_context(_session(), ())
        moved = QSignalSpy(timeline.clip_moved)
        clip = _session().tracks[0].clips[0]
        start = timeline._clip_rect(clip, 0).center()
        destination = QPointF(start.x() + 48, start.y())

        timeline.mousePressEvent(
            QMouseEvent(
                QEvent.Type.MouseButtonPress,
                start,
                start,
                Qt.MouseButton.LeftButton,
                Qt.MouseButton.LeftButton,
                Qt.KeyboardModifier.NoModifier,
            )
        )
        timeline.mouseMoveEvent(
            QMouseEvent(
                QEvent.Type.MouseMove,
                destination,
                destination,
                Qt.MouseButton.NoButton,
                Qt.MouseButton.LeftButton,
                Qt.KeyboardModifier.NoModifier,
            )
        )

        self.assertIsNotNone(timeline._drag_clip)
        self.assertEqual(timeline._drag_clip.timeline_start_ms, 2_000)
        self.assertEqual(timeline._session.tracks[0].clips[0].timeline_start_ms, 0)
        self.assertEqual(moved.count(), 0)

        timeline.mouseReleaseEvent(
            QMouseEvent(
                QEvent.Type.MouseButtonRelease,
                destination,
                destination,
                Qt.MouseButton.LeftButton,
                Qt.MouseButton.NoButton,
                Qt.KeyboardModifier.NoModifier,
            )
        )

        self.assertEqual(moved.count(), 1)
        self.assertEqual(moved.at(0), ["clip-1", "track-original-vocal", 2_000])

    def test_click_without_drag_does_not_commit_a_clip_move(self) -> None:
        timeline = StudioTimelineView()
        timeline.set_context(_session(), ())
        moved = QSignalSpy(timeline.clip_moved)
        clip = _session().tracks[0].clips[0]
        position = timeline._clip_rect(clip, 0).center()

        timeline.mousePressEvent(
            QMouseEvent(
                QEvent.Type.MouseButtonPress,
                position,
                position,
                Qt.MouseButton.LeftButton,
                Qt.MouseButton.LeftButton,
                Qt.KeyboardModifier.NoModifier,
            )
        )
        timeline.mouseReleaseEvent(
            QMouseEvent(
                QEvent.Type.MouseButtonRelease,
                position,
                position,
                Qt.MouseButton.LeftButton,
                Qt.MouseButton.NoButton,
                Qt.KeyboardModifier.NoModifier,
            )
        )

        self.assertEqual(moved.count(), 0)

    def test_effect_drop_target_is_the_exact_audio_clip_under_pointer(self) -> None:
        timeline = StudioTimelineView()
        session = _session()
        timeline.set_context(session, ())
        clip = session.tracks[0].clips[0]
        clip_center = timeline._clip_rect(clip, 0).center().toPoint()

        target = timeline._effect_drop_target(clip_center)

        self.assertEqual(target.clip_id, clip.clip_id)
        self.assertIsNone(timeline._effect_drop_target(QPoint(4, 4)))

    def test_inspector_values_update_clip_without_rendering_a_new_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            asset = _asset(Path(temporary))
            editor = StudioEditor()
            editor.set_context(_session(), (asset,))
            source_before = asset.path.read_bytes()

            editor._set_clip_values("clip-1", 3_000, 250, 1_250, -3)

            clip = editor.session().tracks[0].clips[0]
            self.assertEqual(
                (clip.timeline_start_ms, clip.source_start_ms, clip.source_end_ms, clip.gain_db),
                (3_000, 250, 1_250, -3.0),
            )
            self.assertEqual(asset.path.read_bytes(), source_before)

    def test_inspector_mix_edit_is_restored_as_one_complete_undo_step(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            asset = _asset(Path(temporary))
            editor = StudioEditor()
            editor.set_context(_session(), (asset,))

            editor._set_clip_values("clip-1", 500, 100, 1_600, -2.5, True, 200, 300)

            edited = editor.session().tracks[0].clips[0]
            self.assertEqual(
                (
                    edited.timeline_start_ms,
                    edited.source_start_ms,
                    edited.source_end_ms,
                    edited.gain_db,
                    edited.muted,
                    edited.fade_in_ms,
                    edited.fade_out_ms,
                ),
                (500, 100, 1_600, -2.5, True, 200, 300),
            )
            self.assertTrue(editor.undo())
            self.assertEqual(editor.session(), _session())

    def test_delete_and_backspace_remove_selected_clip_as_undoable_edits(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            asset = _asset(Path(temporary))
            editor = StudioEditor()
            with (
                patch.object(_WAVEFORM_EXECUTOR, "submit"),
                patch.object(_THUMBNAIL_WAVEFORM_EXECUTOR, "submit"),
            ):
                editor.set_context(_session(), (asset,))
                editor.show()
                self.app.processEvents()

                for key in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
                    with self.subTest(key=key):
                        editor.timeline.select_clip("clip-1")
                        editor.timeline.setFocus()
                        QTest.keyClick(editor.timeline, key)
                        self.assertEqual(editor.session().tracks[0].clips, ())
                        self.assertTrue(editor.undo())
                        self.assertEqual(editor.session(), _session())

            editor.close()

    def test_clip_delete_shortcuts_do_not_override_inspector_field_editing(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            asset = _asset(Path(temporary))
            editor = StudioEditor()
            with (
                patch.object(_WAVEFORM_EXECUTOR, "submit"),
                patch.object(_THUMBNAIL_WAVEFORM_EXECUTOR, "submit"),
            ):
                editor.set_context(_session(), (asset,))
                editor.timeline.select_clip("clip-1")
                editor.show()
                self.app.processEvents()

                editor.inspector.gain_spin.setFocus()
                QTest.keyClick(editor.inspector.gain_spin, Qt.Key.Key_Backspace)

            self.assertEqual(len(editor.session().tracks[0].clips), 1)
            editor.close()

    def test_expanded_track_title_occupies_a_separate_row_from_mix_controls(self) -> None:
        timeline = StudioTimelineView()
        track = _session().tracks[0]
        timeline.set_context(StudioSession(tracks=(track,)), ())

        title_rect = timeline._track_title_rect(track, 0)
        mute_rect, volume_rect, value_rect = timeline._track_control_rects(0)

        self.assertLessEqual(title_rect.bottom(), mute_rect.top())
        self.assertFalse(title_rect.intersects(volume_rect))
        self.assertFalse(title_rect.intersects(value_rect))
        self.assertLessEqual(title_rect.right(), timeline._track_collapse_rect(0).left())

        added_track = StudioTrack("track-audio", "Additional Audio")
        timeline.set_context(StudioSession(tracks=(added_track,)), ())
        added_title_rect = timeline._track_title_rect(added_track, 0)
        self.assertLessEqual(added_title_rect.right(), timeline._track_collapse_rect(0).left())

    def test_cut_tool_splits_clip_at_clicked_position_and_stays_active(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            asset = _asset(Path(temporary))
            editor = StudioEditor()
            source_before = asset.path.read_bytes()
            availability = QSignalSpy(editor.split_tool_available_changed)
            mode_changed = QSignalSpy(editor.split_mode_changed)
            changed = QSignalSpy(editor.session_changed)
            with (
                patch.object(_WAVEFORM_EXECUTOR, "submit"),
                patch.object(_THUMBNAIL_WAVEFORM_EXECUTOR, "submit"),
            ):
                editor.resize(1_200, 640)
                editor.set_context(_session(), (asset,))
                editor.set_zoom(24)
                editor.show()
                self.app.processEvents()
                editor.set_split_mode(True)
                first_cut = QPoint(
                    round(editor.timeline._ms_to_x(1_000)),
                    editor.timeline.RULER_HEIGHT + editor.timeline.LANE_HEIGHT // 2,
                )
                QTest.mouseClick(
                    editor.timeline,
                    Qt.MouseButton.LeftButton,
                    pos=first_cut,
                )
                second_cut = QPoint(
                    round(editor.timeline._ms_to_x(1_500)),
                    editor.timeline.RULER_HEIGHT + editor.timeline.LANE_HEIGHT // 2,
                )
                QTest.mouseClick(
                    editor.timeline,
                    Qt.MouseButton.LeftButton,
                    pos=second_cut,
                )

            first, second, third = editor.session().tracks[0].clips
            self.assertEqual((first.source_start_ms, first.source_end_ms), (0, 1_000))
            self.assertEqual((second.source_start_ms, second.source_end_ms), (1_000, 1_500))
            self.assertEqual((third.source_start_ms, third.source_end_ms), (1_500, 2_000))
            self.assertEqual(
                (first.timeline_start_ms, second.timeline_start_ms, third.timeline_start_ms),
                (0, 1_000, 1_500),
            )
            self.assertEqual(asset.path.read_bytes(), source_before)
            self.assertEqual(changed.count(), 2)
            self.assertEqual(availability.count(), 1)
            self.assertTrue(mode_changed.at(0)[0])
            self.assertTrue(editor._split_mode)
            self.assertTrue(editor.timeline._split_mode)
            self.assertEqual(editor._playhead_ms, 1_500)
            editor.close()

    def test_adding_at_playhead_keeps_existing_clips_in_place(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            asset = _asset(Path(temporary))
            editor = StudioEditor()
            editor.set_context(_session(), (asset,))
            editor._drop_asset(asset.asset_id, "track-original-vocal", 0)

            clips = editor.session().tracks[0].clips
            original = next(clip for clip in clips if clip.clip_id == "clip-1")
            self.assertEqual(original.timeline_start_ms, 0)
            self.assertEqual([clip.timeline_start_ms for clip in clips], [0, 0])

    def test_add_track_row_appends_and_selects_an_empty_track(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            asset = _asset(Path(temporary))
            editor = StudioEditor()
            editor.set_context(_session(), (asset,))
            with (
                patch.object(_WAVEFORM_EXECUTOR, "submit"),
                patch.object(_THUMBNAIL_WAVEFORM_EXECUTOR, "submit"),
            ):
                editor.show()
                self.app.processEvents()
                add_rect = editor.timeline._add_track_rect()

                QTest.mouseClick(
                    editor.timeline,
                    Qt.MouseButton.LeftButton,
                    pos=QPoint(round(add_rect.center().x()), round(add_rect.center().y())),
                )

            self.assertEqual(len(editor.session().tracks), 2)
            self.assertEqual(editor.session().tracks[-1].clips, ())
            self.assertEqual(editor.timeline.selected_track_id(), editor.session().tracks[-1].track_id)
            editor.close()

    def test_hover_remove_deletes_track_and_undo_redo_restore_complete_state(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            asset = _asset(Path(temporary))
            source_before = asset.path.read_bytes()
            first_track = _session().tracks[0]
            second_clip = StudioClip("clip-2", asset.reference, 120_000, 250, 1_750)
            second_track = StudioTrack(
                "track-audio-2",
                "Audio 2",
                clips=(second_clip,),
            )
            editor = StudioEditor(include_sidebars=False)
            editor.resize(720, 520)
            availability = QSignalSpy(editor.history_availability_changed)
            changed = QSignalSpy(editor.session_changed)
            with (
                patch.object(_WAVEFORM_EXECUTOR, "submit"),
                patch.object(_THUMBNAIL_WAVEFORM_EXECUTOR, "submit"),
            ):
                editor.set_context(StudioSession(tracks=(first_track, second_track)), (asset,))
                editor.set_zoom(24)
                editor.show()
                self.app.processEvents()
                horizontal_scroll = editor.timeline_scroll.horizontalScrollBar()
                horizontal_scroll.setValue(min(600, horizontal_scroll.maximum()))
                self.app.processEvents()

                self.assertGreater(horizontal_scroll.value(), 0)
                remove_rect = editor.timeline._track_remove_rect(1)
                collapse_rect = editor.timeline._track_collapse_rect(1)
                mute_rect, _volume_rect, _value_rect = editor.timeline._track_control_rects(1)
                self.assertEqual(
                    round(remove_rect.left() - horizontal_scroll.value()),
                    editor.timeline.HEADER_WIDTH - 72,
                )
                self.assertLess(remove_rect.left(), collapse_rect.left())
                self.assertEqual(round(mute_rect.left() - horizontal_scroll.value()), 12)
                hover_position = QPointF(remove_rect.center())
                QApplication.sendEvent(
                    editor.timeline,
                    QMouseEvent(
                        QEvent.Type.MouseMove,
                        hover_position,
                        hover_position,
                        Qt.MouseButton.NoButton,
                        Qt.MouseButton.NoButton,
                        Qt.KeyboardModifier.NoModifier,
                    ),
                )
                self.app.processEvents()

                self.assertEqual(editor.timeline._hover_track_id, second_track.track_id)
                QTest.mouseClick(
                    editor.timeline,
                    Qt.MouseButton.LeftButton,
                    pos=QPoint(round(remove_rect.center().x()), round(remove_rect.center().y())),
                )

            self.assertEqual(editor.session().tracks, (first_track,))
            self.assertEqual(changed.count(), 1)
            self.assertEqual(tuple(availability.at(0)), (True, False))

            self.assertTrue(editor.undo())
            self.assertEqual(editor.session().tracks, (first_track, second_track))
            self.assertEqual(tuple(availability.at(1)), (False, True))

            self.assertTrue(editor.redo())
            self.assertEqual(editor.session().tracks, (first_track,))
            self.assertEqual(tuple(availability.at(2)), (True, False))
            self.assertEqual(changed.count(), 3)
            self.assertEqual(asset.path.read_bytes(), source_before)
            editor.close()

    def test_drop_target_added_track_receives_sound_pool_assets(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            asset = _asset(Path(temporary))
            editor = StudioEditor()
            editor.set_context(_session(), (asset,))
            editor._add_track()

            target_track = editor.session().tracks[-1]
            editor._drop_asset(asset.asset_id, target_track.track_id, 0)

            self.assertEqual(len(editor.session().tracks[0].clips), 1)
            self.assertEqual(len(editor.session().tracks[-1].clips), 1)

    def test_collapsing_track_reduces_lane_height_without_removing_clips(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            asset = _asset(Path(temporary))
            editor = StudioEditor(include_sidebars=False)
            editor.set_context(_session(), (asset,))
            expanded_bottom = editor.timeline._add_track_rect().top()

            editor._set_track_collapsed("track-original-vocal", True)

            track = editor.session().tracks[0]
            self.assertTrue(track.collapsed)
            self.assertEqual(len(track.clips), 1)
            self.assertEqual(
                expanded_bottom - editor.timeline._add_track_rect().top(),
                editor.timeline.LANE_HEIGHT - editor.timeline.COLLAPSED_LANE_HEIGHT,
            )

    def test_fixed_and_added_tracks_share_hover_feedback_but_only_added_tracks_remove(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            asset = _asset(Path(temporary))
            fixed = _session().tracks[0]
            added = StudioTrack("track-audio-2", "Audio 2")
            second_added = StudioTrack("track-audio-3", "Audio 3")
            editor = StudioEditor(include_sidebars=False)
            editor.set_context(StudioSession(tracks=(fixed, added, second_added)), (asset,))

            fixed_point = QPoint(20, editor.timeline.RULER_HEIGHT + 10)
            editor.timeline._update_cursor(fixed_point)

            self.assertEqual(editor.timeline._hover_track_id, fixed.track_id)
            self.assertFalse(editor.timeline._is_first_added_track(0))
            self.assertTrue(editor.timeline._is_first_added_track(1))
            self.assertFalse(editor.timeline._is_first_added_track(2))
            self.assertIsNone(editor.timeline._track_control_at(fixed_point))

            added_point = QPoint(
                round(editor.timeline._track_remove_rect(1).center().x()),
                round(editor.timeline._track_remove_rect(1).center().y()),
            )
            editor.timeline._update_cursor(added_point)
            control = editor.timeline._track_control_at(added_point)
            self.assertIsNotNone(control)
            self.assertEqual(control[1], "remove")
            editor.close()

    def test_timeline_ruler_stays_at_viewport_top_while_tracks_scroll(self) -> None:
        tracks = tuple(
            StudioTrack(f"track-{index}", f"Track {index}")
            for index in range(8)
        )
        editor = StudioEditor(include_sidebars=False)
        editor.resize(720, 360)
        editor.set_context(StudioSession(tracks=tracks), ())
        editor.show()
        self.app.processEvents()

        vertical_scroll = editor.timeline_scroll.verticalScrollBar()
        self.assertGreater(vertical_scroll.maximum(), 0)
        vertical_scroll.setValue(min(180, vertical_scroll.maximum()))
        self.app.processEvents()

        ruler_top = editor.timeline._ruler_top()
        self.assertEqual(ruler_top, vertical_scroll.value())
        self.assertTrue(editor.timeline._point_in_ruler(ruler_top + 1))
        self.assertIsNone(editor.timeline._track_at_y(ruler_top + 1))
        editor.close()

    def test_showing_editor_keeps_all_dynamic_children_parented(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            asset = _asset(Path(temporary))
            host = QWidget()
            layout = QVBoxLayout(host)
            editor = StudioEditor()
            layout.addWidget(editor)
            with (
                patch("jang_app.qt_app.studio_editor.build_waveform_peaks", return_value=[]),
                patch.object(_THUMBNAIL_WAVEFORM_EXECUTOR, "submit"),
            ):
                editor.set_context(_session(), (asset,))
                host.show()
                self.app.processEvents()

            child_windows = [child for child in editor.findChildren(QWidget) if child.isWindow()]
            host.close()

            self.assertEqual(child_windows, [])

    def test_detached_sidebar_mode_keeps_panels_parented_until_workspace_mounts_them(self) -> None:
        editor = StudioEditor(include_sidebars=False)

        self.assertIs(editor.left_sidebar.parentWidget(), editor)
        self.assertIs(editor.sound_pool.parentWidget(), editor.left_sidebar)
        self.assertIs(editor.fx_pool.parentWidget(), editor.left_sidebar)
        self.assertIs(editor.inspector_scroll.parentWidget(), editor)
        self.assertIs(editor.timeline_panel.parentWidget(), editor)
        self.assertIsNone(editor.workspace_splitter)

    def test_waveforms_are_deferred_until_visible_and_only_load_timeline_assets(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            referenced = _asset(root)
            unused_path = root / "unused.wav"
            sf.write(unused_path, np.full(8_000, 0.1, dtype=np.float32), 8_000)
            unused = StudioSoundAsset(
                StudioAssetRef("output-2", TRACK_ORIGINAL_VOCAL),
                "Unused",
                unused_path,
                1_000,
            )
            editor = StudioEditor()

            with (
                patch.object(_WAVEFORM_EXECUTOR, "submit") as timeline_submit,
                patch.object(_THUMBNAIL_WAVEFORM_EXECUTOR, "submit") as thumbnail_submit,
            ):
                editor.set_context(_session(), (referenced, unused))
                self.assertEqual(timeline_submit.call_count, 0)
                self.assertEqual(thumbnail_submit.call_count, 0)
                editor.resize(1_200, 640)
                editor.show()
                QTest.qWait(180)

            editor.close()
            self.assertEqual(timeline_submit.call_count, 1)
            self.assertEqual(timeline_submit.call_args.args[1], referenced.path)
            self.assertGreaterEqual(thumbnail_submit.call_count, 1)

    def test_timeline_track_controls_update_mute_and_volume(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            asset = _asset(Path(temporary))
            editor = StudioEditor()
            editor.resize(1_200, 640)
            editor.set_context(_session(), (asset,))
            with (
                patch.object(_WAVEFORM_EXECUTOR, "submit"),
                patch.object(_THUMBNAIL_WAVEFORM_EXECUTOR, "submit"),
            ):
                editor.show()
                self.app.processEvents()
                changed = QSignalSpy(editor.session_changed)

                mute_rect, volume_rect, _value_rect = editor.timeline._track_control_rects(0)
                QTest.mouseClick(
                    editor.timeline,
                    Qt.MouseButton.LeftButton,
                    pos=QPoint(round(mute_rect.center().x()), round(mute_rect.center().y())),
                )
                volume_rail = volume_rect.adjusted(7, 0, -7, 0)
                volume_position = QPoint(
                    round(volume_rail.left() + volume_rail.width() * 0.75),
                    round(volume_rect.center().y()),
                )
                QTest.mouseClick(
                    editor.timeline,
                    Qt.MouseButton.LeftButton,
                    pos=volume_position,
                )

            track = editor.session().tracks[0]
            editor.close()
            self.assertTrue(track.muted)
            self.assertGreaterEqual(track.volume_percent, 145)
            self.assertLessEqual(track.volume_percent, 155)
            self.assertGreaterEqual(changed.count(), 2)

    def test_media_lookup_uses_the_clip_under_the_playhead(self) -> None:
        image = StudioSoundAsset(
            StudioAssetRef("image", TRACK_VIDEO, "cover.png"),
            "Cover",
            Path("cover.png"),
            20_000,
            media_kind="image",
            default_clip_duration_ms=5_000,
        )
        clip = StudioClip("clip-image", image.reference, 3_000, 1_000, 6_000)
        editor = StudioEditor(include_sidebars=False)
        editor.set_context(
            StudioSession(tracks=(StudioTrack("track-video", "Media", TRACK_VIDEO, clips=(clip,)),)),
            (image,),
        )

        self.assertTrue(editor.has_media_track())
        self.assertIsNone(editor.media_at(2_999))
        self.assertEqual(editor.media_at(4_500), (image, 2_500))
        self.assertIsNone(editor.media_at(8_000))


def _asset(root: Path) -> StudioSoundAsset:
    path = root / "vocals.wav"
    sf.write(path, np.full(16_000, 0.25, dtype=np.float32), 8_000)
    reference = StudioAssetRef("output-1", TRACK_ORIGINAL_VOCAL)
    return StudioSoundAsset(reference, "Run 01 / Original Vocal", path, 2_000)


def _session() -> StudioSession:
    reference = StudioAssetRef("output-1", TRACK_ORIGINAL_VOCAL)
    clip = StudioClip("clip-1", reference, 0, 0, 2_000)
    track = StudioTrack(
        "track-original-vocal",
        "Original Vocal",
        TRACK_ORIGINAL_VOCAL,
        clips=(clip,),
    )
    return StudioSession(tracks=(track,))


if __name__ == "__main__":
    unittest.main()
