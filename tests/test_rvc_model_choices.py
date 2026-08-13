from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from jang_app.services.rvc_model_choices import collect_rvc_model_choices
from jang_app.services.rvc_model_workspace import RvcModelRecord


class RvcModelChoiceTests(unittest.TestCase):
    def test_library_model_wins_over_the_same_legacy_weight(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            weights = root / "weights"
            weights.mkdir()
            model = weights / "voice.pth"
            model.write_bytes(b"model")
            record = _record(root, model, title="Library Voice")

            choices = collect_rvc_model_choices((record,), root)

            self.assertEqual(len(choices), 1)
            self.assertEqual(choices[0].source, "library")
            self.assertEqual(choices[0].label, "Library Voice")
            self.assertEqual(choices[0].model_id, record.model_id)

    def test_library_model_uses_execution_root_when_provided(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            execution_root = root / "execution"
            execution_root.mkdir()
            weights = root / "weights"
            weights.mkdir()
            model = weights / "voice.pth"
            model.write_bytes(b"model")
            record = _record(root, model, title="Library Voice")

            choices = collect_rvc_model_choices(
                (record,),
                root,
                execution_root=execution_root,
            )

            self.assertEqual(choices[0].root, execution_root.resolve())

    def test_legacy_weights_remain_available_without_registration(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            weights = root / "weights"
            weights.mkdir()
            model = weights / "legacy_voice.pth"
            model.write_bytes(b"model")

            choices = collect_rvc_model_choices((), root)

            self.assertEqual(len(choices), 1)
            self.assertEqual(choices[0].source, "legacy")
            self.assertEqual(choices[0].model_path, model.resolve())

    def test_current_external_model_is_preserved_as_a_compatibility_choice(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            legacy_root = root / "rvc"
            legacy_root.mkdir()
            external = root / "external" / "voice.pth"
            external.parent.mkdir()
            external.write_bytes(b"model")

            choices = collect_rvc_model_choices(
                (),
                legacy_root,
                current_root=legacy_root,
                current_model=str(external),
            )

            self.assertEqual(len(choices), 1)
            self.assertEqual(choices[0].source, "current")
            self.assertEqual(choices[0].model_path, external.resolve())


def _record(root: Path, model: Path, *, title: str) -> RvcModelRecord:
    return RvcModelRecord(
        model_id="voice-id",
        name="voice",
        mode="linked",
        runtime_root=root,
        source_folder=root,
        inference_model=model,
        index_file=None,
        generator_checkpoint=None,
        discriminator_checkpoint=None,
        created_at="2026-01-01T00:00:00+00:00",
        display_name=title,
        default_pitch=-12,
        default_device="gpu",
    )


if __name__ == "__main__":
    unittest.main()
