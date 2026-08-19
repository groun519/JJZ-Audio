from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from jang_app.services.job_diagnostics import (
    JobDiagnostics,
    diagnostic_task,
)
from jang_app.services import job_diagnostics
from jang_app.services.rvc_training_diagnostics import (
    RvcTrainingAttemptMonitor,
    RvcTrainingDiagnostics,
    RvcTrainingProcessStatus,
)


class RvcTrainingDiagnosticsTests(unittest.TestCase):
    def test_monitor_reports_a_dead_worker_only_once(self) -> None:
        activity: list[str] = []
        monitor = RvcTrainingAttemptMonitor(
            None,
            None,
            activity_callback=activity.append,
        )
        workers = (
            RvcTrainingProcessStatus(
                123,
                "Process-1",
                "worker",
                False,
                3221225477,
            ),
        )

        monitor._report_dead_workers(workers)
        monitor._report_dead_workers(workers)

        self.assertEqual(
            activity,
            ["JJZERO_DATA_LOADER_WORKER_EXITED pid=123 exit_code=3221225477"],
        )

    def test_records_attempt_and_captures_only_current_log_delta(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            previous = job_diagnostics._diagnostics
            diagnostics = JobDiagnostics(root / "jobs", session_id="session-test")
            job_diagnostics._diagnostics = diagnostics
            try:
                diagnostics.start_job("task-1", "Train Model")
                with diagnostic_task("task-1"):
                    training = RvcTrainingDiagnostics.for_current_task("model-1")
                self.assertIsNotNone(training)
                assert training is not None
                attempt = training.begin_attempt({"data_loader_workers": 4})

                source = root / "train.log"
                previous = "old run\n".encode("utf-8")
                source.write_bytes(previous + "new run\n".encode("utf-8"))
                training.capture_train_log(attempt, source, len(previous))
                training.finish_attempt(
                    attempt,
                    status="completed",
                    returncode=0,
                )

                attempt_data = json.loads(
                    (attempt.folder / "attempt.json").read_text(encoding="utf-8")
                )
                self.assertEqual(attempt_data["status"], "completed")
                self.assertEqual(
                    (attempt.folder / "train.log").read_text(encoding="utf-8"),
                    "new run\n",
                )
                events = (training.root / "events.jsonl").read_text(encoding="utf-8")
                self.assertIn("attempt_started", events)
                self.assertIn("attempt_finished", events)
            finally:
                job_diagnostics._diagnostics = previous

    def test_diagnoses_first_batch_timeout_and_worker_import_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            training = RvcTrainingDiagnostics(
                Path(temporary),
                "task-2",
                "model-2",
            )
            timeout_attempt = training.begin_attempt({"data_loader_workers": 4})
            self.assertEqual(
                training.diagnose_attempt(
                    timeout_attempt,
                    "RuntimeError: DataLoader timed out after 120 seconds",
                ),
                "RVC_FIRST_BATCH_TIMEOUT",
            )

            import_attempt = training.begin_attempt({"data_loader_workers": 4})
            process_log = import_attempt.folder / "processes" / "123.jsonl"
            process_log.write_text(
                json.dumps(
                    {
                        "event": "uncaught_exception",
                        "process_name": "Process-1",
                        "exception_type": "ModuleNotFoundError",
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            self.assertEqual(
                training.diagnose_attempt(import_attempt, "worker stopped"),
                "RVC_WORKER_IMPORT_FAILED",
            )

            exited_attempt = training.begin_attempt({"data_loader_workers": 4})
            (exited_attempt.folder / "processes" / "456.jsonl").write_text(
                json.dumps(
                    {
                        "event": "data_loader_exception",
                        "process_name": "MainProcess",
                        "exception_type": "RuntimeError",
                        "workers": [{"pid": 789, "exit_code": 1}],
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            self.assertEqual(
                training.diagnose_attempt(exited_attempt, "worker stopped"),
                "RVC_WORKER_EXITED",
            )

            crash_attempt = training.begin_attempt({"data_loader_workers": 4})
            (crash_attempt.folder / "processes" / "789.log").write_text(
                "Windows fatal exception: access violation\n"
                "ntdll.dll!RtlUserThreadStart\n",
                encoding="utf-8",
            )
            self.assertEqual(
                training.diagnose_attempt(crash_attempt, "trainer stopped"),
                "RVC_NATIVE_RUNTIME_CRASH",
            )


if __name__ == "__main__":
    unittest.main()
