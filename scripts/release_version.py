from __future__ import annotations

import argparse
import importlib.util
import re
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
VERSION_MODULE = PROJECT_ROOT / "src" / "jang_app" / "version.py"
WINDOWS_VERSION_FILE = PROJECT_ROOT / "packaging" / "windows_version_info.txt"
_VERSION_PATTERN = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")


def load_release_version(version_module: Path = VERSION_MODULE) -> str:
    spec = importlib.util.spec_from_file_location("jjzero_release_version", version_module)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load version module: {version_module}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    version = str(getattr(module, "__version__", "")).strip()
    if not _VERSION_PATTERN.fullmatch(version):
        raise ValueError(f"Release version must use MAJOR.MINOR.PATCH: {version!r}")
    return version


def write_windows_version_info(
    destination: Path = WINDOWS_VERSION_FILE,
    version: str | None = None,
) -> Path:
    resolved_version = version or load_release_version()
    match = _VERSION_PATTERN.fullmatch(resolved_version)
    if match is None:
        raise ValueError(f"Release version must use MAJOR.MINOR.PATCH: {resolved_version!r}")
    major, minor, patch = (int(part) for part in match.groups())
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        _WINDOWS_VERSION_TEMPLATE.format(
            major=major,
            minor=minor,
            patch=patch,
            version=resolved_version,
        ),
        encoding="utf-8",
    )
    return destination


def main() -> int:
    parser = argparse.ArgumentParser(description="Read or generate JJZero Audio release version assets.")
    parser.add_argument("command", choices=("print", "write-windows-info"))
    arguments = parser.parse_args()
    version = load_release_version()
    if arguments.command == "print":
        print(version)
    else:
        destination = write_windows_version_info(version=version)
        print(f"Created Windows version info: {destination}")
    return 0


_WINDOWS_VERSION_TEMPLATE = """VSVersionInfo(
  ffi=FixedFileInfo(
    filevers=({major}, {minor}, {patch}, 0),
    prodvers=({major}, {minor}, {patch}, 0),
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo([
      StringTable(
        u'040904B0',
        [
          StringStruct(u'CompanyName', u'JJZero'),
          StringStruct(u'FileDescription', u'JJZero Audio'),
          StringStruct(u'FileVersion', u'{version}'),
          StringStruct(u'InternalName', u'JJZero Audio'),
          StringStruct(u'OriginalFilename', u'JJZero Audio.exe'),
          StringStruct(u'ProductName', u'JJZero Audio'),
          StringStruct(u'ProductVersion', u'{version}')
        ]
      )
    ]),
    VarFileInfo([VarStruct(u'Translation', [1033, 1200])])
  ]
)
"""


if __name__ == "__main__":
    raise SystemExit(main())
