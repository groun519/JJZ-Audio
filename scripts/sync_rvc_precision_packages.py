from __future__ import annotations

import argparse
from pathlib import Path

try:
    from scripts.prepare_rvc_runtime_profile import install_precision_packages
except ModuleNotFoundError:  # Direct script execution adds scripts/, not the project root.
    from prepare_rvc_runtime_profile import install_precision_packages


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Synchronize precision separation packages for RVC runtime profiles."
    )
    parser.add_argument("profile_roots", nargs="+", type=Path)
    arguments = parser.parse_args()
    for profile_root in arguments.profile_roots:
        root = profile_root.expanduser().resolve()
        python = root / "python.exe"
        if not python.is_file():
            raise FileNotFoundError(f"RVC profile Python was not found: {python}")
        result = install_precision_packages(python, root)
        print(f"Prepared precision separation packages: {result}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
