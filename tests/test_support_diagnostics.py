from __future__ import annotations

import tempfile
import unittest
import zipfile
from pathlib import Path

from jang_app.services.job_diagnostics import JobDiagnostics
from jang_app.services.support_diagnostics import build_support_archive


class SupportDiagnosticsTests(unittest.TestCase):
    def test_builds_app_archive_without_media_or_credentials(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            jobs = root / "jobs"
            diagnostics = JobDiagnostics(jobs, session_id="support")
            diagnostics.start_job("task-1", "Train Model", "voice")
            diagnostics.fail_job("task-1", "token=private-value")
            app_log = root / "jang.log"
            app_log.write_text(
                "INFO started\nERROR token=another-private-value\n",
                encoding="utf-8",
            )

            archive = build_support_archive(
                diagnostics,
                output_dir=root,
                log_file=app_log,
            )

            self.assertIsNotNone(archive)
            assert archive is not None
            with zipfile.ZipFile(archive) as package:
                names = set(package.namelist())
                log_text = package.read("logs/jang.log").decode("utf-8")
                report = package.read("jobs/task-1/report.txt").decode("utf-8")
            self.assertIn("system.json", names)
            self.assertIn("jobs/index.json", names)
            self.assertNotIn("another-private-value", log_text)
            self.assertNotIn("private-value", report)
            self.assertFalse(any(name.endswith((".wav", ".pth")) for name in names))

    def test_final_archive_bytes_redact_common_oauth_formats(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            diagnostics = JobDiagnostics(root / "jobs", session_id="support")
            diagnostics.start_job("task-1", "Share Model", "model")
            job_log = diagnostics.job_path("task-1") / "command.log"
            secrets = (
                "access-value",
                "refresh-value",
                "client-value",
                "json-access-value",
                "json-client-value",
                "bearer-value",
            )
            raw = "\n".join(
                (
                    f"access_token={secrets[0]}",
                    f"refresh_token={secrets[1]}",
                    f"client_secret={secrets[2]}",
                    f'{{\"access_token\": \"{secrets[3]}\"}}',
                    f'{{\"client_secret\": \"{secrets[4]}\"}}',
                    f"Authorization: Bearer {secrets[5]}",
                )
            )
            # Simulate an older diagnostic written before the stronger redactor existed.
            job_log.write_text(raw, encoding="utf-8")
            app_log = root / "jang.log"
            app_log.write_text(raw, encoding="utf-8")

            archive = build_support_archive(
                diagnostics,
                output_dir=root,
                log_file=app_log,
            )

            self.assertIsNotNone(archive)
            assert archive is not None
            with zipfile.ZipFile(archive) as package:
                payload = b"\n".join(
                    package.read(name)
                    for name in package.namelist()
                    if not name.endswith("/")
                )
            for secret in secrets:
                self.assertNotIn(secret.encode("utf-8"), payload)


if __name__ == "__main__":
    unittest.main()
