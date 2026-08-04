from __future__ import annotations

import sys
import time
import unittest

from jang_app.services.command import CommandCancellation, run_cancellable_command


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


if __name__ == "__main__":
    unittest.main()
