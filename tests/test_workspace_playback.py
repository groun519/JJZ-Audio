from __future__ import annotations

import unittest

from jang_app.services.workspace_playback import (
    WorkspacePlaybackScope,
    scope_label,
    scope_track_ids,
)


class WorkspacePlaybackTests(unittest.TestCase):
    def test_each_workspace_scope_allows_only_its_visible_tracks(self) -> None:
        self.assertEqual(
            scope_track_ids(WorkspacePlaybackScope.SEPARATION),
            ("original", "instrumental"),
        )
        self.assertEqual(
            scope_track_ids(WorkspacePlaybackScope.CONVERSION),
            ("original", "converted"),
        )
        self.assertEqual(
            scope_track_ids(WorkspacePlaybackScope.STUDIO),
            ("original", "instrumental", "converted"),
        )

    def test_each_workspace_scope_has_a_transport_label(self) -> None:
        self.assertEqual(scope_label(WorkspacePlaybackScope.SEPARATION), "Separation Preview")
        self.assertEqual(scope_label(WorkspacePlaybackScope.CONVERSION), "Conversion Compare")
        self.assertEqual(scope_label(WorkspacePlaybackScope.STUDIO), "Studio Mix")


if __name__ == "__main__":
    unittest.main()
