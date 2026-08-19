from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from jang_app.services.vocal_split import VocalReferenceRegion, VocalSplitStem
from jang_app.services.vocal_split_store import VocalSplitStore, VocalSplitStoreError


class VocalSplitStoreTests(unittest.TestCase):
    def test_schema_one_manifest_loads_as_a_group_with_active_vocals(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary) / "separation"
            run_dir = parent / "vocal_splits" / "run-legacy"
            run_dir.mkdir(parents=True)
            source = parent / "vocals.wav"
            source.write_bytes(b"source")
            (run_dir / "lead.wav").write_bytes(b"lead")
            (run_dir / "backing.wav").write_bytes(b"backing")
            (run_dir / "vocal_split.json").write_text(
                json.dumps(
                    {
                        "schema": 1,
                        "run_id": "run-legacy",
                        "created_at": "2026-08-18T00:00:00+00:00",
                        "input": "vocals.wav",
                        "method": {
                            "id": "lead-backing-v1",
                            "label": "Lead / Backing",
                            "model": "legacy-model",
                        },
                        "stems": [
                            {"id": "lead", "role": "lead", "label": "Lead", "file": "lead.wav"},
                            {
                                "id": "backing",
                                "role": "backing",
                                "label": "Backing",
                                "file": "backing.wav",
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )

            loaded = VocalSplitStore().runs(parent)[0]

            self.assertEqual(loaded.run_id, "run-legacy")
            self.assertEqual([stem.label for stem in loaded.stems], ["Vocal 1", "Vocal 2"])
            self.assertEqual(len(loaded.operations), 1)
            self.assertEqual(loaded.all_stems[0].origin, "root")

    def test_group_creation_starts_with_one_original_vocal(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary) / "separation"
            parent.mkdir()
            source = parent / "vocals.wav"
            source.write_bytes(b"source")
            store = VocalSplitStore()

            group = store.create_group(parent, source)
            loaded = store.runs(parent)[0]

            self.assertEqual(group, loaded)
            self.assertEqual(len(loaded.stems), 1)
            self.assertEqual(loaded.stems[0].origin, "root")
            self.assertEqual(loaded.stems[0].path, source.resolve())

    def test_recursive_split_replaces_only_the_selected_active_vocal(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary) / "separation"
            parent.mkdir()
            source = parent / "vocals.wav"
            source.write_bytes(b"source")
            store = VocalSplitStore()
            group = store.create_group(parent, source)

            first_operation = store.create_operation_dir(group)
            first_extracted = first_operation / "extracted.wav"
            first_remaining = first_operation / "remaining.wav"
            first_extracted.write_bytes(b"first")
            first_remaining.write_bytes(b"remaining")
            split_once = store.complete_split(
                group,
                "root",
                first_operation,
                first_extracted,
                first_remaining,
                reference_regions=(VocalReferenceRegion("solo-1", 7_000, 24_000),),
                model="singer-model",
            )

            self.assertEqual([stem.label for stem in split_once.stems], ["Vocal 1", "Remaining vocal"])
            first_vocal = split_once.stems[0]
            remaining = split_once.stems[1]
            second_operation = store.create_operation_dir(split_once)
            second_extracted = second_operation / "extracted.wav"
            second_remaining = second_operation / "remaining.wav"
            second_extracted.write_bytes(b"second")
            second_remaining.write_bytes(b"remaining-2")
            split_twice = store.complete_split(
                split_once,
                remaining.stem_id,
                second_operation,
                second_extracted,
                second_remaining,
                reference_regions=(
                    VocalReferenceRegion("solo-2", 26_000, 34_000),
                    VocalReferenceRegion("solo-3", 36_000, 44_000),
                ),
                model="singer-model",
            )

            self.assertEqual(len(split_twice.stems), 3)
            self.assertEqual(split_twice.stems[0], first_vocal)
            self.assertEqual(
                [stem.label for stem in split_twice.stems],
                ["Vocal 1", "Vocal 2", "Remaining vocal"],
            )
            self.assertEqual(len(split_twice.operations), 2)
            self.assertEqual(len(split_twice.operations[-1].reference_regions), 2)
            self.assertEqual(store.runs(parent)[0], split_twice)

    def test_failed_split_validation_leaves_the_saved_group_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary) / "separation"
            parent.mkdir()
            source = parent / "vocals.wav"
            source.write_bytes(b"source")
            store = VocalSplitStore()
            group = store.create_group(parent, source)
            operation = store.create_operation_dir(group)
            extracted = operation / "extracted.wav"
            extracted.write_bytes(b"extracted")

            with self.assertRaises(VocalSplitStoreError):
                store.complete_split(
                    group,
                    "root",
                    operation,
                    extracted,
                    operation / "missing.wav",
                    reference_regions=(
                        VocalReferenceRegion("solo-1", 7_000, 24_000),
                    ),
                    model="singer-model",
                )

            self.assertEqual(store.runs(parent), (group,))

    def test_schema_two_single_reference_range_loads_as_one_region(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary) / "separation"
            parent.mkdir()
            source = parent / "vocals.wav"
            source.write_bytes(b"source")
            store = VocalSplitStore()
            group = store.create_group(parent, source)
            operation = store.create_operation_dir(group)
            extracted = operation / "extracted.wav"
            remaining = operation / "remaining.wav"
            extracted.write_bytes(b"extracted")
            remaining.write_bytes(b"remaining")
            completed = store.complete_split(
                group,
                "root",
                operation,
                extracted,
                remaining,
                reference_regions=(
                    VocalReferenceRegion("solo-1", 7_000, 24_000),
                ),
                model="singer-model",
            )
            manifest = (
                parent
                / "vocal_splits"
                / completed.run_id
                / "vocal_split.json"
            )
            data = json.loads(manifest.read_text(encoding="utf-8"))
            data["schema"] = 2
            saved_operation = data["operations"][0]
            saved_operation.pop("reference_regions")
            saved_operation["reference_start_ms"] = 7_000
            saved_operation["reference_end_ms"] = 24_000
            manifest.write_text(json.dumps(data), encoding="utf-8")

            loaded = store.runs(parent)[0]

            self.assertEqual(
                loaded.operations[0].reference_regions,
                (VocalReferenceRegion("reference-1", 7_000, 24_000),),
            )

    def test_round_trip_supports_a_variable_number_of_stems(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary) / "separation"
            parent.mkdir()
            source = parent / "vocals.wav"
            source.write_bytes(b"source")
            store = VocalSplitStore()
            run_dir = store.create_run_dir(parent)
            stems = tuple(
                _stem(run_dir, f"vocal-{index}", "vocal", f"Vocal {index}")
                for index in range(1, 4)
            )

            registered = store.register(
                parent,
                run_dir,
                source,
                method_id="multi-vocal-v1",
                method_label="Multi-vocal split",
                model="karaoke.ckpt",
                stems=stems,
            )
            loaded = store.runs(parent)

            self.assertEqual(len(loaded), 1)
            self.assertEqual(loaded[0], registered)
            self.assertEqual([stem.role for stem in loaded[0].stems], ["vocal"] * 3)

    def test_legacy_lead_backing_run_is_displayed_as_two_generic_vocals(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary) / "separation"
            parent.mkdir()
            source = parent / "vocals.wav"
            source.write_bytes(b"source")
            store = VocalSplitStore()
            run_dir = store.create_run_dir(parent)
            store.register(
                parent,
                run_dir,
                source,
                method_id="lead-backing-v1",
                method_label="Lead / Backing",
                model="karaoke.ckpt",
                stems=(
                    _stem(run_dir, "lead", "lead", "Lead Vocal"),
                    _stem(run_dir, "backing", "backing", "Backing Vocal"),
                ),
            )

            loaded = store.runs(parent)[0]

            self.assertEqual(loaded.method_label, "Two-vocal split")
            self.assertEqual([stem.role for stem in loaded.stems], ["vocal", "vocal"])
            self.assertEqual([stem.label for stem in loaded.stems], ["Vocal 1", "Vocal 2"])

    def test_rename_and_remove_keep_manifest_in_sync(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary) / "separation"
            parent.mkdir()
            source = parent / "vocals.wav"
            source.write_bytes(b"source")
            store = VocalSplitStore()
            run_dir = store.create_run_dir(parent)
            run = store.register(
                parent,
                run_dir,
                source,
                method_id="method",
                method_label="Method",
                model="model",
                stems=(
                    _stem(run_dir, "vocal-1", "vocal", "Vocal 1"),
                    _stem(run_dir, "vocal-2", "vocal", "Vocal 2"),
                ),
            )

            renamed = store.rename_stem(run, "vocal-1", "Harmony A")
            remaining = store.remove_stem(renamed, "vocal-2")

            self.assertIsNotNone(remaining)
            self.assertEqual(remaining.stems[0].label, "Harmony A")
            self.assertEqual(store.runs(parent), (remaining,))

    def test_rejects_files_outside_the_managed_run(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            parent = root / "separation"
            parent.mkdir()
            source = parent / "vocals.wav"
            source.write_bytes(b"source")
            outside = root / "outside.wav"
            outside.write_bytes(b"outside")
            store = VocalSplitStore()
            run_dir = store.create_run_dir(parent)

            with self.assertRaises(VocalSplitStoreError):
                store.register(
                    parent,
                    run_dir,
                    source,
                    method_id="method",
                    method_label="Method",
                    model="model",
                    stems=(VocalSplitStem("outside", "lead", "Lead", outside),),
                )

    def test_manifest_run_id_cannot_redirect_later_writes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary) / "separation"
            parent.mkdir()
            source = parent / "vocals.wav"
            source.write_bytes(b"source")
            store = VocalSplitStore()
            run_dir = store.create_run_dir(parent)
            store.register(
                parent,
                run_dir,
                source,
                method_id="method",
                method_label="Method",
                model="model",
                stems=(_stem(run_dir, "lead", "lead", "Lead"),),
            )
            manifest = run_dir / "vocal_split.json"
            data = json.loads(manifest.read_text(encoding="utf-8"))
            data["run_id"] = "another-run"
            manifest.write_text(json.dumps(data), encoding="utf-8")

            loaded = store.runs(parent)[0]
            renamed = store.rename_stem(loaded, "lead", "Main")

            self.assertEqual(renamed.run_id, run_dir.name)
            self.assertEqual(store.runs(parent)[0].stems[0].label, "Main")


def _stem(run_dir: Path, stem_id: str, role: str, label: str) -> VocalSplitStem:
    path = run_dir / f"{stem_id}.wav"
    path.write_bytes(stem_id.encode("ascii"))
    return VocalSplitStem(stem_id, role, label, path.resolve())


if __name__ == "__main__":
    unittest.main()
