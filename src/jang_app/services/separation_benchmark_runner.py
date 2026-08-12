from __future__ import annotations

import json
import platform
import sys
import time
import traceback
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path

from jang_app.pipeline.separate import separate_audio
from jang_app.pipeline.separation_engine import ProgressCallback, SeparationResult
from jang_app.services.managed_files import file_sha256, write_json_atomic
from jang_app.services.separation_recipe import SeparationRecipe, separation_recipe


BENCHMARK_RESULT_SCHEMA = 1
BENCHMARK_PROGRESS_SCHEMA = 1

RunProgressCallback = Callable[[str, str, int, int, int], None]
Separator = Callable[
    [Path, Path, SeparationRecipe, ProgressCallback | None],
    SeparationResult,
]


class SeparationBenchmarkRunError(RuntimeError):
    """Raised when a prepared benchmark cannot be executed safely."""


def run_prepared_benchmark(
    manifest_path: Path,
    *,
    candidate_ids: Sequence[str] = (),
    clip_ids: Sequence[str] = (),
    resume: bool = True,
    continue_on_error: bool = False,
    progress: RunProgressCallback | None = None,
    separator: Separator | None = None,
) -> Path:
    manifest_file = manifest_path.expanduser().resolve()
    manifest = _load_manifest(manifest_file)
    root = _required_path(manifest.get("root"), "root")
    clips = _selected_items(
        _mapping_list(manifest.get("clips"), "clips"),
        "clip_id",
        clip_ids,
    )
    candidates = _selected_items(
        _mapping_list(manifest.get("candidates"), "candidates"),
        "candidate_id",
        candidate_ids,
    )
    definition_sha256 = _required_text(
        manifest.get("definition_sha256"),
        "definition_sha256",
    )
    execute = separator or _separate
    total = len(clips) * len(candidates)
    completed = 0
    failed = 0
    skipped = 0
    started_at = datetime.now(UTC).isoformat()

    for candidate in candidates:
        candidate_id = _required_text(candidate.get("candidate_id"), "candidate_id")
        recipe_id = _required_text(candidate.get("recipe_id"), "recipe_id")
        recipe = separation_recipe(recipe_id)
        if recipe.recipe_id != recipe_id:
            raise SeparationBenchmarkRunError(f"Unknown separation recipe: {recipe_id}")
        for clip in clips:
            clip_id = _required_text(clip.get("clip_id"), "clip_id")
            source = _required_path(clip.get("path"), f"clip {clip_id} path")
            source_sha256 = _required_text(
                clip.get("sha256"),
                f"clip {clip_id} sha256",
            )
            if not source.is_file() or file_sha256(source) != source_sha256:
                raise SeparationBenchmarkRunError(
                    f"Prepared benchmark clip changed or is missing: {source}"
                )
            output_dir = root / "results" / candidate_id / clip_id
            result_manifest = output_dir / "benchmark-result.json"
            if resume and _completed_result_matches(
                result_manifest,
                definition_sha256=definition_sha256,
                source_sha256=source_sha256,
                recipe_id=recipe_id,
            ):
                skipped += 1
                _report(progress, candidate_id, clip_id, 100, completed, total)
                completed += 1
                _write_progress(
                    root,
                    manifest_file,
                    started_at,
                    completed,
                    failed,
                    skipped,
                    total,
                    candidate_id,
                    clip_id,
                    "skipped",
                )
                continue

            output_dir.mkdir(parents=True, exist_ok=True)
            item_started_at = datetime.now(UTC).isoformat()
            start = time.perf_counter()

            def report_item(value: int) -> None:
                _report(progress, candidate_id, clip_id, value, completed, total)

            try:
                result = execute(source, output_dir, recipe, report_item)
                duration_seconds = time.perf_counter() - start
                result_data = _completed_result(
                    manifest_file,
                    definition_sha256,
                    candidate,
                    clip,
                    result,
                    item_started_at,
                    duration_seconds,
                )
                write_json_atomic(result_manifest, result_data)
                status = "completed"
            except Exception as exc:
                failed += 1
                status = "failed"
                write_json_atomic(
                    result_manifest,
                    _failed_result(
                        manifest_file,
                        definition_sha256,
                        candidate,
                        clip,
                        item_started_at,
                        time.perf_counter() - start,
                        exc,
                    ),
                )
                _write_progress(
                    root,
                    manifest_file,
                    started_at,
                    completed,
                    failed,
                    skipped,
                    total,
                    candidate_id,
                    clip_id,
                    status,
                )
                if not continue_on_error:
                    raise SeparationBenchmarkRunError(
                        f"Benchmark failed for {candidate_id}/{clip_id}: {exc}"
                    ) from exc
                continue

            _report(progress, candidate_id, clip_id, 100, completed, total)
            completed += 1
            _write_progress(
                root,
                manifest_file,
                started_at,
                completed,
                failed,
                skipped,
                total,
                candidate_id,
                clip_id,
                status,
            )

    return _write_progress(
        root,
        manifest_file,
        started_at,
        completed,
        failed,
        skipped,
        total,
        "",
        "",
        "completed" if failed == 0 else "completed_with_errors",
    )


def _separate(
    source: Path,
    output_dir: Path,
    recipe: SeparationRecipe,
    progress: ProgressCallback | None,
) -> SeparationResult:
    return separate_audio(
        source,
        output_dir,
        recipe=recipe,
        progress_callback=progress,
    )


def _completed_result(
    benchmark_manifest: Path,
    definition_sha256: str,
    candidate: Mapping[str, object],
    clip: Mapping[str, object],
    result: SeparationResult,
    started_at: str,
    duration_seconds: float,
) -> dict[str, object]:
    vocals = result.vocals_path.expanduser().resolve()
    accompaniment = result.accompaniment_path.expanduser().resolve()
    if not vocals.is_file() or not accompaniment.is_file():
        raise SeparationBenchmarkRunError("Separation did not produce both output stems.")
    return {
        "schema": BENCHMARK_RESULT_SCHEMA,
        "status": "completed",
        "benchmark_manifest": str(benchmark_manifest),
        "definition_sha256": definition_sha256,
        "candidate_id": candidate["candidate_id"],
        "candidate_label": candidate["label"],
        "recipe_id": candidate["recipe_id"],
        "clip_id": clip["clip_id"],
        "clip_title": clip["title"],
        "source_path": clip["path"],
        "source_sha256": clip["sha256"],
        "started_at": started_at,
        "finished_at": datetime.now(UTC).isoformat(),
        "duration_seconds": round(duration_seconds, 3),
        "outputs": {
            "vocals": _file_record(vocals),
            "instrumental": _file_record(accompaniment),
        },
    }


def _failed_result(
    benchmark_manifest: Path,
    definition_sha256: str,
    candidate: Mapping[str, object],
    clip: Mapping[str, object],
    started_at: str,
    duration_seconds: float,
    error: Exception,
) -> dict[str, object]:
    return {
        "schema": BENCHMARK_RESULT_SCHEMA,
        "status": "failed",
        "benchmark_manifest": str(benchmark_manifest),
        "definition_sha256": definition_sha256,
        "candidate_id": candidate["candidate_id"],
        "candidate_label": candidate["label"],
        "recipe_id": candidate["recipe_id"],
        "clip_id": clip["clip_id"],
        "clip_title": clip["title"],
        "source_path": clip["path"],
        "source_sha256": clip["sha256"],
        "started_at": started_at,
        "finished_at": datetime.now(UTC).isoformat(),
        "duration_seconds": round(duration_seconds, 3),
        "error_type": type(error).__name__,
        "error": str(error),
        "traceback": "".join(
            traceback.format_exception(type(error), error, error.__traceback__)
        ),
    }


def _completed_result_matches(
    path: Path,
    *,
    definition_sha256: str,
    source_sha256: str,
    recipe_id: str,
) -> bool:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        outputs = data["outputs"]
        if (
            data.get("schema") != BENCHMARK_RESULT_SCHEMA
            or data.get("status") != "completed"
            or data.get("definition_sha256") != definition_sha256
            or data.get("source_sha256") != source_sha256
            or data.get("recipe_id") != recipe_id
            or not isinstance(outputs, Mapping)
        ):
            return False
        for name in ("vocals", "instrumental"):
            record = outputs.get(name)
            if not isinstance(record, Mapping):
                return False
            output = Path(str(record.get("path", ""))).expanduser().resolve()
            if not output.is_file() or file_sha256(output) != record.get("sha256"):
                return False
        return True
    except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError):
        return False


def _file_record(path: Path) -> dict[str, object]:
    return {
        "path": str(path),
        "sha256": file_sha256(path),
        "size": path.stat().st_size,
    }


def _write_progress(
    root: Path,
    manifest: Path,
    started_at: str,
    completed: int,
    failed: int,
    skipped: int,
    total: int,
    candidate_id: str,
    clip_id: str,
    status: str,
) -> Path:
    target = root / "benchmark-progress.json"
    write_json_atomic(
        target,
        {
            "schema": BENCHMARK_PROGRESS_SCHEMA,
            "status": status,
            "benchmark_manifest": str(manifest),
            "started_at": started_at,
            "updated_at": datetime.now(UTC).isoformat(),
            "completed": completed,
            "failed": failed,
            "skipped": skipped,
            "total": total,
            "current_candidate_id": candidate_id,
            "current_clip_id": clip_id,
            "system": {
                "platform": platform.platform(),
                "python": sys.version.split()[0],
            },
        },
    )
    return target


def _load_manifest(path: Path) -> Mapping[str, object]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SeparationBenchmarkRunError(f"Could not read benchmark manifest: {path}") from exc
    if not isinstance(data, Mapping) or data.get("schema") != 1:
        raise SeparationBenchmarkRunError("Unsupported prepared benchmark manifest.")
    return data


def _selected_items(
    items: tuple[Mapping[str, object], ...],
    key: str,
    selected: Sequence[str],
) -> tuple[Mapping[str, object], ...]:
    if not selected:
        return items
    wanted = tuple(value.strip() for value in selected if value.strip())
    available = {_required_text(item.get(key), key): item for item in items}
    missing = tuple(value for value in wanted if value not in available)
    if missing:
        raise SeparationBenchmarkRunError(
            f"Unknown {key} values: {', '.join(missing)}"
        )
    return tuple(available[value] for value in wanted)


def _mapping_list(value: object, label: str) -> tuple[Mapping[str, object], ...]:
    if not isinstance(value, list) or not value:
        raise SeparationBenchmarkRunError(f"Benchmark {label} must be a non-empty list.")
    if not all(isinstance(item, Mapping) for item in value):
        raise SeparationBenchmarkRunError(f"Benchmark {label} contains invalid items.")
    return tuple(value)  # type: ignore[return-value]


def _required_text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SeparationBenchmarkRunError(f"Benchmark {label} is required.")
    return value.strip()


def _required_path(value: object, label: str) -> Path:
    return Path(_required_text(value, label)).expanduser().resolve()


def _report(
    progress: RunProgressCallback | None,
    candidate_id: str,
    clip_id: str,
    value: int,
    completed: int,
    total: int,
) -> None:
    if progress is not None:
        progress(
            candidate_id,
            clip_id,
            max(0, min(100, int(value))),
            completed,
            total,
        )
