from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

from jang_app.services.rvc_hardware import RvcComputeBackend
from jang_app.services.rvc_training_telemetry import (
    RvcTrainingHealth,
    RvcTrainingTelemetryProbe,
    RvcTrainingTelemetrySnapshot,
    append_telemetry_snapshot,
    assess_rvc_training_performance,
    parse_nvidia_smi_telemetry,
)


def _snapshot(
    gpu: float | None,
    *,
    vram_percent: float = 50.0,
    cpu: float = 30.0,
) -> RvcTrainingTelemetrySnapshot:
    total = 10 * 1024**3
    return RvcTrainingTelemetrySnapshot(
        captured_at=datetime.now(UTC).isoformat(),
        gpu_utilization_percent=gpu,
        gpu_memory_used_bytes=round(total * vram_percent / 100),
        gpu_memory_total_bytes=total,
        cpu_utilization_percent=cpu,
        system_memory_used_bytes=8 * 1024**3,
        system_memory_total_bytes=32 * 1024**3,
    )


class RvcTrainingTelemetryTests(unittest.TestCase):
    def test_parses_nvidia_smi_values(self) -> None:
        utilization, used, total, temperature = parse_nvidia_smi_telemetry(
            "87, 4096, 12288, 64\n"
        )

        self.assertEqual(utilization, 87)
        self.assertEqual(used, 4096 * 1024**2)
        self.assertEqual(total, 12288 * 1024**2)
        self.assertEqual(temperature, 64)

    def test_assessment_detects_memory_pressure(self) -> None:
        assessment = assess_rvc_training_performance(
            [_snapshot(90, vram_percent=96) for _ in range(8)],
            RvcComputeBackend.CUDA,
        )

        self.assertEqual(assessment.health, RvcTrainingHealth.MEMORY_PRESSURE)

    def test_assessment_detects_likely_data_supply_bottleneck(self) -> None:
        assessment = assess_rvc_training_performance(
            [_snapshot(25, cpu=85) for _ in range(8)],
            RvcComputeBackend.CUDA,
        )

        self.assertEqual(assessment.health, RvcTrainingHealth.DATA_SUPPLY)

    def test_probe_collects_gpu_and_system_metrics(self) -> None:
        completed = subprocess.CompletedProcess(
            ["nvidia-smi"],
            0,
            stdout="75, 3072, 8192, 58\n",
            stderr="",
        )
        probe = RvcTrainingTelemetryProbe(
            RvcComputeBackend.CUDA,
            nvidia_runner=lambda _args: completed,
        )
        with patch(
            "jang_app.services.rvc_training_telemetry._sample_system_memory",
            return_value=(4 * 1024**3, 16 * 1024**3),
        ):
            snapshot = probe.sample()

        self.assertEqual(snapshot.gpu_utilization_percent, 75)
        self.assertEqual(snapshot.gpu_memory_percent, 37.5)
        self.assertEqual(snapshot.system_memory_percent, 25)
        self.assertEqual(snapshot.monitor_error, "")

    def test_snapshot_is_persisted_as_jsonl(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary) / "job"
            append_telemetry_snapshot(folder, _snapshot(81))

            payload = json.loads((folder / "telemetry.jsonl").read_text(encoding="utf-8"))

        self.assertEqual(payload["gpu_utilization_percent"], 81)


if __name__ == "__main__":
    unittest.main()
