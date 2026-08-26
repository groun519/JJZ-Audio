from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from jang_app.services.command import (
    CommandCancellation,
    active_command_count,
    hidden_subprocess_kwargs,
    run_binary_command,
    run_cancellable_command,
    run_command,
    start_detached_command,
    terminate_all_commands,
)
from jang_app.services.job_diagnostics import JobDiagnostics, diagnostic_task


class CancellableCommandTests(unittest.TestCase):
    @unittest.skipUnless(os.name == "nt", "Windows-only process visibility behavior")
    def test_hidden_process_options_suppress_console_windows(self) -> None:
        options = hidden_subprocess_kwargs()

        self.assertTrue(int(options["creationflags"]) & subprocess.CREATE_NO_WINDOW)
        startupinfo = options["startupinfo"]
        self.assertTrue(startupinfo.dwFlags & subprocess.STARTF_USESHOWWINDOW)
        self.assertEqual(startupinfo.wShowWindow, subprocess.SW_HIDE)

    @unittest.skipUnless(os.name == "nt", "Windows-only windowless Python behavior")
    def test_background_runner_keeps_python_for_captured_output(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            runtime = Path(temporary)
            python = runtime / "python.exe"
            pythonw = runtime / "pythonw.exe"
            python.write_bytes(b"python")
            pythonw.write_bytes(b"pythonw")
            process = MagicMock()
            process.communicate.return_value = ("ready", "")
            process.returncode = 0
            process.poll.return_value = 0

            with patch(
                "jang_app.services.command.subprocess.Popen",
                return_value=process,
            ) as runner:
                result = run_command([str(python), "-c", "print('ready')"])

            self.assertEqual(result.returncode, 0)
            self.assertEqual(Path(runner.call_args.args[0][0]), python)

    @unittest.skipUnless(os.name == "nt", "Windows-only process visibility behavior")
    def test_binary_runner_uses_the_same_hidden_window_policy(self) -> None:
        process = MagicMock()
        process.communicate.return_value = (b"audio", b"")
        process.returncode = 0
        process.poll.return_value = 0

        with patch(
            "jang_app.services.command.subprocess.Popen",
            return_value=process,
        ) as runner:
            result = run_binary_command(["ffmpeg.exe", "-version"])

        options = runner.call_args.kwargs
        self.assertEqual(result.stdout, b"audio")
        self.assertTrue(int(options["creationflags"]) & subprocess.CREATE_NO_WINDOW)
        self.assertTrue(options["startupinfo"].dwFlags & subprocess.STARTF_USESHOWWINDOW)

    def test_operational_launch_failures_are_closed_by_command_owner(self) -> None:
        with patch(
            "jang_app.services.command.subprocess.Popen",
            side_effect=OSError("launch failed"),
        ):
            result = run_command(["missing-tool"], timeout_seconds=1)

        self.assertEqual(result.returncode, 1)
        self.assertIn("launch failed", result.output)

    def test_application_services_cannot_bypass_the_process_owner(self) -> None:
        source_root = Path(__file__).resolve().parents[1] / "src" / "jang_app"
        offenders = []
        import_pattern = re.compile(r"^\s*(?:import subprocess|from subprocess import)", re.MULTILINE)
        for path in source_root.rglob("*.py"):
            if path.name == "command.py":
                continue
            if import_pattern.search(path.read_text(encoding="utf-8")):
                offenders.append(str(path.relative_to(source_root)))

        self.assertEqual(offenders, [], f"Use services.command instead: {offenders}")

    @unittest.skipUnless(os.name == "nt", "Windows-only detached process behavior")
    def test_detached_runner_is_windowless_and_prefers_pythonw(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            runtime = Path(temporary)
            python = runtime / "python.exe"
            pythonw = runtime / "pythonw.exe"
            python.write_bytes(b"python")
            pythonw.write_bytes(b"pythonw")

            with patch("jang_app.services.command.subprocess.Popen") as popen:
                started = start_detached_command((str(python), "worker.py"), cwd=runtime)

            self.assertTrue(started)
            command = popen.call_args.args[0]
            options = popen.call_args.kwargs
            self.assertEqual(Path(command[0]), pythonw)
            self.assertTrue(int(options["creationflags"]) & subprocess.CREATE_NO_WINDOW)
            self.assertEqual(options["stdout"], subprocess.DEVNULL)
            self.assertEqual(options["stderr"], subprocess.DEVNULL)

    def test_detached_runner_reports_launch_failure(self) -> None:
        with patch(
            "jang_app.services.command.subprocess.Popen",
            side_effect=OSError("launch failed"),
        ):
            self.assertFalse(start_detached_command(("missing-tool",)))

    def test_cancellation_terminates_a_running_process(self) -> None:
        cancellation = CommandCancellation()
        started = time.monotonic()

        result = run_cancellable_command(
            [
                sys.executable,
                "-u",
                "-c",
                "import sys,time; sys.stdout.write('ready\\r'); sys.stdout.flush(); time.sleep(30)",
            ],
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

    def test_global_shutdown_terminates_an_ordinary_command(self) -> None:
        results = []
        worker = threading.Thread(
            target=lambda: results.append(
                run_command([sys.executable, "-c", "import time; time.sleep(30)"])
            )
        )
        started = time.monotonic()
        worker.start()
        for _ in range(100):
            if active_command_count():
                break
            time.sleep(0.01)

        terminate_all_commands()
        worker.join(8)

        self.assertFalse(worker.is_alive())
        self.assertLess(time.monotonic() - started, 10)
        self.assertEqual(active_command_count(), 0)
        self.assertTrue(results)


if __name__ == "__main__":
    unittest.main()
