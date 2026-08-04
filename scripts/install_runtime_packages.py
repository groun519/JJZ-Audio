from __future__ import annotations

import argparse
from pathlib import Path

from jang_app.services.runtime_bootstrap import install_ai_runtime_offline


def main() -> int:
    parser = argparse.ArgumentParser(description="Install verified JJZero AI runtime packages.")
    parser.add_argument("package_index", type=Path)
    parser.add_argument("runtime_root", type=Path)
    arguments = parser.parse_args()
    result = install_ai_runtime_offline(arguments.runtime_root, arguments.package_index)
    print(f"Installed AI runtime {result.version}: {result.root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
