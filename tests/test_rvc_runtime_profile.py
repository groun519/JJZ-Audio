from __future__ import annotations

import subprocess
import unittest

from jang_app.services.rvc_runtime_profile import (
    NvidiaGpu,
    RVC_PROFILE_CU118,
    RVC_PROFILE_CU128,
    probe_nvidia_gpus,
    select_rvc_runtime_profile,
)


class RvcRuntimeProfileTests(unittest.TestCase):
    def test_selects_cu128_for_blackwell_compute_capability(self) -> None:
        profile = select_rvc_runtime_profile((NvidiaGpu("NVIDIA RTX PRO", (12, 0)),))

        self.assertEqual(profile, RVC_PROFILE_CU128)

    def test_selects_cu128_from_rtx_50_name_when_capability_query_is_unsupported(self) -> None:
        responses = iter(
            (
                subprocess.CompletedProcess((), 1, "", "unsupported field"),
                subprocess.CompletedProcess((), 0, "NVIDIA GeForce RTX 5070\n", ""),
            )
        )

        gpus = probe_nvidia_gpus(lambda _args: next(responses))

        self.assertEqual(gpus[0].name, "NVIDIA GeForce RTX 5070")
        self.assertEqual(select_rvc_runtime_profile(gpus), RVC_PROFILE_CU128)

    def test_keeps_cu118_for_older_gpu(self) -> None:
        result = subprocess.CompletedProcess(
            (),
            0,
            "NVIDIA GeForce RTX 3060, 8.6\n",
            "",
        )

        gpus = probe_nvidia_gpus(lambda _args: result)

        self.assertEqual(gpus[0].compute_capability, (8, 6))
        self.assertEqual(select_rvc_runtime_profile(gpus), RVC_PROFILE_CU118)

    def test_selects_cu128_from_blackwell_product_name(self) -> None:
        self.assertEqual(
            select_rvc_runtime_profile((NvidiaGpu("NVIDIA RTX PRO 6000 Blackwell"),)),
            RVC_PROFILE_CU128,
        )

    def test_cpu_only_pc_uses_base_profile(self) -> None:
        failed = subprocess.CompletedProcess((), 1, "", "not found")

        self.assertEqual(
            select_rvc_runtime_profile(probe_nvidia_gpus(lambda _args: failed)),
            RVC_PROFILE_CU118,
        )


if __name__ == "__main__":
    unittest.main()
