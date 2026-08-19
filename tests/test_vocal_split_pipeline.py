from __future__ import annotations

import tempfile
import unittest
import wave
from pathlib import Path
from jang_app.pipeline.vocal_split import (
    VocalSplitError,
    _find_vocal_split_outputs,
    split_selected_vocal,
)
from jang_app.services.vocal_split_assets import VOCAL_SPLIT_MODEL_SIZE, vocal_split_asset_status
from jang_app.services.vocal_split import VocalReferenceRegion
from jang_app.services.vocal_split_store import VocalSplitStore


class VocalSplitPipelineTests(unittest.TestCase):
    def test_maps_both_separator_outputs_to_two_vocal_tracks(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            vocal_two = root / "input_(Instrumental)_5_HP-Karaoke-UVR.wav"
            vocal_one = root / "input_(Vocals)_5_HP-Karaoke-UVR.wav"
            vocal_two.write_bytes(b"vocal-2")
            vocal_one.write_bytes(b"vocal-1")

            self.assertEqual(
                _find_vocal_split_outputs(root),
                (vocal_one, vocal_two),
            )

    def test_missing_output_is_reported_before_registration(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "input_(Vocals)_model.wav").write_bytes(b"lead")

            with self.assertRaises(VocalSplitError):
                _find_vocal_split_outputs(root)

    def test_asset_status_reports_first_download_size(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            status = vocal_split_asset_status(Path(temporary))

            self.assertFalse(status.ready)
            self.assertEqual(status.missing_bytes, VOCAL_SPLIT_MODEL_SIZE)

    def test_singer_backend_result_atomically_replaces_one_active_vocal(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary) / "separation"
            parent.mkdir()
            source = parent / "vocals.wav"
            _write_silence(source)
            store = VocalSplitStore()
            group = store.create_group(parent, source)

            updated = split_selected_vocal(
                group,
                group.stems[0],
                (
                    VocalReferenceRegion("solo-1", 1_000, 2_000),
                    VocalReferenceRegion("solo-2", 2_200, 2_800),
                ),
                store=store,
                backend=_FakeSingerBackend(),
            )

            self.assertEqual(len(updated.stems), 2)
            self.assertEqual(
                [stem.label for stem in updated.stems],
                ["Vocal 1", "Remaining vocal"],
            )
            self.assertEqual(store.runs(parent), (updated,))

    def test_failed_singer_backend_does_not_change_group_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary) / "separation"
            parent.mkdir()
            source = parent / "vocals.wav"
            _write_silence(source)
            store = VocalSplitStore()
            group = store.create_group(parent, source)

            with self.assertRaises(RuntimeError):
                split_selected_vocal(
                    group,
                    group.stems[0],
                    (VocalReferenceRegion("solo-1", 1_000, 2_000),),
                    store=store,
                    backend=_FailingSingerBackend(),
                )

            self.assertEqual(store.runs(parent), (group,))
            operations = parent / "vocal_splits" / group.run_id / "operations"
            self.assertFalse(operations.exists() and any(operations.iterdir()))


class _FakeSingerBackend:
    model_name = "fake-singer-model"

    def separate(
        self,
        input_path: Path,
        _reference_regions: tuple[VocalReferenceRegion, ...],
        output_dir: Path,
        _progress_callback,
    ) -> tuple[Path, Path]:
        extracted = output_dir / "extracted.wav"
        remaining = output_dir / "remaining.wav"
        _copy_wave(input_path, extracted)
        _copy_wave(input_path, remaining)
        return extracted, remaining


class _FailingSingerBackend:
    model_name = "failing-singer-model"

    def separate(self, *_args, **_kwargs) -> tuple[Path, Path]:
        raise RuntimeError("backend failed")


def _write_silence(path: Path) -> None:
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(8_000)
        output.writeframes(b"\0\0" * 24_000)


def _copy_wave(source: Path, destination: Path) -> None:
    with wave.open(str(source), "rb") as input_audio:
        params = input_audio.getparams()
        frames = input_audio.readframes(input_audio.getnframes())
    with wave.open(str(destination), "wb") as output:
        output.setparams(params)
        output.writeframes(frames)


if __name__ == "__main__":
    unittest.main()
