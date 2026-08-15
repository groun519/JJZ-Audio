from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from uuid import uuid4

from jang_app.services.command import background_command_args, hidden_subprocess_kwargs
from jang_app.services.rvc_script_launcher import (
    _ROCM_SINGLE_PROCESS_TRAINING_BOOTSTRAP,
    RvcScriptLauncherError,
    prepare_rvc_script_launcher,
    prepare_rvc_script_workspace,
)
from jang_app.services.rvc_training_performance import RvcTrainingDataLoaderSettings


class RvcScriptLauncherTests(unittest.TestCase):
    def test_launcher_forces_spawned_children_to_pythonw(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            runtime = root / "rvc"
            script = runtime / "worker.py"
            pythonw = runtime / "runtime" / "pythonw.exe"
            pythonw.parent.mkdir(parents=True)
            pythonw.write_bytes(b"pythonw")
            script.write_text("print('ready')\n", encoding="utf-8")

            launcher = prepare_rvc_script_launcher(
                root / "workspace" / "launcher.py",
                runtime,
                script,
            )

            content = launcher.read_text(encoding="utf-8")
            self.assertIn("multiprocessing.set_executable", content)
            self.assertIn("pythonw.exe", content)

    def test_launcher_bootstraps_rvc_imports_in_spawned_children(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            runtime = root / "runtime"
            package = runtime / "lib" / "train"
            package.mkdir(parents=True)
            (runtime / "lib" / "__init__.py").write_text("", encoding="utf-8")
            (package / "__init__.py").write_text("VALUE = 'ready'\n", encoding="utf-8")
            script = runtime / "spawn_probe.py"
            script.write_text(_SPAWN_PROBE, encoding="utf-8")
            workspace = root / "model" / "rvc"
            launcher = prepare_rvc_script_launcher(
                workspace / ".jjzero" / "probe.py",
                runtime,
                script,
            )

            completed = _run_python((str(launcher),), cwd=workspace)

            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual(completed.stdout.strip(), "ready")

    def test_rejects_script_outside_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            runtime = root / "runtime"
            runtime.mkdir()
            script = root / "outside.py"
            script.write_text("", encoding="utf-8")

            with self.assertRaises(RvcScriptLauncherError):
                prepare_rvc_script_launcher(root / "launcher.py", runtime, script)

    def test_workspace_links_available_language_resources(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            runtime = root / "runtime"
            resources = runtime / "lib" / "i18n"
            resources.mkdir(parents=True)
            (resources / "en_US.json").write_text("{}", encoding="utf-8")
            (resources / "ko_KR.json").write_text("{}", encoding="utf-8")

            prepared = prepare_rvc_script_workspace(root / "workspace", runtime)

            self.assertEqual(len(prepared), 2)
            self.assertTrue(
                (root / "workspace" / "lib" / "i18n" / "en_US.json").is_file()
            )
            self.assertTrue(
                (root / "workspace" / "lib" / "i18n" / "ko_KR.json").is_file()
            )

    def test_launcher_can_enable_atomic_legacy_torch_saves(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            runtime = root / "runtime"
            runtime.mkdir()
            script = runtime / "save_probe.py"
            script.write_text(_SAVE_PROBE, encoding="utf-8")
            workspace = root / "workspace"
            launcher = prepare_rvc_script_launcher(
                workspace / "launcher.py",
                runtime,
                script,
                atomic_torch_saves=True,
            )

            completed = _run_python((str(launcher),), cwd=workspace)

            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual(completed.stdout.strip(), "ready")
            self.assertTrue((workspace / "checkpoint.pth").is_file())
            self.assertFalse(tuple(workspace.glob(".*.tmp")))

    def test_launcher_can_supply_missing_legacy_i18n_module(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            runtime = root / "runtime"
            runtime.mkdir()
            script = runtime / "i18n_probe.py"
            script.write_text(
                "from i18n import I18nAuto\nprint(I18nAuto('en_US')('ready'))\n",
                encoding="utf-8",
            )
            workspace = root / "workspace"
            resources = workspace / "lib" / "i18n"
            resources.mkdir(parents=True)
            (resources / "en_US.json").write_text(
                '{"ready": "translated"}',
                encoding="utf-8",
            )
            launcher = prepare_rvc_script_launcher(
                workspace / "launcher.py",
                runtime,
                script,
                legacy_i18n=True,
            )

            completed = _run_python((str(launcher),), cwd=workspace)

            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual(completed.stdout.strip(), "translated")

    def test_launcher_can_omit_unused_optimizer_checkpoint_state(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            runtime = root / "runtime"
            package = runtime / "lib" / "train"
            package.mkdir(parents=True)
            (runtime / "lib" / "__init__.py").write_text("", encoding="utf-8")
            (package / "__init__.py").write_text("", encoding="utf-8")
            (package / "utils.py").write_text(
                "import logging\nlogger = logging.getLogger('probe')\n",
                encoding="utf-8",
            )
            script = runtime / "compact_probe.py"
            script.write_text(_COMPACT_CHECKPOINT_PROBE, encoding="utf-8")
            workspace = root / "workspace"
            launcher = prepare_rvc_script_launcher(
                workspace / "launcher.py",
                runtime,
                script,
                compact_rvc_checkpoints=True,
            )

            completed = _run_python((str(launcher),), cwd=workspace)

            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual(completed.stdout.strip(), "ready")

    def test_launcher_configures_parallel_windowless_data_loading(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            runtime = root / "runtime"
            runtime.mkdir()
            pythonw = runtime / "runtime" / "pythonw.exe"
            pythonw.parent.mkdir()
            pythonw.write_bytes(b"pythonw")
            script = runtime / "loader_probe.py"
            script.write_text(_DATA_LOADER_PROBE, encoding="utf-8")
            workspace = root / "workspace"
            launcher = prepare_rvc_script_launcher(
                workspace / "launcher.py",
                runtime,
                script,
                data_loader_settings=RvcTrainingDataLoaderSettings(
                    workers=4,
                    prefetch_factor=2,
                    pin_memory=True,
                    persistent_workers=True,
                ),
            )

            completed = _run_python((str(launcher),), cwd=workspace)

            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual(completed.stdout.strip(), "4 2 True True 120")

            self.assertIn(
                'if __name__ == "__main__"',
                _ROCM_SINGLE_PROCESS_TRAINING_BOOTSTRAP,
            )

    def test_launcher_replaces_unnecessary_ddp_for_single_device_training(self) -> None:
        probe = (
            "import torch\n"
            "torch.version.hip = '7.2.1'\n"
            f"{_ROCM_SINGLE_PROCESS_TRAINING_BOOTSTRAP}\n"
            f"{_ROCM_SINGLE_PROCESS_PROBE}"
        )
        completed = _run_python(("-c", probe))

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("JJZERO_SINGLE_DEVICE_TRAINING", completed.stdout)
        self.assertTrue(completed.stdout.rstrip().endswith("ready"))

    def test_bundled_pythonw_workers_return_a_real_first_batch(self) -> None:
        repository = Path(__file__).resolve().parents[1]
        runtime = repository / "third_party" / "rvc"
        python = runtime / "runtime" / "python.exe"
        pythonw = runtime / "runtime" / "pythonw.exe"
        if not python.is_file() or not pythonw.is_file():
            self.skipTest("Bundled RVC Python runtime is unavailable.")

        probe = runtime / f".jjzero-loader-probe-{uuid4().hex}.py"
        try:
            probe.write_text(_SPAWNED_DATA_LOADER_PROBE, encoding="utf-8")
            with tempfile.TemporaryDirectory() as temporary:
                workspace = Path(temporary)
                diagnostics = workspace / "diagnostics"
                launcher = prepare_rvc_script_launcher(
                    workspace / "launcher.py",
                    runtime,
                    probe,
                    data_loader_settings=RvcTrainingDataLoaderSettings(
                        workers=2,
                        prefetch_factor=2,
                        pin_memory=False,
                        persistent_workers=False,
                        timeout_seconds=60,
                    ),
                    diagnostic_directory=diagnostics,
                    diagnostic_attempt_id="integration-test",
                )

                completed = subprocess.run(
                    (str(python), str(launcher)),
                    cwd=workspace,
                    check=False,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=90,
                    **hidden_subprocess_kwargs(),
                )

                self.assertEqual(completed.returncode, 0, completed.stderr)
                self.assertEqual(
                    (workspace / "loader-result.txt").read_text(encoding="utf-8"),
                    "0,1,2,3",
                )
                events = "\n".join(
                    path.read_text(encoding="utf-8", errors="replace")
                    for path in (diagnostics / "processes").glob("*.jsonl")
                )
                self.assertIn('"event": "data_worker_initialized"', events)
                self.assertIn('"event": "first_batch_ready"', events)
        finally:
            probe.unlink(missing_ok=True)


def _run_python(
    args: tuple[str, ...],
    *,
    cwd: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        background_command_args((sys.executable, *args)),
        cwd=cwd,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        **hidden_subprocess_kwargs(),
    )


_SPAWN_PROBE = """\
import multiprocessing
from lib.train import VALUE


def read_value(queue):
    from lib.train import VALUE
    queue.put(VALUE)


if __name__ == "__main__":
    multiprocessing.set_start_method("spawn")
    queue = multiprocessing.Queue()
    process = multiprocessing.Process(target=read_value, args=(queue,))
    process.start()
    process.join()
    if process.exitcode != 0:
        raise SystemExit(process.exitcode)
    print(queue.get(timeout=2))
"""

_SAVE_PROBE = """\
from pathlib import Path
import torch

target = Path("checkpoint.pth")
torch.save({"value": torch.tensor([1, 2, 3])}, target)
loaded = torch.load(target, map_location="cpu", weights_only=False)
print("ready" if loaded["value"].tolist() == [1, 2, 3] else "failed")
"""

_COMPACT_CHECKPOINT_PROBE = """\
from pathlib import Path
import torch
from lib.train import utils


class UnusedOptimizer:
    def state_dict(self):
        raise RuntimeError("optimizer state must not be serialized")


target = Path("compact.pth")
model = torch.nn.Linear(3, 2)
utils.save_checkpoint(model, UnusedOptimizer(), 0.0001, 5, target)
loaded = torch.load(target, map_location="cpu", weights_only=False)
restored = torch.nn.Linear(3, 2)
restored.load_state_dict(loaded["model"])
is_ready = (
    loaded["optimizer"] is None
    and loaded["iteration"] == 5
    and loaded["model"]["weight"].dtype == torch.float16
    and restored.weight.dtype == torch.float32
)
print("ready" if is_ready else "failed")
"""

_DATA_LOADER_PROBE = """\
from torch.utils.data import DataLoader, TensorDataset
import torch

loader = DataLoader(
    TensorDataset(torch.arange(4)),
    batch_size=1,
    num_workers=4,
    prefetch_factor=8,
    persistent_workers=True,
)
print(
    loader.num_workers,
    loader.prefetch_factor,
    loader.persistent_workers,
    loader.pin_memory,
    loader.timeout,
)
"""

_SPAWNED_DATA_LOADER_PROBE = """\
from pathlib import Path
import torch
from torch.utils.data import DataLoader, TensorDataset


if __name__ == "__main__":
    loader = DataLoader(
        TensorDataset(torch.arange(4)),
        batch_size=1,
        num_workers=0,
    )
    values = [str(int(batch[0].item())) for batch in loader]
    Path("loader-result.txt").write_text(",".join(values), encoding="utf-8")
"""

_ROCM_SINGLE_PROCESS_PROBE = """\
from torch.nn.parallel import DistributedDataParallel as DDP

events = []
process = torch.multiprocessing.Process(target=lambda: events.append("ran"))
process.start()
process.join()
model = DDP(torch.nn.Linear(3, 2), device_ids=[0])
result = model(torch.ones(1, 3)).sum()
result.backward()
torch.distributed.init_process_group(backend="gloo")
ready = events == ["ran"] and process.exitcode == 0 and hasattr(model, "module")
print("ready" if ready else "failed")
"""


if __name__ == "__main__":
    unittest.main()
