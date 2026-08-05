from __future__ import annotations

import sys
import tempfile
import time
import unittest
from pathlib import Path

from jang_app.services.command import CommandCancellation, run_cancellable_command, run_command
from jang_app.services.job_diagnostics import JobDiagnostics, diagnostic_task


class CancellableCommandTests(unittest.TestCase):
    def test_cancellation_terminates_a_running_process(self) -> None:
        cancellation = CommandCancellation()
        started = time.monotonic()

        result = run_cancellable_command(
            [sys.executable, "-u", "-c", "import time; print('ready'); time.sleep(30)"],
            output_callback=lambda _line: cancellation.request_cancel(),
            cancellation=cancellation,
        )

        self.assertTrue(result.cancelled)
        self.assertLess(time.monotonic() - started, 10)

    def test_records_command_output_for_current_diagnostic_task(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            diagnostics = JobDiagnostics(Path(temporary), session_id="command-test")
            diagnostics.start_job("task-command", "Command")

            with diagnostic_task("task-command"):
                result = run_command(
                    [sys.executable, "-u", "-c", "print('diagnostic output')"],
                    diagnostics=diagnostics,
                )

            self.assertEqual(result.returncode, 0)
            job_path = Path(temporary) / "task-command"
            self.assertIn("diagnostic output", (job_path / "command.log").read_text(encoding="utf-8"))
            events = (job_path / "events.jsonl").read_text(encoding="utf-8")
            self.assertIn('"event": "command_started"', events)
            self.assertIn('"event": "command_finished"', events)


if __name__ == "__main__":
    unittest.main()
