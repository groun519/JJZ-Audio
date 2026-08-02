from __future__ import annotations

import unittest

from jang_app.services.clip_edit_history import (
    ClipEditHistory,
    ClipEditState,
    REVIEW_EDITING,
    REVIEW_READY,
    TRAINING_MODE_CLIPS,
    history_from_data,
    history_to_data,
)


class ClipEditHistoryTests(unittest.TestCase):
    def test_undo_and_redo_restore_complete_edit_state(self) -> None:
        ready = ClipEditState(TRAINING_MODE_CLIPS, REVIEW_READY, ((100, 500),))
        edited = ClipEditState(TRAINING_MODE_CLIPS, REVIEW_EDITING, ((120, 480),))
        history = ClipEditHistory().record(ready)

        undo_state, history = history.undo(edited)
        redo_state, history = history.redo(ready)

        self.assertEqual(undo_state, ready)
        self.assertEqual(redo_state, edited)
        self.assertTrue(history.can_undo)
        self.assertFalse(history.can_redo)

    def test_history_serialization_ignores_invalid_ranges(self) -> None:
        history = ClipEditHistory(
            undo_states=(ClipEditState(TRAINING_MODE_CLIPS, REVIEW_EDITING, ((100, 500),)),),
        )
        data = history_to_data(history)
        data["undo"][0]["ranges"].append([400, 420])

        restored = history_from_data(data)

        self.assertEqual(restored, history)


if __name__ == "__main__":
    unittest.main()
