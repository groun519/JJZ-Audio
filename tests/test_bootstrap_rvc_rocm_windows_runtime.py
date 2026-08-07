from __future__ import annotations

import tempfile
import unittest
import subprocess
import sys
from pathlib import Path

from jang_app.services.command import background_command_args, hidden_subprocess_kwargs
from scripts.bootstrap_rvc_rocm_windows_runtime import (
    _enable_site_packages,
    _patch_fairseq_dataclasses,
    _patch_fairseq_hydra_initialization,
)


class BootstrapRvcRocmWindowsRuntimeTests(unittest.TestCase):
    def test_script_entry_point_loads_without_project_on_python_path(self) -> None:
        project_root = Path(__file__).resolve().parents[1]
        result = subprocess.run(
            background_command_args([
                sys.executable,
                str(project_root / "scripts" / "bootstrap_rvc_rocm_windows_runtime.py"),
                "--help",
            ]),
            cwd=project_root.parent,
            capture_output=True,
            text=True,
            check=False,
            **hidden_subprocess_kwargs(),
        )

        self.assertEqual(result.returncode, 0, result.stderr)

    def test_enables_embedded_site_packages(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path_file = root / "python312._pth"
            path_file.write_text("python312.zip\n.\n#import site\n", encoding="utf-8")

            _enable_site_packages(root)

            content = path_file.read_text(encoding="utf-8")
            self.assertIn("Lib/site-packages", content)
            self.assertIn("import site", content)

    def test_patches_mutable_fairseq_config_defaults_for_python_312(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "fairseq"
            root.mkdir()
            source = root / "configs.py"
            source.write_text(
                "from dataclasses import dataclass\n"
                "@dataclass\n"
                "class Config:\n"
                "    common: CommonConfig = CommonConfig()\n"
                "    quant_noise: QuantNoiseConfig = field(default=QuantNoiseConfig())\n",
                encoding="utf-8",
            )

            changed = _patch_fairseq_dataclasses(root)

            content = source.read_text(encoding="utf-8")
            self.assertEqual(changed, 2)
            self.assertIn("from dataclasses import dataclass, field", content)
            self.assertIn("field(default_factory=CommonConfig)", content)
            self.assertIn("field(default_factory=QuantNoiseConfig)", content)

    def test_fairseq_hydra_initialization_uses_default_factory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "fairseq"
            module = root / "dataclass" / "initialize.py"
            module.parent.mkdir(parents=True)
            module.write_text(
                "import logging\n"
                "def hydra_init():\n"
                "    for k in FairseqConfig.__dataclass_fields__:\n"
                "        v = FairseqConfig.__dataclass_fields__[k].default\n"
                "        try:\n"
                "            store(v)\n",
                encoding="utf-8",
            )

            _patch_fairseq_hydra_initialization(root)

            content = module.read_text(encoding="utf-8")
            self.assertIn("import dataclasses", content)
            self.assertIn("field_info.default_factory()", content)
            self.assertIn("if v is dataclasses.MISSING", content)


if __name__ == "__main__":
    unittest.main()
