from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import soundfile as sf
from unittest.mock import patch

from jang_app.services.audio_player import AudioPlayer, PreparedPlaybackAudio
from jang_app.services.studio_character_fx_presets import character_effect
from jang_app.services.studio_session import StudioEffect, StudioReverbSettings


class AudioPlayerTests(unittest.TestCase):
    def test_duration_supports_float32_wav(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "float-output.wav"
            sf.write(
                path,
                np.zeros((44_100, 2), dtype=np.float32),
                44_100,
                subtype="FLOAT",
            )

            self.assertEqual(AudioPlayer().duration_ms(path), 1_000)

    def test_prepared_audio_replaces_the_live_buffer_without_restarting_the_sink(self) -> None:
        player = AudioPlayer()
        player._tracks = [np.zeros((4_000, 2), dtype=np.float32)]
        player._volumes = [1.0]
        player._frame_index = 1_000
        player._duration_frames = 4_000
        player._duration_ms = 90
        replacement = PreparedPlaybackAudio(
            (np.ones((5_000, 2), dtype=np.float32),),
            5_000,
        )

        with patch.object(player, "is_playing", return_value=True), patch.object(
            player,
            "stop",
        ) as stop:
            replaced = player.replace_prepared(replacement, (0.75,), crossfade_ms=20)

        self.assertTrue(replaced)
        stop.assert_not_called()
        self.assertIs(player._tracks[0], replacement.tracks[0])
        self.assertEqual(player._volumes, [0.75])
        self.assertEqual(player._duration_frames, 5_000)
        self.assertIsNotNone(player._transition)

    def test_buffer_replacement_crossfades_old_audio_into_new_audio(self) -> None:
        player = AudioPlayer()
        old_track = np.zeros((2_000, 2), dtype=np.float32)
        new_track = np.ones((2_000, 2), dtype=np.float32)
        player._tracks = [old_track]
        player._volumes = [1.0]
        player._frame_index = 500
        player._duration_frames = 2_000
        player._duration_ms = 45

        with patch.object(player, "is_playing", return_value=True):
            player.replace_prepared(
                PreparedPlaybackAudio((new_track,), 2_000),
                crossfade_ms=10,
            )

        blended = player._crossfade_replacement(
            np.ones((441, 2), dtype=np.float32),
            500,
            441,
        )

        self.assertAlmostEqual(float(blended[0, 0]), 0.0, places=4)
        self.assertGreater(float(blended[-1, 0]), 0.99)
        self.assertIsNone(player._transition)

    def test_reverb_settings_replace_the_live_chain_without_replacing_tracks(self) -> None:
        player = AudioPlayer()
        player._tracks = [np.ones((2_000, 2), dtype=np.float32)]
        player._volumes = [1.0]
        dry = StudioEffect(
            "fx-1",
            "reverb",
            reverb=StudioReverbSettings(dry_wet_percent=0),
        )
        wet = StudioEffect(
            "fx-1",
            "reverb",
            reverb=StudioReverbSettings(dry_wet_percent=100),
        )

        self.assertTrue(player.set_effect_chains(((dry,),)))
        processor = player._effect_chains[0]
        dry_chunk = player._mix_live_chunk(0, 128)
        self.assertTrue(player.set_effect_chains(((wet,),)))
        wet_chunk = player._mix_live_chunk(128, 128)

        self.assertIs(player._effect_chains[0], processor)
        self.assertGreater(float(np.mean(dry_chunk)), 0.99)
        self.assertLess(float(np.mean(np.abs(wet_chunk))), 0.01)

    def test_character_effect_settings_update_the_existing_live_chain(self) -> None:
        player = AudioPlayer()
        player._tracks = [np.linspace(-0.8, 0.8, 2_000, dtype=np.float32)[:, None]]
        player._volumes = [1.0]
        subtle = character_effect("distortion", "warm")
        strong = StudioEffect(
            subtle.effect_id,
            subtle.kind,
            distortion=replace(subtle.distortion, drive_percent=100, mix_percent=100),
        )

        self.assertTrue(player.set_effect_chains(((subtle,),)))
        chain = player._effect_chains[0]
        player._mix_live_chunk(0, 128)
        self.assertTrue(player.set_effect_chains(((strong,),)))
        processed = player._mix_live_chunk(128, 128)

        self.assertIs(player._effect_chains[0], chain)
        self.assertTrue(np.isfinite(processed).all())

    def test_paused_prepared_audio_resumes_without_reloading_track_arrays(self) -> None:
        player = AudioPlayer()
        track = np.ones((44_100, 2), dtype=np.float32)
        player._tracks = [track]
        player._volumes = [1.0]
        player._effect_chains = []
        player._duration_frames = 44_100
        player._duration_ms = 1_000

        with patch.object(player, "_start_output") as start_output:
            resumed = player.resume(425, (0.65,))

        self.assertTrue(resumed)
        self.assertIs(player._tracks[0], track)
        self.assertEqual(player._volumes, [0.65])
        self.assertEqual(player._frame_index, 18_742)
        start_output.assert_called_once_with()

    def test_background_preparation_can_replace_a_paused_buffer(self) -> None:
        player = AudioPlayer()
        replacement = PreparedPlaybackAudio(
            (np.ones((22_050, 2), dtype=np.float32),),
            22_050,
        )

        replaced = player.set_prepared(replacement, (0.5,))

        self.assertTrue(replaced)
        self.assertIs(player._tracks[0], replacement.tracks[0])
        self.assertEqual(player._volumes, [0.5])
        self.assertEqual(player._duration_ms, 500)

    def test_prepared_audio_keeps_studio_gain_above_the_legacy_ceiling(self) -> None:
        player = AudioPlayer()
        prepared = PreparedPlaybackAudio(
            (np.ones((100, 2), dtype=np.float32),),
            100,
        )

        self.assertTrue(player.set_prepared(prepared, (32.0,)))

        self.assertEqual(player._volumes, [32.0])

    def test_compact_track_starts_at_its_timeline_offset(self) -> None:
        player = AudioPlayer()
        prepared = PreparedPlaybackAudio(
            (np.ones((100, 2), dtype=np.float32),),
            200,
            track_start_frames=(50,),
        )
        self.assertTrue(player.set_prepared(prepared))

        before = player._mix_live_chunk(0, 50)
        active = player._mix_live_chunk(50, 100)

        self.assertTrue(np.allclose(before, 0.0))
        self.assertTrue(np.allclose(active, 1.0))

    def test_inactive_effect_chain_is_not_processed_outside_clip_range(self) -> None:
        player = AudioPlayer()
        prepared = PreparedPlaybackAudio(
            (np.ones((100, 2), dtype=np.float32),),
            1_000,
            track_start_frames=(200,),
            track_effect_end_frames=(300,),
        )
        self.assertTrue(player.set_prepared(prepared))

        with patch.object(player._effect_chains[0], "process") as process:
            player._mix_live_chunk(0, 100)
            player._mix_live_chunk(400, 100)

        process.assert_not_called()

    def test_position_uses_audio_device_clock_instead_of_wall_clock(self) -> None:
        player = AudioPlayer()
        player._audio_sink = SimpleNamespace(processedUSecs=lambda: 425_000)
        player._start_ms = 100
        player._duration_ms = 1_000

        self.assertEqual(player.position_ms(), 525)

    def test_partial_device_write_keeps_unwritten_pcm_for_the_next_tick(self) -> None:
        player = AudioPlayer()
        player._audio_sink = SimpleNamespace(
            bytesFree=lambda: 16,
            bufferSize=lambda: 16,
        )
        writes = iter((8, 0))
        player._audio_device = SimpleNamespace(write=lambda _audio: next(writes))
        player._pending_pcm = b"\0" * 16
        player._duration_frames = 100
        player._duration_ms = 1_000
        player._output_start_frame = 0

        with patch.object(player, "position_ms", return_value=0), patch.object(
            player._renderer,
            "ensure_lookahead",
        ):
            player._feed_audio()

        self.assertEqual(player._pending_pcm, b"\0" * 8)
        self.assertEqual(player._frame_index, 2)

    def test_ui_feed_only_drains_background_rendered_audio(self) -> None:
        player = AudioPlayer()
        player._audio_sink = SimpleNamespace(
            bytesFree=lambda: 16,
            bufferSize=lambda: 16,
        )
        writes = iter((16, 0))
        player._audio_device = SimpleNamespace(write=lambda _audio: next(writes))
        player._duration_frames = 100
        player._duration_ms = 1_000
        rendered = SimpleNamespace(audio=np.ones((4, 2), dtype=np.float32))

        with patch.object(player, "position_ms", return_value=0), patch.object(
            player,
            "_mix_live_chunk",
            side_effect=AssertionError("UI thread must not mix audio"),
        ), patch.object(
            player._renderer,
            "ensure_lookahead",
        ), patch.object(
            player._renderer,
            "take_ready",
            side_effect=(rendered, None),
        ):
            player._feed_audio()

        self.assertEqual(player._frame_index, 4)


if __name__ == "__main__":
    unittest.main()
