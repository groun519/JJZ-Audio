from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from pathlib import Path

from jang_app.services.app_logging import get_logger
from jang_app.services.managed_files import (
    file_sha256,
    link_or_copy_file,
    write_json_atomic,
    write_text_atomic,
)
from jang_app.services.rvc_model_package import RvcModelPackageLayout
from jang_app.services.rvc_training_artifacts import (
    publish_training_outputs,
    remove_training_staging,
)
from jang_app.services.rvc_training_extract import (
    RvcTrainingExtractResult,
    load_rvc_extract_result,
)
from jang_app.services.rvc_training_preprocess import (
    RvcTrainingPreprocessResult,
    load_rvc_preprocess_result,
)
from jang_app.services.rvc_training_runtime import inspect_rvc_training_runtime
from jang_app.services.rvc_training_state import RvcTrainingPhase, RvcTrainingStateStore


FILELIST_NAME = "filelist.txt"
FILELIST_MANIFEST_NAME = "jjzero_filelist.json"
MUTE_ENTRY_COUNT = 2
_MUTE_ASSETS = (
    Path("logs/mute/0_gt_wavs/mute40k.wav"),
    Path("logs/mute/0_gt_wavs/mute40k.spec.pt"),
    Path("logs/mute/2a_f0/mute.wav.npy"),
    Path("logs/mute/2b-f0nsf/mute.wav.npy"),
    Path("logs/mute/3_feature768/mute.npy"),
)
_PUBLISHED_OUTPUTS = (FILELIST_NAME, FILELIST_MANIFEST_NAME)


class RvcTrainingFilelistError(RuntimeError):
    """Raised when an RVC training file list cannot be built or verified."""


@dataclass(frozen=True)
class RvcTrainingFilelistResult:
    path: Path
    dataset_fingerprint: str
    real_entry_count: int
    mute_entry_count: int

    @property
    def entry_count(self) -> int:
        return self.real_entry_count + self.mute_entry_count


def build_rvc_training_filelist(
    model_id: str,
    layout: RvcModelPackageLayout,
    runtime_root: Path,
) -> RvcTrainingFilelistResult:
    runtime = runtime_root.expanduser().resolve()
    inspection = inspect_rvc_training_runtime(runtime)
    if not inspection.assets_ready:
        missing = ", ".join(path.as_posix() for path in inspection.missing_paths)
        raise RvcTrainingFilelistError(f"RVC training runtime is incomplete: {missing}")

    extract = load_rvc_extract_result(model_id, layout)
    preprocess = load_rvc_preprocess_result(model_id, layout)
    state_store = RvcTrainingStateStore(model_id, layout)
    staging = _staging_dir(layout)
    logger = get_logger()
    try:
        mute_root = _prepare_packaged_mute_assets(runtime, layout)
        lines = _filelist_lines(preprocess, extract, mute_root)
        staging.mkdir(parents=True, exist_ok=False)
        filelist_path = staging / FILELIST_NAME
        write_text_atomic(filelist_path, "\n".join(lines) + "\n")
        write_json_atomic(
            staging / FILELIST_MANIFEST_NAME,
            {
                "version": 1,
                "dataset_fingerprint": preprocess.snapshot.fingerprint,
                "real_entry_count": len(lines) - MUTE_ENTRY_COUNT,
                "mute_entry_count": MUTE_ENTRY_COUNT,
                "filelist_sha256": file_sha256(filelist_path),
            },
        )
        publish_training_outputs(
            staging,
            layout.experiment_dir,
            _PUBLISHED_OUTPUTS,
            backup_label="filelist",
        )
        result = load_rvc_training_filelist(model_id, layout)
        state_store.update_phase(RvcTrainingPhase.FILELIST_READY)
        logger.info(
            "RVC training file list ready: model=%s entries=%s",
            model_id,
            result.entry_count,
        )
        return result
    except Exception as exc:
        logger.error("RVC training file list failed: model=%s error=%s", model_id, exc)
        state_store.update_phase(RvcTrainingPhase.FAILED, last_error=str(exc))
        if isinstance(exc, RvcTrainingFilelistError):
            raise
        raise RvcTrainingFilelistError(str(exc)) from exc
    finally:
        remove_training_staging(staging, layout.model_dir)


def load_rvc_training_filelist(
    model_id: str,
    layout: RvcModelPackageLayout,
) -> RvcTrainingFilelistResult:
    extract = load_rvc_extract_result(model_id, layout)
    preprocess = load_rvc_preprocess_result(model_id, layout)
    path = layout.experiment_dir / FILELIST_NAME
    manifest_path = layout.experiment_dir / FILELIST_MANIFEST_NAME
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RvcTrainingFilelistError("RVC training file list cannot be read.") from exc

    if not isinstance(data, dict):
        raise RvcTrainingFilelistError("RVC training file list manifest is invalid.")
    _verify_packaged_mute_assets(layout)
    expected = _filelist_lines(preprocess, extract, layout.root / "logs" / "mute")
    real_entry_count = len(expected) - MUTE_ENTRY_COUNT
    if lines != list(expected):
        raise RvcTrainingFilelistError("RVC training file list does not match extracted features.")
    if (
        data.get("version") != 1
        or data.get("dataset_fingerprint") != preprocess.snapshot.fingerprint
        or data.get("real_entry_count") != real_entry_count
        or data.get("mute_entry_count") != MUTE_ENTRY_COUNT
        or data.get("filelist_sha256") != file_sha256(path)
    ):
        raise RvcTrainingFilelistError("RVC training file list manifest is invalid.")
    return RvcTrainingFilelistResult(
        path=path,
        dataset_fingerprint=preprocess.snapshot.fingerprint,
        real_entry_count=real_entry_count,
        mute_entry_count=MUTE_ENTRY_COUNT,
    )


def _prepare_packaged_mute_assets(
    runtime: Path,
    layout: RvcModelPackageLayout,
) -> Path:
    for relative_path in _MUTE_ASSETS:
        source = runtime / relative_path
        if not source.is_file():
            raise RvcTrainingFilelistError(f"RVC mute asset is missing: {source}")
        link_or_copy_file(source, layout.root / relative_path)
    return layout.root / "logs" / "mute"


def _verify_packaged_mute_assets(layout: RvcModelPackageLayout) -> None:
    for relative_path in _MUTE_ASSETS:
        path = layout.root / relative_path
        if not path.is_file():
            raise RvcTrainingFilelistError(f"Packaged RVC mute asset is missing: {path}")


def _filelist_lines(
    preprocess: RvcTrainingPreprocessResult,
    extract: RvcTrainingExtractResult,
    mute_root: Path,
) -> tuple[str, ...]:
    gt_by_stem = {path.stem: path for path in preprocess.gt_wavs}
    feature_by_stem = {path.stem: path for path in extract.feature_files}
    f0_by_stem = {_f0_stem(path): path for path in extract.f0_files}
    f0_nsf_by_stem = {_f0_stem(path): path for path in extract.f0_nsf_files}
    stems = set(gt_by_stem)
    if not stems or not (
        stems == set(feature_by_stem) == set(f0_by_stem) == set(f0_nsf_by_stem)
    ):
        raise RvcTrainingFilelistError("RVC training outputs do not have matching sample names.")

    lines = [
        _entry(
            gt_by_stem[stem],
            feature_by_stem[stem],
            f0_by_stem[stem],
            f0_nsf_by_stem[stem],
        )
        for stem in sorted(stems, key=str.casefold)
    ]
    mute_line = _entry(
        mute_root / "0_gt_wavs" / "mute40k.wav",
        mute_root / "3_feature768" / "mute.npy",
        mute_root / "2a_f0" / "mute.wav.npy",
        mute_root / "2b-f0nsf" / "mute.wav.npy",
    )
    for path in _entry_paths(mute_line):
        if not path.is_file():
            raise RvcTrainingFilelistError(f"Packaged RVC mute asset is missing: {path}")
    lines.extend(mute_line for _ in range(MUTE_ENTRY_COUNT))
    return tuple(lines)


def _entry(wav: Path, feature: Path, f0: Path, f0_nsf: Path) -> str:
    paths = (wav, feature, f0, f0_nsf)
    for path in paths:
        if not path.is_file():
            raise RvcTrainingFilelistError(f"RVC training input is missing: {path}")
    return "|".join((*(_filelist_path(path) for path in paths), "0"))


def _entry_paths(line: str) -> tuple[Path, ...]:
    fields = line.split("|")
    if len(fields) != 5 or fields[-1] != "0":
        raise RvcTrainingFilelistError("RVC training file list entry is invalid.")
    return tuple(Path(value.replace("\\\\", "\\")) for value in fields[:4])


def _filelist_path(path: Path) -> str:
    return str(path.expanduser().resolve()).replace("\\", "\\\\")


def _f0_stem(path: Path) -> str:
    return path.name.removesuffix(".wav.npy")


def _staging_dir(layout: RvcModelPackageLayout) -> Path:
    return layout.model_dir / "training" / "filelist" / f".building-{uuid.uuid4().hex}"
