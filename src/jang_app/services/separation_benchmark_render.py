from __future__ import annotations

import json
import time
import traceback
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path

from jang_app.pipeline.rvc_convert import convert_vocal_with_rvc
from jang_app.services.audio_export import AudioMixSource, export_mix
from jang_app.services.managed_files import file_sha256, write_json_atomic
from jang_app.services.settings import RvcSettings


BENCHMARK_RENDER_SCHEMA = 1
BENCHMARK_MIX_POLICY = {
    "converted_vocals_volume": 1.0,
    "instrumental_volume": 0.35,
}
RenderProgressCallback = Callable[[str, str, str, int, int], None]
Converter = Callable[[Path, Path, RvcSettings], Path]
Mixer = Callable[[Path, Path, Path], Path]


class SeparationBenchmarkRenderError(RuntimeError):
    """Raised when RVC and mix review renders cannot be produced safely."""


def render_prepared_benchmark(
    manifest_path: Path,
    *,
    candidate_ids: Sequence[str] = (),
    clip_ids: Sequence[str] = (),
    resume: bool = True,
    continue_on_error: bool = False,
    progress: RenderProgressCallback | None = None,
    converter: Converter | None = None,
    mixer: Mixer | None = None,
) -> Path:
    manifest_file = manifest_path.expanduser().resolve()
    manifest = _load_json(manifest_file, "benchmark manifest")
    root = _required_path(manifest.get("root"), "root")
    definition_sha256 = _required_text(
        manifest.get("definition_sha256"), "definition_sha256"
    )
    rvc_data = _required_mapping(manifest.get("rvc"), "rvc")
    rvc_settings = _rvc_settings(rvc_data)
    clips = _selected_items(
        _mapping_list(manifest.get("clips"), "clips"), "clip_id", clip_ids
    )
    candidates = _selected_items(
        _mapping_list(manifest.get("candidates"), "candidates"),
        "candidate_id",
        candidate_ids,
    )
    execute_conversion = converter or _convert
    execute_mix = mixer or _mix
    total = len(clips) * len(candidates)
    completed = 0
    failed = 0
    skipped = 0
    started_at = datetime.now(UTC).isoformat()

    for candidate in candidates:
        candidate_id = _required_text(candidate.get("candidate_id"), "candidate_id")
        for clip in clips:
            clip_id = _required_text(clip.get("clip_id"), "clip_id")
            result_file = root / "results" / candidate_id / clip_id / "benchmark-result.json"
            result = _load_separation_result(result_file, definition_sha256)
            outputs = _required_mapping(result.get("outputs"), "separation outputs")
            vocals = _verified_file(outputs, "vocals")
            instrumental = _verified_file(outputs, "instrumental")
            output_dir = result_file.parent / "downstream"
            render_manifest = output_dir / "benchmark-render.json"
            if resume and _completed_render_matches(
                render_manifest,
                definition_sha256=definition_sha256,
                vocals=vocals,
                instrumental=instrumental,
                rvc_data=rvc_data,
            ):
                skipped += 1
                completed += 1
                _report(progress, candidate_id, clip_id, "skipped", completed, total)
                continue

            item_started_at = datetime.now(UTC).isoformat()
            start = time.perf_counter()
            try:
                output_dir.mkdir(parents=True, exist_ok=True)
                converted = _reusable_converted_output(
                    render_manifest,
                    definition_sha256=definition_sha256,
                    vocals=vocals,
                    instrumental=instrumental,
                    rvc_data=rvc_data,
                )
                if converted is None:
                    _report(progress, candidate_id, clip_id, "converting", completed, total)
                    converted = execute_conversion(vocals, output_dir, rvc_settings)
                else:
                    _report(
                        progress,
                        candidate_id,
                        clip_id,
                        "reusing conversion",
                        completed,
                        total,
                    )
                if not converted.is_file():
                    raise SeparationBenchmarkRenderError(
                        f"RVC conversion output is missing: {converted}"
                    )
                final_mix = output_dir / "final_mix.wav"
                _report(progress, candidate_id, clip_id, "mixing", completed, total)
                execute_mix(converted, instrumental, final_mix)
                if not final_mix.is_file():
                    raise SeparationBenchmarkRenderError(
                        f"Final mix output is missing: {final_mix}"
                    )
                write_json_atomic(
                    render_manifest,
                    {
                        "schema": BENCHMARK_RENDER_SCHEMA,
                        "status": "completed",
                        "benchmark_manifest": str(manifest_file),
                        "definition_sha256": definition_sha256,
                        "candidate_id": candidate_id,
                        "clip_id": clip_id,
                        "started_at": item_started_at,
                        "finished_at": datetime.now(UTC).isoformat(),
                        "duration_seconds": round(time.perf_counter() - start, 3),
                        "inputs": {
                            "vocals": _file_record(vocals),
                            "instrumental": _file_record(instrumental),
                        },
                        "rvc": dict(rvc_data),
                        "mix": dict(BENCHMARK_MIX_POLICY),
                        "outputs": {
                            "converted_vocals": _file_record(converted),
                            "final_mix": _file_record(final_mix),
                        },
                    },
                )
            except Exception as exc:
                failed += 1
                write_json_atomic(
                    render_manifest,
                    {
                        "schema": BENCHMARK_RENDER_SCHEMA,
                        "status": "failed",
                        "benchmark_manifest": str(manifest_file),
                        "definition_sha256": definition_sha256,
                        "candidate_id": candidate_id,
                        "clip_id": clip_id,
                        "started_at": item_started_at,
                        "finished_at": datetime.now(UTC).isoformat(),
                        "duration_seconds": round(time.perf_counter() - start, 3),
                        "error_type": type(exc).__name__,
                        "error": str(exc),
                        "traceback": "".join(
                            traceback.format_exception(type(exc), exc, exc.__traceback__)
                        ),
                    },
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
                    "failed",
                )
                if not continue_on_error:
                    raise SeparationBenchmarkRenderError(
                        f"Review render failed for {candidate_id}/{clip_id}: {exc}"
                    ) from exc
                continue
            completed += 1
            _report(progress, candidate_id, clip_id, "completed", completed, total)
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
                "running",
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


def _convert(source: Path, output_dir: Path, settings: RvcSettings) -> Path:
    return convert_vocal_with_rvc(source, output_dir, settings).output_path


def _mix(converted: Path, instrumental: Path, output: Path) -> Path:
    return export_mix(
        (
            AudioMixSource("Converted Vocal", converted),
            AudioMixSource(
                "Instrumental",
                instrumental,
                volume=BENCHMARK_MIX_POLICY["instrumental_volume"],
            ),
        ),
        output,
    )


def _rvc_settings(data: Mapping[str, object]) -> RvcSettings:
    return RvcSettings(
        root=_required_path(data.get("root"), "rvc.root"),
        voice_model=_required_text(data.get("voice_model"), "rvc.voice_model"),
        index_file=_required_text(data.get("index_file"), "rvc.index_file"),
        pitch=_required_integer(data.get("pitch"), "rvc.pitch"),
        device=_required_text(data.get("device"), "rvc.device"),
        f0_method=_required_text(data.get("f0_method"), "rvc.f0_method"),
    )


def _load_separation_result(path: Path, definition_sha256: str) -> Mapping[str, object]:
    data = _load_json(path, "separation result")
    if (
        data.get("status") != "completed"
        or data.get("definition_sha256") != definition_sha256
    ):
        raise SeparationBenchmarkRenderError(f"Incomplete separation result: {path}")
    return data


def _completed_render_matches(
    path: Path,
    *,
    definition_sha256: str,
    vocals: Path,
    instrumental: Path,
    rvc_data: Mapping[str, object],
) -> bool:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if (
            data.get("schema") != BENCHMARK_RENDER_SCHEMA
            or data.get("status") != "completed"
            or data.get("definition_sha256") != definition_sha256
            or data.get("rvc") != dict(rvc_data)
            or data.get("mix") != BENCHMARK_MIX_POLICY
        ):
            return False
        inputs = _required_mapping(data.get("inputs"), "render inputs")
        if not _record_matches(inputs.get("vocals"), vocals) or not _record_matches(
            inputs.get("instrumental"), instrumental
        ):
            return False
        outputs = _required_mapping(data.get("outputs"), "render outputs")
        return all(
            _record_is_current(outputs.get(name))
            for name in ("converted_vocals", "final_mix")
        )
    except (OSError, TypeError, ValueError, json.JSONDecodeError, SeparationBenchmarkRenderError):
        return False


def _reusable_converted_output(
    path: Path,
    *,
    definition_sha256: str,
    vocals: Path,
    instrumental: Path,
    rvc_data: Mapping[str, object],
) -> Path | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if (
            data.get("schema") != BENCHMARK_RENDER_SCHEMA
            or data.get("status") != "completed"
            or data.get("definition_sha256") != definition_sha256
            or data.get("rvc") != dict(rvc_data)
        ):
            return None
        inputs = _required_mapping(data.get("inputs"), "render inputs")
        if not _record_matches(inputs.get("vocals"), vocals) or not _record_matches(
            inputs.get("instrumental"), instrumental
        ):
            return None
        outputs = _required_mapping(data.get("outputs"), "render outputs")
        converted = outputs.get("converted_vocals")
        if not _record_is_current(converted) or not isinstance(converted, Mapping):
            return None
        return _required_path(converted.get("path"), "converted vocals path")
    except (OSError, TypeError, ValueError, json.JSONDecodeError, SeparationBenchmarkRenderError):
        return None


def _record_matches(value: object, path: Path) -> bool:
    if not isinstance(value, Mapping):
        return False
    return value.get("path") == str(path) and value.get("sha256") == file_sha256(path)


def _record_is_current(value: object) -> bool:
    if not isinstance(value, Mapping):
        return False
    path = Path(str(value.get("path", ""))).expanduser().resolve()
    return path.is_file() and value.get("sha256") == file_sha256(path)


def _verified_file(outputs: Mapping[str, object], name: str) -> Path:
    record = outputs.get(name)
    if not isinstance(record, Mapping):
        raise SeparationBenchmarkRenderError(f"Missing separation output: {name}")
    path = _required_path(record.get("path"), f"{name} path")
    if not path.is_file() or file_sha256(path) != record.get("sha256"):
        raise SeparationBenchmarkRenderError(f"Separation output changed: {path}")
    return path


def _file_record(path: Path) -> dict[str, object]:
    resolved = path.expanduser().resolve()
    return {
        "path": str(resolved),
        "sha256": file_sha256(resolved),
        "size": resolved.stat().st_size,
    }


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
        raise SeparationBenchmarkRenderError(
            f"Unknown {key} values: {', '.join(missing)}"
        )
    return tuple(available[value] for value in wanted)


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
    target = root / "benchmark-render-progress.json"
    write_json_atomic(
        target,
        {
            "schema": 1,
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
        },
    )
    return target


def _report(
    progress: RenderProgressCallback | None,
    candidate_id: str,
    clip_id: str,
    stage: str,
    completed: int,
    total: int,
) -> None:
    if progress is not None:
        progress(candidate_id, clip_id, stage, completed, total)


def _load_json(path: Path, label: str) -> dict[str, object]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SeparationBenchmarkRenderError(f"Could not read {label}: {path}") from exc
    if not isinstance(data, dict):
        raise SeparationBenchmarkRenderError(f"Invalid {label}: {path}")
    return data


def _mapping_list(value: object, label: str) -> tuple[Mapping[str, object], ...]:
    if not isinstance(value, list) or not value:
        raise SeparationBenchmarkRenderError(f"Benchmark {label} must be a non-empty list.")
    if not all(isinstance(item, Mapping) for item in value):
        raise SeparationBenchmarkRenderError(f"Benchmark {label} contains invalid items.")
    return tuple(value)  # type: ignore[return-value]


def _required_mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise SeparationBenchmarkRenderError(f"Benchmark {label} must be an object.")
    return value


def _required_text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SeparationBenchmarkRenderError(f"Benchmark {label} is required.")
    return value.strip()


def _required_path(value: object, label: str) -> Path:
    return Path(_required_text(value, label)).expanduser().resolve()


def _required_integer(value: object, label: str) -> int:
    if isinstance(value, bool):
        raise SeparationBenchmarkRenderError(f"Benchmark {label} must be an integer.")
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise SeparationBenchmarkRenderError(
            f"Benchmark {label} must be an integer."
        ) from exc
