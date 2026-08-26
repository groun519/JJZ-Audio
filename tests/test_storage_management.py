from __future__ import annotations

import os
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from jang_app.services.app_paths import discover_app_paths
from jang_app.services.storage_management import (
    CleanupCandidate,
    StorageCleanupPlan,
    build_safe_cleanup_plan,
    execute_cleanup,
    scan_storage,
)


class StorageManagementTests(unittest.TestCase):
    def test_inventory_separates_protected_assets_and_cache(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            paths = _paths(Path(temporary))
            _write(paths.workspace_root / "library" / "song.wav", 11)
            _write(paths.workspace_root / "models" / "voice.pth", 13)
            _write(paths.cache_dir / "separation" / "model.onnx", 17)
            _write(paths.cache_dir / "jobs" / "temp.wav", 19)
            _write(paths.output_root / "mix.wav", 23)
            _write(paths.runtime_root / "rvc" / "runtime" / "python.exe", 29)

            inventory = scan_storage(paths)
            categories = {category.key: category for category in inventory.categories}

        self.assertEqual(categories["library"].size_bytes, 11)
        self.assertEqual(categories["models"].size_bytes, 13)
        self.assertEqual(categories["ai_assets"].size_bytes, 17)
        self.assertEqual(categories["cache"].size_bytes, 19)
        self.assertEqual(categories["exports"].size_bytes, 23)
        self.assertEqual(categories["runtime"].size_bytes, 29)
        self.assertEqual(categories["library"].safety, "protected")

    def test_active_jobs_exclude_transient_cache_from_cleanup(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            paths = _paths(Path(temporary))
            cached = paths.cache_dir / "jobs" / "active.tmp"
            _write(cached, 20)

            plan = build_safe_cleanup_plan(paths, active_jobs=True)

        self.assertTrue(plan.skipped_for_active_jobs)
        self.assertNotIn(cached, tuple(candidate.path for candidate in plan.candidates))

    def test_safe_cleanup_removes_cache_without_touching_user_data(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            paths = _paths(Path(temporary))
            cached = paths.cache_dir / "jobs" / "old.tmp"
            protected = paths.workspace_root / "library" / "song.wav"
            diagnostic = paths.log_dir / "JJZero-Support-Diagnostics-old.zip"
            _write(cached, 31)
            _write(protected, 37)
            _write(diagnostic, 41)
            old = datetime.now(UTC) - timedelta(days=9)
            os.utime(diagnostic, (old.timestamp(), old.timestamp()))

            plan = build_safe_cleanup_plan(paths)
            report = execute_cleanup(plan)

            self.assertFalse(cached.exists())
            self.assertFalse(diagnostic.exists())
            self.assertTrue(protected.exists())
            self.assertGreaterEqual(report.reclaimed_bytes, 72)
            self.assertFalse(report.failed_paths)

    def test_cleanup_rejects_path_outside_its_allowed_root(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            allowed = root / "allowed"
            outside = root / "outside.bin"
            allowed.mkdir()
            _write(outside, 7)
            plan = StorageCleanupPlan(
                (CleanupCandidate("invalid", outside, allowed, 7, 1),)
            )

            report = execute_cleanup(plan)

        self.assertTrue(report.failed_paths)

    def test_stale_transient_candidate_is_kept_when_a_job_starts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            paths = _paths(Path(temporary))
            cached = paths.cache_dir / "jobs" / "active.tmp"
            _write(cached, 20)
            plan = build_safe_cleanup_plan(paths, active_jobs=False)

            report = execute_cleanup(plan, active_jobs=lambda: True)

            self.assertTrue(cached.exists())
            self.assertIn(cached, report.skipped_paths)
            self.assertEqual(report.reclaimed_bytes, 0)

    def test_idle_guard_atomically_rejects_a_stale_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            paths = _paths(Path(temporary))
            cached = paths.cache_dir / "jobs" / "active.tmp"
            _write(cached, 20)
            plan = build_safe_cleanup_plan(paths, active_jobs=False)
            moves: list[bool] = []

            report = execute_cleanup(
                plan,
                active_jobs=lambda: False,
                idle_guard=lambda _move: moves.append(True) or False,
            )

            self.assertTrue(cached.exists())
            self.assertEqual(moves, [True])
            self.assertIn(cached, report.skipped_paths)

    def test_delete_failure_restores_candidate_to_original_location(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            paths = _paths(Path(temporary))
            cached = paths.cache_dir / "jobs" / "recover.tmp"
            _write(cached, 20)
            plan = build_safe_cleanup_plan(paths)

            with patch(
                "jang_app.services.storage_management._remove_path",
                side_effect=OSError("locked"),
            ):
                report = execute_cleanup(plan)

            self.assertTrue(cached.exists())
            self.assertIn(cached, report.failed_paths)

    def test_unrestored_quarantine_is_visible_in_next_cleanup_plan(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            paths = _paths(Path(temporary))
            cached = paths.cache_dir / "jobs" / "recover.tmp"
            _write(cached, 20)
            plan = build_safe_cleanup_plan(paths)

            with (
                patch(
                    "jang_app.services.storage_management._remove_path",
                    side_effect=OSError("locked"),
                ),
                patch(
                    "jang_app.services.storage_management._restore_staged_candidate",
                    return_value=False,
                ),
            ):
                report = execute_cleanup(plan)
            retry = build_safe_cleanup_plan(paths)

            self.assertTrue(report.failed_paths[0].exists())
            self.assertTrue(
                any(candidate.quarantined for candidate in retry.candidates)
            )

    def test_library_preview_and_incomplete_run_are_safe_cleanup_candidates(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            paths = _paths(Path(temporary))
            separations = (
                paths.workspace_root
                / "library"
                / "songs"
                / "song-1"
                / "02_vocal"
                / "separations"
            )
            complete = separations / "r_complete"
            incomplete = separations / "r_incomplete"
            preview = complete / "cleanup" / ".preview" / "preview-old"
            _write(complete / "separation.json", 2)
            _write(complete / "vocals.wav", 11)
            _write(preview / "preview.wav", 13)
            _write(incomplete / "vocals.wav", 17)

            active_plan = build_safe_cleanup_plan(paths, active_jobs=True)
            plan = build_safe_cleanup_plan(paths, active_jobs=False)
            candidate_paths = {candidate.path for candidate in plan.candidates}

            self.assertNotIn(preview, {item.path for item in active_plan.candidates})
            self.assertIn(preview, candidate_paths)
            self.assertIn(incomplete, candidate_paths)
            self.assertNotIn(complete, candidate_paths)
            report = execute_cleanup(plan, active_jobs=lambda: False)

            self.assertFalse(preview.exists())
            self.assertFalse(incomplete.exists())
            self.assertTrue((complete / "vocals.wav").is_file())
            self.assertFalse(report.failed_paths)


def _write(path: Path, size: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * size)


def _paths(root: Path):
    package = root / "source" / "src" / "jang_app"
    package.mkdir(parents=True)
    return discover_app_paths(
        package,
        environ={
            "JJZERO_DATA_ROOT": str(root / "appdata"),
            "JJZERO_STORAGE_ROOT": str(root / "storage"),
            "USERPROFILE": str(root / "user"),
        },
        frozen=True,
        executable=root / "install" / "JJZero Audio.exe",
        source_root=root / "source",
    )


if __name__ == "__main__":
    unittest.main()
