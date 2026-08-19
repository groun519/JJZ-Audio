from __future__ import annotations

import shutil
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from jang_app.config import TOOL_WORKSPACE_DIR, VOCAL_SPLIT_MODEL_DIR
from jang_app.pipeline.roformer_engine import (
    build_roformer_environment,
    build_roformer_progress_callback,
    require_roformer_tools,
    roformer_python_executable,
)
from jang_app.services.app_logging import get_logger
from jang_app.services.audio_metadata import read_audio_metadata
from jang_app.services.command import run_command
from jang_app.services.tool_workspace import ToolWorkspace
from jang_app.services.vocal_split import (
    VocalReferenceRegion,
    VocalSplitRun,
    VocalSplitStem,
)
from jang_app.services.vocal_split_assets import (
    VOCAL_SPLIT_MODEL,
    VocalSplitAssetError,
    prepare_vocal_split_model,
)
from jang_app.services.vocal_split_store import VocalSplitStore


ProgressCallback = Callable[[int], None]
VOCAL_SPLIT_METHOD_ID = "two-vocal-v1"
VOCAL_SPLIT_METHOD_LABEL = "Two-vocal split"
_CLI_ENTRYPOINT = "from audio_separator.utils.cli import main; main()"


class VocalSplitError(RuntimeError):
    pass


@dataclass(frozen=True)
class SingerSplitCapability:
    available: bool
    detail: str
    minimum_reference_ms: int = 1_000
    maximum_reference_ms: int = 60_000


def singer_split_capability() -> SingerSplitCapability:
    # The bundled karaoke model separates foreground/background energy; it does
    # not identify a singer from a solo reference. Keep the UI/backend contract
    # honest until a validated singer-informed model is connected here.
    return SingerSplitCapability(
        False,
        "Singer separation model is not connected yet.",
    )


class SingerSplitBackend(Protocol):
    model_name: str

    def separate(
        self,
        input_path: Path,
        reference_regions: tuple[VocalReferenceRegion, ...],
        output_dir: Path,
        progress_callback: ProgressCallback | None,
    ) -> tuple[Path, Path]: ...


def split_selected_vocal(
    group: VocalSplitRun,
    stem: VocalSplitStem,
    reference_regions: tuple[VocalReferenceRegion, ...],
    progress_callback: ProgressCallback | None = None,
    *,
    store: VocalSplitStore | None = None,
    backend: SingerSplitBackend | None = None,
) -> VocalSplitRun:
    if backend is None:
        raise VocalSplitError(singer_split_capability().detail)
    if group.stem(stem.stem_id) is None:
        raise VocalSplitError("The selected vocal is no longer part of this group")
    if not reference_regions or any(
        region.start_ms < 0 or region.end_ms <= region.start_ms
        for region in reference_regions
    ):
        raise VocalSplitError("At least one valid solo reference range is required")

    split_store = store or VocalSplitStore()
    operation_dir = split_store.create_operation_dir(group)
    logger = get_logger()
    logger.info(
        "Starting singer-reference split: group=%s stem=%s references=%s model=%s",
        group.run_id,
        stem.stem_id,
        tuple((region.start_ms, region.end_ms) for region in reference_regions),
        backend.model_name,
    )
    try:
        if progress_callback is not None:
            progress_callback(2)
        extracted, remaining = backend.separate(
            stem.path,
            reference_regions,
            operation_dir,
            progress_callback,
        )
        _validate_singer_split_outputs(stem.path, extracted, remaining)
        updated = split_store.complete_split(
            group,
            stem.stem_id,
            operation_dir,
            extracted,
            remaining,
            reference_regions=reference_regions,
            model=backend.model_name,
        )
    except Exception:
        shutil.rmtree(operation_dir, ignore_errors=True)
        raise
    if progress_callback is not None:
        progress_callback(100)
    logger.info(
        "Singer-reference split complete: group=%s stem=%s outputs=%s",
        group.run_id,
        stem.stem_id,
        tuple(node.stem_id for node in updated.stems),
    )
    return updated


def _validate_singer_split_outputs(
    source_path: Path,
    extracted_path: Path,
    remaining_path: Path,
) -> None:
    source = read_audio_metadata(source_path)
    outputs = tuple(read_audio_metadata(path) for path in (extracted_path, remaining_path))
    if any(metadata.duration_ms <= 0 for metadata in outputs):
        raise VocalSplitError("Singer separation produced an empty vocal")
    if any(abs(metadata.duration_ms - source.duration_ms) > 500 for metadata in outputs):
        raise VocalSplitError("Singer separation output length does not match its input")
    if any(metadata.sample_rate <= 0 or metadata.channels <= 0 for metadata in outputs):
        raise VocalSplitError("Singer separation produced an invalid audio format")


def split_vocal(
    input_path: Path,
    parent_job_dir: Path,
    progress_callback: ProgressCallback | None = None,
    *,
    store: VocalSplitStore | None = None,
) -> VocalSplitRun:
    source = input_path.expanduser().resolve()
    parent = parent_job_dir.expanduser().resolve()
    if not source.is_file():
        raise VocalSplitError(f"Vocal input does not exist: {source}")
    try:
        source.relative_to(parent)
    except ValueError as exc:
        raise VocalSplitError("Vocal input is outside the selected separation result") from exc

    require_roformer_tools()
    split_store = store or VocalSplitStore()
    run_dir = split_store.create_run_dir(parent)
    logger = get_logger()
    logger.info(
        "Starting two-vocal split: input=%s parent=%s model=%s",
        source,
        parent,
        VOCAL_SPLIT_MODEL,
    )
    try:
        if progress_callback is not None:
            progress_callback(2)
        try:
            prepare_vocal_split_model(
                progress=lambda value: progress_callback(2 + round(value * 0.30))
                if progress_callback is not None
                else None,
            )
        except VocalSplitAssetError as exc:
            raise VocalSplitError(str(exc)) from exc

        with ToolWorkspace(TOOL_WORKSPACE_DIR, "vsplit") as workspace:
            staged_source = workspace.stage_input(source)
            completed = run_command(
                _build_vocal_split_command(staged_source, workspace.output_dir),
                env=build_roformer_environment(),
                output_callback=build_roformer_progress_callback(
                    progress_callback,
                    minimum_percent=33,
                    maximum_percent=92,
                ),
            )
            if completed.returncode != 0:
                logger.error(
                    "Two-vocal split failed with exit code %s\n%s",
                    completed.returncode,
                    completed.output,
                )
                raise VocalSplitError(
                    f"Two-vocal split failed with exit code {completed.returncode}. "
                    "See logs for details."
                )
            vocal_one_source, vocal_two_source = _find_vocal_split_outputs(
                workspace.output_dir
            )
            vocal_one_path = workspace.publish_file(
                vocal_one_source,
                run_dir / "vocal-1.wav",
            )
            vocal_two_path = workspace.publish_file(
                vocal_two_source,
                run_dir / "vocal-2.wav",
            )

        run = split_store.register(
            parent,
            run_dir,
            source,
            method_id=VOCAL_SPLIT_METHOD_ID,
            method_label=VOCAL_SPLIT_METHOD_LABEL,
            model=VOCAL_SPLIT_MODEL,
            stems=(
                VocalSplitStem("vocal-1", "vocal", "Vocal 1", vocal_one_path),
                VocalSplitStem("vocal-2", "vocal", "Vocal 2", vocal_two_path),
            ),
        )
    except Exception:
        if run_dir.is_dir():
            shutil.rmtree(run_dir, ignore_errors=True)
        raise
    if progress_callback is not None:
        progress_callback(100)
    logger.info("Two-vocal split complete: run=%s", run.run_id)
    return run


def _build_vocal_split_command(source: Path, output_dir: Path) -> list[str]:
    return [
        str(roformer_python_executable()),
        "-c",
        _CLI_ENTRYPOINT,
        str(source),
        "--model_filename",
        VOCAL_SPLIT_MODEL,
        "--model_file_dir",
        str(VOCAL_SPLIT_MODEL_DIR),
        "--output_dir",
        str(output_dir),
        "--output_format",
        "WAV",
        "--sample_rate",
        "44100",
        "--vr_batch_size",
        "1",
    ]


def _find_vocal_split_outputs(output_dir: Path) -> tuple[Path, Path]:
    files = tuple(path for path in output_dir.glob("*.wav") if path.is_file())
    vocal_one = _single_output(files, "vocals")
    vocal_two = _single_output(files, "instrumental")
    if vocal_one is None or vocal_two is None:
        names = ", ".join(path.name for path in files) or "none"
        raise VocalSplitError(
            "The vocal split model did not produce both vocal outputs. "
            f"Created files: {names}"
        )
    return vocal_one, vocal_two


def _single_output(files: tuple[Path, ...], stem_name: str) -> Path | None:
    token = f"({stem_name})".casefold()
    return next((path for path in files if token in path.name.casefold()), None)
