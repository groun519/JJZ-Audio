from __future__ import annotations

import json
import platform
import sys
import zipfile
from datetime import UTC, datetime
from pathlib import Path

from jang_app.config import APP_PATHS, LOG_FILE
from jang_app.services.hardware_diagnostics_state import recorded_hardware_selection
from jang_app.services.job_diagnostics import JobDiagnostics, redact_text
from jang_app.services.managed_files import atomic_output_path
from jang_app.services.runtime_installation import installed_rvc_runtime_profile
from jang_app.version import __version__


_MAX_LOG_BYTES = 1_500_000
_MAX_JOB_REPORTS = 20


def build_support_archive(
    diagnostics: JobDiagnostics,
    *,
    output_dir: Path | None = None,
    log_file: Path = LOG_FILE,
) -> Path | None:
    destination = Path(output_dir or APP_PATHS.log_dir)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    archive = destination / f"JJZero-Support-Diagnostics-{timestamp}.zip"
    try:
        destination.mkdir(parents=True, exist_ok=True)
        with atomic_output_path(archive, operation="support") as temporary:
            with zipfile.ZipFile(
                temporary,
                "w",
                compression=zipfile.ZIP_DEFLATED,
                compresslevel=6,
            ) as package:
                package.writestr(
                    "system.json",
                    json.dumps(
                        _system_summary(),
                        ensure_ascii=False,
                        indent=2,
                        sort_keys=True,
                    ),
                )
                for index, source in enumerate(_log_sources(log_file)):
                    text = _read_text_tail_bytes(source, _MAX_LOG_BYTES)
                    if text:
                        name = "jang.log" if index == 0 else f"jang.log.{index}"
                        package.writestr(f"logs/{name}", redact_text(text))
                records = diagnostics.records(limit=_MAX_JOB_REPORTS)
                index_payload = [
                    {
                        "task_id": record.task_id,
                        "title": record.title,
                        "status": record.status,
                        "progress": record.progress,
                        "started_at": record.started_at.isoformat(),
                        "finished_at": (
                            record.finished_at.isoformat()
                            if record.finished_at is not None
                            else None
                        ),
                        "diagnostic_code": record.diagnostic_code,
                        "app_version": record.app_version,
                    }
                    for record in records
                ]
                package.writestr(
                    "jobs/index.json",
                    json.dumps(index_payload, ensure_ascii=False, indent=2),
                )
                for record in records:
                    package.writestr(
                        f"jobs/{record.task_id}/report.txt",
                        redact_text(diagnostics.build_report(record.task_id)),
                    )
        return archive
    except (OSError, ValueError, zipfile.BadZipFile):
        return None


def _system_summary() -> dict[str, object]:
    selection = recorded_hardware_selection(APP_PATHS)
    installed = installed_rvc_runtime_profile(APP_PATHS.runtime_root / "rvc")
    adapter = selection.adapter if selection is not None else None
    return {
        "app_version": __version__,
        "created_at": datetime.now(UTC).isoformat(),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "python": platform.python_version(),
        "frozen": bool(getattr(sys, "frozen", False)),
        "storage_root": str(APP_PATHS.storage_root),
        "workspace_root": str(APP_PATHS.workspace_root),
        "output_root": str(APP_PATHS.output_root),
        "runtime_root": str(APP_PATHS.runtime_root),
        "hardware_profile": selection.profile if selection is not None else "",
        "training_backend": (
            selection.training_backend.value if selection is not None else ""
        ),
        "adapter_name": adapter.name if adapter is not None else "",
        "adapter_vendor": adapter.vendor if adapter is not None else "",
        "runtime_profile": installed.profile if installed is not None else "",
        "runtime_version": installed.version if installed is not None else "",
        "runtime_activation": (
            installed.activation_status if installed is not None else ""
        ),
    }


def _log_sources(log_file: Path) -> tuple[Path, ...]:
    candidates = (log_file, *(Path(f"{log_file}.{index}") for index in range(1, 4)))
    return tuple(path for path in candidates if path.is_file())


def _read_text_tail_bytes(path: Path, max_bytes: int) -> str:
    try:
        with path.open("rb") as stream:
            stream.seek(0, 2)
            size = stream.tell()
            stream.seek(max(0, size - max(1, max_bytes)))
            data = stream.read()
    except OSError:
        return ""
    text = data.decode("utf-8", errors="replace")
    if size > max_bytes:
        _discarded, separator, text = text.partition("\n")
        if not separator:
            return ""
    return text
