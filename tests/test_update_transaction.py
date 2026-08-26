from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from jang_app.services.app_paths import discover_app_paths
from jang_app.services.app_update import (
    ReleaseArtifact,
    ReleaseComponent,
    ReleaseManifest,
    UpdateError,
    UpdatePlan,
)
from jang_app.services.update_cache import UPDATE_CLEANUP_MARKER
from jang_app.services.update_transaction import (
    PENDING_UPDATE_NAME,
    apply_pending_component_updates,
    stage_pending_component_update,
)


class UpdateTransactionTests(unittest.TestCase):
    def test_combined_update_applies_runtime_only_after_new_app_starts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            paths = _paths(root)
            plan, installer, package = _combined_plan(paths.cache_dir)
            journal = stage_pending_component_update(
                paths.cache_dir,
                plan,
                (installer, package),
            )

            with patch(
                "jang_app.services.update_transaction.provision_update_runtime_components"
            ) as provision:
                self.assertEqual(
                    apply_pending_component_updates(paths, current_version="0.3.10"),
                    (),
                )
                provision.assert_not_called()

                applied = apply_pending_component_updates(
                    paths,
                    current_version=plan.release.version,
                )

            self.assertEqual(len(applied), 1)
            provision.assert_called_once_with(
                plan,
                (package,),
                paths.runtime_root,
                cache_dir=journal.parent,
            )
            self.assertTrue((journal.parent / UPDATE_CLEANUP_MARKER).is_file())

    def test_corrupt_runtime_package_keeps_pending_journal_for_retry(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            paths = _paths(root)
            plan, installer, package = _combined_plan(paths.cache_dir)
            journal = stage_pending_component_update(
                paths.cache_dir,
                plan,
                (installer, package),
            )
            package.write_bytes(b"corrupt")

            with self.assertRaisesRegex(UpdateError, "runtime artifact is invalid"):
                apply_pending_component_updates(
                    paths,
                    current_version=plan.release.version,
                )

            self.assertTrue(journal.is_file())
            self.assertFalse((journal.parent / UPDATE_CLEANUP_MARKER).exists())


def _paths(root: Path):
    package = root / "source" / "src" / "jang_app"
    package.mkdir(parents=True)
    return discover_app_paths(
        package,
        environ={"JJZERO_DATA_ROOT": str(root / "data")},
        frozen=False,
        source_root=root / "source",
    )


def _combined_plan(cache_root: Path):
    update = cache_root / "updates" / "0.3.11"
    update.mkdir(parents=True)
    installer = update / "setup.exe"
    package = update / "runtime.zip"
    installer.write_bytes(b"installer")
    package.write_bytes(b"runtime")
    app_artifact = ReleaseArtifact(
        installer.name,
        installer.stat().st_size,
        hashlib.sha256(installer.read_bytes()).hexdigest(),
        "https://example.test/setup.exe",
        True,
        "JJZero Software",
        certificate_sha256="c" * 64,
    )
    runtime_artifact = ReleaseArtifact(
        package.name,
        package.stat().st_size,
        hashlib.sha256(package.read_bytes()).hexdigest(),
        "https://example.test/runtime.zip",
    )
    release = ReleaseManifest(
        "0.3.11",
        (
            ReleaseComponent("application", "0.3.11", "installer", (app_artifact,)),
            ReleaseComponent("ai-runtime", "5", "extract", (runtime_artifact,)),
        ),
    )
    return UpdatePlan(release, True, True), installer, package


if __name__ == "__main__":
    unittest.main()
