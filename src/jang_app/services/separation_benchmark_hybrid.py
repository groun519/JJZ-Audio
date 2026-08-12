from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path

from jang_app.services.audio_export import AudioMixSource, export_mix
from jang_app.services.managed_files import file_sha256, write_json_atomic
from jang_app.services.separation_benchmark_render import BENCHMARK_MIX_POLICY


HYBRID_BENCHMARK_SCHEMA = 1
HYBRID_RESULT_SCHEMA = 1
Mixer = Callable[[Path, Path, Path], Path]


class SeparationBenchmarkHybridError(RuntimeError):
    """Raised when a hybrid comparison cannot be rendered reproducibly."""


def render_hybrid_benchmark(
    benchmark_manifest_path: Path,
    plan_path: Path,
    *,
    mixer: Mixer | None = None,
) -> Path:
    benchmark_file = benchmark_manifest_path.expanduser().resolve()
    plan_file = plan_path.expanduser().resolve()
    benchmark = _load_json(benchmark_file, "benchmark manifest")
    plan = _load_json(plan_file, "hybrid plan")
    if plan.get("schema") != HYBRID_BENCHMARK_SCHEMA:
        raise SeparationBenchmarkHybridError("Unsupported hybrid plan schema.")
    if plan.get("benchmark_id") != benchmark.get("benchmark_id"):
        raise SeparationBenchmarkHybridError(
            "Hybrid plan and benchmark IDs do not match."
        )

    root = _required_path(benchmark.get("root"), "root")
    definition_sha256 = _required_text(
        benchmark.get("definition_sha256"), "definition_sha256"
    )
    plan_sha256 = file_sha256(plan_file)
    benchmark_clips = {
        _required_text(clip.get("clip_id"), "clip_id"): clip
        for clip in _mapping_list(benchmark.get("clips"), "clips")
    }
    candidate_ids = {
        _required_text(candidate.get("candidate_id"), "candidate_id")
        for candidate in _mapping_list(benchmark.get("candidates"), "candidates")
    }
    execute_mix = mixer or _mix
    rendered_clips: list[dict[str, object]] = []

    for planned_clip in _mapping_list(plan.get("clips"), "plan clips"):
        clip_id = _required_text(planned_clip.get("clip_id"), "clip_id")
        clip = benchmark_clips.get(clip_id)
        if clip is None:
            raise SeparationBenchmarkHybridError(
                f"Unknown clip in hybrid plan: {clip_id}"
            )
        source = _verified_clip_source(clip)
        rendered_candidates: list[dict[str, object]] = []
        seen_candidates: set[str] = set()
        for candidate in _mapping_list(
            planned_clip.get("candidates"), f"{clip_id} candidates"
        ):
            comparison_id = _required_text(
                candidate.get("candidate_id"), "candidate_id"
            )
            if comparison_id in seen_candidates:
                raise SeparationBenchmarkHybridError(
                    f"Duplicate hybrid candidate for {clip_id}: {comparison_id}"
                )
            seen_candidates.add(comparison_id)
            vocal_candidate_id = _known_candidate(
                candidate.get("vocal_candidate_id"), candidate_ids
            )
            instrumental_candidate_id = _known_candidate(
                candidate.get("instrumental_candidate_id"), candidate_ids
            )
            converted_vocals = _converted_vocals(
                root, vocal_candidate_id, clip_id, definition_sha256
            )
            instrumental = _instrumental(
                root, instrumental_candidate_id, clip_id, definition_sha256
            )
            output_dir = root / "hybrid-results" / clip_id / comparison_id
            result_path = output_dir / "hybrid-result.json"
            final_mix = output_dir / "final_mix.wav"
            if not _completed_result_matches(
                result_path,
                definition_sha256=definition_sha256,
                plan_sha256=plan_sha256,
                converted_vocals=converted_vocals,
                instrumental=instrumental,
            ):
                output_dir.mkdir(parents=True, exist_ok=True)
                execute_mix(converted_vocals, instrumental, final_mix)
                if not final_mix.is_file():
                    raise SeparationBenchmarkHybridError(
                        f"Hybrid final mix was not created: {final_mix}"
                    )
                write_json_atomic(
                    result_path,
                    {
                        "schema": HYBRID_RESULT_SCHEMA,
                        "status": "completed",
                        "benchmark_manifest": str(benchmark_file),
                        "hybrid_plan": str(plan_file),
                        "definition_sha256": definition_sha256,
                        "plan_sha256": plan_sha256,
                        "clip_id": clip_id,
                        "candidate_id": comparison_id,
                        "vocal_candidate_id": vocal_candidate_id,
                        "instrumental_candidate_id": instrumental_candidate_id,
                        "generated_at": datetime.now(UTC).isoformat(),
                        "mix": dict(BENCHMARK_MIX_POLICY),
                        "inputs": {
                            "converted_vocals": _file_record(converted_vocals),
                            "instrumental": _file_record(instrumental),
                        },
                        "outputs": {"final_mix": _file_record(final_mix)},
                    },
                )
            result = _load_completed_hybrid_result(
                result_path, definition_sha256, plan_sha256
            )
            inputs = _required_mapping(result.get("inputs"), "hybrid inputs")
            outputs = _required_mapping(result.get("outputs"), "hybrid outputs")
            rendered_candidates.append(
                {
                    "candidate_id": comparison_id,
                    "label": candidate.get("label", comparison_id),
                    "vocal_candidate_id": vocal_candidate_id,
                    "instrumental_candidate_id": instrumental_candidate_id,
                    "converted_vocals": dict(
                        _required_mapping(
                            inputs.get("converted_vocals"), "converted vocals"
                        )
                    ),
                    "instrumental": dict(
                        _required_mapping(inputs.get("instrumental"), "instrumental")
                    ),
                    "final_mix": dict(
                        _required_mapping(outputs.get("final_mix"), "final mix")
                    ),
                }
            )
        if len(rendered_candidates) < 2:
            raise SeparationBenchmarkHybridError(
                f"Hybrid clip requires at least two candidates: {clip_id}"
            )
        rendered_clips.append(
            {
                "clip_id": clip_id,
                "title": clip.get("title", clip_id),
                "role": clip.get("role", ""),
                "source": _file_record(source),
                "candidates": rendered_candidates,
            }
        )

    target = root / "hybrid-results" / "hybrid-benchmark.json"
    write_json_atomic(
        target,
        {
            "schema": HYBRID_BENCHMARK_SCHEMA,
            "status": "completed",
            "benchmark_id": benchmark.get("benchmark_id", ""),
            "title": plan.get("title", "Hybrid separation comparison"),
            "generated_at": datetime.now(UTC).isoformat(),
            "benchmark_manifest": str(benchmark_file),
            "hybrid_plan": str(plan_file),
            "definition_sha256": definition_sha256,
            "plan_sha256": plan_sha256,
            "root": str(root),
            "mix": dict(BENCHMARK_MIX_POLICY),
            "clips": rendered_clips,
        },
    )
    return target


def _mix(converted_vocals: Path, instrumental: Path, output: Path) -> Path:
    return export_mix(
        (
            AudioMixSource("Converted Vocal", converted_vocals),
            AudioMixSource(
                "Instrumental",
                instrumental,
                volume=BENCHMARK_MIX_POLICY["instrumental_volume"],
            ),
        ),
        output,
    )


def _converted_vocals(
    root: Path,
    candidate_id: str,
    clip_id: str,
    definition_sha256: str,
) -> Path:
    render_path = (
        root
        / "results"
        / candidate_id
        / clip_id
        / "downstream"
        / "benchmark-render.json"
    )
    render = _load_json(render_path, "benchmark conversion render")
    if (
        render.get("status") != "completed"
        or render.get("definition_sha256") != definition_sha256
    ):
        raise SeparationBenchmarkHybridError(
            f"Incomplete conversion render: {render_path}"
        )
    return _verified_record_path(
        _required_mapping(render.get("outputs"), "render outputs").get(
            "converted_vocals"
        ),
        "converted vocals",
    )


def _instrumental(
    root: Path,
    candidate_id: str,
    clip_id: str,
    definition_sha256: str,
) -> Path:
    result_path = root / "results" / candidate_id / clip_id / "benchmark-result.json"
    result = _load_json(result_path, "benchmark separation result")
    if (
        result.get("status") != "completed"
        or result.get("definition_sha256") != definition_sha256
    ):
        raise SeparationBenchmarkHybridError(
            f"Incomplete separation result: {result_path}"
        )
    return _verified_record_path(
        _required_mapping(result.get("outputs"), "separation outputs").get(
            "instrumental"
        ),
        "instrumental",
    )


def _verified_clip_source(clip: Mapping[str, object]) -> Path:
    path = _required_path(clip.get("path"), "clip path")
    expected_hash = _required_text(clip.get("sha256"), "clip sha256")
    if not path.is_file() or file_sha256(path) != expected_hash:
        raise SeparationBenchmarkHybridError(f"Benchmark clip changed: {path}")
    return path


def _verified_record_path(value: object, label: str) -> Path:
    record = _required_mapping(value, label)
    path = _required_path(record.get("path"), f"{label} path")
    expected_hash = _required_text(record.get("sha256"), f"{label} sha256")
    if not path.is_file() or file_sha256(path) != expected_hash:
        raise SeparationBenchmarkHybridError(f"Hybrid input changed: {path}")
    return path


def _load_completed_hybrid_result(
    path: Path, definition_sha256: str, plan_sha256: str
) -> Mapping[str, object]:
    result = _load_json(path, "hybrid result")
    if (
        result.get("schema") != HYBRID_RESULT_SCHEMA
        or result.get("status") != "completed"
        or result.get("definition_sha256") != definition_sha256
        or result.get("plan_sha256") != plan_sha256
    ):
        raise SeparationBenchmarkHybridError(f"Incomplete hybrid result: {path}")
    return result


def _completed_result_matches(
    path: Path,
    *,
    definition_sha256: str,
    plan_sha256: str,
    converted_vocals: Path,
    instrumental: Path,
) -> bool:
    try:
        result = _load_completed_hybrid_result(
            path, definition_sha256, plan_sha256
        )
        if result.get("mix") != BENCHMARK_MIX_POLICY:
            return False
        inputs = _required_mapping(result.get("inputs"), "hybrid inputs")
        outputs = _required_mapping(result.get("outputs"), "hybrid outputs")
        return (
            _record_matches(inputs.get("converted_vocals"), converted_vocals)
            and _record_matches(inputs.get("instrumental"), instrumental)
            and _record_is_current(outputs.get("final_mix"))
        )
    except (OSError, ValueError, SeparationBenchmarkHybridError):
        return False


def _record_matches(value: object, path: Path) -> bool:
    return (
        isinstance(value, Mapping)
        and value.get("path") == str(path)
        and value.get("sha256") == file_sha256(path)
    )


def _record_is_current(value: object) -> bool:
    if not isinstance(value, Mapping):
        return False
    path = Path(str(value.get("path", ""))).expanduser().resolve()
    return path.is_file() and value.get("sha256") == file_sha256(path)


def _file_record(path: Path) -> dict[str, object]:
    resolved = path.expanduser().resolve()
    return {
        "path": str(resolved),
        "sha256": file_sha256(resolved),
        "size": resolved.stat().st_size,
    }


def _known_candidate(value: object, available: set[str]) -> str:
    candidate_id = _required_text(value, "candidate ID")
    if candidate_id not in available:
        raise SeparationBenchmarkHybridError(
            f"Unknown benchmark candidate: {candidate_id}"
        )
    return candidate_id


def _load_json(path: Path, label: str) -> dict[str, object]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SeparationBenchmarkHybridError(f"Could not read {label}: {path}") from exc
    if not isinstance(data, dict):
        raise SeparationBenchmarkHybridError(f"Invalid {label}: {path}")
    return data


def _mapping_list(value: object, label: str) -> tuple[Mapping[str, object], ...]:
    if not isinstance(value, list) or not value:
        raise SeparationBenchmarkHybridError(f"{label} must be a non-empty list.")
    if not all(isinstance(item, Mapping) for item in value):
        raise SeparationBenchmarkHybridError(f"{label} contains invalid items.")
    return tuple(value)  # type: ignore[return-value]


def _required_mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise SeparationBenchmarkHybridError(f"{label} must be an object.")
    return value


def _required_text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SeparationBenchmarkHybridError(f"{label} is required.")
    return value.strip()


def _required_path(value: object, label: str) -> Path:
    return Path(_required_text(value, label)).expanduser().resolve()
