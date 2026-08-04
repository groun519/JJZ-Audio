from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from jang_app.services.rvc_training_runtime import required_rvc_training_paths
from scripts.verify_distribution import required_distribution_files


class VerifyDistributionTests(unittest.TestCase):
    def test_required_files_include_complete_training_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            distribution = Path(temporary).resolve()
            required = set(required_distribution_files(distribution))
            rvc_root = distribution / "runtime" / "rvc"

            self.assertTrue(
                {rvc_root / path for path in required_rvc_training_paths()}.issubset(required)
            )
            self.assertIn(rvc_root / "pretrained_v2" / "f0G40k.pth", required)
            self.assertIn(rvc_root / "train_nsf_sim_cache_sid_load_pretrain.py", required)
            self.assertIn(
                distribution
                / "_internal"
                / "jang_app"
                / "rvc_tools"
                / "rvc_artifact_worker.py",
                required,
            )


if __name__ == "__main__":
    unittest.main()
