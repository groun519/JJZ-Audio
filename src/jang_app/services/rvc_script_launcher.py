from __future__ import annotations

from pathlib import Path

from jang_app.services.managed_files import link_or_copy_file, write_text_atomic


class RvcScriptLauncherError(ValueError):
    """Raised when an RVC script launcher cannot be prepared safely."""


def prepare_rvc_script_workspace(workspace: Path, rvc_root: Path) -> tuple[Path, ...]:
    root = rvc_root.expanduser().resolve()
    source_dir = root / "lib" / "i18n"
    locale_files = tuple(
        sorted(source_dir.glob("*.json"), key=lambda path: path.name.casefold())
    )
    if not (source_dir / "en_US.json").is_file() or not locale_files:
        raise RvcScriptLauncherError(
            f"RVC language resources were not found: {source_dir}"
        )

    destination_dir = workspace.expanduser().resolve() / "lib" / "i18n"
    return tuple(
        link_or_copy_file(source, destination_dir / source.name) for source in locale_files
    )


def prepare_rvc_script_launcher(
    target: Path,
    rvc_root: Path,
    script: Path,
    *,
    atomic_torch_saves: bool = False,
    compact_rvc_checkpoints: bool = False,
    conservative_data_loading: bool = False,
    rocm_single_process_training: bool = False,
    legacy_i18n: bool = False,
) -> Path:
    root = rvc_root.expanduser().resolve()
    source = script.expanduser().resolve()
    destination = target.expanduser().resolve()
    if not source.is_file():
        raise RvcScriptLauncherError(f"RVC script was not found: {source}")
    if not _is_within(source, root):
        raise RvcScriptLauncherError("RVC script must be inside the selected runtime.")

    # Keep __file__ pointed at this launcher so multiprocessing children rerun
    # the same path bootstrap before importing the original RVC script.
    lines = [
        "from pathlib import Path",
        "import multiprocessing",
        "import sys",
        "",
        f"RVC_ROOT = Path({str(root)!r})",
        f"RVC_SCRIPT = Path({str(source)!r})",
        "RVC_PYTHONW = RVC_ROOT / 'runtime' / 'pythonw.exe'",
        "if RVC_PYTHONW.is_file():",
        "    multiprocessing.set_executable(str(RVC_PYTHONW))",
        "sys.path.insert(0, str(RVC_ROOT))",
    ]
    if legacy_i18n:
        lines.extend(("", _LEGACY_I18N_BOOTSTRAP.rstrip(), ""))
    if atomic_torch_saves:
        lines.extend(("", _ATOMIC_TORCH_SAVE_BOOTSTRAP.rstrip(), ""))
    if compact_rvc_checkpoints:
        lines.extend(("", _COMPACT_RVC_CHECKPOINT_BOOTSTRAP.rstrip(), ""))
    if conservative_data_loading:
        lines.extend(("", _CONSERVATIVE_DATA_LOADER_BOOTSTRAP.rstrip(), ""))
    if rocm_single_process_training:
        lines.extend(("", _ROCM_SINGLE_PROCESS_TRAINING_BOOTSTRAP.rstrip(), ""))
    lines.extend(
        (
            "sys.argv[0] = str(RVC_SCRIPT)",
            "exec(compile(RVC_SCRIPT.read_bytes(), str(RVC_SCRIPT), 'exec'), globals(), globals())",
            "",
        )
    )
    content = "\n".join(lines)
    write_text_atomic(destination, content)
    return destination


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


_ATOMIC_TORCH_SAVE_BOOTSTRAP = '''import gc
import os
import time
import uuid

import torch


_jjzero_original_torch_save = torch.save


class _JjzeroPythonWriteStream:
    def __init__(self, stream):
        self._stream = stream

    def write(self, data):
        return self._stream.write(data)

    def flush(self):
        return self._stream.flush()


def _jjzero_atomic_torch_save(value, destination, *args, **kwargs):
    if not isinstance(destination, (str, os.PathLike)):
        return _jjzero_original_torch_save(value, destination, *args, **kwargs)
    target = Path(destination).expanduser().resolve()
    options = dict(kwargs)
    options["_use_new_zipfile_serialization"] = False
    target.parent.mkdir(parents=True, exist_ok=True)
    for attempt in range(3):
        temporary = target.with_name(
            f".{target.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp"
        )
        try:
            with temporary.open("wb", buffering=1024 * 1024) as output:
                _jjzero_original_torch_save(
                    value,
                    _JjzeroPythonWriteStream(output),
                    *args,
                    **options,
                )
                output.flush()
            if not temporary.is_file() or temporary.stat().st_size <= 0:
                raise OSError(f"Torch save did not produce a complete file: {target}")
            os.replace(temporary, target)
            return None
        except (OSError, RuntimeError):
            temporary.unlink(missing_ok=True)
            if attempt == 2:
                raise
            gc.collect()
            time.sleep(attempt + 1)


torch.save = _jjzero_atomic_torch_save
'''


_LEGACY_I18N_BOOTSTRAP = '''import json
import locale
import types


if "i18n" not in sys.modules:
    _jjzero_i18n_module = types.ModuleType("i18n")

    class _JjzeroI18nAuto:
        def __init__(self, language=None):
            if language in {"Auto", None}:
                language = locale.getlocale()[0] or "en_US"
            resources = Path.cwd() / "lib" / "i18n"
            language_path = resources / f"{language}.json"
            if not language_path.is_file():
                language = "en_US"
                language_path = resources / "en_US.json"
            self.language = language
            try:
                self.language_map = json.loads(language_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                self.language_map = {}

        def __call__(self, key):
            return self.language_map.get(key, key)

        def print(self):
            print("Use Language:", self.language)

    _jjzero_i18n_module.I18nAuto = _JjzeroI18nAuto
    sys.modules["i18n"] = _jjzero_i18n_module
'''


_COMPACT_RVC_CHECKPOINT_BOOTSTRAP = '''import torch

from lib.train import utils as _jjzero_train_utils


def _jjzero_state_dict(model):
    source = model.module.state_dict() if hasattr(model, "module") else model.state_dict()
    compact = {}
    for name, value in source.items():
        if not torch.is_tensor(value):
            compact[name] = value
            continue
        value = value.detach().cpu()
        if torch.is_floating_point(value):
            value = value.half()
        compact[name] = value.contiguous()
    return compact


def _jjzero_save_checkpoint(
    model,
    optimizer,
    learning_rate,
    iteration,
    checkpoint_path,
):
    _jjzero_train_utils.logger.info(
        "Saving compact model state at epoch %s to %s",
        iteration,
        checkpoint_path,
    )
    torch.save(
        {
            "model": _jjzero_state_dict(model),
            "iteration": iteration,
            "optimizer": None,
            "learning_rate": learning_rate,
        },
        checkpoint_path,
    )


def _jjzero_save_checkpoint_d(
    combined_discriminator,
    sub_discriminator,
    optimizer,
    learning_rate,
    iteration,
    checkpoint_path,
):
    _jjzero_train_utils.logger.info(
        "Saving compact discriminator state at epoch %s to %s",
        iteration,
        checkpoint_path,
    )
    torch.save(
        {
            "combd": _jjzero_state_dict(combined_discriminator),
            "sbd": _jjzero_state_dict(sub_discriminator),
            "iteration": iteration,
            "optimizer": None,
            "learning_rate": learning_rate,
        },
        checkpoint_path,
    )


_jjzero_train_utils.save_checkpoint = _jjzero_save_checkpoint
_jjzero_train_utils.save_checkpoint_d = _jjzero_save_checkpoint_d
'''


_CONSERVATIVE_DATA_LOADER_BOOTSTRAP = '''import torch.utils.data


_jjzero_original_data_loader = torch.utils.data.DataLoader


class _JjzeroConservativeDataLoader(_jjzero_original_data_loader):
    def __init__(self, *args, **kwargs):
        requested_workers = max(0, int(kwargs.get("num_workers", 0)))
        if requested_workers > 0:
            # Embedded Python workers can briefly create console windows on
            # some CUDA runtime profiles. RVC datasets are already prepared
            # locally, so loading them in the trainer process is predictable.
            kwargs["num_workers"] = 0
            kwargs.pop("prefetch_factor", None)
            kwargs["persistent_workers"] = False
        super().__init__(*args, **kwargs)

    def __iter__(self):
        print("JJZERO_TRAINING_DATA_LOADER_START", flush=True)
        for index, batch in enumerate(super().__iter__()):
            if index == 0:
                print("JJZERO_TRAINING_FIRST_BATCH_READY", flush=True)
            yield batch


torch.utils.data.DataLoader = _JjzeroConservativeDataLoader
'''


_ROCM_SINGLE_PROCESS_TRAINING_BOOTSTRAP = '''import torch
import torch.distributed
import torch.nn.parallel


if getattr(torch.version, "hip", None) or torch.cuda.device_count() <= 1:
    print("JJZERO_SINGLE_DEVICE_TRAINING", flush=True)

    class _JjzeroSingleProcessDistributedDataParallel(torch.nn.Module):
        def __init__(self, module, *args, **kwargs):
            super().__init__()
            self.module = module

        def forward(self, *args, **kwargs):
            return self.module(*args, **kwargs)


    def _jjzero_skip_single_process_group(*args, **kwargs):
        return None


    torch.distributed.init_process_group = _jjzero_skip_single_process_group
    torch.nn.parallel.DistributedDataParallel = (
        _JjzeroSingleProcessDistributedDataParallel
    )
'''
