from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import numpy as np
import soundfile as sf
from PySide6.QtCore import QEvent, QPoint, QPointF, QRectF, Qt
from PySide6.QtGui import QMouseEvent, QWheelEvent
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
    StudioMediaSettings,
    StudioSession,
    StudioTrack,
)


class StudioEditorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_timeline_zoom_accepts_twenty_times_the_default_scale(self) -> None:
        timeline = StudioTimelineView()

        timeline.set_zoom(140)
        self.assertEqual(timeline._pixels_per_second, 140)

        timeline.set_zoom(500)
        self.assertEqual(timeline._pixels_per_second, 140)
        timeline.close()

    def test_timeline_scrollbar_starts_after_header_and_ctrl_wheel_moves_it(self) -> None:
        reference = StudioAssetRef("long", TRACK_ORIGINAL_VOCAL)
        clip = StudioClip("long-clip", reference, 0, 0, 120_000)
        session = StudioSession(
            tracks=(
                StudioTrack(
                    "track-original-vocal",
                    "Original Vocal",
                    TRACK_ORIGINAL_VOCAL,
                    clips=(clip,),
                ),
            )
        )
        editor = StudioEditor(include_sidebars=False)
        editor.resize(720, 420)
        editor.set_context(session, ())
        editor.set_zoom(140)
        editor.show()
        self.app.processEvents()

        native_scroll = editor.timeline_scroll.horizontalScrollBar()
        visible_scroll = editor.timeline_horizontal_scroll
        self.assertGreater(native_scroll.maximum(), 0)
        self.assertEqual(visible_scroll.maximum(), native_scroll.maximum())
        self.assertEqual(
            visible_scroll.geometry().left(),
            editor.timeline.HEADER_WIDTH,
        )

        wheel = QWheelEvent(
            QPointF(10, 10),
            QPointF(10, 10),
            QPoint(),
            QPoint(0, -120),
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.ControlModifier,
            Qt.ScrollPhase.ScrollUpdate,
            False,
        )
        QApplication.sendEvent(editor.timeline_scroll.viewport(), wheel)
        self.app.processEvents()

        self.assertGreater(native_scroll.value(), 0)
        self.assertEqual(visible_scroll.value(), native_scroll.value())
        editor.close()

    def test_sound_pool_drop_adds_non_destructive_clip_at_target_position(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            asset = _asset(Path(temporary))
            editor = StudioEditor()
            editor.set_context(_session(), (asset,))
            changed = QSignalSpy(editor.session_changed)
            source_before = asset.path.read_bytes()

            self.assertEqual(editor.sound_assets(), (asset,))

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

    def test_effect_drop_can_link_all_pieces_from_the_same_audio(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            asset = _asset(Path(temporary))
            reference = asset.reference
            clips = (
                StudioClip("clip-1", reference, 0, 0, 1_000),
                StudioClip("clip-2", reference, 1_000, 1_000, 2_000),
            )
            session = StudioSession(
                tracks=(
                    StudioTrack(
                        "track-original-vocal",
                        "Original Vocal",
                        TRACK_ORIGINAL_VOCAL,
                        clips=clips,
                    ),
                )
            )
            editor = StudioEditor()
            editor.set_context(session, (asset,))

            with patch(
                "jang_app.qt_app.studio_editor.StudioEffectScopeDialog.choose",
                return_value="source",
            ) as choose:
                editor._drop_effect("reverb", "clip-1")

            first, second = editor.session().tracks[0].clips
            self.assertEqual(choose.call_args.args[1], 2)
            self.assertEqual(first.effects, second.effects)
            self.assertEqual(len(first.effects), 1)

            changed = replace(
                first.effects[0],
                reverb=replace(first.effects[0].reverb, dry_wet_percent=67),
            )
            editor._update_effect("clip-2", changed)
            first, second = editor.session().tracks[0].clips
            self.assertEqual(first.effects, (changed,))
            self.assertEqual(second.effects, (changed,))

            editor._remove_effect("clip-1", changed.effect_id)
            self.assertTrue(
                all(not clip.effects for clip in editor.session().tracks[0].clips)
            )
            self.assertTrue(editor.undo())
            self.assertTrue(
                all(
                    clip.effects == (changed,)
                    for clip in editor.session().tracks[0].clips
                )
            )
            editor.close()

    def test_effect_scope_cancel_keeps_split_pieces_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            asset = _asset(Path(temporary))
            reference = asset.reference
            session = StudioSession(
                tracks=(
                    StudioTrack(
                        "track-original-vocal",
                        "Original Vocal",
                        TRACK_ORIGINAL_VOCAL,
                        clips=(
                            StudioClip("clip-1", reference, 0, 0, 1_000),
                            StudioClip("clip-2", reference, 1_000, 1_000, 2_000),
                        ),
                    ),
                )
            )
            editor = StudioEditor()
            editor.set_context(session, (asset,))

            with patch(
                "jang_app.qt_app.studio_editor.StudioEffectScopeDialog.choose",
                return_value=None,
            ):
                editor._drop_effect("reverb", "clip-1")

            self.assertTrue(
                all(not clip.effects for clip in editor.session().tracks[0].clips)
            )
            editor.close()

    def test_delay_drop_adds_an_editable_clip_effect(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            asset = _asset(Path(temporary))
            editor = StudioEditor()
            editor.set_context(_session(), (asset,))

            editor._drop_effect("delay", "clip-1")

            effect = editor.session().tracks[0].clips[0].effects[0]
            self.assertEqual(effect.kind, "delay")
            self.assertEqual(effect.delay.delay_ms, 320)
            self.assertIn(effect.effect_id, editor.inspector.effect_tab_ids())
            editor.close()

    def test_doubler_drop_adds_an_editable_clip_effect(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            asset = _asset(Path(temporary))
            editor = StudioEditor()
            editor.set_context(_session(), (asset,))

            editor._drop_effect("doubler", "clip-1")

            effect = editor.session().tracks[0].clips[0].effects[0]
            self.assertEqual(effect.kind, "doubler")
            self.assertEqual(effect.doubler.voice_spacing_ms, 18)
            self.assertIn(effect.effect_id, editor.inspector.effect_tab_ids())
            editor.close()

    def test_character_chain_preset_is_added_and_undone_as_one_edit(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            asset = _asset(Path(temporary))
            editor = StudioEditor()
            editor.set_context(_session(), (asset,))

            editor._drop_effect("preset:animatronic", "clip-1")

            effects = editor.session().tracks[0].clips[0].effects
            self.assertEqual(
                tuple(effect.kind for effect in effects),
                ("radio_filter", "ring_modulator", "bitcrusher", "distortion"),
            )
            self.assertTrue(editor.undo())
            self.assertEqual(editor.session().tracks[0].clips[0].effects, ())
            editor.close()

    def test_karaoke_preset_adds_delay_and_reverb_as_one_edit(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            asset = _asset(Path(temporary))
            editor = StudioEditor()
            editor.set_context(_session(), (asset,))

            editor._drop_effect("preset:karaoke", "clip-1")

            effects = editor.session().tracks[0].clips[0].effects
            self.assertEqual(tuple(effect.kind for effect in effects), ("delay", "reverb"))
            self.assertEqual(effects[0].delay.delay_ms, 190)
            self.assertEqual(effects[0].delay.feedback_percent, 24)
            self.assertEqual(effects[1].reverb.decay_ms, 1_250)
            self.assertEqual(effects[1].reverb.dry_wet_percent, 22)
            self.assertTrue(editor.undo())
            self.assertEqual(editor.session().tracks[0].clips[0].effects, ())
            editor.close()

    def test_lush_preset_adds_bloom_and_level_match_as_one_edit(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            asset = _asset(Path(temporary))
            editor = StudioEditor()
            editor.set_context(_session(), (asset,))

            editor._drop_effect("preset:lush", "clip-1")

            effects = editor.session().tracks[0].clips[0].effects
            self.assertEqual(
                tuple(effect.kind for effect in effects),
                ("reverb", "level_match"),
            )
            self.assertEqual(effects[0].reverb.decay_ms, 950)
            self.assertEqual(effects[1].level_match.strength_percent, 75)
            self.assertTrue(editor.undo())
            self.assertEqual(editor.session().tracks[0].clips[0].effects, ())
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

    def test_timeline_effect_chips_use_the_actual_effect_kind(self) -> None:
        timeline = StudioTimelineView()
        kinds = (
            "reverb",
            "delay",
            "radio_filter",
            "ring_modulator",
            "bitcrusher",
            "distortion",
        )

        labels = tuple(
            timeline._effect_label(StudioEffect(f"fx-{kind}", kind))
            for kind in kinds
        )

        self.assertEqual(len(set(labels)), len(kinds))
        self.assertNotEqual(labels[1:], (labels[0],) * (len(kinds) - 1))

    def test_timeline_effect_chip_identifies_bypassed_effect(self) -> None:
        effect = StudioEffect("fx-level", "level_match", enabled=False)

        label = StudioTimelineView._effect_label(effect)

        self.assertIn("꺼짐", label)

    def test_waveform_height_is_not_reduced_by_effect_badge_space(self) -> None:
        rect = QRectF(10, 20, 320, 90)

        center, nominal_height, available_height = (
            StudioTimelineView._waveform_vertical_metrics(rect)
        )

        self.assertEqual(center, rect.center().y() + 8)
        self.assertAlmostEqual(nominal_height, 23.4)
        self.assertAlmostEqual(available_height, 31.0)

    def test_timeline_only_selects_clips_intersecting_the_exposed_region(self) -> None:
        reference = StudioAssetRef("output-1", TRACK_ORIGINAL_VOCAL)
        clips = tuple(
            StudioClip(
                f"clip-{index}",
                reference,
                index * 1_000,
                index * 1_000,
                (index + 1) * 1_000,
            )
            for index in range(500)
        )
        track = StudioTrack(
            "track-original-vocal",
            "Original Vocal",
            TRACK_ORIGINAL_VOCAL,
            clips=clips,
        )
        timeline = StudioTimelineView()
        timeline.set_zoom(24)
        timeline.set_context(StudioSession(tracks=(track,)), ())
        exposed = QRectF(
            timeline._ms_to_x(200_000),
            timeline.RULER_HEIGHT,
            240,
            timeline.LANE_HEIGHT,
        )

        visible = timeline._visible_track_clips(track, 0, exposed)

        self.assertLess(len(visible), 20)
        self.assertIn("clip-205", {clip.clip_id for clip in visible})
        self.assertNotIn("clip-20", {clip.clip_id for clip in visible})

    def test_playhead_move_invalidates_only_narrow_regions(self) -> None:
        class RecordingTimeline(StudioTimelineView):
            def __init__(self) -> None:
                self.updated_regions = []
                super().__init__()

            def update(self, *args) -> None:
                if args:
                    self.updated_regions.append(args[0])

        timeline = RecordingTimeline()
        timeline.set_context(_session(), ())
        timeline.updated_regions.clear()

        timeline.set_playhead(1_000)
        timeline.set_playhead(1_000)

        self.assertEqual(len(timeline.updated_regions), 2)
        self.assertTrue(all(region.width() <= 16 for region in timeline.updated_regions))

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

    def test_drag_preview_snaps_to_neighbor_boundary_before_release(self) -> None:
        reference = StudioAssetRef("output-1", TRACK_ORIGINAL_VOCAL)
        first = StudioClip("first", reference, 0, 0, 1_000)
        second = StudioClip("second", reference, 2_000, 0, 1_000)
        track = StudioTrack(
            "track-original-vocal",
            "Original Vocal",
            TRACK_ORIGINAL_VOCAL,
            clips=(first, second),
        )
        timeline = StudioTimelineView()
        timeline.set_zoom(24)
        timeline.set_context(StudioSession(tracks=(track,)), ())
        moved = QSignalSpy(timeline.clip_moved)
        start = timeline._clip_rect(first, 0).center()
        destination = QPointF(timeline._ms_to_x(2_100), start.y())

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

        self.assertEqual(timeline._drag_clip.timeline_start_ms, 1_000)
        self.assertTrue(timeline._drag_snapped)

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

        self.assertEqual(moved.at(0), ["first", "track-original-vocal", 1_000])

    def test_magnet_snaps_move_to_cross_track_edge_and_alt_temporarily_bypasses_it(self) -> None:
        reference = StudioAssetRef("output-1", TRACK_ORIGINAL_VOCAL)
        moving = StudioClip("moving", reference, 0, 0, 1_000)
        marker = StudioClip("marker", reference, 3_000, 0, 1_000)
        session = StudioSession(
            tracks=(
                StudioTrack("track-a", "Audio A", clips=(moving,)),
                StudioTrack("track-b", "Audio B", clips=(marker,)),
            )
        )
        timeline = StudioTimelineView()
        timeline.set_zoom(24)
        timeline.set_context(session, ())
        start = timeline._clip_rect(moving, 0).center()
        destination = QPointF(timeline._ms_to_x(3_100), start.y())

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

        self.assertEqual(timeline._drag_clip.timeline_start_ms, 3_000)
        self.assertEqual(timeline._snap_preview.target.position_ms, 3_000)

        timeline.mouseMoveEvent(
            QMouseEvent(
                QEvent.Type.MouseMove,
                destination,
                destination,
                Qt.MouseButton.NoButton,
                Qt.MouseButton.LeftButton,
                Qt.KeyboardModifier.AltModifier,
            )
        )

        self.assertEqual(timeline._drag_clip.timeline_start_ms, 2_600)
        self.assertIsNone(timeline._snap_preview)

    def test_playhead_and_split_tool_share_the_edit_point_index(self) -> None:
        reference = StudioAssetRef("output-1", TRACK_ORIGINAL_VOCAL)
        long_clip = StudioClip("long", reference, 0, 0, 5_000)
        marker = StudioClip("marker", reference, 2_000, 0, 1_000)
        session = StudioSession(
            tracks=(
                StudioTrack("track-a", "Audio A", clips=(long_clip,)),
                StudioTrack("track-b", "Audio B", clips=(marker,)),
            )
        )
        timeline = StudioTimelineView()
        timeline.set_zoom(24)
        timeline.set_context(session, ())

        ruler_point = QPointF(
            timeline._ms_to_x(1_800),
            timeline._ruler_top() + 8,
        )
        timeline.mousePressEvent(
            QMouseEvent(
                QEvent.Type.MouseButtonPress,
                ruler_point,
                ruler_point,
                Qt.MouseButton.LeftButton,
                Qt.MouseButton.LeftButton,
                Qt.KeyboardModifier.NoModifier,
            )
        )
        self.assertEqual(timeline._playhead_ms, 2_000)
        self.assertEqual(timeline._snap_preview.target.position_ms, 2_000)

        timeline.mouseReleaseEvent(
            QMouseEvent(
                QEvent.Type.MouseButtonRelease,
                ruler_point,
                ruler_point,
                Qt.MouseButton.LeftButton,
                Qt.MouseButton.NoButton,
                Qt.KeyboardModifier.NoModifier,
            )
        )
        timeline.set_split_mode(True)
        split_point = QPoint(
            round(timeline._ms_to_x(1_800)),
            round(timeline._clip_rect(long_clip, 0).center().y()),
        )
        timeline._update_cursor(split_point, Qt.KeyboardModifier.NoModifier)

        self.assertEqual(timeline._split_hover, ("long", 2_000))
        self.assertEqual(timeline._snap_preview.target.position_ms, 2_000)

    def test_sound_pool_drop_uses_the_same_magnetic_position_resolver(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            asset = _asset(Path(temporary))
            marker = StudioClip("marker", asset.reference, 5_000, 0, 1_000)
            session = StudioSession(
                tracks=(
                    StudioTrack("track-a", "Audio A"),
                    StudioTrack("track-b", "Audio B", clips=(marker,)),
                )
            )
            timeline = StudioTimelineView()
            timeline.set_zoom(24)
            timeline.set_context(session, (asset,))

            position_ms, snap_result = timeline._resolve_asset_drop_position(
                asset.asset_id,
                session.tracks[0],
                timeline._ms_to_x(4_650),
                Qt.KeyboardModifier.NoModifier,
            )

            self.assertEqual(position_ms, 5_000)
            self.assertTrue(snap_result.snapped)

    def test_left_trim_preview_stops_at_previous_clip_boundary(self) -> None:
        reference = StudioAssetRef("output-1", TRACK_ORIGINAL_VOCAL)
        previous = StudioClip("previous", reference, 0, 0, 1_000)
        middle = StudioClip("middle", reference, 1_500, 1_000, 2_000)
        track = StudioTrack(
            "track-original-vocal",
            "Original Vocal",
            TRACK_ORIGINAL_VOCAL,
            clips=(previous, middle),
        )
        timeline = StudioTimelineView()
        timeline.set_zoom(24)
        timeline.set_context(StudioSession(tracks=(track,)), ())
        trimmed = QSignalSpy(timeline.clip_trimmed)
        rect = timeline._clip_rect(middle, 0)
        start = QPointF(rect.left(), rect.center().y())
        destination = QPointF(timeline._ms_to_x(500), start.y())

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

        self.assertEqual(
            (timeline._drag_clip.timeline_start_ms, timeline._drag_clip.source_start_ms),
            (1_000, 500),
        )
        self.assertTrue(timeline._drag_snapped)

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

        self.assertEqual(trimmed.at(0), ["middle", 500, 2_000, True])

    def test_drag_to_incompatible_track_is_rejected_without_commit(self) -> None:
        audio_ref = StudioAssetRef("audio", TRACK_ORIGINAL_VOCAL)
        video_ref = StudioAssetRef("video", TRACK_VIDEO)
        audio = StudioClip("audio-clip", audio_ref, 0, 0, 1_000)
        video = StudioClip("video-clip", video_ref, 0, 0, 1_000)
        session = StudioSession(
            tracks=(
                StudioTrack(
                    "track-audio",
                    "Original Vocal",
                    TRACK_ORIGINAL_VOCAL,
                    clips=(audio,),
                ),
                StudioTrack(
                    "track-video",
                    "Media",
                    TRACK_VIDEO,
                    clips=(video,),
                ),
            )
        )
        timeline = StudioTimelineView()
        timeline.set_zoom(24)
        timeline.set_context(session, ())
        moved = QSignalSpy(timeline.clip_moved)
        start = timeline._clip_rect(audio, 0).center()
        destination = QPointF(start.x(), timeline._clip_rect(video, 1).center().y())

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

        self.assertFalse(timeline._drag_target_valid)

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

        self.assertEqual(moved.count(), 0)

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

    def test_playhead_line_in_clip_lane_does_not_capture_clip_interaction(self) -> None:
        timeline = StudioTimelineView()
        timeline.set_zoom(24)
        timeline.set_context(_session(), ())
        timeline.set_playhead(1_000)
        seeked = QSignalSpy(timeline.seek_requested)
        moved = QSignalSpy(timeline.clip_moved)
        start = QPointF(
            timeline._ms_to_x(1_000),
            timeline.RULER_HEIGHT + timeline.LANE_HEIGHT / 2,
        )
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

        self.assertEqual(timeline._drag_mode, "move")
        self.assertEqual(timeline._playhead_ms, 1_000)
        self.assertEqual(seeked.count(), 0)
        self.assertEqual(moved.count(), 0)

        timeline.mouseReleaseEvent(
            QMouseEvent(
                QEvent.Type.MouseButtonRelease,
                start,
                start,
                Qt.MouseButton.LeftButton,
                Qt.MouseButton.NoButton,
                Qt.KeyboardModifier.NoModifier,
            )
        )

        self.assertEqual(timeline._drag_mode, "")
        self.assertEqual(timeline._playhead_ms, 1_000)
        self.assertEqual(moved.count(), 0)

    def test_cut_tool_can_split_a_clip_directly_under_the_playhead_line(self) -> None:
        timeline = StudioTimelineView()
        timeline.set_zoom(24)
        timeline.set_context(_session(), ())
        timeline.set_playhead(1_000)
        timeline.set_split_mode(True)
        split = QSignalSpy(timeline.clip_split_requested)
        point = QPointF(
            timeline._ms_to_x(1_000),
            timeline.RULER_HEIGHT + timeline.LANE_HEIGHT / 2,
        )

        timeline.mousePressEvent(
            QMouseEvent(
                QEvent.Type.MouseButtonPress,
                point,
                point,
                Qt.MouseButton.LeftButton,
                Qt.MouseButton.LeftButton,
                Qt.KeyboardModifier.NoModifier,
            )
        )

        self.assertEqual(split.count(), 1)
        self.assertEqual(split.at(0), ["clip-1", 1_000])
        self.assertNotEqual(timeline._drag_mode, "playhead")

    def test_ruler_drag_clamps_playhead_to_session_duration(self) -> None:
        timeline = StudioTimelineView()
        timeline.set_zoom(24)
        timeline.set_context(_session(), ())
        seeked = QSignalSpy(timeline.seek_requested)
        start = QPointF(timeline._ms_to_x(500), timeline.RULER_HEIGHT / 2)
        beyond_end = QPointF(timeline._ms_to_x(8_000), start.y())

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
                beyond_end,
                beyond_end,
                Qt.MouseButton.NoButton,
                Qt.MouseButton.LeftButton,
                Qt.KeyboardModifier.NoModifier,
            )
        )
        timeline.mouseReleaseEvent(
            QMouseEvent(
                QEvent.Type.MouseButtonRelease,
                beyond_end,
                beyond_end,
                Qt.MouseButton.LeftButton,
                Qt.MouseButton.NoButton,
                Qt.KeyboardModifier.NoModifier,
            )
        )

        self.assertEqual(timeline._playhead_ms, 2_000)
        self.assertEqual(seeked.at(seeked.count() - 1), [2_000])

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

    def test_right_click_exits_cut_tool_without_editing_the_timeline(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            asset = _asset(Path(temporary))
            editor = StudioEditor()
            editor.set_context(_session(), (asset,))
            mode_changed = QSignalSpy(editor.split_mode_changed)
            original_session = editor.session()
            editor.set_split_mode(True)

            QTest.mouseClick(
                editor.timeline,
                Qt.MouseButton.RightButton,
                pos=QPoint(
                    round(editor.timeline._ms_to_x(1_000)),
                    editor.timeline.RULER_HEIGHT + editor.timeline.LANE_HEIGHT // 2,
                ),
            )

            self.assertFalse(editor._split_mode)
            self.assertFalse(editor.timeline._split_mode)
            self.assertEqual(tuple(mode_changed.at(0)), (True,))
            self.assertEqual(tuple(mode_changed.at(1)), (False,))
            self.assertEqual(editor.session(), original_session)
            editor.close()

    def test_adding_at_occupied_playhead_keeps_existing_clip_and_snaps_new_clip(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            asset = _asset(Path(temporary))
            editor = StudioEditor()
            editor.set_context(_session(), (asset,))
            editor._drop_asset(asset.asset_id, "track-original-vocal", 0)

            clips = editor.session().tracks[0].clips
            original = next(clip for clip in clips if clip.clip_id == "clip-1")
            self.assertEqual(original.timeline_start_ms, 0)
            self.assertEqual([clip.timeline_start_ms for clip in clips], [0, 2_000])

    def test_legacy_overlap_warning_clears_after_user_resolves_the_conflict(self) -> None:
        reference = StudioAssetRef("output-1", TRACK_ORIGINAL_VOCAL)
        first = StudioClip("first", reference, 0, 0, 2_000)
        second = StudioClip("second", reference, 1_000, 0, 2_000)
        track = StudioTrack(
            "track-original-vocal",
            "Original Vocal",
            TRACK_ORIGINAL_VOCAL,
            clips=(first, second),
        )
        editor = StudioEditor()

        editor.set_context(StudioSession(tracks=(track,)), ())

        self.assertFalse(editor.status_label.isHidden())
        self.assertEqual(editor._legacy_overlap_count, 1)

        editor._move_clip("second", track.track_id, 2_000)

        self.assertTrue(editor.status_label.isHidden())
        self.assertEqual(editor._legacy_overlap_count, 0)
        editor.close()

    def test_snapped_move_is_restored_as_one_undo_and_redo_step(self) -> None:
        reference = StudioAssetRef("output-1", TRACK_ORIGINAL_VOCAL)
        first = StudioClip("first", reference, 0, 0, 1_000)
        second = StudioClip("second", reference, 2_000, 0, 1_000)
        track = StudioTrack(
            "track-original-vocal",
            "Original Vocal",
            TRACK_ORIGINAL_VOCAL,
            clips=(first, second),
        )
        original = StudioSession(tracks=(track,))
        editor = StudioEditor()
        editor.set_context(original, ())

        editor._move_clip("first", track.track_id, 1_600)

        moved = next(clip for clip in editor.session().tracks[0].clips if clip.clip_id == "first")
        self.assertEqual(moved.timeline_start_ms, 1_000)
        self.assertTrue(editor.undo())
        self.assertEqual(editor.session(), original)
        self.assertTrue(editor.redo())
        moved = next(clip for clip in editor.session().tracks[0].clips if clip.clip_id == "first")
        self.assertEqual(moved.timeline_start_ms, 1_000)
        editor.close()

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
                patch(
                    "jang_app.qt_app.studio_editor.build_waveform_amplitude_peaks",
                    return_value=[],
                ),
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
        self.assertEqual(editor.media_at(4_500), (image, 2_500, clip.media))
        self.assertIsNone(editor.media_at(8_000))

    def test_image_media_values_update_duration_and_layout_together(self) -> None:
        image = StudioSoundAsset(
            StudioAssetRef("image", TRACK_VIDEO, "cover.png"),
            "Cover",
            Path("cover.png"),
            20_000,
            media_kind="image",
            default_clip_duration_ms=5_000,
        )
        clip = StudioClip("clip-image", image.reference, 3_000, 0, 5_000)
        editor = StudioEditor(include_sidebars=False)
        editor.set_context(
            StudioSession(
                tracks=(StudioTrack("track-video", "Media", TRACK_VIDEO, clips=(clip,)),)
            ),
            (image,),
        )
        settings = StudioMediaSettings(scale_percent=140, offset_x_percent=20)

        editor._set_media_values(clip.clip_id, 7_500, settings)

        updated = editor.session().tracks[0].clips[0]
        self.assertEqual(updated.duration_ms, 7_500)
        self.assertEqual(updated.media, settings)


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
