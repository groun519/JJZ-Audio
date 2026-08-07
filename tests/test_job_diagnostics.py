from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from jang_app.services.job_diagnostics import (
    JobDiagnostics,
    classify_error,
    redact_command,
    redact_text,
)


class JobDiagnosticsTests(unittest.TestCase):
    def test_records_structured_failure_and_builds_report(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            diagnostics = JobDiagnostics(Path(temporary), session_id="session-test")
            path = diagnostics.start_job("task-1", "Convert Vocal", "song.wav")
            self.assertIsNotNone(path)

            diagnostics.update_progress("task-1", 42)
            diagnostics.update_detail("task-1", "RVC inference")
            diagnostics.append_command_output("task-1", "runtime output")
            classification = diagnostics.fail_job(
                "task-1",
                "RVC conversion failed with exit code 3221225620.",
            )

            summary = json.loads((Path(temporary) / "task-1" / "summary.json").read_text(encoding="utf-8"))
            self.assertEqual(classification.code, "RVC_CPU_RUNTIME_INCOMPATIBLE")
            self.assertEqual(summary["status"], "failed")
            self.assertEqual(summary["progress"], 42)
            self.assertEqual(summary["diagnostic_code"], classification.code)
            self.assertIn("runtime output", (Path(temporary) / "task-1" / "command.log").read_text(encoding="utf-8"))
            report = diagnostics.build_report("task-1")
            self.assertIn("Task ID: task-1", report)
            self.assertIn("Command output tail:", report)
            self.assertIn("runtime output", report)

    def test_redacts_command_secrets_and_url_queries(self) -> None:
        command = redact_command(
            [
                "tool",
                "https://example.test/audio?id=123&token=secret",
                "--token",
                "secret-value",
                "--api-key=another-secret",
            ]
        )

        self.assertEqual(command[1], "https://example.test/audio")
        self.assertEqual(command[3], "<redacted>")
        self.assertEqual(command[4], "--api-key=<redacted>")
        self.assertNotIn("secret", " ".join(command))
        self.assertEqual(redact_text("token=abc"), "token=<redacted>")

    def test_classifies_common_runtime_failures(self) -> None:
        self.assertEqual(classify_error("CUDA out of memory").code, "CUDA_OUT_OF_MEMORY")
        self.assertEqual(
            classify_error("CUDA error: no kernel image is available for execution").code,
            "CUDA_ARCHITECTURE_UNSUPPORTED",
        )
        self.assertEqual(classify_error("No module named 'lib.train'").code, "PYTHON_MODULE_MISSING")
        self.assertEqual(
            classify_error("ModuleNotFoundError: No module named 'lib.jjzero_device'").code,
            "RVC_RUNTIME_INCOMPLETE",
        )
        self.assertEqual(
            classify_error("ModuleNotFoundError: No module named 'i18n'").code,
            "RVC_RUNTIME_INCOMPLETE",
        )
        self.assertEqual(
            classify_error("Could not run operator on privateuseone:0").code,
            "DIRECTML_RUNTIME_FAILED",
        )
        self.assertEqual(
            classify_error("ONNX Runtime has no DmlExecutionProvider").code,
            "DIRECTML_RUNTIME_FAILED",
        )
        self.assertEqual(
            classify_error("The installed DirectML runtime is missing rmvpe.onnx").code,
            "DIRECTML_RUNTIME_FAILED",
        )
        self.assertEqual(
            classify_error("UnicodeEncodeError: 'cp949' codec can't encode character").code,
            "RVC_CONSOLE_ENCODING_ERROR",
        )
        self.assertEqual(classify_error("HIP runtime failure in ROCm").code, "ROCM_RUNTIME_FAILED")
        self.assertEqual(classify_error("unknown").code, "UNEXPECTED_ERROR")


if __name__ == "__main__":
    unittest.main()
