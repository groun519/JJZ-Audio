from __future__ import annotations

import unittest

from jang_app.services.rvc_training_recovery import (
    RvcTrainingRecoveryAction,
    advise_rvc_training_recovery,
)


class RvcTrainingRecoveryTests(unittest.TestCase):
    def test_cuda_memory_failure_recommends_a_smaller_batch(self) -> None:
        advice = advise_rvc_training_recovery(
            "RuntimeError: CUDA out of memory",
            can_resume=True,
            current_batch_size=6,
        )

        self.assertEqual(advice.diagnostic_code, "CUDA_OUT_OF_MEMORY")
        self.assertEqual(
            advice.action,
            RvcTrainingRecoveryAction.RETRY_SAFE_BATCH,
        )
        self.assertEqual(advice.suggested_batch_size, 3)

    def test_runtime_failure_routes_to_system_setup(self) -> None:
        advice = advise_rvc_training_recovery(
            "ModuleNotFoundError: No module named 'torch'",
            can_resume=False,
            current_batch_size=2,
        )

        self.assertEqual(advice.diagnostic_code, "PYTHON_MODULE_MISSING")
        self.assertEqual(
            advice.action,
            RvcTrainingRecoveryAction.OPEN_SYSTEM_SETUP,
        )

    def test_storage_failure_routes_to_preflight(self) -> None:
        advice = advise_rvc_training_recovery(
            "OSError: No space left on device",
            can_resume=False,
            current_batch_size=2,
        )

        self.assertEqual(
            advice.action,
            RvcTrainingRecoveryAction.RECHECK,
        )

    def test_unexpected_failure_prefers_a_valid_checkpoint(self) -> None:
        resumable = advise_rvc_training_recovery(
            "Unexpected trainer failure",
            can_resume=True,
            current_batch_size=4,
        )
        fresh = advise_rvc_training_recovery(
            "Unexpected trainer failure",
            can_resume=False,
            current_batch_size=4,
        )

        self.assertEqual(resumable.action, RvcTrainingRecoveryAction.RESUME)
        self.assertEqual(fresh.action, RvcTrainingRecoveryAction.RETRY)

    def test_old_unexpected_code_is_reclassified_from_saved_error(self) -> None:
        advice = advise_rvc_training_recovery(
            "KeyError: param 'initial_lr' is not specified when resuming an optimizer",
            can_resume=True,
            current_batch_size=6,
            diagnostic_code="UNEXPECTED_ERROR",
        )

        self.assertEqual(advice.diagnostic_code, "RVC_CHECKPOINT_RESUME_FAILED")
        self.assertEqual(advice.action, RvcTrainingRecoveryAction.RESUME)


if __name__ == "__main__":
    unittest.main()
