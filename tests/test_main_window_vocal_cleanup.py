from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from jang_app.qt_app.main_window import MainWindow, WorkTaskScope


class _CleanupWorkspaceState:
    def __init__(self) -> None:
        self.statuses: list[str] = []
        self.render_bar = SimpleNamespace(
            status=SimpleNamespace(setToolTip=lambda _text: None)
        )

    def set_render_status(self, text: str) -> None:
        self.statuses.append(text)


class MainWindowVocalCleanupTests(unittest.TestCase):
    def test_failed_render_discards_unregistered_result_and_companions(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            result_root = Path(temporary) / "run" / "cleanup" / "results"
            target = result_root / "vocals-clean.wav"
            companions = (
                target,
                target.with_suffix(".rendering.wav"),
                target.with_name("vocals-clean-removed.wav"),
                target.with_name("vocals-clean-removed.rendering.wav"),
            )
            for path in companions:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"audio")
            workspace = _CleanupWorkspaceState()
            window = SimpleNamespace(
                current_work_item=SimpleNamespace(id="song-1"),
                vocal_cleanup_workspace=workspace,
            )

            MainWindow._on_vocal_cleanup_render_failed(
                window,
                WorkTaskScope("song-1"),
                "render failed",
                target,
            )

            self.assertTrue(all(not path.exists() for path in companions))
            self.assertEqual(workspace.statuses, ["render failed"])

    def test_late_failed_render_is_cleaned_for_an_inactive_song(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            target = (
                Path(temporary)
                / "run"
                / "cleanup"
                / "results"
                / "vocals-clean.wav"
            )
            target.parent.mkdir(parents=True)
            target.write_bytes(b"audio")
            workspace = _CleanupWorkspaceState()
            window = SimpleNamespace(
                current_work_item=SimpleNamespace(id="song-2"),
                vocal_cleanup_workspace=workspace,
            )

            MainWindow._on_vocal_cleanup_render_failed(
                window,
                WorkTaskScope("song-1"),
                "render failed",
                target,
            )

            self.assertFalse(target.exists())
            self.assertEqual(workspace.statuses, [])


if __name__ == "__main__":
    unittest.main()
