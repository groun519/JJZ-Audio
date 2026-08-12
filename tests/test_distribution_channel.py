from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from jang_app.services.distribution_channel import (
    DIRECT_CHANNEL,
    STORE_CHANNEL,
    application_updates_enabled,
    current_distribution_channel,
)


class DistributionChannelTests(unittest.TestCase):
    def test_development_build_defaults_to_direct(self) -> None:
        self.assertEqual(
            current_distribution_channel(environ={}, frozen=False),
            DIRECT_CHANNEL,
        )

    def test_environment_can_select_store_channel(self) -> None:
        self.assertEqual(
            current_distribution_channel(
                environ={"JJZERO_DISTRIBUTION_CHANNEL": " STORE "},
                frozen=False,
            ),
            STORE_CHANNEL,
        )

    def test_frozen_build_reads_store_marker(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            executable = root / "JJZero Audio.exe"
            (root / "distribution-channel.json").write_text(
                json.dumps({"channel": "store"}),
                encoding="utf-8",
            )

            self.assertEqual(
                current_distribution_channel(
                    environ={},
                    frozen=True,
                    executable=executable,
                ),
                STORE_CHANNEL,
            )
            self.assertFalse(
                application_updates_enabled(
                    environ={},
                    frozen=True,
                    executable=executable,
                )
            )

    def test_invalid_marker_preserves_direct_updates(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "distribution-channel.json").write_text("not-json", encoding="utf-8")

            self.assertTrue(
                application_updates_enabled(
                    environ={},
                    frozen=True,
                    executable=root / "JJZero Audio.exe",
                )
            )

    def test_frozen_build_accepts_marker_with_utf8_bom(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "distribution-channel.json").write_text(
                json.dumps({"channel": "store"}),
                encoding="utf-8-sig",
            )

            self.assertEqual(
                current_distribution_channel(
                    environ={},
                    frozen=True,
                    executable=root / "JJZero Audio.exe",
                ),
                STORE_CHANNEL,
            )


if __name__ == "__main__":
    unittest.main()
