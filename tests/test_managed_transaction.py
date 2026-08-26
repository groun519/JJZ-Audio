from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from jang_app.services.managed_transaction import (
    ManagedPathTransaction,
    ManagedTransactionError,
    recover_managed_transactions,
)


class ManagedPathTransactionTests(unittest.TestCase):
    def test_stages_and_rolls_back_multiple_paths_in_reverse_order(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first = root / "first" / "one.txt"
            second = root / "second"
            first.parent.mkdir()
            second.mkdir()
            first.write_text("one", encoding="utf-8")
            (second / "two.txt").write_text("two", encoding="utf-8")
            transaction = ManagedPathTransaction(root, "delete", "song-1")

            transaction.stage(first, "first")
            transaction.stage(second, "second")
            self.assertFalse(first.exists())
            self.assertFalse(second.exists())

            transaction.rollback()

            self.assertEqual(first.read_text(encoding="utf-8"), "one")
            self.assertEqual((second / "two.txt").read_text(encoding="utf-8"), "two")
            self.assertFalse(transaction.folder.exists())

    def test_commit_keeps_payload_quarantined_until_purge(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "model"
            source.mkdir()
            (source / "voice.pth").write_bytes(b"model")
            transaction = ManagedPathTransaction(root, "delete", "model-1")

            move = transaction.stage(source, "package")
            transaction.mark_committed()

            journal = json.loads(transaction.journal.read_text(encoding="utf-8"))
            self.assertEqual(journal["state"], "committed")
            self.assertTrue((move.staged / "voice.pth").is_file())
            self.assertTrue(transaction.purge())
            self.assertFalse(transaction.folder.exists())

    def test_partial_stage_failure_does_not_hide_the_first_path_after_rollback(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first = root / "first"
            second = root / "second"
            first.mkdir()
            second.mkdir()
            transaction = ManagedPathTransaction(root, "delete", "model-1")
            original_replace = __import__("os").replace

            def replace(source, target):
                if Path(source).resolve() == second.resolve():
                    raise PermissionError("second path locked")
                return original_replace(source, target)

            with patch(
                "jang_app.services.managed_transaction.os.replace",
                side_effect=replace,
            ):
                transaction.stage(first, "first")
                with self.assertRaises(PermissionError):
                    transaction.stage(second, "second")
                transaction.rollback()

            self.assertTrue(first.is_dir())
            self.assertTrue(second.is_dir())

    def test_rollback_refuses_to_overwrite_a_recreated_source(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "song"
            source.mkdir()
            transaction = ManagedPathTransaction(root, "delete", "song-1")
            transaction.stage(source, "package")
            source.mkdir()

            with self.assertRaises(ManagedTransactionError):
                transaction.rollback()

            self.assertTrue(source.is_dir())
            self.assertTrue(transaction.folder.is_dir())

    def test_promoted_path_is_discarded_before_previous_path_is_restored(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            destination = root / "live" / "model.pth"
            destination.parent.mkdir(parents=True)
            destination.write_bytes(b"old")
            incoming = root / "incoming" / "model.pth"
            incoming.parent.mkdir(parents=True)
            incoming.write_bytes(b"new")
            transaction = ManagedPathTransaction(root, "replace", "model")

            transaction.stage(destination, "previous")
            transaction.promote(incoming, destination, "replacement")
            transaction.rollback()

            self.assertEqual(destination.read_bytes(), b"old")
            self.assertFalse(incoming.exists())
            self.assertFalse(transaction.folder.exists())

    def test_startup_recovery_rolls_back_replacement_and_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            model = root / "library" / "model.pth"
            catalog = root / "catalog.json"
            model.parent.mkdir(parents=True)
            model.write_bytes(b"old-model")
            catalog.write_text("old-catalog", encoding="utf-8")
            incoming = root / "incoming" / "model.pth"
            incoming.parent.mkdir(parents=True)
            incoming.write_bytes(b"new-model")
            transaction = ManagedPathTransaction(root, "replace", "model")
            transaction.stage(catalog, "catalog")
            transaction.stage(model, "model")
            transaction.promote(incoming, model, "replacement")
            catalog.write_text("new-catalog", encoding="utf-8")

            reports = recover_managed_transactions(root)

            self.assertEqual(reports[0].action, "rolled_back")
            self.assertEqual(model.read_bytes(), b"old-model")
            self.assertEqual(catalog.read_text(encoding="utf-8"), "old-catalog")
            self.assertFalse(transaction.folder.exists())

    def test_startup_recovery_purges_committed_payload_without_rollback(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / "target.txt"
            target.write_text("delete", encoding="utf-8")
            transaction = ManagedPathTransaction(root, "delete", "target")
            transaction.stage(target, "target")
            transaction.mark_committed()

            reports = recover_managed_transactions(root)

            self.assertEqual(reports[0].action, "purged")
            self.assertFalse(target.exists())
            self.assertFalse(transaction.folder.exists())

    def test_startup_recovery_rejects_paths_outside_managed_root(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            managed = root / "managed"
            outside = root / "outside.txt"
            outside.write_text("preserve", encoding="utf-8")
            transaction = ManagedPathTransaction(managed, "delete", "unsafe")
            transaction.folder.mkdir(parents=True)
            transaction.journal.write_text(
                json.dumps(
                    {
                        "version": 1,
                        "state": "staged",
                        "moves": [
                            {
                                "label": "unsafe",
                                "source": str(outside),
                                "staged": str(transaction.folder / "payload" / "unsafe"),
                            }
                        ],
                        "created": [],
                    }
                ),
                encoding="utf-8",
            )

            reports = recover_managed_transactions(managed)

            self.assertEqual(reports[0].action, "failed")
            self.assertEqual(outside.read_text(encoding="utf-8"), "preserve")


if __name__ == "__main__":
    unittest.main()
