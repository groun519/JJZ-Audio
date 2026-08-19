from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from jang_app.services.update_cache import (
    UPDATE_CLEANUP_MARKER,
    cleanup_completed_updates,
    discard_completed_update,
    mark_update_cleanup_ready,
)


class UpdateCacheTests(unittest.TestCase):
    def test_marked_update_is_removed_only_after_target_version_starts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            cache = Path(temporary) / "cache"
            update = cache / "updates" / "0.3.1"
            installer = update / "setup.exe"
            installer.parent.mkdir(parents=True)
            installer.write_bytes(b"installer")

            self.assertTrue(mark_update_cleanup_ready(cache, update, "0.3.1"))

            pending = cleanup_completed_updates(cache, "0.3.0")
            completed = cleanup_completed_updates(cache, "0.3.1")

            self.assertEqual(pending.removed_files, 0)
            self.assertEqual(completed.removed_files, 2)
            self.assertGreaterEqual(completed.reclaimed_bytes, len(b"installer"))
            self.assertFalse(update.exists())

    def test_unmarked_partial_download_is_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            cache = Path(temporary) / "cache"
            partial = cache / "updates" / "0.3.1" / "setup.exe.part"
            partial.parent.mkdir(parents=True)
            partial.write_bytes(b"partial")

            report = cleanup_completed_updates(cache, "0.3.1")

            self.assertEqual(report.removed_files, 0)
            self.assertTrue(partial.is_file())

    def test_unmarked_partial_from_an_older_version_is_removed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            cache = Path(temporary) / "cache"
            partial = cache / "updates" / "0.3.0" / "setup.exe.part"
            partial.parent.mkdir(parents=True)
            partial.write_bytes(b"partial")

            report = cleanup_completed_updates(cache, "0.3.1")

            self.assertEqual(report.removed_files, 1)
            self.assertGreaterEqual(report.reclaimed_bytes, len(b"partial"))
            self.assertFalse(partial.parent.exists())

    def test_unmarked_partial_from_a_future_version_is_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            cache = Path(temporary) / "cache"
            partial = cache / "updates" / "0.3.2" / "setup.exe.part"
            partial.parent.mkdir(parents=True)
            partial.write_bytes(b"partial")

            report = cleanup_completed_updates(cache, "0.3.1")

            self.assertEqual(report.removed_files, 0)
            self.assertTrue(partial.is_file())

    def test_external_update_directory_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            cache = root / "cache"
            external = root / "external"
            external.mkdir()
            payload = external / "setup.exe"
            payload.write_bytes(b"installer")

            marked = mark_update_cleanup_ready(cache, external, "0.3.1")
            report = discard_completed_update(cache, external)

            self.assertFalse(marked)
            self.assertEqual(report.removed_files, 0)
            self.assertTrue(payload.is_file())

    def test_runtime_only_completion_removes_the_entire_update_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            cache = Path(temporary) / "cache"
            update = cache / "updates" / "0.3.0"
            package = update / "runtime.zip"
            partial = update / "obsolete.zip.part"
            package.parent.mkdir(parents=True)
            package.write_bytes(b"runtime")
            partial.write_bytes(b"partial")

            report = discard_completed_update(cache, update)

            self.assertEqual(report.removed_files, 2)
            self.assertFalse(update.exists())

    def test_failed_cleanup_keeps_marker_for_next_startup(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            cache = Path(temporary) / "cache"
            update = cache / "updates" / "0.3.1"
            locked = update / "locked.bin"
            locked.parent.mkdir(parents=True)
            locked.write_bytes(b"locked")
            self.assertTrue(mark_update_cleanup_ready(cache, update, "0.3.1"))
            original_unlink = Path.unlink

            def fail_locked(path: Path, *args, **kwargs) -> None:
                if path.name == locked.name:
                    raise PermissionError("locked")
                original_unlink(path, *args, **kwargs)

            with patch.object(Path, "unlink", fail_locked):
                report = cleanup_completed_updates(cache, "0.3.1")

            self.assertEqual(report.failed_paths, (locked.resolve(),))
            self.assertTrue((update / UPDATE_CLEANUP_MARKER).is_file())
            self.assertTrue(locked.is_file())


if __name__ == "__main__":
    unittest.main()
