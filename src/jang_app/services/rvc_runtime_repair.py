from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from jang_app.services.managed_files import copy_file_atomic


_LOGGER = logging.getLogger("jang_app")
_ADAPTER_RELATIVE_PATH = Path("lib/jjzero_device.py")


@dataclass(frozen=True)
class RvcRuntimeRepair:
    target: Path
    status: str
    detail: str = ""

    @property
    def repaired(self) -> bool:
        return self.status == "repaired"


def bundled_device_adapter() -> Path:
    return Path(__file__).resolve().parents[1] / "rvc_tools" / "jjzero_device.py"


def repair_rvc_runtime_adapter(
    rvc_root: Path,
    adapter_source: Path | None = None,
) -> RvcRuntimeRepair:
    root = rvc_root.expanduser().resolve()
    target = root / _ADAPTER_RELATIVE_PATH
    if not root.is_dir():
        return RvcRuntimeRepair(target, "unavailable")

    source = (adapter_source or bundled_device_adapter()).expanduser().resolve()
    if not source.is_file():
        detail = f"Bundled RVC device adapter is missing: {source}"
        _LOGGER.warning(detail)
        return RvcRuntimeRepair(target, "failed", detail)

    try:
        if target.is_file() and target.read_bytes() == source.read_bytes():
            return RvcRuntimeRepair(target, "ready")
        copy_file_atomic(source, target)
    except OSError as exc:
        detail = f"Could not repair the RVC device adapter at {target}: {exc}"
        _LOGGER.warning(detail)
        return RvcRuntimeRepair(target, "failed", detail)

    _LOGGER.info("Repaired RVC device adapter: %s", target)
    return RvcRuntimeRepair(target, "repaired")
