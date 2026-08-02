from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def open_in_file_browser(path: Path) -> Path:
    target = path.expanduser().resolve()
    if not target.exists():
        raise FileNotFoundError(f"File does not exist: {target}")
    if sys.platform == "win32":
        command = ["explorer.exe", str(target)] if target.is_dir() else ["explorer.exe", f"/select,{target}"]
        subprocess.Popen(command)
    else:
        subprocess.Popen(["open", str(target if target.is_dir() else target.parent)])
    return target
