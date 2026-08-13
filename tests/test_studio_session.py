from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

import numpy as np
import soundfile as sf

import jang_app.services.studio_session as studio_session
from jang_app.services.song_package import SongPackageStore
from jang_app.services.studio_assets import resolve_studio_asset, studio_sound_pool
from jang_app.services.studio_session import (
    STUDIO_SESSION_VERSION,
    TRACK_CONVERTED_VOCAL,
    TRACK_INSTRUMENTAL,
    TRACK_ORIGINAL_VOCAL,
    TRACK_VIDEO,
    MEDIA_FILL,
    StudioMediaSettings,
    StudioSession,
    StudioTrack,
    StudioTrackState,
    load_studio_session,
    save_studio_session,
    studio_session_path,
)
from jang_app.services.video_source import VideoSourceStore
from jang_app.services.studio_timeline import (
    add_studio_clip,
    move_studio_clip,
    session_duration_ms,
    split_studio_clip,
    trim_studio_clip,
)
from jang_app.services.vocal_project import VocalConversionSettings
from jang_app.services.vocal_project_store import VocalProjectStore


class StudioSessionTests(unittest.TestCase):
    def test_current_reverb_effect_round_trips_and_version_four_defaults_empty(self) -> None:
        self.assertTrue(hasattr(studio_session, "StudioEffect"))
        with tempfile.TemporaryDirectory() as temporary:
            package = _package_with_audio_output(Path(temporary))
            session = load_studio_session(package)
            track = session.tracks[0]
            clip = track.clips[0]
            effect = studio_session.StudioEffect(
                effect_id="fx-reverb",
                kind="reverb",
                reverb=studio_session.StudioReverbSettings(
                    room_width_m=8.5,
                    pre_delay_ms=42,
                    dry_wet_percent=37,
                ),
            )
            edited = replace(
                session,
                tracks=(replace(track, clips=(replace(clip, effects=(effect,)),)), *session.tracks[1:]),
            )

            save_studio_session(package, edited)
            restored = load_studio_session(package)

            self.assertEqual(restored.tracks[0].clips[0].effects, (effect,))
            saved = json.loads(studio_session_path(package).read_text(encoding="utf-8"))
            self.assertEqual(saved["version"], STUDIO_SESSION_VERSION)
            self.assertEqual(saved["tracks"][0]["clips"][0]["effects"][0]["kind"], "reverb")

            saved["version"] = 4
            saved["tracks"][0]["clips"][0].pop("effects")
            studio_session_path(package).write_text(json.dumps(saved), encoding="utf-8")
            migrated = load_studio_session(package)
            self.assertEqual(migrated.tracks[0].clips[0].effects, ())

    def test_invalid_reverb_values_are_clamped_when_loading(self) -> None:
        self.assertTrue(hasattr(studio_session, "StudioReverbSettings"))
        with tempfile.TemporaryDirectory() as temporary:
            package = _package_with_audio_output(Path(temporary))
            session = load_studio_session(package)
            save_studio_session(package, session)
            data = json.loads(studio_session_path(package).read_text(encoding="utf-8"))
            data["tracks"][0]["clips"][0]["effects"] = [
                {
                    "effect_id": "fx-reverb",
                    "kind": "reverb",
                    "enabled": True,
                    "settings": {
                        "room_height_m": -10,
                        "pre_delay_ms": -120,
                        "decay_ms": 99_999,
                        "dry_wet_percent": 250,
                        "early_high_hz": 3,
                    },
                }
            ]
            data["tracks"][0]["clips"][0]["media"] = {
                "fit_mode": "unknown",
                "scale_percent": "bad",
                "offset_x_percent": 999,
                "offset_y_percent": -999,
                "source_audio_enabled": True,
            }
            studio_session_path(package).write_text(json.dumps(data), encoding="utf-8")

            settings = load_studio_session(package).tracks[0].clips[0].effects[0].reverb

            self.assertEqual(settings.room_height_m, 1.0)
            self.assertEqual(settings.pre_delay_ms, -120)
            self.assertEqual(settings.decay_ms, 4_000)
            self.assertEqual(settings.dry_wet_percent, 100)
            self.assertEqual(settings.early_high_hz, 1_000)
            media = load_studio_session(package).tracks[0].clips[0].media
            self.assertEqual(media.fit_mode, "fit")
            self.assertEqual(media.scale_percent, 100)
            self.assertEqual(media.offset_x_percent, 100)
            self.assertEqual(media.offset_y_percent, -100)
            self.assertTrue(media.source_audio_enabled)

    def test_character_effect_settings_round_trip_and_clamp(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            package = _package_with_audio_output(Path(temporary))
            session = load_studio_session(package)
            track = session.tracks[0]
            clip = track.clips[0]
            effects = (
                studio_session.StudioEffect(
                    "fx-radio",
                    "radio_filter",
                    radio_filter=studio_session.StudioRadioFilterSettings(300, 3_400, 90),
                ),
                studio_session.StudioEffect(
                    "fx-ring",
                    "ring_modulator",
                    ring_modulator=studio_session.StudioRingModulatorSettings(75, 35),
                ),
                studio_session.StudioEffect(
                    "fx-bits",
                    "bitcrusher",
                    bitcrusher=studio_session.StudioBitcrusherSettings(8, 8_000, 55),
                ),
                studio_session.StudioEffect(
                    "fx-drive",
                    "distortion",
                    distortion=studio_session.StudioDistortionSettings(65, 45),
                ),
                studio_session.StudioEffect(
                    "fx-level",
                    "level_match",
                    level_match=studio_session.StudioLevelMatchSettings(85, 120, 8, -55),
                ),
            )
            edited = replace(
                session,
                tracks=(replace(track, clips=(replace(clip, effects=effects),)), *session.tracks[1:]),
            )
            save_studio_session(package, edited)

            restored = load_studio_session(package)

            self.assertEqual(restored.tracks[0].clips[0].effects, effects)
            data = json.loads(studio_session_path(package).read_text(encoding="utf-8"))
            data["tracks"][0]["clips"][0]["effects"][2]["settings"] = {
                "bit_depth": 2,
                "sample_rate_hz": 100,
                "mix_percent": 500,
            }
            studio_session_path(package).write_text(json.dumps(data), encoding="utf-8")
            clamped = load_studio_session(package).tracks[0].clips[0].effects[2].bitcrusher
            self.assertEqual(clamped, studio_session.StudioBitcrusherSettings(4, 2_000, 100))

    def test_legacy_mix_state_migrates_to_non_destructive_full_length_clips(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            package = _package_with_audio_output(Path(temporary))
            session_path = studio_session_path(package)
            session_path.write_text(
                json.dumps(
                    {
                        "version": 1,
                        "song_id": package.song_id,
                        "tracks": {
                            "original_vocal": {"muted": True, "volume_percent": 125},
                            "instrumental": {"muted": False, "volume_percent": 80},
                            "converted_vocal": {"muted": False, "volume_percent": 175},
                        },
                    }
                ),
                encoding="utf-8",
            )

            restored = load_studio_session(package)

            self.assertEqual(len(restored.tracks), 3)
            self.assertEqual(restored.original_vocal, StudioTrackState(True, 125))
            self.assertEqual(restored.instrumental, StudioTrackState(False, 80))
            self.assertEqual(restored.converted_vocal, StudioTrackState(False, 175))
            self.assertEqual([len(track.clips) for track in restored.tracks], [1, 1, 1])
            self.assertEqual(session_duration_ms(restored), 2_000)

    def test_timeline_edits_persist_without_modifying_source_audio(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            package = _package_with_audio_output(Path(temporary))
            session = load_studio_session(package)
            original_track = session.tracks[0]
            original_clip = original_track.clips[0]
            source_path = resolve_studio_asset(package, original_clip.asset)
            self.assertIsNotNone(source_path)
            source_bytes = source_path.read_bytes()

            edited = trim_studio_clip(
                session,
                original_clip.clip_id,
                source_start_ms=250,
                source_end_ms=1_250,
            )
            edited = move_studio_clip(
                edited,
                original_clip.clip_id,
                track_id=original_track.track_id,
                timeline_start_ms=3_000,
            )
            save_studio_session(package, edited)
            restored = load_studio_session(package)
            restored_clip = restored.tracks[0].clips[0]

            self.assertEqual(restored_clip.source_start_ms, 250)
            self.assertEqual(restored_clip.source_end_ms, 1_250)
            self.assertEqual(restored_clip.timeline_start_ms, 3_000)
            self.assertEqual(source_path.read_bytes(), source_bytes)
            saved_data = json.loads(studio_session_path(package).read_text(encoding="utf-8"))
            self.assertEqual(saved_data["version"], STUDIO_SESSION_VERSION)
            self.assertIsInstance(saved_data["tracks"], list)

    def test_sound_pool_contains_all_output_roles_and_converted_takes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            package = _package_with_audio_output(Path(temporary))

            assets = studio_sound_pool(package)

            self.assertEqual(len(assets), 4)
            self.assertEqual(
                [asset.reference.role for asset in assets],
                ["original_vocal", "instrumental", "converted_vocal", "converted_vocal"],
            )
            self.assertTrue(all(asset.can_remove for asset in assets))
            self.assertTrue(all(resolve_studio_asset(package, asset.reference) == asset.path for asset in assets))

    def test_sound_pool_includes_compact_rvc_output_names(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            package = _package_with_audio_output(Path(temporary))
            compact = package.active_output.job_dir / "rvc_p0_0123456789.wav"
            sf.write(compact, np.full(16_000, 0.4, dtype=np.float32), 8_000)
            VocalProjectStore().register_take(
                package.active_output.job_dir,
                compact,
                conversion=VocalConversionSettings(
                    voice_model="models/voice-a.pth",
                    index_file="models/voice-a.index",
                    pitch=-12,
                    requested_device="cuda:0",
                    effective_device="cuda:0",
                    f0_method="rmvpe",
                ),
            )

            converted = [
                asset
                for asset in studio_sound_pool(package)
                if asset.reference.role == "converted_vocal"
            ]

            self.assertIn(compact.resolve(), [asset.path for asset in converted])
            compact_asset = next(asset for asset in converted if asset.path == compact.resolve())
            self.assertIsNotNone(compact_asset.take)
            self.assertEqual(compact_asset.take.label, "voice-a / Pitch -12")
            reference = compact_asset.reference
            self.assertEqual(resolve_studio_asset(package, reference), compact.resolve())

    def test_asset_can_be_added_and_moved_between_tracks_without_copying_it(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            package = _package_with_audio_output(Path(temporary))
            session = load_studio_session(package)
            asset = studio_sound_pool(package)[0]
            before = asset.path.read_bytes()

            added = add_studio_clip(
                session,
                session.tracks[2].track_id,
                asset.reference,
                asset.duration_ms,
                timeline_start_ms=4_000,
            )
            new_clip = added.tracks[2].clips[-1]
            moved = move_studio_clip(
                added,
                new_clip.clip_id,
                track_id=session.tracks[0].track_id,
                timeline_start_ms=5_000,
            )

            self.assertEqual(len(moved.tracks[0].clips), 2)
            self.assertEqual(len(moved.tracks[2].clips), 1)
            self.assertEqual(asset.path.read_bytes(), before)

    def test_invalid_or_out_of_range_session_data_uses_safe_values(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            source = project / "source.wav"
            source.write_bytes(b"source")
            store = SongPackageStore(project / "workspace" / "library" / "songs", project)
            package, _created = store.import_audio(source, title="Song")
            session_path = studio_session_path(package)
            session_path.write_text(
                json.dumps({"version": 2, "tracks": [{"track_id": "", "role": "bad"}]}),
                encoding="utf-8",
            )

            self.assertEqual(load_studio_session(package), StudioSession())

            session_path.write_text("not-json", encoding="utf-8")
            self.assertEqual(load_studio_session(package), StudioSession())

    def test_version_two_timeline_migrates_with_safe_inspector_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            package = _package_with_audio_output(Path(temporary))
            output = package.active_output
            studio_session_path(package).write_text(
                json.dumps(
                    {
                        "version": 2,
                        "song_id": package.song_id,
                        "tracks": [
                            {
                                "track_id": "track-original-vocal",
                                "name": "Original Vocal",
                                "role": "original_vocal",
                                "volume_percent": 125,
                                "clips": [
                                    {
                                        "clip_id": "clip-original",
                                        "asset": {
                                            "output_id": output.output_id,
                                            "role": "original_vocal",
                                            "filename": "",
                                        },
                                        "timeline_start_ms": 250,
                                        "source_start_ms": 100,
                                        "source_end_ms": 1_100,
                                        "gain_db": -2.5,
                                    }
                                ],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            restored = load_studio_session(package)

            track = restored.tracks[0]
            clip = track.clips[0]
            self.assertEqual(track.pan_percent, 0)
            self.assertFalse(clip.muted)
            self.assertEqual((clip.fade_in_ms, clip.fade_out_ms), (0, 0))
            self.assertEqual(clip.gain_db, -2.5)

    def test_new_inspector_properties_round_trip_in_version_three_session(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            package = _package_with_audio_output(Path(temporary))
            session = load_studio_session(package)
            track = session.tracks[0]
            clip = track.clips[0]
            edited_clip = replace(clip, muted=True, fade_in_ms=250, fade_out_ms=400)
            edited_track = replace(track, pan_percent=-35, clips=(edited_clip,))
            edited = replace(session, tracks=(edited_track, *session.tracks[1:]))

            save_studio_session(package, edited)
            restored = load_studio_session(package)

            self.assertEqual(restored.tracks[0].pan_percent, -35)
            self.assertTrue(restored.tracks[0].clips[0].muted)
            self.assertEqual(
                (restored.tracks[0].clips[0].fade_in_ms, restored.tracks[0].clips[0].fade_out_ms),
                (250, 400),
            )

    def test_local_video_appears_in_pool_timeline_and_persists_collapsed_state(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            package = _package_with_audio_output(root)
            source_video = root / "reference.mp4"
            source_video.write_bytes(b"video")
            imported = VideoSourceStore().import_file(package, source_video)

            session = load_studio_session(package)
            assets = studio_sound_pool(package)
            video_asset = next(asset for asset in assets if asset.media_kind == "video")

            self.assertEqual(session.tracks[0].role, TRACK_VIDEO)
            self.assertEqual(session.tracks[0].clips[0].asset, video_asset.reference)
            self.assertEqual(resolve_studio_asset(package, video_asset.reference), imported.path)

            session = split_studio_clip(
                session,
                session.tracks[0].clips[0].clip_id,
                timeline_position_ms=1_000,
            )
            video_track = replace(session.tracks[0], collapsed=True)
            save_studio_session(package, replace(session, tracks=(video_track, *session.tracks[1:])))
            restored = load_studio_session(package)

            self.assertTrue(restored.tracks[0].collapsed)
            self.assertEqual(restored.tracks[0].role, TRACK_VIDEO)
            self.assertEqual(len(restored.tracks[0].clips), 2)

    def test_local_image_uses_a_five_second_default_media_clip(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            package = _package_with_audio_output(root)
            source_image = root / "cover.png"
            source_image.write_bytes(b"image")
            VideoSourceStore().import_file(package, source_image)

            session = load_studio_session(package)
            assets = studio_sound_pool(package)
            image_asset = next(asset for asset in assets if asset.media_kind == "image")
            media_track = next(track for track in session.tracks if track.role == TRACK_VIDEO)

            self.assertEqual(image_asset.clip_duration_ms, 5_000)
            self.assertGreaterEqual(image_asset.duration_ms, image_asset.clip_duration_ms)
            self.assertEqual(media_track.name, "Media")
            self.assertEqual(media_track.clips[0].duration_ms, 5_000)

    def test_media_settings_round_trip_and_version_five_uses_safe_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            package = _package_with_audio_output(root)
            source_image = root / "cover.png"
            source_image.write_bytes(b"image")
            VideoSourceStore().import_file(package, source_image)
            session = load_studio_session(package)
            media_track = next(track for track in session.tracks if track.role == TRACK_VIDEO)
            settings = StudioMediaSettings(
                fit_mode=MEDIA_FILL,
                scale_percent=135,
                offset_x_percent=-20,
                offset_y_percent=15,
                source_audio_enabled=True,
            )
            edited_track = replace(
                media_track,
                clips=(replace(media_track.clips[0], media=settings),),
            )

            save_studio_session(
                package,
                replace(
                    session,
                    tracks=tuple(
                        edited_track if track.track_id == media_track.track_id else track
                        for track in session.tracks
                    ),
                ),
            )
            restored = load_studio_session(package)
            restored_track = next(track for track in restored.tracks if track.role == TRACK_VIDEO)
            self.assertEqual(restored_track.clips[0].media, settings)

            saved = json.loads(studio_session_path(package).read_text(encoding="utf-8"))
            saved["version"] = 5
            next(track for track in saved["tracks"] if track["role"] == TRACK_VIDEO)["clips"][0].pop(
                "media"
            )
            studio_session_path(package).write_text(json.dumps(saved), encoding="utf-8")

            migrated = load_studio_session(package)
            migrated_track = next(track for track in migrated.tracks if track.role == TRACK_VIDEO)
            self.assertEqual(migrated_track.clips[0].media, StudioMediaSettings())

    def test_video_only_session_restores_required_audio_tracks(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            package = _package_with_audio_output(root)
            source_video = root / "reference.mp4"
            source_video.write_bytes(b"video")
            VideoSourceStore().import_file(package, source_video)
            session = load_studio_session(package)
            video_track = next(track for track in session.tracks if track.role == TRACK_VIDEO)
            save_studio_session(package, session)
            data = json.loads(studio_session_path(package).read_text(encoding="utf-8"))
            data["tracks"] = [
                track for track in data["tracks"] if track["role"] == TRACK_VIDEO
            ]
            studio_session_path(package).write_text(json.dumps(data), encoding="utf-8")

            restored = load_studio_session(package)

            self.assertEqual(restored.tracks[0], video_track)
            self.assertEqual(
                [track.role for track in restored.tracks],
                [
                    TRACK_VIDEO,
                    TRACK_ORIGINAL_VOCAL,
                    TRACK_INSTRUMENTAL,
                    TRACK_CONVERTED_VOCAL,
                ],
            )
            self.assertTrue(all(restored.tracks[index].clips for index in (1, 2, 3)))

    def test_partial_session_preserves_edits_and_backfills_missing_roles(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            package = _package_with_audio_output(Path(temporary))
            session = load_studio_session(package)
            original = replace(session.tracks[0], volume_percent=137)
            custom = StudioTrack("track-custom", "Custom")
            partial = replace(session, tracks=(original, custom))

            save_studio_session(package, partial)
            restored = load_studio_session(package)

            self.assertEqual(restored.tracks[0].volume_percent, 137)
            self.assertIn(custom, restored.tracks)
            roles = [track.role for track in restored.tracks]
            self.assertEqual(roles.count(TRACK_ORIGINAL_VOCAL), 1)
            self.assertEqual(roles.count(TRACK_INSTRUMENTAL), 1)
            self.assertEqual(roles.count(TRACK_CONVERTED_VOCAL), 1)


def _package_with_audio_output(root: Path):
    source = root / "source.wav"
    sf.write(source, np.full(16_000, 0.1, dtype=np.float32), 8_000)
    store = SongPackageStore(root / "workspace" / "library" / "songs", root)
    package, _created = store.import_audio(source, title="Song")
    output_dir = root / "vocal-output"
    output_dir.mkdir()
    sf.write(output_dir / "vocals.wav", np.full(16_000, 0.5, dtype=np.float32), 8_000)
    sf.write(output_dir / "no_vocals.wav", np.full(16_000, 0.1, dtype=np.float32), 8_000)
    sf.write(output_dir / "vocals_rvc_first.wav", np.full(16_000, 0.2, dtype=np.float32), 8_000)
    sf.write(output_dir / "vocals_rvc_second.wav", np.full(16_000, 0.3, dtype=np.float32), 8_000)
    package = store.attach_output(package.song_id, output_dir, "Run 01")
    return store.activate_converted_output(
        package.song_id,
        output_dir,
        output_dir / "vocals_rvc_second.wav",
    )


if __name__ == "__main__":
    unittest.main()
