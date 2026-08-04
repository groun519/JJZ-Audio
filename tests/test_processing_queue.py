from __future__ import annotations

import unittest

from jang_app.services.processing_queue import (
    ProcessingQueue,
    TASK_CANCELLED,
    TASK_COMPLETED,
    TASK_FAILED,
    TASK_RUNNING,
)


class ProcessingQueueTests(unittest.TestCase):
    def test_tracks_progress_and_completion(self) -> None:
        queue = ProcessingQueue()
        task_id = queue.start("Separate Audio", "song.wav", progress=3)

        queue.update_progress(task_id, 55)
        running = queue.tasks()[0]
        self.assertEqual(running.status, TASK_RUNNING)
        self.assertEqual(running.progress, 55)
        self.assertEqual(queue.active_count(), 1)

        queue.complete(task_id)
        completed = queue.tasks()[0]
        self.assertEqual(completed.status, TASK_COMPLETED)
        self.assertEqual(completed.progress, 100)
        self.assertIsNotNone(completed.finished_at)
        self.assertEqual(queue.active_count(), 0)

    def test_preserves_failure_detail_and_clamps_progress(self) -> None:
        queue = ProcessingQueue()
        task_id = queue.start("Convert Vocal", progress=-20)
        self.assertEqual(queue.tasks()[0].progress, 0)

        queue.update_progress(task_id, 220)
        queue.fail(task_id, "full traceback\nconversion failed")
        failed = queue.tasks()[0]

        self.assertEqual(failed.status, TASK_FAILED)
        self.assertEqual(failed.progress, 100)
        self.assertEqual(failed.error, "full traceback\nconversion failed")

    def test_clear_finished_keeps_active_tasks(self) -> None:
        queue = ProcessingQueue()
        completed_id = queue.start("Completed")
        queue.complete(completed_id)
        queue.start("Running")

        queue.clear_finished()

        self.assertEqual([task.title for task in queue.tasks()], ["Running"])

    def test_updates_detail_and_marks_task_cancelled(self) -> None:
        queue = ProcessingQueue()
        task_id = queue.start("Train Model", "Preparing")

        queue.update_detail(task_id, "Training")
        queue.update_progress(task_id, 64)
        queue.cancel(task_id)

        task = queue.tasks()[0]
        self.assertEqual(task.status, TASK_CANCELLED)
        self.assertEqual(task.detail, "Stopped")
        self.assertEqual(task.progress, 64)
        self.assertTrue(task.is_finished)

    def test_notifies_subscribers_for_each_change(self) -> None:
        queue = ProcessingQueue()
        snapshots: list[tuple[int, int]] = []
        queue.subscribe(lambda tasks: snapshots.append((len(tasks), sum(task.is_active for task in tasks))))

        task_id = queue.start("Download")
        queue.update_progress(task_id, 50)
        queue.complete(task_id)

        self.assertEqual(snapshots, [(0, 0), (1, 1), (1, 1), (1, 0)])


if __name__ == "__main__":
    unittest.main()
