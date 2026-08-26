from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from jang_app.services.managed_files import (
    managed_path_lock,
    write_json_atomic,
)


class ManagedFilesTests(unittest.TestCase):
    def test_json_write_retries_a_transient_windows_file_lock(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "state.json"
            with patch(
                "jang_app.services.managed_files.os.replace",
                side_effect=(PermissionError("locked"), None),
            ) as replace:
                write_json_atomic(target, {"ready": True})

            self.assertEqual(replace.call_count, 2)
            self.assertFalse(target.with_suffix(".json.tmp").exists())

    def test_concurrent_json_writers_are_serialized_and_leave_no_temporary_files(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "state.json"
            original_replace = os.replace
            active = 0
            maximum_active = 0
            counter_lock = threading.Lock()

            def observed_replace(source, destination):
                nonlocal active, maximum_active
                with counter_lock:
                    active += 1
                    maximum_active = max(maximum_active, active)
                try:
                    time.sleep(0.01)
                    return original_replace(source, destination)
                finally:
                    with counter_lock:
                        active -= 1

            with patch(
                "jang_app.services.managed_files.os.replace",
                side_effect=observed_replace,
            ):
                with ThreadPoolExecutor(max_workers=8) as executor:
                    futures = [
                        executor.submit(
                            write_json_atomic,
                            target,
                            {"writer": writer, "payload": "x" * 4096},
                        )
                        for writer in range(24)
                    ]
                    for future in futures:
                        future.result()

            saved = json.loads(target.read_text(encoding="utf-8"))
            self.assertIn(saved["writer"], range(24))
            self.assertEqual(saved["payload"], "x" * 4096)
            self.assertEqual(maximum_active, 1)
            self.assertEqual(tuple(target.parent.glob(f".{target.name}.*.tmp")), ())

    def test_path_lock_serializes_independent_processes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / "shared.json"
            trace = root / "trace.txt"
            script = "\n".join(
                (
                    "import sys, time",
                    "from pathlib import Path",
                    "from jang_app.services.managed_files import managed_path_lock",
                    "target, trace, label = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]",
                    "with managed_path_lock(target):",
                    "    with trace.open('a', encoding='utf-8') as output:",
                    "        output.write(label + ':start\\n')",
                    "        output.flush()",
                    "    time.sleep(0.15)",
                    "    with trace.open('a', encoding='utf-8') as output:",
                    "        output.write(label + ':end\\n')",
                )
            )
            environment = os.environ.copy()
            source_root = str(Path(__file__).resolve().parents[1] / "src")
            environment["PYTHONPATH"] = os.pathsep.join(
                part
                for part in (source_root, environment.get("PYTHONPATH", ""))
                if part
            )
            processes = [
                subprocess.Popen(
                    [sys.executable, "-c", script, str(target), str(trace), label],
                    env=environment,
                )
                for label in ("A", "B")
            ]
            for process in processes:
                self.assertEqual(process.wait(timeout=10), 0)

            lines = trace.read_text(encoding="utf-8").splitlines()
            self.assertIn(
                lines,
                (["A:start", "A:end", "B:start", "B:end"],
                 ["B:start", "B:end", "A:start", "A:end"]),
            )

    def test_failed_write_removes_only_its_unique_temporary_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "state.json"
            with patch(
                "jang_app.services.managed_files.os.replace",
                side_effect=PermissionError("permanently locked"),
            ):
                with self.assertRaises(PermissionError):
                    write_json_atomic(target, {"ready": False})

            self.assertFalse(target.exists())
            self.assertEqual(tuple(target.parent.glob(f".{target.name}.*.tmp")), ())

    def test_path_lock_is_reentrant_for_nested_storage_operations(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "state.json"
            with managed_path_lock(target):
                write_json_atomic(target, {"ready": True})

            self.assertEqual(
                json.loads(target.read_text(encoding="utf-8")),
                {"ready": True},
            )


if __name__ == "__main__":
    unittest.main()
