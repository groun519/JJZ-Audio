from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from jang_app.services.rvc_script_launcher import (
    RvcScriptLauncherError,
    prepare_rvc_script_launcher,
    prepare_rvc_script_workspace,
)


class RvcScriptLauncherTests(unittest.TestCase):
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

            completed = subprocess.run(
                [sys.executable, str(launcher)],
                cwd=workspace,
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )

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

            completed = subprocess.run(
                [sys.executable, str(launcher)],
                cwd=workspace,
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual(completed.stdout.strip(), "ready")
            self.assertTrue((workspace / "checkpoint.pth").is_file())
            self.assertFalse(tuple(workspace.glob(".*.tmp")))

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

            completed = subprocess.run(
                [sys.executable, str(launcher)],
                cwd=workspace,
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual(completed.stdout.strip(), "ready")

    def test_launcher_can_reduce_rvc_data_loader_memory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            runtime = root / "runtime"
            runtime.mkdir()
            script = runtime / "loader_probe.py"
            script.write_text(_DATA_LOADER_PROBE, encoding="utf-8")
            workspace = root / "workspace"
            launcher = prepare_rvc_script_launcher(
                workspace / "launcher.py",
                runtime,
                script,
                conservative_data_loading=True,
            )

            completed = subprocess.run(
                [sys.executable, str(launcher)],
                cwd=workspace,
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual(completed.stdout.strip(), "1 2 False")


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
print(loader.num_workers, loader.prefetch_factor, loader.persistent_workers)
"""


if __name__ == "__main__":
    unittest.main()
