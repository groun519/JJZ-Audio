from __future__ import annotations

import json
import os
import random
import shutil
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path

from jang_app.services.file_names import safe_display_filename_stem
from jang_app.services.managed_files import file_sha256, write_json_atomic


INCREMENTAL_REVIEW_SCHEMA = 1
INCREMENTAL_REVIEW_KEY_SCHEMA = 1
INCREMENTAL_RESPONSE_SCHEMA = 1
STAGES = ("vocals", "instrumental")
COMPARISON_VALUES = ("better", "same", "worse")
SUPPORTED_REVIEW_TYPES = {"incremental-separation", "incremental-followup"}
DEFAULT_STAGE_DEFINITIONS = (
    {
        "key": "vocals",
        "label": "보컬",
        "criteria": "보컬 누락 · 악기 유입 · 잔향/효과 · 음색 손상과 아티팩트",
    },
    {
        "key": "instrumental",
        "label": "반주",
        "criteria": "원보컬 잔류 · 악기 손실 · 타격감 보존 · 아티팩트",
    },
)


class IncrementalSeparationReviewError(RuntimeError):
    """Raised when a baseline comparison review cannot be prepared safely."""


def build_incremental_review(
    challenger_manifest_path: Path,
    baseline_manifest_path: Path,
    *,
    baseline_vocal_candidate_id: str,
    baseline_instrumental_candidate_ids: Mapping[str, str] | None = None,
    challenger_candidate_ids: Sequence[str] = (),
) -> tuple[Path, Path]:
    challenger_file = challenger_manifest_path.expanduser().resolve()
    baseline_file = baseline_manifest_path.expanduser().resolve()
    challenger = _load_json(challenger_file, "challenger manifest")
    baseline = _load_json(baseline_file, "baseline manifest")
    root = _required_path(challenger.get("root"), "challenger root")
    definition_sha256 = _required_text(
        challenger.get("definition_sha256"), "definition_sha256"
    )
    baseline_definition_sha256 = _required_text(
        baseline.get("definition_sha256"), "baseline definition_sha256"
    )
    challengers = _selected_candidates(challenger, challenger_candidate_ids)
    baseline_candidates = _candidate_map(baseline)
    if baseline_vocal_candidate_id not in baseline_candidates:
        raise IncrementalSeparationReviewError(
            f"Unknown baseline vocal candidate: {baseline_vocal_candidate_id}"
        )

    instrumental_ids = dict(baseline_instrumental_candidate_ids or {})
    media_root = root / "review" / "incremental-media"
    review_clips: list[dict[str, object]] = []
    key_clips: list[dict[str, object]] = []
    for clip in _mapping_list(challenger.get("clips"), "clips"):
        clip_id = _required_text(clip.get("clip_id"), "clip_id")
        clip_token = safe_display_filename_stem(clip_id, fallback="clip")
        baseline_instrumental_id = instrumental_ids.get(
            clip_id, baseline_vocal_candidate_id
        )
        if baseline_instrumental_id not in baseline_candidates:
            raise IncrementalSeparationReviewError(
                f"Unknown instrumental baseline for {clip_id}: "
                f"{baseline_instrumental_id}"
            )
        source = _stage_audio(
            _verified_path(clip, "path", "sha256", "source"),
            media_root / clip_token / "source.wav",
        )
        ordered_challengers = list(challengers)
        random.Random(
            f"{definition_sha256}:incremental:{clip_id}"
        ).shuffle(ordered_challengers)
        challenger_codes = {
            _required_text(candidate.get("candidate_id"), "candidate_id"): chr(
                ord("B") + index
            )
            for index, candidate in enumerate(ordered_challengers)
        }
        stage_reviews: dict[str, object] = {}
        stage_keys: dict[str, object] = {}
        for stage in STAGES:
            baseline_candidate_id = (
                baseline_vocal_candidate_id
                if stage == "vocals"
                else baseline_instrumental_id
            )
            baseline_output = _candidate_output(
                baseline,
                baseline_candidate_id,
                clip_id,
                stage,
                baseline_definition_sha256,
            )
            reference = {
                "code": "A",
                "path": str(
                    _stage_audio(
                        baseline_output,
                        media_root / clip_token / stage / "A.wav",
                    )
                ),
            }
            unique_hashes = {file_sha256(baseline_output)}
            pending: list[tuple[str, Mapping[str, object], Path]] = []
            for candidate in ordered_challengers:
                candidate_id = _required_text(
                    candidate.get("candidate_id"), "candidate_id"
                )
                output = _candidate_output(
                    challenger,
                    candidate_id,
                    clip_id,
                    stage,
                    definition_sha256,
                )
                output_hash = file_sha256(output)
                if output_hash in unique_hashes:
                    continue
                unique_hashes.add(output_hash)
                pending.append((challenger_codes[candidate_id], candidate, output))
            review_candidates: list[dict[str, object]] = [reference]
            key_candidates: list[dict[str, object]] = [
                {
                    "code": "A",
                    "candidate_id": baseline_candidate_id,
                    "candidate_label": baseline_candidates[baseline_candidate_id].get(
                        "label", baseline_candidate_id
                    ),
                    "role": "reference",
                }
            ]
            for code, candidate, output in pending:
                review_candidates.append(
                    {
                        "code": code,
                        "path": str(
                            _stage_audio(
                                output,
                                media_root / clip_token / stage / f"{code}.wav",
                            )
                        ),
                    }
                )
                candidate_id = _required_text(
                    candidate.get("candidate_id"), "candidate_id"
                )
                key_candidates.append(
                    {
                        "code": code,
                        "candidate_id": candidate_id,
                        "candidate_label": candidate.get("label", candidate_id),
                        "role": "challenger",
                    }
                )
            stage_reviews[stage] = {"candidates": review_candidates}
            stage_keys[stage] = {"candidates": key_candidates}
        review_clips.append(
            {
                "clip_id": clip_id,
                "title": clip.get("title", clip_id),
                "role": clip.get("role", ""),
                "source": str(source),
                "stages": stage_reviews,
            }
        )
        key_clips.append({"clip_id": clip_id, "stages": stage_keys})

    review_dir = root / "review"
    review_file = review_dir / "incremental-review.json"
    key_file = review_dir / "incremental-key.json"
    generated_at = datetime.now(UTC).isoformat()
    write_json_atomic(
        review_file,
        {
            "schema": INCREMENTAL_REVIEW_SCHEMA,
            "review_type": "incremental-separation",
            "benchmark_id": challenger.get("benchmark_id", ""),
            "title": challenger.get("title", ""),
            "generated_at": generated_at,
            "responses": str(review_dir / "incremental-review-responses.json"),
            "clips": review_clips,
        },
    )
    write_json_atomic(
        key_file,
        {
            "schema": INCREMENTAL_REVIEW_KEY_SCHEMA,
            "review_type": "incremental-separation",
            "benchmark_id": challenger.get("benchmark_id", ""),
            "generated_at": generated_at,
            "challenger_definition_sha256": definition_sha256,
            "baseline_definition_sha256": baseline_definition_sha256,
            "clips": key_clips,
        },
    )
    return review_file, key_file


def load_incremental_review(path: Path) -> dict[str, object]:
    data = _load_json(path.expanduser().resolve(), "incremental review")
    if (
        data.get("schema") != INCREMENTAL_REVIEW_SCHEMA
        or data.get("review_type") not in SUPPORTED_REVIEW_TYPES
    ):
        raise IncrementalSeparationReviewError("Unsupported incremental review.")
    _mapping_list(data.get("clips"), "clips")
    review_stage_definitions(data)
    return data


def review_stage_definitions(
    review: Mapping[str, object],
) -> tuple[Mapping[str, str], ...]:
    value = review.get("stage_definitions")
    if value is None:
        return DEFAULT_STAGE_DEFINITIONS
    if not isinstance(value, list) or not value:
        raise IncrementalSeparationReviewError(
            "stage_definitions must be a non-empty list."
        )
    definitions: list[Mapping[str, str]] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, Mapping):
            raise IncrementalSeparationReviewError(
                "stage_definitions contains invalid items."
            )
        key = _required_text(item.get("key"), "stage key")
        if key == "source" or key in seen:
            raise IncrementalSeparationReviewError(f"Invalid stage key: {key}")
        seen.add(key)
        definitions.append(
            {
                "key": key,
                "label": _required_text(item.get("label"), "stage label"),
                "criteria": _required_text(
                    item.get("criteria"), "stage criteria"
                ),
            }
        )
    return tuple(definitions)


def load_incremental_responses(path: Path) -> dict[str, object]:
    target = path.expanduser().resolve()
    if not target.is_file():
        return {
            "schema": INCREMENTAL_RESPONSE_SCHEMA,
            "updated_at": "",
            "comparisons": {},
            "notes": {},
        }
    data = _load_json(target, "incremental responses")
    if data.get("schema") != INCREMENTAL_RESPONSE_SCHEMA:
        raise IncrementalSeparationReviewError(
            "Unsupported incremental response schema."
        )
    if not isinstance(data.get("comparisons"), Mapping):
        data["comparisons"] = {}
    if not isinstance(data.get("notes"), Mapping):
        data["notes"] = {}
    return data


def save_incremental_responses(
    path: Path, responses: Mapping[str, object]
) -> Path:
    target = path.expanduser().resolve()
    data = dict(responses)
    data["schema"] = INCREMENTAL_RESPONSE_SCHEMA
    data["updated_at"] = datetime.now(UTC).isoformat()
    write_json_atomic(target, data)
    return target


def _selected_candidates(
    manifest: Mapping[str, object], selected: Sequence[str]
) -> tuple[Mapping[str, object], ...]:
    candidates = _mapping_list(manifest.get("candidates"), "candidates")
    if not selected:
        return candidates
    candidate_map = {
        _required_text(value.get("candidate_id"), "candidate_id"): value
        for value in candidates
    }
    missing = [candidate_id for candidate_id in selected if candidate_id not in candidate_map]
    if missing:
        raise IncrementalSeparationReviewError(
            f"Unknown challenger candidates: {', '.join(missing)}"
        )
    return tuple(candidate_map[candidate_id] for candidate_id in selected)


def _candidate_map(manifest: Mapping[str, object]) -> dict[str, Mapping[str, object]]:
    return {
        _required_text(value.get("candidate_id"), "candidate_id"): value
        for value in _mapping_list(manifest.get("candidates"), "candidates")
    }


def _candidate_output(
    manifest: Mapping[str, object],
    candidate_id: str,
    clip_id: str,
    stage: str,
    definition_sha256: str,
) -> Path:
    root = _required_path(manifest.get("root"), "manifest root")
    result_path = root / "results" / candidate_id / clip_id / "benchmark-result.json"
    result = _load_json(result_path, "benchmark result")
    if (
        result.get("status") != "completed"
        or result.get("definition_sha256") != definition_sha256
    ):
        raise IncrementalSeparationReviewError(
            f"Incomplete benchmark result: {result_path}"
        )
    outputs = _mapping(result.get("outputs"), "outputs")
    output_name = "vocals" if stage == "vocals" else "instrumental"
    record = _mapping(outputs.get(output_name), output_name)
    return _verified_path(record, "path", "sha256", output_name)


def _verified_path(
    data: Mapping[str, object], path_key: str, hash_key: str, label: str
) -> Path:
    path = _required_path(data.get(path_key), f"{label} path")
    expected = _required_text(data.get(hash_key), f"{label} sha256")
    if not path.is_file() or file_sha256(path) != expected:
        raise IncrementalSeparationReviewError(f"Changed {label} file: {path}")
    return path


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
            f"Could not stage anonymous review audio: {target}"
        )
    return target


def _load_json(path: Path, label: str) -> dict[str, object]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise IncrementalSeparationReviewError(
            f"Could not read {label}: {path}"
        ) from exc
    if not isinstance(data, dict):
        raise IncrementalSeparationReviewError(f"Invalid {label}: {path}")
    return data


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


def _required_text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise IncrementalSeparationReviewError(f"{label} is required.")
    return value.strip()


def _required_path(value: object, label: str) -> Path:
    return Path(_required_text(value, label)).expanduser().resolve()
