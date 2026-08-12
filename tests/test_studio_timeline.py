from __future__ import annotations

import unittest

from jang_app.services.studio_session import (
    TRACK_AUDIO,
    TRACK_VIDEO,
    StudioAssetRef,
    StudioClip,
    StudioSession,
    StudioTrack,
)
from jang_app.services.studio_timeline import (
    StudioTimelineError,
    add_studio_clip,
    add_studio_track,
    remove_studio_track,
    set_studio_clip_mix,
    set_studio_track_collapsed,
    set_studio_track_mix,
    split_studio_clip,
)


class StudioTimelineTests(unittest.TestCase):
    def test_add_track_appends_an_empty_audio_track(self) -> None:
        session = _session(StudioClip("first", _asset("first"), 0, 0, 1_000))

        updated = add_studio_track(session)

        added = updated.tracks[-1]
        self.assertEqual(len(updated.tracks), 2)
        self.assertEqual(added.role, TRACK_AUDIO)
        self.assertEqual(added.name, "Audio 2")
        self.assertEqual(added.clips, ())

    def test_add_track_uses_unique_ids_and_sequential_names(self) -> None:
        first = add_studio_track(_session())
        second = add_studio_track(first)

        self.assertNotEqual(first.tracks[-1].track_id, second.tracks[-1].track_id)
        self.assertEqual([track.name for track in second.tracks], ["Audio", "Audio 2", "Audio 3"])

    def test_remove_track_removes_the_track_and_all_of_its_clips(self) -> None:
        first = StudioTrack(
            "first-track",
            "First",
            clips=(StudioClip("first", _asset("first"), 0, 0, 1_000),),
        )
        second = StudioTrack(
            "second-track",
            "Second",
            clips=(StudioClip("second", _asset("second"), 0, 0, 1_000),),
        )

        updated = remove_studio_track(StudioSession(tracks=(first, second)), "second-track")

        self.assertEqual(updated.tracks, (first,))
        with self.assertRaises(StudioTimelineError):
            remove_studio_track(updated, "missing-track")

    def test_split_clip_preserves_timeline_source_and_gain(self) -> None:
        clip = StudioClip("first", _asset("first"), 2_000, 500, 4_500, gain_db=-3.0)

        updated = split_studio_clip(
            _session(clip),
            clip.clip_id,
            timeline_position_ms=3_500,
        )

        left, right = updated.tracks[0].clips
        self.assertEqual(
            (left.timeline_start_ms, left.source_start_ms, left.source_end_ms),
            (2_000, 500, 2_000),
        )
        self.assertEqual(
            (right.timeline_start_ms, right.source_start_ms, right.source_end_ms),
            (3_500, 2_000, 4_500),
        )
        self.assertEqual((left.gain_db, right.gain_db), (-3.0, -3.0))
        self.assertEqual(left.asset, right.asset)
        self.assertNotEqual(left.clip_id, right.clip_id)

    def test_split_rejects_clip_boundaries(self) -> None:
        clip = StudioClip("first", _asset("first"), 2_000, 500, 4_500)

        for position in (2_000, 6_000):
            with self.subTest(position=position):
                with self.assertRaises(StudioTimelineError):
                    split_studio_clip(
                        _session(clip),
                        clip.clip_id,
                        timeline_position_ms=position,
                    )

    def test_split_keeps_fades_only_at_the_outer_clip_edges(self) -> None:
        clip = StudioClip(
            "first",
            _asset("first"),
            0,
            0,
            4_000,
            fade_in_ms=500,
            fade_out_ms=700,
        )

        updated = split_studio_clip(_session(clip), clip.clip_id, timeline_position_ms=2_000)

        left, right = updated.tracks[0].clips
        self.assertEqual((left.fade_in_ms, left.fade_out_ms), (500, 0))
        self.assertEqual((right.fade_in_ms, right.fade_out_ms), (0, 700))

    def test_clip_fades_and_track_pan_are_clamped(self) -> None:
        session = _session(StudioClip("first", _asset("first"), 0, 0, 1_000))

        updated = set_studio_clip_mix(
            session,
            "first",
            muted=True,
            fade_in_ms=800,
            fade_out_ms=800,
        )
        updated = set_studio_track_mix(updated, "track-audio", pan_percent=140)

        clip = updated.tracks[0].clips[0]
        self.assertTrue(clip.muted)
        self.assertEqual((clip.fade_in_ms, clip.fade_out_ms), (800, 200))
        self.assertEqual(updated.tracks[0].pan_percent, 100)

    def test_track_collapsed_state_is_non_destructive(self) -> None:
        session = _session(StudioClip("first", _asset("first"), 0, 0, 1_000))

        updated = set_studio_track_collapsed(session, "track-audio", True)

        self.assertTrue(updated.tracks[0].collapsed)
        self.assertEqual(updated.tracks[0].clips, session.tracks[0].clips)

    def test_video_asset_is_rejected_by_audio_track(self) -> None:
        session = _session()
        video = StudioAssetRef("video-source", TRACK_VIDEO, "source.mp4")

        with self.assertRaises(StudioTimelineError):
            add_studio_clip(session, "track-audio", video, 1_000)


def _asset(output_id: str) -> StudioAssetRef:
    return StudioAssetRef(output_id, "audio")


def _session(*clips: StudioClip) -> StudioSession:
    return StudioSession(
        tracks=(StudioTrack("track-audio", "Audio", clips=tuple(clips)),),
    )


if __name__ == "__main__":
    unittest.main()
