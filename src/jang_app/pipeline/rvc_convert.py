from __future__ import annotations

import re
import shutil
from dataclasses import dataclass
from pathlib import Path

from jang_app.config import RVC_WORKSPACE_DIR
from jang_app.services.app_logging import get_logger
from jang_app.services.command import run_command
from jang_app.services.managed_files import link_or_copy_file
from jang_app.services.rvc_environment import build_rvc_environment
from jang_app.services.rvc_inference_runtime import (
    RvcInferenceRuntimeError,
    select_rvc_inference_device,
)
from jang_app.services.settings import RvcSettings
from jang_app.services.text_tail import combined_output, text_tail


class RvcConversionError(RuntimeError):
    """Raised when RVC vocal conversion cannot be completed."""


@dataclass(frozen=True)
class RvcConversionResult:
    input_path: Path
    output_path: Path
    voice_model_path: Path
    index_path: Path | None


def convert_vocal_with_rvc(input_path: Path, output_dir: Path, settings: RvcSettings) -> RvcConversionResult:
    logger = get_logger()
    source = input_path.expanduser().resolve()
    rvc_root = settings.root.expanduser().resolve()
    runtime_python = rvc_root / "runtime" / "python.exe"
    infer_script = rvc_root / "infer_cli.py"
    model_path = _resolve_rvc_path(rvc_root, settings.voice_model)
    index_path = _resolve_optional_rvc_path(rvc_root, settings.index_file)
    output_path = _next_output_path(output_dir.expanduser().resolve(), _build_rvc_output_stem(source, settings), ".wav")

    _validate_conversion_input(source, rvc_root, runtime_python, infer_script, model_path, index_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        device = select_rvc_inference_device(rvc_root, settings.device)
    except RvcInferenceRuntimeError as exc:
        raise RvcConversionError(str(exc)) from exc
    workspace = _prepare_rvc_workspace(rvc_root)
    wrapper_script = workspace / "run_infer_cli.py"

    logger.info(
        "Starting RVC conversion: input=%s output=%s model=%s requested_device=%s effective_device=%s",
        source,
        output_path,
        model_path,
        device.requested_device,
        device.effective_device,
    )
    if device.fallback_reason:
        logger.warning("RVC device fallback: %s", device.fallback_reason)
    capabilities = device.capabilities
    logger.info(
        "RVC runtime: backend=%s torch=%s cuda=%s hip=%s gpu=%s capability=%s architectures=%s",
        capabilities.accelerator_backend.value,
        capabilities.torch_version or "unknown",
        capabilities.cuda_version or "unknown",
        capabilities.hip_version or "none",
        capabilities.device_name or capabilities.directml_device_name or "none",
        ".".join(str(part) for part in capabilities.device_capability) or "unknown",
        ",".join(capabilities.cuda_arch_list) or "unknown",
    )
    completed = run_command(
        [
            runtime_python,
            wrapper_script,
            rvc_root,
            str(settings.pitch),
            source,
            output_path,
            model_path,
            str(index_path) if index_path else "",
            device.effective_device,
            settings.f0_method,
        ],
        cwd=workspace,
        env=build_rvc_environment(rvc_root),
    )
    if completed.returncode != 0:
        process_output = text_tail(combined_output(completed.stdout, completed.stderr))
        logger.error("RVC conversion failed with exit code %s\n%s", completed.returncode, process_output)
        raise RvcConversionError(
            _conversion_failure_message(
                completed.returncode,
                device.effective_device,
                process_output,
            )
        )
    if not output_path.exists():
        raise RvcConversionError(f"RVC conversion did not create output: {output_path}")

    logger.info("RVC conversion complete: output=%s", output_path)
    return RvcConversionResult(source, output_path, model_path, index_path)


def list_voice_models(rvc_root: Path) -> list[str]:
    weights_dir = rvc_root.expanduser() / "weights"
    if not weights_dir.exists():
        return []
    return sorted(_relative_to_root(path, rvc_root) for path in weights_dir.glob("*.pth"))


def list_index_files(rvc_root: Path) -> list[str]:
    logs_dir = rvc_root.expanduser() / "logs"
    if not logs_dir.exists():
        return []
    return sorted(
        _relative_to_root(path, rvc_root)
        for path in logs_dir.rglob("*.index")
        if "trained" not in path.name.lower()
    )


def _validate_conversion_input(
    source: Path,
    rvc_root: Path,
    runtime_python: Path,
    infer_script: Path,
    model_path: Path,
    index_path: Path | None,
) -> None:
    checks = [
        (source.is_file(), f"Input vocal file does not exist: {source}"),
        (rvc_root.is_dir(), f"RVC root does not exist: {rvc_root}"),
        (runtime_python.is_file(), f"RVC runtime python was not found: {runtime_python}"),
        (infer_script.is_file(), f"RVC CLI script was not found: {infer_script}"),
        (model_path.is_file(), f"RVC voice model was not found: {model_path}"),
    ]
    for is_valid, message in checks:
        if not is_valid:
            raise RvcConversionError(message)
    if index_path is not None and not index_path.is_file():
        raise RvcConversionError(f"RVC index file was not found: {index_path}")


def _prepare_rvc_workspace(rvc_root: Path) -> Path:
    RVC_WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)
    _copy_tree(rvc_root / "configs", RVC_WORKSPACE_DIR / "configs")
    _copy_file(rvc_root / "trainset_preprocess_pipeline_print.py", RVC_WORKSPACE_DIR / "trainset_preprocess_pipeline_print.py")
    for name in ("hubert_base.pt", "rmvpe.pt"):
        source = rvc_root / name
        if not source.is_file():
            raise RvcConversionError(f"Required RVC file was not found: {source}")
        link_or_copy_file(source, RVC_WORKSPACE_DIR / name)
    _write_cli_wrapper(RVC_WORKSPACE_DIR / "run_infer_cli.py")
    return RVC_WORKSPACE_DIR


def _write_cli_wrapper(target: Path) -> None:
    target.write_text(
        "\n".join(
            [
                "from __future__ import annotations",
                "",
                "import runpy",
                "import sys",
                "from pathlib import Path",
                "",
                "rvc_root = Path(sys.argv[1]).resolve()",
                "infer_script = rvc_root / 'infer_cli.py'",
                "sys.argv = [str(infer_script)] + sys.argv[2:]",
                "sys.path.insert(0, str(rvc_root))",
                "runpy.run_path(str(infer_script), run_name='__main__')",
                "",
            ]
        ),
        encoding="utf-8",
    )


def _resolve_rvc_path(rvc_root: Path, value: str) -> Path:
    if not value.strip():
        return Path()
    path = Path(value).expanduser()
    if path.is_absolute():
        return path
    return rvc_root / path


def _resolve_optional_rvc_path(rvc_root: Path, value: str) -> Path | None:
    if not value.strip():
        return None
    return _resolve_rvc_path(rvc_root, value)


def _next_output_path(output_dir: Path, stem: str, suffix: str) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    first_path = output_dir / f"{stem}{suffix}"
    if not first_path.exists():
        return first_path

    index = 2
    while True:
        candidate = output_dir / f"{stem}_{index:03d}{suffix}"
        if not candidate.exists():
            return candidate
        index += 1


def _build_rvc_output_stem(source: Path, settings: RvcSettings) -> str:
    model_name = _slugify_path_stem(settings.voice_model, "model")
    index_name = _slugify_index_name(settings.index_file)
    pitch_name = f"pitch_{settings.pitch:+d}".replace("+", "p").replace("-", "m")
    f0_name = _slugify(settings.f0_method or "rmvpe")
    return f"{source.stem}_rvc_{model_name}_{pitch_name}_{index_name}_{f0_name}"


def _slugify_path_stem(value: str, fallback: str) -> str:
    if not value.strip():
        return fallback
    return _slugify(Path(value).stem) or fallback


def _slugify_index_name(value: str) -> str:
    if not value.strip():
        return "noindex"
    path = Path(value)
    parent_name = path.parent.name
    if parent_name and parent_name.lower() not in {"logs", "."}:
        return _slugify(parent_name)

    stem = path.stem
    match = re.search(r"_nprobe_\d+_(?P<name>.+)$", stem)
    if match:
        return _slugify(match.group("name"))
    return _slugify(stem) or "index"


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", value).strip("_").lower()
    return slug or "value"


def _copy_tree(source: Path, target: Path) -> None:
    if not source.exists():
        raise RvcConversionError(f"Required RVC folder was not found: {source}")
    shutil.copytree(source, target, dirs_exist_ok=True)


def _copy_file(source: Path, target: Path) -> None:
    if not source.exists():
        raise RvcConversionError(f"Required RVC file was not found: {source}")
    shutil.copy2(source, target)


def _relative_to_root(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root.expanduser()))
    except ValueError:
        return str(path)


def _conversion_failure_message(returncode: int, device: str, process_output: str = "") -> str:
    windows_code = returncode & 0xFFFFFFFF
    if windows_code == 0xC0000094:
        message = (
            "RVC runtime crashed with Windows status 0xC0000094 (integer divide by zero). "
            f"Selected device: {device}."
        )
    else:
        message = f"RVC conversion failed with exit code {returncode}. Selected device: {device}."
    if process_output:
        return f"{message}\n\nRVC output:\n{process_output}"
    return f"{message} See logs for details."
