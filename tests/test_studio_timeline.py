from __future__ import annotations

import unittest
from dataclasses import replace

import jang_app.services.studio_session as studio_session
import jang_app.services.studio_timeline as studio_timeline
from jang_app.services.studio_session import (
    TRACK_AUDIO,
    TRACK_VIDEO,
    StudioAssetRef,
    StudioClip,
    StudioMediaSettings,
    StudioSession,
    StudioTrack,
)
from jang_app.services.studio_timeline import (
    StudioTimelineError,
    add_studio_clip,
    add_studio_track,
    move_studio_clip,
    remove_studio_track,
    resolve_studio_clip_position,
    resolve_studio_clip_trim,
    set_studio_clip_mix,
    set_studio_clip_media,
    set_studio_clip_pitch,
    set_studio_clip_timing,
    set_studio_track_collapsed,
    set_studio_track_mix,
    split_studio_clip,
    trim_studio_clip,
)


class StudioTimelineTests(unittest.TestCase):
    def test_add_clip_snaps_to_the_nearest_legal_track_boundary(self) -> None:
        existing = StudioClip("first", _asset("first"), 1_000, 0, 1_000)

        after = add_studio_clip(
            _session(existing),
            "track-audio",
            _asset("new"),
            500,
            timeline_start_ms=1_800,
        )
        before = add_studio_clip(
            _session(existing),
            "track-audio",
            _asset("new"),
            500,
            timeline_start_ms=700,
        )

        added_after = next(clip for clip in after.tracks[0].clips if clip.clip_id != "first")
        added_before = next(clip for clip in before.tracks[0].clips if clip.clip_id != "first")
        self.assertEqual(added_after.timeline_start_ms, 2_000)
        self.assertEqual(added_before.timeline_start_ms, 500)

    def test_clip_boundaries_can_touch_without_being_treated_as_overlap(self) -> None:
        existing = StudioClip("first", _asset("first"), 0, 0, 1_000)

        position = resolve_studio_clip_position(
            _session(existing),
            "track-audio",
            timeline_start_ms=1_000,
            duration_ms=500,
        )

        self.assertEqual(position, 1_000)

    def test_position_resolver_skips_a_contiguous_block_of_clips(self) -> None:
        first = StudioClip("first", _asset("first"), 0, 0, 1_000)
        second = StudioClip("second", _asset("second"), 1_000, 0, 1_000)

        position = resolve_studio_clip_position(
            _session(first, second),
            "track-audio",
            timeline_start_ms=900,
            duration_ms=500,
        )

        self.assertEqual(position, 2_000)

    def test_move_clip_ignores_itself_and_snaps_against_target_neighbors(self) -> None:
        first = StudioClip("first", _asset("first"), 0, 0, 1_000)
        second = StudioClip("second", _asset("second"), 2_000, 0, 1_000)

        updated = move_studio_clip(
            _session(first, second),
            "first",
            track_id="track-audio",
            timeline_start_ms=1_600,
        )

        moved = next(clip for clip in updated.tracks[0].clips if clip.clip_id == "first")
        self.assertEqual(moved.timeline_start_ms, 1_000)

    def test_trim_edges_stop_at_adjacent_clip_boundaries(self) -> None:
        previous = StudioClip("previous", _asset("previous"), 0, 0, 1_000)
        middle = StudioClip("middle", _asset("middle"), 1_500, 1_000, 2_000)
        following = StudioClip("following", _asset("following"), 3_000, 0, 1_000)
        session = _session(previous, middle, following)

        left = resolve_studio_clip_trim(
            session,
            "middle",
            source_start_ms=0,
            source_end_ms=2_000,
            preserve_timeline_end=True,
        )
        right = resolve_studio_clip_trim(
            session,
            "middle",
            source_start_ms=1_000,
            source_end_ms=3_000,
        )

        self.assertEqual((left.timeline_start_ms, left.source_start_ms), (1_000, 500))
        self.assertEqual(left.timeline_end_ms, middle.timeline_end_ms)
        self.assertEqual((right.source_end_ms, right.timeline_end_ms), (2_500, 3_000))

    def test_trim_and_atomic_timing_edits_cannot_create_new_overlap(self) -> None:
        first = StudioClip("first", _asset("first"), 0, 0, 1_000)
        second = StudioClip("second", _asset("second"), 2_000, 0, 1_000)
        session = _session(first, second)

        trimmed = trim_studio_clip(
            session,
            "first",
            source_start_ms=0,
            source_end_ms=3_000,
        )
        edited = set_studio_clip_timing(
            session,
            "first",
            timeline_start_ms=1_600,
            source_start_ms=0,
            source_end_ms=1_000,
        )

        self.assertEqual(trimmed.tracks[0].clips[0].timeline_end_ms, 2_000)
        moved = next(clip for clip in edited.tracks[0].clips if clip.clip_id == "first")
        self.assertEqual(moved.timeline_start_ms, 1_000)

    def test_existing_legacy_overlap_is_not_rewritten_just_by_resolving_a_position(self) -> None:
        first = StudioClip("first", _asset("first"), 0, 0, 2_000)
        second = StudioClip("second", _asset("second"), 1_000, 0, 2_000)
        session = _session(first, second)

        resolve_studio_clip_position(
            session,
            "track-audio",
            timeline_start_ms=500,
            duration_ms=500,
        )

        self.assertEqual(session.tracks[0].clips, (first, second))
        self.assertEqual(studio_timeline.studio_overlap_count(session), 1)

    def test_overlap_count_treats_touching_clip_boundaries_as_legal(self) -> None:
        first = StudioClip("first", _asset("first"), 0, 0, 1_000)
        second = StudioClip("second", _asset("second"), 1_000, 0, 1_000)

        self.assertEqual(studio_timeline.studio_overlap_count(_session(first, second)), 0)

    def test_clips_on_different_tracks_may_share_the_same_time_range(self) -> None:
        first = StudioClip("first", _asset("first"), 0, 0, 1_000)
        second = StudioClip("second", _asset("second"), 0, 0, 1_000)
        session = StudioSession(
            tracks=(
                StudioTrack("track-a", "Audio A", clips=(first,)),
                StudioTrack("track-b", "Audio B", clips=(second,)),
            )
        )

        self.assertEqual(studio_timeline.studio_overlap_count(session), 0)

    def test_media_settings_only_update_media_clips(self) -> None:
        clip = StudioClip(
            "media",
            StudioAssetRef("media", TRACK_VIDEO, "cover.png"),
            0,
            0,
            5_000,
        )
        session = StudioSession(tracks=(StudioTrack("media-track", "Media", TRACK_VIDEO, clips=(clip,)),))
        settings = StudioMediaSettings(scale_percent=125, source_audio_enabled=True)

        updated = set_studio_clip_media(session, clip.clip_id, settings)

        self.assertEqual(updated.tracks[0].clips[0].media, settings)
        audio_clip = StudioClip("audio", _asset("audio"), 0, 0, 1_000)
        with self.assertRaises(StudioTimelineError):
            set_studio_clip_media(_session(audio_clip), audio_clip.clip_id, settings)

    def test_clip_effect_add_update_remove_targets_one_clip(self) -> None:
        self.assertTrue(hasattr(studio_timeline, "add_studio_clip_effect"))
        first = StudioClip("first", _asset("first"), 0, 0, 1_000)
        second = StudioClip("second", _asset("second"), 1_000, 0, 1_000)
        effect = studio_session.StudioEffect("fx-reverb", "reverb")

        added = studio_timeline.add_studio_clip_effect(_session(first, second), "first", effect)
        changed = replace(
            effect,
            reverb=replace(effect.reverb, dry_wet_percent=55),
        )
        updated = studio_timeline.update_studio_clip_effect(added, "first", changed)
        removed = studio_timeline.remove_studio_clip_effect(updated, "first", effect.effect_id)

        self.assertEqual(added.tracks[0].clips[0].effects, (effect,))
        self.assertEqual(added.tracks[0].clips[1].effects, ())
        self.assertEqual(updated.tracks[0].clips[0].effects, (changed,))
        self.assertEqual(removed.tracks[0].clips[0].effects, ())

    def test_clip_effect_errors_and_split_inherits_effects(self) -> None:
        self.assertTrue(hasattr(studio_session, "StudioEffect"))
        effect = studio_session.StudioEffect("fx-reverb", "reverb")
        clip = StudioClip("first", _asset("first"), 0, 0, 4_000, effects=(effect,))

        split = split_studio_clip(_session(clip), clip.clip_id, timeline_position_ms=2_000)

        self.assertEqual(tuple(part.effects for part in split.tracks[0].clips), ((effect,), (effect,)))
        with self.assertRaises(StudioTimelineError):
            studio_timeline.add_studio_clip_effect(_session(clip), clip.clip_id, effect)
        with self.assertRaises(StudioTimelineError):
            studio_timeline.update_studio_clip_effect(
                _session(clip),
                clip.clip_id,
                replace(effect, effect_id="missing"),
            )
        with self.assertRaises(StudioTimelineError):
            studio_timeline.remove_studio_clip_effect(_session(clip), clip.clip_id, "missing")

    def test_linked_effect_update_and_remove_follow_same_source_pieces(self) -> None:
        shared_asset = _asset("shared")
        other_asset = _asset("other")
        effect = studio_session.StudioEffect("fx-linked", "reverb")
        first = StudioClip("first", shared_asset, 0, 0, 1_000, effects=(effect,))
        second = StudioClip("second", shared_asset, 1_000, 1_000, 2_000, effects=(effect,))
        other = StudioClip("other", other_asset, 0, 0, 1_000, effects=(effect,))
        session = _session(first, second, other)
        changed = replace(effect, reverb=replace(effect.reverb, dry_wet_percent=61))

        updated = studio_timeline.update_studio_clip_effect(session, "first", changed)
        removed = studio_timeline.remove_studio_clip_effect(
            updated,
            "second",
            effect.effect_id,
        )

        self.assertEqual(updated.tracks[0].clips[0].effects, (changed,))
        self.assertEqual(updated.tracks[0].clips[1].effects, (changed,))
        self.assertEqual(updated.tracks[0].clips[2].effects, (effect,))
        self.assertEqual(removed.tracks[0].clips[0].effects, ())
        self.assertEqual(removed.tracks[0].clips[1].effects, ())
        self.assertEqual(removed.tracks[0].clips[2].effects, (effect,))

    def test_studio_clip_siblings_are_limited_to_the_same_source_asset(self) -> None:
        shared_asset = _asset("shared")
        first = StudioClip("first", shared_asset, 0, 0, 1_000)
        second = StudioClip("second", shared_asset, 1_000, 1_000, 2_000)
        other = StudioClip("other", _asset("other"), 0, 0, 1_000)

        siblings = studio_timeline.studio_clip_siblings(
            _session(first, second, other),
            "first",
        )

        self.assertEqual(tuple(clip.clip_id for clip in siblings), ("first", "second"))

    def test_new_split_inherits_and_keeps_a_linked_effect(self) -> None:
        shared_asset = _asset("shared")
        effect = studio_session.StudioEffect("fx-linked", "delay")
        first = StudioClip("first", shared_asset, 0, 0, 1_000, effects=(effect,))
        second = StudioClip("second", shared_asset, 1_000, 1_000, 3_000, effects=(effect,))
        split = split_studio_clip(
            _session(first, second),
            "second",
            timeline_position_ms=2_000,
        )
        changed = replace(effect, delay=replace(effect.delay, dry_wet_percent=48))

        updated = studio_timeline.update_studio_clip_effect(split, "first", changed)

        self.assertEqual(len(updated.tracks[0].clips), 3)
        self.assertTrue(
            all(clip.effects == (changed,) for clip in updated.tracks[0].clips)
        )

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

    def test_split_clip_preserves_timeline_source_gain_and_pitch(self) -> None:
        clip = StudioClip(
            "first",
            _asset("first"),
            2_000,
            500,
            4_500,
            gain_db=-3.0,
            pitch_semitones=7,
        )

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
        self.assertEqual((left.pitch_semitones, right.pitch_semitones), (7, 7))
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

    def test_clip_gain_supports_configured_range_and_clamps_outside_it(self) -> None:
        session = _session(StudioClip("first", _asset("first"), 0, 0, 1_000))

        at_upper_limit = set_studio_clip_mix(session, "first", gain_db=30.0)
        above_limit = set_studio_clip_mix(at_upper_limit, "first", gain_db=80.0)
        at_lower_limit = set_studio_clip_mix(above_limit, "first", gain_db=-100.0)
        below_limit = set_studio_clip_mix(at_lower_limit, "first", gain_db=-140.0)

        self.assertEqual(at_upper_limit.tracks[0].clips[0].gain_db, 30.0)
        self.assertEqual(above_limit.tracks[0].clips[0].gain_db, 30.0)
        self.assertEqual(at_lower_limit.tracks[0].clips[0].gain_db, -100.0)
        self.assertEqual(below_limit.tracks[0].clips[0].gain_db, -100.0)

    def test_clip_pitch_is_non_destructive_and_clamped(self) -> None:
        session = _session(StudioClip("first", _asset("first"), 0, 0, 1_000))

        shifted = set_studio_clip_pitch(session, "first", 12)
        clamped = set_studio_clip_pitch(shifted, "first", 999)

        self.assertEqual(session.tracks[0].clips[0].pitch_semitones, 0)
        self.assertEqual(shifted.tracks[0].clips[0].pitch_semitones, 12)
        self.assertEqual(clamped.tracks[0].clips[0].pitch_semitones, 48)

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
