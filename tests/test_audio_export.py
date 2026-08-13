from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import soundfile as sf

from jang_app.services.audio_export import AudioMixSource, export_audio_file, export_mix
from jang_app.services.audio_mix_processing import process_mix_source
from jang_app.services.studio_character_fx_presets import character_effect_chain
from jang_app.services.studio_session import (
    StudioEffect,
    StudioLevelMatchSettings,
    StudioReverbSettings,
)


class AudioExportTests(unittest.TestCase):
    def test_export_reads_the_cached_pitch_render_for_a_shifted_clip(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.wav"
            shifted = root / "shifted.wav"
            output = root / "mix.wav"
            sf.write(source, np.full(800, 0.1, dtype=np.float32), 8_000)
            sf.write(shifted, np.full(800, 0.3, dtype=np.float32), 8_000)

            with patch(
                "jang_app.services.audio_export.prepare_pitch_shifted_audio",
                return_value=shifted,
            ) as prepare:
                export_mix(
                    (AudioMixSource("Shifted", source, pitch_semitones=12),),
                    output,
                )

            rendered, _sample_rate = sf.read(output, dtype="float32")
            prepare.assert_called_once_with(source, 12)
            self.assertAlmostEqual(float(np.mean(rendered)), 0.3, places=3)

    def test_exported_reverb_keeps_the_effect_tail(self) -> None:
        self.assertIn("effects", AudioMixSource.__dataclass_fields__)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "impulse.wav"
            output = root / "reverb.wav"
            impulse = np.zeros(800, dtype=np.float32)
            impulse[0] = 0.5
            sf.write(source, impulse, 8_000, subtype="FLOAT")
            effect = StudioEffect(
                "fx-reverb",
                "reverb",
                reverb=StudioReverbSettings(decay_ms=300, dry_wet_percent=60),
            )

            export_mix((AudioMixSource("Reverb", source, effects=(effect,)),), output)
            rendered, sample_rate = sf.read(output, dtype="float32")

            self.assertEqual(sample_rate, 8_000)
            self.assertGreater(len(rendered), len(impulse))
            self.assertGreater(float(np.max(np.abs(rendered[len(impulse) :]))), 0.0)

    def test_mix_processing_applies_fades_and_constant_power_pan(self) -> None:
        source = np.ones((1_000, 1), dtype=np.float32)

        processed = process_mix_source(
            source,
            1_000,
            fade_in_ms=100,
            fade_out_ms=200,
            pan_percent=100,
        )

        self.assertEqual(processed.shape, (1_000, 2))
        self.assertAlmostEqual(float(processed[0, 1]), 0.0, places=5)
        self.assertGreater(float(processed[100, 1]), 1.3)
        self.assertAlmostEqual(float(processed[-1, 1]), 0.0, places=5)
        self.assertAlmostEqual(float(np.max(np.abs(processed[:, 0]))), 0.0, places=5)

    def test_mix_processing_keeps_studio_gain_above_the_legacy_ceiling(self) -> None:
        source = np.full((8, 1), 0.001, dtype=np.float32)

        processed = process_mix_source(source, 8_000, volume=32.0)

        self.assertAlmostEqual(float(processed[0, 0]), 0.032, places=5)

    def test_mix_processing_applies_character_chain_in_declared_order(self) -> None:
        source = np.linspace(-0.5, 0.5, 8_000, dtype=np.float32)[:, None]
        effects = character_effect_chain("broken_robot")

        processed = process_mix_source(source, 8_000, effects=effects)

        self.assertEqual(processed.shape, source.shape)
        self.assertTrue(np.isfinite(processed).all())
        self.assertGreater(float(np.max(np.abs(processed - source))), 0.05)

    def test_export_level_match_uses_optional_reference_audio(self) -> None:
        source = np.full((8_000, 1), 0.2, dtype=np.float32)
        reference = np.full((8_000, 1), 0.4, dtype=np.float32)
        effect = StudioEffect(
            "fx-level",
            "level_match",
            level_match=StudioLevelMatchSettings(100, 100, 12, -60),
        )

        processed = process_mix_source(
            source,
            8_000,
            effects=(effect,),
            reference_audio=reference,
        )

        self.assertAlmostEqual(float(np.mean(processed)), 0.4, places=2)

    def test_export_uses_the_same_output_ceiling_as_realtime_playback(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.wav"
            output = root / "mix.wav"
            sf.write(source, np.array([0.8, 0.2], dtype=np.float32), 8000, subtype="FLOAT")

            export_mix(
                (AudioMixSource("One", source), AudioMixSource("Two", source)),
                output,
            )
            mixed, _sample_rate = sf.read(output, dtype="float32")

            self.assertAlmostEqual(float(mixed[0]), 1.0, places=4)
            self.assertAlmostEqual(float(mixed[1]), 0.4, places=3)

    def test_track_export_preserves_display_title_and_uses_numbered_duplicates(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.wav"
            source.write_bytes(b"audio")
            output_dir = root / "exports"

            first = export_audio_file("윤하 - Instrumental", source, output_dir)
            second = export_audio_file("윤하 - Instrumental", source, output_dir)

            self.assertEqual(first.name, "윤하 - Instrumental.wav")
            self.assertEqual(second.name, "윤하 - Instrumental (2).wav")


if __name__ == "__main__":
    unittest.main()
