from __future__ import annotations

from pathlib import Path

from jang_app.services.managed_files import link_or_copy_file, write_text_atomic
from jang_app.services.rvc_training_performance import RvcTrainingDataLoaderSettings


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
    data_loader_settings: RvcTrainingDataLoaderSettings | None = None,
    rocm_single_process_training: bool = False,
    legacy_i18n: bool = False,
    diagnostic_directory: Path | None = None,
    diagnostic_attempt_id: str = "",
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
        (
            "JJZERO_DIAGNOSTIC_DIRECTORY = "
            + (
                f"Path({str(diagnostic_directory.expanduser().resolve())!r})"
                if diagnostic_directory is not None
                else "None"
            )
        ),
        f"JJZERO_DIAGNOSTIC_ATTEMPT_ID = {str(diagnostic_attempt_id)!r}",
        _DIAGNOSTIC_BOOTSTRAP.rstrip(),
        "",
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
    if data_loader_settings is not None:
        data_loader_settings.validate()
        lines.extend(
            (
                "",
                f"JJZERO_DATA_LOADER_WORKERS = {data_loader_settings.workers}",
                f"JJZERO_DATA_LOADER_PREFETCH = {data_loader_settings.prefetch_factor}",
                f"JJZERO_DATA_LOADER_PIN_MEMORY = {data_loader_settings.pin_memory!r}",
                "JJZERO_DATA_LOADER_PERSISTENT = "
                f"{data_loader_settings.persistent_workers!r}",
                f"JJZERO_DATA_LOADER_TIMEOUT = {data_loader_settings.timeout_seconds}",
                _OPTIMIZED_DATA_LOADER_BOOTSTRAP.rstrip(),
                "",
            )
        )
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


_DIAGNOSTIC_BOOTSTRAP = '''import atexit
import faulthandler
import json
import os
import threading
import traceback
from datetime import datetime, timezone


_jjzero_diag_stream = None


def _jjzero_diag_event(event, **data):
    if JJZERO_DIAGNOSTIC_DIRECTORY is None:
        return
    try:
        process_dir = JJZERO_DIAGNOSTIC_DIRECTORY / "processes"
        process_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "attempt_id": JJZERO_DIAGNOSTIC_ATTEMPT_ID,
            "event": str(event),
            "pid": os.getpid(),
            "ppid": os.getppid(),
            "process_name": multiprocessing.current_process().name,
            "module_name": __name__,
            **data,
        }
        with (process_dir / f"{os.getpid()}.jsonl").open(
            "a",
            encoding="utf-8",
        ) as output:
            output.write(json.dumps(payload, ensure_ascii=False, default=str, sort_keys=True))
            output.write("\\n")
    except BaseException:
        return


def _jjzero_diag_exception(event, exception_type, exception, exception_traceback):
    _jjzero_diag_event(
        event,
        exception_type=getattr(exception_type, "__name__", str(exception_type)),
        detail=str(exception),
        traceback="".join(
            traceback.format_exception(exception_type, exception, exception_traceback)
        ),
    )


if JJZERO_DIAGNOSTIC_DIRECTORY is not None:
    try:
        _jjzero_process_dir = JJZERO_DIAGNOSTIC_DIRECTORY / "processes"
        _jjzero_process_dir.mkdir(parents=True, exist_ok=True)
        _jjzero_diag_stream = (_jjzero_process_dir / f"{os.getpid()}.log").open(
            "a",
            encoding="utf-8",
            errors="replace",
            buffering=1,
        )
        if sys.stdout is None:
            sys.stdout = _jjzero_diag_stream
        if sys.stderr is None:
            sys.stderr = _jjzero_diag_stream
        faulthandler.enable(file=_jjzero_diag_stream, all_threads=True)
    except BaseException as _jjzero_stream_error:
        _jjzero_diag_stream = None

    _jjzero_original_excepthook = sys.excepthook

    def _jjzero_excepthook(exception_type, exception, exception_traceback):
        _jjzero_diag_exception(
            "uncaught_exception",
            exception_type,
            exception,
            exception_traceback,
        )
        _jjzero_original_excepthook(exception_type, exception, exception_traceback)

    sys.excepthook = _jjzero_excepthook
    if hasattr(threading, "excepthook"):
        _jjzero_original_threading_excepthook = threading.excepthook

        def _jjzero_threading_excepthook(args):
            _jjzero_diag_exception(
                "thread_exception",
                args.exc_type,
                args.exc_value,
                args.exc_traceback,
            )
            _jjzero_original_threading_excepthook(args)

        threading.excepthook = _jjzero_threading_excepthook

    def _jjzero_process_exit():
        _jjzero_diag_event("process_exit")
        if _jjzero_diag_stream is not None:
            try:
                _jjzero_diag_stream.flush()
            except BaseException:
                pass

    atexit.register(_jjzero_process_exit)

_jjzero_diag_event(
    "process_boot",
    executable=sys.executable,
    argv=list(sys.argv),
    stdout_available=sys.stdout is not None,
    stderr_available=sys.stderr is not None,
)
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


_jjzero_original_load_checkpoint = getattr(
    _jjzero_train_utils,
    "load_checkpoint",
    None,
)


def _jjzero_load_checkpoint(
    checkpoint_path,
    model,
    optimizer=None,
    load_opt=1,
):
    # Compact JJZero checkpoints intentionally omit the optimizer state. RVC's
    # broad resume exception otherwise hides that load error and starts again
    # from the pretrained model at epoch one.
    optimizer_restored = False
    try:
        result = _jjzero_original_load_checkpoint(
            checkpoint_path,
            model,
            optimizer,
            load_opt=load_opt,
        )
        optimizer_restored = optimizer is not None and bool(load_opt)
    except BaseException:
        if optimizer is None or not load_opt:
            raise
        try:
            result = _jjzero_original_load_checkpoint(
                checkpoint_path,
                model,
                optimizer,
                load_opt=0,
            )
        except BaseException as exc:
            print(
                "JJZERO_CHECKPOINT_LOAD_FAILED "
                f"file={Path(checkpoint_path).name} "
                f"type={type(exc).__name__} detail={exc}",
                flush=True,
            )
            raise
    iteration = result[3] if len(result) > 3 else 0
    optimizer_needs_schedule = optimizer is not None and (
        not optimizer_restored
        or any(
            "initial_lr" not in parameter_group
            for parameter_group in optimizer.param_groups
        )
    )
    if optimizer_needs_schedule:
        learning_rate = float(result[2])
        training = getattr(globals().get("hps"), "train", None)
        decay = float(getattr(training, "lr_decay", 1.0))
        completed_epochs = max(0, int(iteration) - 1)
        resumed_learning_rate = learning_rate * (decay ** completed_epochs)
        for parameter_group in optimizer.param_groups:
            parameter_group["initial_lr"] = learning_rate
            parameter_group["lr"] = resumed_learning_rate
        print(
            "JJZERO_CHECKPOINT_OPTIMIZER_REBUILT "
            f"file={Path(checkpoint_path).name} epoch={iteration} "
            f"lr={resumed_learning_rate:.12g}",
            flush=True,
        )
    print(
        "JJZERO_CHECKPOINT_LOADED "
        f"file={Path(checkpoint_path).name} epoch={iteration}",
        flush=True,
    )
    return result


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
if callable(_jjzero_original_load_checkpoint):
    _jjzero_train_utils.load_checkpoint = _jjzero_load_checkpoint
'''


_OPTIMIZED_DATA_LOADER_BOOTSTRAP = '''import torch.utils.data


_jjzero_original_data_loader = torch.utils.data.DataLoader
_jjzero_diag_event("torch_data_imported", torch_version=torch.__version__)


class _JjzeroWorkerInit:
    def __init__(self, original):
        self._original = original

    def __call__(self, worker_id):
        _jjzero_diag_event("data_worker_initialized", worker_id=int(worker_id))
        if self._original is not None:
            self._original(worker_id)


def _jjzero_worker_statuses(iterator):
    statuses = []
    for worker in getattr(iterator, "_workers", ()):
        try:
            alive = bool(worker.is_alive())
        except BaseException:
            alive = False
        statuses.append(
            {
                "pid": getattr(worker, "pid", None),
                "alive": alive,
                "exit_code": getattr(worker, "exitcode", None),
            }
        )
    return statuses


class _JjzeroOptimizedDataLoader(_jjzero_original_data_loader):
    def __init__(self, *args, **kwargs):
        workers = max(0, int(JJZERO_DATA_LOADER_WORKERS))
        kwargs["num_workers"] = workers
        kwargs["pin_memory"] = bool(JJZERO_DATA_LOADER_PIN_MEMORY and workers)
        if workers > 0:
            kwargs["prefetch_factor"] = max(1, int(JJZERO_DATA_LOADER_PREFETCH))
            kwargs["persistent_workers"] = bool(JJZERO_DATA_LOADER_PERSISTENT)
            kwargs["timeout"] = max(1, int(JJZERO_DATA_LOADER_TIMEOUT))
            kwargs["worker_init_fn"] = _JjzeroWorkerInit(
                kwargs.get("worker_init_fn")
            )
        else:
            kwargs.pop("prefetch_factor", None)
            kwargs["persistent_workers"] = False
            kwargs["timeout"] = 0
        super().__init__(*args, **kwargs)
        self._jjzero_configuration_reported = False
        _jjzero_diag_event(
            "data_loader_created",
            workers=self.num_workers,
            pin_memory=bool(self.pin_memory),
            persistent_workers=bool(self.persistent_workers),
            timeout=int(self.timeout),
        )

    def __iter__(self):
        if not self._jjzero_configuration_reported:
            print(
                "JJZERO_DATA_LOADER_CONFIG "
                f"workers={self.num_workers} "
                f"pin_memory={int(bool(self.pin_memory))} "
                f"persistent={int(bool(self.persistent_workers))} "
                f"timeout={self.timeout}",
                flush=True,
            )
            self._jjzero_configuration_reported = True
        print("JJZERO_TRAINING_DATA_LOADER_START", flush=True)
        _jjzero_diag_event("data_loader_iterator_requested")
        iterator = None
        try:
            iterator = super().__iter__()
            worker_pids = [
                int(worker.pid)
                for worker in getattr(iterator, "_workers", ())
                if getattr(worker, "pid", None) is not None
            ]
            _jjzero_diag_event(
                "data_loader_iterator_created",
                worker_pids=worker_pids,
                workers=_jjzero_worker_statuses(iterator),
            )
            print(
                "JJZERO_DATA_LOADER_WORKERS_STARTED "
                f"count={len(worker_pids)} pids={','.join(map(str, worker_pids))}",
                flush=True,
            )
            for index, batch in enumerate(iterator):
                if index == 0:
                    _jjzero_diag_event(
                        "first_batch_ready",
                        worker_pids=worker_pids,
                    )
                    print("JJZERO_TRAINING_FIRST_BATCH_READY", flush=True)
                yield batch
        except BaseException as exc:
            _jjzero_diag_event(
                "data_loader_exception",
                exception_type=type(exc).__name__,
                detail=str(exc),
                traceback=traceback.format_exc(),
                workers=_jjzero_worker_statuses(iterator),
            )
            print(
                "JJZERO_DATA_LOADER_ERROR "
                f"type={type(exc).__name__} detail={exc}",
                flush=True,
            )
            raise


torch.utils.data.DataLoader = _JjzeroOptimizedDataLoader
'''


_ROCM_SINGLE_PROCESS_TRAINING_BOOTSTRAP = '''import torch
import torch.distributed
import torch.multiprocessing
import torch.nn.parallel


if __name__ == "__main__" and (
    getattr(torch.version, "hip", None) or torch.cuda.device_count() <= 1
):
    print("JJZERO_SINGLE_DEVICE_TRAINING", flush=True)

    _jjzero_original_training_process = torch.multiprocessing.Process

    class _JjzeroSingleProcessDistributedDataParallel(torch.nn.Module):
        def __init__(self, module, *args, **kwargs):
            super().__init__()
            self.module = module

        def forward(self, *args, **kwargs):
            return self.module(*args, **kwargs)


    def _jjzero_skip_single_process_group(*args, **kwargs):
        return None


    class _JjzeroInlineTrainingProcess:
        def __init__(self, group=None, target=None, name=None, args=(), kwargs=None, daemon=None):
            self._target = target
            self._args = tuple(args)
            self._kwargs = dict(kwargs or {})
            self.exitcode = None

        def start(self):
            print("JJZERO_SINGLE_DEVICE_WORKER_START", flush=True)
            try:
                if self._target is not None:
                    self._target(*self._args, **self._kwargs)
            except BaseException:
                self.exitcode = 1
                raise
            else:
                self.exitcode = 0

        def join(self, timeout=None):
            return None

        def is_alive(self):
            return False


    def _jjzero_training_process(*args, **kwargs):
        target = kwargs.get("target")
        if target is None and len(args) > 1:
            target = args[1]
        if getattr(target, "__name__", "") == "run":
            return _JjzeroInlineTrainingProcess(*args, **kwargs)
        return _jjzero_original_training_process(*args, **kwargs)


    torch.distributed.init_process_group = _jjzero_skip_single_process_group
    # Only the RVC rank process runs inline. DataLoader must keep the real
    # multiprocessing Process or its first worker blocks the training thread.
    torch.multiprocessing.Process = _jjzero_training_process
    torch.nn.parallel.DistributedDataParallel = (
        _JjzeroSingleProcessDistributedDataParallel
    )
'''
