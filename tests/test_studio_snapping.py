from __future__ import annotations

import unittest

from jang_app.services.studio_session import (
    StudioAssetRef,
    StudioClip,
    StudioSession,
    StudioTrack,
)
from jang_app.services.studio_snapping import (
    SNAP_TARGET_CLIP_END,
    SNAP_TARGET_PLAYHEAD,
    build_studio_snap_index,
    snap_studio_clip_position,
    snap_studio_clip_trim,
    snap_studio_timeline_point,
)


class StudioSnappingTests(unittest.TestCase):
    def test_point_snaps_to_the_nearest_edit_point_inside_threshold(self) -> None:
        clip = StudioClip("clip", _asset("clip"), 1_000, 0, 1_000)
        index = build_studio_snap_index(_session(("track-a", (clip,))))

        snapped = snap_studio_timeline_point(index, 1_970, threshold_ms=40)
        untouched = snap_studio_timeline_point(index, 1_950, threshold_ms=40)

        self.assertTrue(snapped.snapped)
        self.assertEqual(snapped.position_ms, 2_000)
        self.assertEqual(snapped.target.kind, SNAP_TARGET_CLIP_END)
        self.assertFalse(untouched.snapped)
        self.assertEqual(untouched.position_ms, 1_950)

    def test_same_track_wins_only_when_targets_are_equally_close(self) -> None:
        same = StudioClip("same", _asset("same"), 1_000, 0, 1_000)
        other = StudioClip("other", _asset("other"), 1_020, 0, 1_000)
        index = build_studio_snap_index(
            _session(("track-a", (same,)), ("track-b", (other,)))
        )

        result = snap_studio_timeline_point(
            index,
            1_010,
            threshold_ms=20,
            preferred_track_id="track-a",
        )

        self.assertEqual(result.position_ms, 1_000)
        self.assertEqual(result.target.track_id, "track-a")

    def test_playhead_is_a_snap_target_without_entering_the_static_index(self) -> None:
        index = build_studio_snap_index(StudioSession())

        result = snap_studio_timeline_point(
            index,
            4_970,
            threshold_ms=40,
            playhead_ms=5_000,
        )

        self.assertEqual(result.position_ms, 5_000)
        self.assertEqual(result.target.kind, SNAP_TARGET_PLAYHEAD)

    def test_clip_move_can_snap_its_start_or_end(self) -> None:
        moving = StudioClip("moving", _asset("moving"), 4_000, 0, 1_000)
        same = StudioClip("same", _asset("same"), 0, 0, 1_000)
        other = StudioClip("other", _asset("other"), 2_500, 0, 500)
        session = _session(
            ("track-a", (same, moving)),
            ("track-b", (other,)),
        )
        index = build_studio_snap_index(session)

        start = snap_studio_clip_position(
            session,
            index,
            "track-a",
            timeline_start_ms=1_020,
            duration_ms=1_000,
            threshold_ms=30,
            exclude_clip_id="moving",
        )
        end = snap_studio_clip_position(
            session,
            index,
            "track-a",
            timeline_start_ms=1_480,
            duration_ms=1_000,
            threshold_ms=30,
            exclude_clip_id="moving",
        )

        self.assertEqual((start.position_ms, start.moving_edge), (1_000, "start"))
        self.assertEqual((end.position_ms, end.moving_edge), (1_500, "end"))

    def test_clip_move_rejects_a_magnetic_candidate_that_would_overlap(self) -> None:
        existing = StudioClip("existing", _asset("existing"), 1_000, 0, 1_000)
        moving = StudioClip("moving", _asset("moving"), 3_000, 0, 500)
        session = _session(("track-a", (existing, moving)))

        result = snap_studio_clip_position(
            session,
            build_studio_snap_index(session),
            "track-a",
            timeline_start_ms=1_050,
            duration_ms=500,
            threshold_ms=60,
            exclude_clip_id="moving",
        )

        self.assertFalse(result.snapped)
        self.assertEqual(result.position_ms, 1_050)

    def test_trim_snaps_only_the_active_edge(self) -> None:
        previous = StudioClip("previous", _asset("previous"), 0, 0, 1_400)
        moving = StudioClip("moving", _asset("moving"), 2_000, 500, 1_500)
        marker = StudioClip("marker", _asset("marker"), 1_000, 0, 500)
        session = _session(
            ("track-a", (previous, moving)),
            ("track-b", (marker,)),
        )

        preview, result = snap_studio_clip_trim(
            session,
            build_studio_snap_index(session),
            "moving",
            source_start_ms=20,
            source_end_ms=1_500,
            preserve_timeline_end=True,
            threshold_ms=30,
        )

        self.assertTrue(result.snapped)
        self.assertEqual(result.moving_edge, "start")
        self.assertEqual(preview.timeline_start_ms, 1_500)
        self.assertEqual(preview.source_start_ms, 0)

    def test_point_can_exclude_current_clip_and_respect_split_bounds(self) -> None:
        clip = StudioClip("clip", _asset("clip"), 1_000, 0, 1_000)
        index = build_studio_snap_index(_session(("track-a", (clip,))))

        result = snap_studio_timeline_point(
            index,
            1_010,
            threshold_ms=20,
            exclude_clip_id="clip",
            minimum_ms=1_001,
            maximum_ms=1_999,
        )

        self.assertFalse(result.snapped)


def _asset(output_id: str) -> StudioAssetRef:
    return StudioAssetRef(output_id, "audio")


def _session(*tracks: tuple[str, tuple[StudioClip, ...]]) -> StudioSession:
    return StudioSession(
        tracks=tuple(
            StudioTrack(track_id, track_id, clips=clips)
            for track_id, clips in tracks
        )
    )


if __name__ == "__main__":
    unittest.main()
