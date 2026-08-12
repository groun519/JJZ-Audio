from __future__ import annotations

import hashlib
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
from jang_app.services.tool_workspace import ToolWorkspace


# The bundled SciPy runtime still opens WAV outputs through the legacy Windows
# file API. Keep conversion paths below MAX_PATH with room for collision suffixes.
_RVC_SAFE_OUTPUT_PATH_LENGTH = 240


class RvcConversionError(RuntimeError):
    """Raised when RVC vocal conversion cannot be completed."""


@dataclass(frozen=True)
class RvcConversionResult:
    input_path: Path
    output_path: Path
    voice_model_path: Path
    index_path: Path | None
    voice_model: str = ""
    index_file: str = ""
    pitch: int = 0
    requested_device: str = "auto"
    effective_device: str = "cpu"
    f0_method: str = "rmvpe"


def convert_vocal_with_rvc(input_path: Path, output_dir: Path, settings: RvcSettings) -> RvcConversionResult:
    logger = get_logger()
    source = input_path.expanduser().resolve()
    rvc_root = settings.root.expanduser().resolve()
    runtime_python = rvc_root / "runtime" / "python.exe"
    infer_script = rvc_root / "infer_cli.py"
    model_path = _resolve_rvc_path(rvc_root, settings.voice_model)
    index_path = _resolve_optional_rvc_path(rvc_root, settings.index_file)
    resolved_output_dir = output_dir.expanduser().resolve()
    descriptive_stem = _build_rvc_output_stem(source, settings)
    output_stem = _safe_rvc_output_stem(resolved_output_dir, descriptive_stem, ".wav", settings.pitch)
    output_path = _next_output_path(resolved_output_dir, output_stem, ".wav")

    _validate_conversion_input(source, rvc_root, runtime_python, infer_script, model_path, index_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        device = select_rvc_inference_device(rvc_root, settings.device)
    except RvcInferenceRuntimeError as exc:
        raise RvcConversionError(str(exc)) from exc
    workspace = _prepare_rvc_workspace(
        rvc_root,
        require_directml_rmvpe=(
            settings.f0_method.casefold() == "rmvpe"
            and device.effective_device.casefold().startswith("privateuseone")
        ),
    )
    wrapper_script = workspace / "run_infer_cli.py"

    if output_stem != descriptive_stem:
        logger.info(
            "RVC output path shortened for Windows compatibility: original_length=%s safe_length=%s output=%s",
            _path_length(resolved_output_dir / f"{descriptive_stem}.wav"),
            _path_length(output_path),
            output_path,
        )

    logger.info(
        "Starting RVC conversion: input=%s output=%s model=%s index=%s pitch=%s "
        "f0_method=%s requested_device=%s effective_device=%s",
        source,
        output_path,
        model_path,
        index_path or "none",
        settings.pitch,
        settings.f0_method,
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
    staging_root = workspace / "conversion_jobs"
    with ToolWorkspace(staging_root, "rvc") as job:
        staged_input = job.stage_input(source)
        staged_model = job.stage_file(model_path, f"m{model_path.suffix.casefold()}")
        staged_index = (
            job.stage_file(index_path, f"x{index_path.suffix.casefold()}")
            if index_path is not None
            else None
        )
        staged_output = job.root / "o.wav"
        _require_safe_rvc_runtime_paths(staged_input, staged_output)
        completed = run_command(
            [
                runtime_python,
                wrapper_script,
                rvc_root,
                str(settings.pitch),
                staged_input,
                staged_output,
                staged_model,
                str(staged_index) if staged_index else "",
                device.effective_device,
                settings.f0_method,
            ],
            cwd=workspace,
            env=build_rvc_environment(rvc_root),
        )
        if completed.returncode != 0:
            process_output = text_tail(combined_output(completed.stdout, completed.stderr))
            logger.error(
                "RVC conversion failed with exit code %s\n%s",
                completed.returncode,
                process_output,
            )
            raise RvcConversionError(
                _conversion_failure_message(
                    completed.returncode,
                    device.effective_device,
                    process_output,
                )
            )
        if not staged_output.is_file():
            raise RvcConversionError(
                f"RVC conversion did not create a staged output: {staged_output}"
            )
        _publish_rvc_output(staged_output, output_path)

    logger.info("RVC conversion complete: output=%s", output_path)
    return RvcConversionResult(
        source,
        output_path,
        model_path,
        index_path,
        voice_model=settings.voice_model,
        index_file=settings.index_file,
        pitch=settings.pitch,
        requested_device=settings.device,
        effective_device=device.effective_device,
        f0_method=settings.f0_method,
    )


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


def _prepare_rvc_workspace(
    rvc_root: Path,
    *,
    require_directml_rmvpe: bool = False,
) -> Path:
    RVC_WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)
    _copy_tree(rvc_root / "configs", RVC_WORKSPACE_DIR / "configs")
    _copy_file(rvc_root / "trainset_preprocess_pipeline_print.py", RVC_WORKSPACE_DIR / "trainset_preprocess_pipeline_print.py")
    for name in ("hubert_base.pt", "rmvpe.pt"):
        source = rvc_root / name
        if not source.is_file():
            raise RvcConversionError(f"Required RVC file was not found: {source}")
        link_or_copy_file(source, RVC_WORKSPACE_DIR / name)
    if require_directml_rmvpe:
        source = _find_directml_rmvpe_model(rvc_root)
        link_or_copy_file(source, RVC_WORKSPACE_DIR / "rmvpe.onnx")
    _write_cli_wrapper(RVC_WORKSPACE_DIR / "run_infer_cli.py")
    return RVC_WORKSPACE_DIR


def _find_directml_rmvpe_model(rvc_root: Path) -> Path:
    candidates = (
        rvc_root / "runtime" / "rmvpe.onnx",
        rvc_root / "rmvpe.onnx",
    )
    model = next((path for path in candidates if path.is_file()), None)
    if model is None:
        raise RvcConversionError(
            "The installed DirectML runtime is missing rmvpe.onnx. "
            "Repair or update the AMD runtime before converting."
        )
    return model


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
        if _path_length(candidate) > _RVC_SAFE_OUTPUT_PATH_LENGTH:
            digest = hashlib.sha256(f"{stem}:{index}".encode("utf-8")).hexdigest()[:10]
            candidate = output_dir / f"rvc_{digest}{suffix}"
        if not candidate.exists():
            return candidate
        index += 1


def _safe_rvc_output_stem(output_dir: Path, stem: str, suffix: str, pitch: int) -> str:
    candidate = output_dir / f"{stem}{suffix}"
    if _path_length(candidate) <= _RVC_SAFE_OUTPUT_PATH_LENGTH:
        return stem

    digest = hashlib.sha256(stem.encode("utf-8")).hexdigest()[:10]
    pitch_name = f"p{pitch}" if pitch >= 0 else f"m{abs(pitch)}"
    return f"rvc_{pitch_name}_{digest}"


def _require_safe_rvc_runtime_paths(*paths: Path) -> None:
    unsafe = next(
        (path for path in paths if _path_length(path) > _RVC_SAFE_OUTPUT_PATH_LENGTH),
        None,
    )
    if unsafe is not None:
        raise RvcConversionError(
            "The RVC working path is too long for the bundled Windows audio runtime. "
            f"Choose a shorter workspace location: {unsafe.parent}"
        )


def _publish_rvc_output(staged_output: Path, output_path: Path) -> None:
    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(staged_output), str(output_path))
    except OSError as exc:
        raise RvcConversionError(
            f"RVC conversion finished, but the output could not be saved: {output_path}"
        ) from exc


def _path_length(path: Path) -> int:
    # UTF-16 code units match the length Windows uses for legacy file paths.
    return len(str(path).encode("utf-16-le")) // 2


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
