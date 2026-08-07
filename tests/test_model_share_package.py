from __future__ import annotations

import tempfile
import unittest
import zipfile
from datetime import UTC, datetime
from pathlib import Path

from jang_app.services.model_share_package import (
    MODEL_SHARE_MANIFEST,
    ModelShareCancelled,
    ModelSharePackageError,
    create_model_share_package,
    find_current_model_share_package,
    import_model_share_package,
    inspect_model_share_package,
)
from jang_app.services.rvc_model_workspace import RvcModelRecord, RvcModelWorkspace


class ModelSharePackageTests(unittest.TestCase):
    def test_inference_model_and_index_round_trip_as_managed_model(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            source.mkdir()
            model = source / "voice.pth"
            index = source / "added_voice.index"
            model.write_bytes(b"model-data")
            index.write_bytes(b"index-data")
            record = _record(model, index)
            package = create_model_share_package(record, root / "packages")
            workspace = RvcModelWorkspace(root / "workspace")

            imported = import_model_share_package(package.path, workspace)

            self.assertEqual(len(imported.records), 1)
            self.assertTrue(imported.records[0].can_convert)
            self.assertTrue(imported.records[0].has_index)
            self.assertEqual(imported.records[0].display_name, "Shared Voice")

    def test_inference_pth_without_index_is_a_valid_shared_model(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            model = root / "voice.pth"
            model.write_bytes(b"model-data")
            package = create_model_share_package(_record(model, None), root / "packages")
            workspace = RvcModelWorkspace(root / "workspace")

            imported = import_model_share_package(package.path, workspace)

            self.assertEqual(len(imported.records), 1)
            self.assertTrue(imported.records[0].can_convert)
            self.assertFalse(imported.records[0].has_index)
            self.assertFalse(package.includes_index)

    def test_unchanged_model_reuses_existing_package(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            model = root / "voice.pth"
            model.write_bytes(b"model-data")
            record = _record(model, None)

            first = create_model_share_package(record, root / "packages")
            first_modified_ns = first.path.stat().st_mtime_ns
            second = create_model_share_package(record, root / "packages")

            self.assertEqual(second.path, first.path)
            self.assertEqual(second.path.stat().st_mtime_ns, first_modified_ns)

    def test_current_package_lookup_rejects_changed_model(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            model = root / "voice.pth"
            model.write_bytes(b"model-data")
            record = _record(model, None)
            packages = root / "packages"
            package = create_model_share_package(record, packages)

            self.assertEqual(
                find_current_model_share_package(record, packages),
                package,
            )

            model.write_bytes(b"updated-model-data")

            self.assertIsNone(find_current_model_share_package(record, packages))

    def test_cancelled_package_removes_partial_archive(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            model = root / "voice.pth"
            model.write_bytes(b"model-data")
            packages = root / "packages"

            with self.assertRaises(ModelShareCancelled):
                create_model_share_package(
                    _record(model, None),
                    packages,
                    cancelled=lambda: True,
                )

            self.assertEqual(tuple(packages.iterdir()), ())

    def test_unsafe_manifest_path_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            package = Path(directory) / "unsafe.zip"
            with zipfile.ZipFile(package, "w") as archive:
                archive.writestr(
                    MODEL_SHARE_MANIFEST,
                    (
                        '{"format":"jjzero-rvc-model","version":1,"files":['
                        '{"artifact":"inference_model","path":"../voice.pth",'
                        '"size":1,"sha256":"' + "0" * 64 + '"}]}'
                    ),
                )
                archive.writestr("../voice.pth", b"x")

            with self.assertRaises(ModelSharePackageError):
                inspect_model_share_package(package)


def _record(model: Path, index: Path | None) -> RvcModelRecord:
    return RvcModelRecord(
        model_id="voice",
        name="voice",
        mode="linked",
        runtime_root=model.parent,
        source_folder=model.parent,
        inference_model=model,
        index_file=index,
        generator_checkpoint=None,
        discriminator_checkpoint=None,
        created_at=datetime.now(UTC).isoformat(),
        display_name="Shared Voice",
        tags=("test",),
        notes="Round trip",
        default_pitch=-12,
    )


if __name__ == "__main__":
    unittest.main()
