from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import soundfile as sf

from jang_app.pipeline.vocal_cleanup import (
    _render_deecho_segment,
    _render_denoise_segment,
    discard_vocal_cleanup_preview,
    preview_vocal_cleanup,
    render_vocal_cleanup,
)
from jang_app.services.vocal_cleanup import (
    VOCAL_CLEANUP_EFFECT_DEECHO,
    VocalCleanupProject,
)
from jang_app.services.vocal_cleanup_store import VocalCleanupStore, VocalCleanupStoreError


class VocalCleanupStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.job_dir = self.root / "result"
        self.job_dir.mkdir()
        self.source = self.job_dir / "vocals.wav"
        samples = np.zeros((44_100, 2), dtype=np.float32)
        samples[:, 0] = np.linspace(-0.5, 0.5, len(samples), dtype=np.float32)
        samples[:, 1] = samples[:, 0]
        sf.write(self.source, samples, 44_100, subtype="FLOAT")
        self.store = VocalCleanupStore()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_project_round_trip_preserves_region_and_result(self) -> None:
        project = self.store.load(self.job_dir, self.source)
        processed, removed = self._preview_segments("first", 13_230)
        project = self.store.import_preview(
            self.job_dir,
            project,
            start_ms=100,
            end_ms=400,
            effect="dereverb",
            strength="standard",
            processed_segment_path=processed,
            removed_segment_path=removed,
        )
        result_path = self.store.create_result_path(self.job_dir)
        sf.write(result_path, np.zeros((44_100, 2), dtype=np.float32), 44_100)
        project = self.store.register_result(self.job_dir, project, result_path)

        restored = self.store.load(self.job_dir, self.source)

        self.assertEqual(len(restored.regions), 1)
        self.assertEqual(restored.regions[0].strength, "standard")
        self.assertTrue(restored.regions[0].processed_segment_path.is_file())
        self.assertEqual(len(restored.results), 1)
        self.assertTrue(restored.results[0].path.is_file())

    def test_overlapping_regions_are_rejected(self) -> None:
        project = self.store.load(self.job_dir, self.source)
        processed, removed = self._preview_segments("first", 13_230)
        project = self.store.import_preview(
            self.job_dir,
            project,
            start_ms=100,
            end_ms=400,
            effect="dereverb",
            strength="standard",
            processed_segment_path=processed,
            removed_segment_path=removed,
        )
        processed, removed = self._preview_segments("second", 8_820)

        with self.assertRaises(VocalCleanupStoreError):
            self.store.import_preview(
                self.job_dir,
                project,
                start_ms=300,
                end_ms=500,
                effect="dereverb",
                strength="standard",
                processed_segment_path=processed,
                removed_segment_path=removed,
            )
        self.assertTrue(processed.is_file())
        self.assertTrue(removed.is_file())

    def test_noise_removal_region_round_trip_is_supported(self) -> None:
        project = self.store.load(self.job_dir, self.source)
        processed, removed = self._preview_segments("denoise", 13_230)

        project = self.store.import_preview(
            self.job_dir,
            project,
            start_ms=100,
            end_ms=400,
            effect="denoise",
            strength="conservative",
            processed_segment_path=processed,
            removed_segment_path=removed,
        )
        restored = self.store.load(self.job_dir, self.source)

        self.assertEqual(project.regions[0].effect, "denoise")
        self.assertEqual(restored.regions[0].effect, "denoise")

    def test_noise_removal_preview_dispatches_to_denoise_renderer(self) -> None:
        project = self.store.load(self.job_dir, self.source)

        def render_segment(_source, processed, removed, **_kwargs) -> None:
            samples = np.zeros((13_230, 2), dtype=np.float32)
            sf.write(processed, samples, 44_100, subtype="FLOAT")
            sf.write(removed, samples, 44_100, subtype="FLOAT")

        def compose(_source, _regions, processed, removed, **_kwargs) -> None:
            samples = np.zeros((44_100, 2), dtype=np.float32)
            sf.write(processed, samples, 44_100, subtype="FLOAT")
            sf.write(removed, samples, 44_100, subtype="FLOAT")

        with (
            patch(
                "jang_app.pipeline.vocal_cleanup._render_denoise_segment",
                side_effect=render_segment,
            ) as denoise,
            patch("jang_app.pipeline.vocal_cleanup._render_dereverb_segment") as dereverb,
            patch("jang_app.pipeline.vocal_cleanup._compose_audio", side_effect=compose),
        ):
            preview = preview_vocal_cleanup(
                self.source,
                self.job_dir,
                project.regions,
                start_ms=100,
                end_ms=400,
                effect="denoise",
                strength="standard",
            )

        self.assertEqual(preview.effect, "denoise")
        denoise.assert_called_once()
        dereverb.assert_not_called()
        discard_vocal_cleanup_preview(preview)

    def test_echo_removal_preview_dispatches_to_deecho_renderer(self) -> None:
        project = self.store.load(self.job_dir, self.source)

        def render_segment(_source, processed, removed, **_kwargs) -> None:
            samples = np.zeros((13_230, 2), dtype=np.float32)
            sf.write(processed, samples, 44_100, subtype="FLOAT")
            sf.write(removed, samples, 44_100, subtype="FLOAT")

        def compose(_source, _regions, processed, removed, **_kwargs) -> None:
            samples = np.zeros((44_100, 2), dtype=np.float32)
            sf.write(processed, samples, 44_100, subtype="FLOAT")
            sf.write(removed, samples, 44_100, subtype="FLOAT")

        with (
            patch(
                "jang_app.pipeline.vocal_cleanup._render_deecho_segment",
                side_effect=render_segment,
            ) as deecho,
            patch("jang_app.pipeline.vocal_cleanup._render_dereverb_segment") as dereverb,
            patch("jang_app.pipeline.vocal_cleanup._render_denoise_segment") as denoise,
            patch("jang_app.pipeline.vocal_cleanup._compose_audio", side_effect=compose),
        ):
            preview = preview_vocal_cleanup(
                self.source,
                self.job_dir,
                project.regions,
                start_ms=100,
                end_ms=400,
                effect=VOCAL_CLEANUP_EFFECT_DEECHO,
                strength="standard",
            )

        self.assertEqual(preview.effect, VOCAL_CLEANUP_EFFECT_DEECHO)
        deecho.assert_called_once()
        dereverb.assert_not_called()
        denoise.assert_not_called()
        discard_vocal_cleanup_preview(preview)

    def test_noise_removal_uses_managed_short_path_workspace(self) -> None:
        processed = self.root / "denoised-segment.wav"
        removed = self.root / "removed-segment.wav"

        def render(source, target, _strength, *, progress=None, **_kwargs):
            shutil.copyfile(source, target)
            if progress is not None:
                progress(100)
            return target

        with (
            patch(
                "jang_app.pipeline.vocal_cleanup.TOOL_WORKSPACE_DIR",
                self.root / "tool-workspaces",
            ),
            patch(
                "jang_app.pipeline.vocal_cleanup.render_denoised_audio",
                side_effect=render,
            ),
        ):
            _render_denoise_segment(
                self.source,
                processed,
                removed,
                start_ms=100,
                end_ms=400,
                strength="standard",
                progress_callback=None,
            )

        self.assertTrue(processed.is_file())
        self.assertTrue(removed.is_file())
        self.assertEqual(
            list((self.root / "tool-workspaces" / "vocaldenoise").glob("j_*")),
            [],
        )

    def test_echo_removal_uses_managed_short_path_workspace(self) -> None:
        processed = self.root / "deechoed-segment.wav"
        removed = self.root / "removed-echo.wav"

        def run(command, **_kwargs):
            output = Path(command[command.index("--output_dir") + 1])
            output.mkdir(parents=True, exist_ok=True)
            sf.write(
                output / "i_(No Echo)_model.wav",
                np.zeros((44_100, 2), dtype=np.float32),
                44_100,
                subtype="FLOAT",
            )
            sf.write(
                output / "i_(Instrumental)_model.wav",
                np.zeros((44_100, 2), dtype=np.float32),
                44_100,
                subtype="FLOAT",
            )
            return type("Completed", (), {"returncode": 0})()

        with (
            patch(
                "jang_app.pipeline.vocal_cleanup.TOOL_WORKSPACE_DIR",
                self.root / "tool-workspaces",
            ),
            patch("jang_app.pipeline.vocal_cleanup.require_roformer_tools"),
            patch("jang_app.pipeline.vocal_cleanup.prepare_roformer_model_assets"),
            patch("jang_app.pipeline.vocal_cleanup.run_command", side_effect=run),
        ):
            _render_deecho_segment(
                self.source,
                processed,
                removed,
                start_ms=100,
                end_ms=400,
                strength="standard",
                progress_callback=None,
            )

        self.assertTrue(processed.is_file())
        self.assertTrue(removed.is_file())
        self.assertEqual(
            list((self.root / "tool-workspaces" / "vocaldeecho").glob("j_*")),
            [],
        )

    def test_render_keeps_length_channels_and_unselected_audio(self) -> None:
        project = self.store.load(self.job_dir, self.source)
        processed = self.root / "processed.wav"
        removed = self.root / "removed.wav"
        replacement = np.full((13_230, 2), 0.25, dtype=np.float32)
        sf.write(processed, replacement, 44_100, subtype="FLOAT")
        sf.write(removed, replacement, 44_100, subtype="FLOAT")
        project = self.store.import_preview(
            self.job_dir,
            project,
            start_ms=400,
            end_ms=700,
            effect="dereverb",
            strength="strong",
            processed_segment_path=processed,
            removed_segment_path=removed,
        )
        target = self.store.create_result_path(self.job_dir)

        render_vocal_cleanup(project, target)

        source_audio, source_rate = sf.read(self.source, always_2d=True)
        rendered, rendered_rate = sf.read(target, always_2d=True)
        self.assertEqual(rendered_rate, source_rate)
        self.assertEqual(rendered.shape, source_audio.shape)
        np.testing.assert_allclose(rendered[:17_000], source_audio[:17_000], atol=1e-6)
        np.testing.assert_allclose(rendered[32_000:], source_audio[32_000:], atol=1e-6)
        self.assertGreater(float(np.max(np.abs(rendered[20_000:29_000] - source_audio[20_000:29_000]))), 0.1)

    def _preview_segments(self, prefix: str, frames: int) -> tuple[Path, Path]:
        processed = self.root / f"{prefix}-processed.wav"
        removed = self.root / f"{prefix}-removed.wav"
        samples = np.zeros((frames, 2), dtype=np.float32)
        sf.write(processed, samples, 44_100, subtype="FLOAT")
        sf.write(removed, samples, 44_100, subtype="FLOAT")
        return processed, removed


if __name__ == "__main__":
    unittest.main()
