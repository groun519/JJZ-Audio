from __future__ import annotations

import json
import os
import shutil
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path

from jang_app.services.audio_export import AudioMixSource, export_mix
from jang_app.services.file_names import safe_display_filename_stem
from jang_app.services.managed_files import file_sha256, write_json_atomic
from jang_app.services.separation_benchmark_render import BENCHMARK_MIX_POLICY
from jang_app.services.separation_incremental_review import (
    INCREMENTAL_REVIEW_KEY_SCHEMA,
    INCREMENTAL_REVIEW_SCHEMA,
    IncrementalSeparationReviewError,
)


FOLLOWUP_RESULT_SCHEMA = 1
FOLLOWUP_STAGE_DEFINITIONS = (
    {
        "key": "converted_vocals",
        "label": "변환 보컬",
        "criteria": "보컬 누락 · 음정 · 음색 · 금속성 또는 갈라짐",
    },
    {
        "key": "final_mix",
        "label": "최종 믹스",
        "criteria": "원보컬 잔류 · 변환 보컬 선명도 · 밸런스 · 자연스러움",
    },
)


def build_incremental_followup(
    challenger_manifest_path: Path,
    baseline_manifest_path: Path,
    analysis_path: Path,
) -> tuple[Path, Path, Path]:
    challenger_file = challenger_manifest_path.expanduser().resolve()
    baseline_file = baseline_manifest_path.expanduser().resolve()
    analysis_file = analysis_path.expanduser().resolve()
    challenger = _load_json(challenger_file, "challenger manifest")
    baseline = _load_json(baseline_file, "baseline manifest")
    analysis = _load_json(analysis_file, "incremental analysis")
    if analysis.get("schema") != 1 or not analysis.get("complete"):
        raise IncrementalSeparationReviewError("Incremental analysis is incomplete.")
    if analysis.get("benchmark_id") != challenger.get("benchmark_id"):
        raise IncrementalSeparationReviewError(
            "Incremental analysis and challenger benchmark do not match."
        )

    challenger_candidates = _candidate_ids(challenger)
    baseline_candidates = _candidate_ids(baseline)
    clip_map = {
        _required_text(clip.get("clip_id"), "clip_id"): clip
        for clip in _mapping_list(challenger.get("clips"), "clips")
    }
    root = _required_path(challenger.get("root"), "challenger root")
    output_root = root / "followup-results"
    review_dir = root / "review"
    media_root = review_dir / "followup-media"
    review_clips: list[dict[str, object]] = []
    key_clips: list[dict[str, object]] = []
    result_clips: list[dict[str, object]] = []

    for clip_result in _mapping_list(analysis.get("clip_results"), "clip_results"):
        clip_id = _required_text(clip_result.get("clip_id"), "clip_id")
        clip = clip_map.get(clip_id)
        if clip is None:
            raise IncrementalSeparationReviewError(
                f"Unknown clip in incremental analysis: {clip_id}"
            )
        stages = _mapping(clip_result.get("stages"), f"{clip_id} stages")
        vocal = _selected_stage(stages, "vocals")
        instrumental = _selected_stage(stages, "instrumental")
        reference_vocal = vocal[0]
        selected_vocal = vocal[1]
        reference_instrumental = instrumental[0]
        selected_instrumental = instrumental[1]
        if (
            reference_vocal == selected_vocal
            and reference_instrumental == selected_instrumental
        ):
            continue

        source = _verified_clip_source(clip)
        reference_converted = _converted_vocals(
            _manifest_for_candidate(
                reference_vocal,
                challenger,
                baseline,
                challenger_candidates,
                baseline_candidates,
            ),
            reference_vocal,
            clip_id,
        )
        selected_converted = _converted_vocals(
            _manifest_for_candidate(
                selected_vocal,
                challenger,
                baseline,
                challenger_candidates,
                baseline_candidates,
            ),
            selected_vocal,
            clip_id,
        )
        reference_instrument = _instrumental(
            _manifest_for_candidate(
                reference_instrumental,
                challenger,
                baseline,
                challenger_candidates,
                baseline_candidates,
            ),
            reference_instrumental,
            clip_id,
        )
        selected_instrument = _instrumental(
            _manifest_for_candidate(
                selected_instrumental,
                challenger,
                baseline,
                challenger_candidates,
                baseline_candidates,
            ),
            selected_instrumental,
            clip_id,
        )
        clip_output = output_root / safe_display_filename_stem(
            clip_id, fallback="clip"
        )
        reference_mix = _render_mix(
            reference_converted,
            reference_instrument,
            clip_output / "reference" / "final_mix.wav",
        )
        selected_mix = _render_mix(
            selected_converted,
            selected_instrument,
            clip_output / "challenger" / "final_mix.wav",
        )

        staged_source = _stage_audio(
            source, media_root / safe_display_filename_stem(clip_id) / "source.wav"
        )
        stage_rows: dict[str, object] = {}
        if file_sha256(reference_converted) != file_sha256(selected_converted):
            stage_rows["converted_vocals"] = {
                "candidates": _stage_pair(
                    reference_converted,
                    selected_converted,
                    media_root,
                    clip_id,
                    "converted_vocals",
                )
            }
        stage_rows["final_mix"] = {
            "candidates": _stage_pair(
                reference_mix,
                selected_mix,
                media_root,
                clip_id,
                "final_mix",
            )
        }
        recipes = {
            "A": {
                "vocal_candidate_id": reference_vocal,
                "instrumental_candidate_id": reference_instrumental,
            },
            "B": {
                "vocal_candidate_id": selected_vocal,
                "instrumental_candidate_id": selected_instrumental,
            },
        }
        review_clips.append(
            {
                "clip_id": clip_id,
                "title": clip.get("title", clip_id),
                "role": clip.get("role", ""),
                "source": str(staged_source),
                "stages": stage_rows,
            }
        )
        key_clips.append(
            {
                "clip_id": clip_id,
                "candidates": [
                    {"code": code, "role": role, **recipes[code]}
                    for code, role in (("A", "reference"), ("B", "challenger"))
                ],
            }
        )
        result_clips.append(
            {
                "clip_id": clip_id,
                "reference": {
                    **recipes["A"],
                    "converted_vocals": _file_record(reference_converted),
                    "instrumental": _file_record(reference_instrument),
                    "final_mix": _file_record(reference_mix),
                },
                "challenger": {
                    **recipes["B"],
                    "converted_vocals": _file_record(selected_converted),
                    "instrumental": _file_record(selected_instrument),
                    "final_mix": _file_record(selected_mix),
                },
            }
        )

    if not review_clips:
        raise IncrementalSeparationReviewError(
            "No challenger advanced to the RVC follow-up."
        )

    generated_at = datetime.now(UTC).isoformat()
    result_file = output_root / "followup-combinations.json"
    review_file = review_dir / "followup-review.json"
    key_file = review_dir / "followup-key.json"
    write_json_atomic(
        result_file,
        {
            "schema": FOLLOWUP_RESULT_SCHEMA,
            "status": "completed",
            "benchmark_id": challenger.get("benchmark_id", ""),
            "generated_at": generated_at,
            "analysis": str(analysis_file),
            "mix": dict(BENCHMARK_MIX_POLICY),
            "clips": result_clips,
        },
    )
    write_json_atomic(
        review_file,
        {
            "schema": INCREMENTAL_REVIEW_SCHEMA,
            "review_type": "incremental-followup",
            "benchmark_id": challenger.get("benchmark_id", ""),
            "title": "승자 조합 최종 검수",
            "subtitle": "원본 분리에서 기준을 이긴 조합만 기존 승인본 A와 비교합니다.",
            "generated_at": generated_at,
            "responses": str(review_dir / "followup-review-responses.json"),
            "stage_definitions": list(FOLLOWUP_STAGE_DEFINITIONS),
            "clips": review_clips,
        },
    )
    write_json_atomic(
        key_file,
        {
            "schema": INCREMENTAL_REVIEW_KEY_SCHEMA,
            "review_type": "incremental-followup",
            "benchmark_id": challenger.get("benchmark_id", ""),
            "generated_at": generated_at,
            "analysis": str(analysis_file),
            "clips": key_clips,
        },
    )
    return result_file, review_file, key_file


def _selected_stage(
    stages: Mapping[str, object], stage: str
) -> tuple[str, str]:
    data = _mapping(stages.get(stage), stage)
    reference = _mapping(data.get("reference"), f"{stage} reference")
    reference_id = _required_text(reference.get("candidate_id"), "candidate_id")
    advancing = _mapping_list_allow_empty(data.get("advancing"))
    if len(advancing) > 1:
        raise IncrementalSeparationReviewError(
            f"Multiple {stage} candidates advanced; select one before follow-up."
        )
    selected_id = (
        _required_text(advancing[0].get("candidate_id"), "candidate_id")
        if advancing
        else reference_id
    )
    return reference_id, selected_id


def _manifest_for_candidate(
    candidate_id: str,
    challenger: Mapping[str, object],
    baseline: Mapping[str, object],
    challenger_candidates: set[str],
    baseline_candidates: set[str],
) -> Mapping[str, object]:
    if candidate_id in challenger_candidates:
        return challenger
    if candidate_id in baseline_candidates:
        return baseline
    raise IncrementalSeparationReviewError(f"Unknown candidate: {candidate_id}")


def _converted_vocals(
    manifest: Mapping[str, object], candidate_id: str, clip_id: str
) -> Path:
    root = _required_path(manifest.get("root"), "manifest root")
    render = _load_json(
        root
        / "results"
        / candidate_id
        / clip_id
        / "downstream"
        / "benchmark-render.json",
        "benchmark render",
    )
    _verify_completed(render, manifest, "benchmark render")
    outputs = _mapping(render.get("outputs"), "render outputs")
    return _verified_record(outputs.get("converted_vocals"), "converted vocals")


def _instrumental(
    manifest: Mapping[str, object], candidate_id: str, clip_id: str
) -> Path:
    root = _required_path(manifest.get("root"), "manifest root")
    result = _load_json(
        root / "results" / candidate_id / clip_id / "benchmark-result.json",
        "benchmark result",
    )
    _verify_completed(result, manifest, "benchmark result")
    outputs = _mapping(result.get("outputs"), "result outputs")
    return _verified_record(outputs.get("instrumental"), "instrumental")


def _verify_completed(
    result: Mapping[str, object], manifest: Mapping[str, object], label: str
) -> None:
    if (
        result.get("status") != "completed"
        or result.get("definition_sha256") != manifest.get("definition_sha256")
    ):
        raise IncrementalSeparationReviewError(f"Incomplete {label}.")


def _verified_clip_source(clip: Mapping[str, object]) -> Path:
    path = _required_path(clip.get("path"), "clip path")
    expected = _required_text(clip.get("sha256"), "clip sha256")
    if not path.is_file() or file_sha256(path) != expected:
        raise IncrementalSeparationReviewError(f"Changed clip source: {path}")
    return path


def _verified_record(value: object, label: str) -> Path:
    record = _mapping(value, label)
    path = _required_path(record.get("path"), f"{label} path")
    expected = _required_text(record.get("sha256"), f"{label} sha256")
    if not path.is_file() or file_sha256(path) != expected:
        raise IncrementalSeparationReviewError(f"Changed {label}: {path}")
    return path


def _render_mix(converted: Path, instrumental: Path, output: Path) -> Path:
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


def _stage_pair(
    reference: Path,
    challenger: Path,
    media_root: Path,
    clip_id: str,
    stage: str,
) -> list[dict[str, str]]:
    clip_token = safe_display_filename_stem(clip_id, fallback="clip")
    return [
        {
            "code": "A",
            "path": str(_stage_audio(reference, media_root / clip_token / stage / "A.wav")),
        },
        {
            "code": "B",
            "path": str(_stage_audio(challenger, media_root / clip_token / stage / "B.wav")),
        },
    ]


def _stage_audio(source: Path, target: Path) -> Path:
    source_hash = file_sha256(source)
    if target.is_file() and file_sha256(target) == source_hash:
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    target.unlink(missing_ok=True)
    try:
        os.link(source, target)
    except OSError:
        shutil.copy2(source, target)
    if file_sha256(target) != source_hash:
        raise IncrementalSeparationReviewError(
            f"Could not stage follow-up audio: {target}"
        )
    return target


def _file_record(path: Path) -> dict[str, object]:
    return {
        "path": str(path),
        "sha256": file_sha256(path),
        "size": path.stat().st_size,
    }


def _candidate_ids(manifest: Mapping[str, object]) -> set[str]:
    return {
        _required_text(candidate.get("candidate_id"), "candidate_id")
        for candidate in _mapping_list(manifest.get("candidates"), "candidates")
    }


def _load_json(path: Path, label: str) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise IncrementalSeparationReviewError(f"Could not read {label}: {path}") from exc
    if not isinstance(value, dict):
        raise IncrementalSeparationReviewError(f"Invalid {label}: {path}")
    return value


def _mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise IncrementalSeparationReviewError(f"{label} must be an object.")
    return value


def _mapping_list(value: object, label: str) -> tuple[Mapping[str, object], ...]:
    if not isinstance(value, list) or not value:
        raise IncrementalSeparationReviewError(f"{label} must be a non-empty list.")
    if not all(isinstance(item, Mapping) for item in value):
        raise IncrementalSeparationReviewError(f"{label} contains invalid items.")
    return tuple(value)  # type: ignore[return-value]


def _mapping_list_allow_empty(value: object) -> tuple[Mapping[str, object], ...]:
    if not isinstance(value, list) or not all(isinstance(item, Mapping) for item in value):
        raise IncrementalSeparationReviewError("Expected a list of objects.")
    return tuple(value)  # type: ignore[return-value]


def _required_text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise IncrementalSeparationReviewError(f"{label} is required.")
    return value.strip()


def _required_path(value: object, label: str) -> Path:
    return Path(_required_text(value, label)).expanduser().resolve()
