from __future__ import annotations

import json
import os
import random
import shutil
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path

from jang_app.services.file_names import safe_display_filename_stem
from jang_app.services.managed_files import file_sha256, write_json_atomic


BLIND_REVIEW_SCHEMA = 1
BLIND_REVIEW_KEY_SCHEMA = 1
BLIND_REVIEW_RESPONSES_SCHEMA = 2
_SUPPORTED_RESPONSE_SCHEMAS = {1, BLIND_REVIEW_RESPONSES_SCHEMA}
REVIEW_TYPE_SEPARATION = "separation"
REVIEW_TYPE_CONVERSION = "conversion"
REVIEW_TYPE_HYBRID = "hybrid"


class SeparationBenchmarkReviewError(RuntimeError):
    """Raised when complete benchmark outputs cannot form a blind review."""


def build_blind_review(manifest_path: Path) -> tuple[Path, Path]:
    return _build_review(manifest_path, REVIEW_TYPE_SEPARATION)


def build_conversion_review(manifest_path: Path) -> tuple[Path, Path]:
    return _build_review(manifest_path, REVIEW_TYPE_CONVERSION)


def build_hybrid_review(hybrid_manifest_path: Path) -> tuple[Path, Path]:
    manifest_file = hybrid_manifest_path.expanduser().resolve()
    manifest = _load_json(manifest_file, "hybrid benchmark manifest")
    if manifest.get("schema") != 1 or manifest.get("status") != "completed":
        raise SeparationBenchmarkReviewError(
            f"Incomplete hybrid benchmark manifest: {manifest_file}"
        )
    root = _required_path(manifest.get("root"), "root")
    plan_sha256 = _required_text(manifest.get("plan_sha256"), "plan_sha256")
    review_dir = root / "review"
    media_dir = review_dir / "hybrid-media"
    review_clips: list[dict[str, object]] = []
    key_clips: list[dict[str, object]] = []
    for clip in _mapping_list(manifest.get("clips"), "clips"):
        clip_id = _required_text(clip.get("clip_id"), "clip_id")
        clip_token = safe_display_filename_stem(clip_id, fallback="clip")
        source = _stage_anonymous_audio(
            _verified_output_record(clip.get("source"), "source"),
            media_dir / clip_token / "source.wav",
        )
        shuffled = list(_mapping_list(clip.get("candidates"), "clip candidates"))
        random.Random(f"{plan_sha256}:{REVIEW_TYPE_HYBRID}:{clip_id}").shuffle(
            shuffled
        )
        review_candidates: list[dict[str, object]] = []
        key_candidates: list[dict[str, object]] = []
        for index, candidate in enumerate(shuffled):
            code = chr(ord("A") + index)
            candidate_id = _required_text(
                candidate.get("candidate_id"), "candidate_id"
            )
            review_candidates.append(
                {
                    "code": code,
                    "final_mix": str(
                        _stage_anonymous_audio(
                            _verified_output_record(
                                candidate.get("final_mix"), "final mix"
                            ),
                            media_dir / clip_token / code / "final_mix.wav",
                        )
                    ),
                    "converted_vocals": str(
                        _stage_anonymous_audio(
                            _verified_output_record(
                                candidate.get("converted_vocals"), "converted vocals"
                            ),
                            media_dir / clip_token / code / "converted_vocals.wav",
                        )
                    ),
                    "instrumental": str(
                        _stage_anonymous_audio(
                            _verified_output_record(
                                candidate.get("instrumental"), "instrumental"
                            ),
                            media_dir / clip_token / code / "instrumental.wav",
                        )
                    ),
                }
            )
            key_candidates.append(
                {
                    "code": code,
                    "candidate_id": candidate_id,
                    "candidate_label": candidate.get("label", candidate_id),
                    "recipe_id": (
                        f"vocal={candidate.get('vocal_candidate_id', '')};"
                        f"instrumental={candidate.get('instrumental_candidate_id', '')}"
                    ),
                    "vocal_candidate_id": candidate.get("vocal_candidate_id", ""),
                    "instrumental_candidate_id": candidate.get(
                        "instrumental_candidate_id", ""
                    ),
                }
            )
        review_clips.append(
            {
                "clip_id": clip_id,
                "title": clip.get("title", clip_id),
                "role": clip.get("role", ""),
                "source": str(source),
                "candidates": review_candidates,
            }
        )
        key_clips.append({"clip_id": clip_id, "candidates": key_candidates})

    review_file = review_dir / "hybrid-review.json"
    key_file = review_dir / "hybrid-key.json"
    generated_at = datetime.now(UTC).isoformat()
    write_json_atomic(
        review_file,
        {
            "schema": BLIND_REVIEW_SCHEMA,
            "review_type": REVIEW_TYPE_HYBRID,
            "benchmark_id": manifest.get("benchmark_id", ""),
            "title": manifest.get("title", ""),
            "generated_at": generated_at,
            "hybrid_manifest": str(manifest_file),
            "plan_sha256": plan_sha256,
            "responses": str(review_dir / "hybrid-review-responses.json"),
            "clips": review_clips,
        },
    )
    write_json_atomic(
        key_file,
        {
            "schema": BLIND_REVIEW_KEY_SCHEMA,
            "review_type": REVIEW_TYPE_HYBRID,
            "benchmark_id": manifest.get("benchmark_id", ""),
            "generated_at": generated_at,
            "plan_sha256": plan_sha256,
            "clips": key_clips,
        },
    )
    return review_file, key_file


def _build_review(manifest_path: Path, review_type: str) -> tuple[Path, Path]:
    if review_type not in {REVIEW_TYPE_SEPARATION, REVIEW_TYPE_CONVERSION}:
        raise SeparationBenchmarkReviewError(f"Unsupported review type: {review_type}")
    manifest_file = manifest_path.expanduser().resolve()
    benchmark = _load_json(manifest_file, "benchmark manifest")
    root = _required_path(benchmark.get("root"), "root")
    definition_sha256 = _required_text(
        benchmark.get("definition_sha256"),
        "definition_sha256",
    )
    candidates = _mapping_list(benchmark.get("candidates"), "candidates")
    clips = _mapping_list(benchmark.get("clips"), "clips")
    review_clips: list[dict[str, object]] = []
    key_clips: list[dict[str, object]] = []

    for clip in clips:
        clip_id = _required_text(clip.get("clip_id"), "clip_id")
        shuffled = list(candidates)
        random.Random(f"{definition_sha256}:{review_type}:{clip_id}").shuffle(shuffled)
        review_candidates: list[dict[str, object]] = []
        key_candidates: list[dict[str, object]] = []
        for index, candidate in enumerate(shuffled):
            code = chr(ord("A") + index)
            candidate_id = _required_text(candidate.get("candidate_id"), "candidate_id")
            result_file = (
                root / "results" / candidate_id / clip_id / "benchmark-result.json"
            )
            result = _load_completed_result(result_file, definition_sha256)
            outputs = result["outputs"]
            assert isinstance(outputs, Mapping)
            vocals = _verified_output(outputs, "vocals")
            instrumental = _verified_output(outputs, "instrumental")
            review_candidates.append(
                {
                    "code": code,
                    "vocals": str(vocals),
                    "instrumental": str(instrumental),
                }
            )
            if review_type == REVIEW_TYPE_CONVERSION:
                render_file = result_file.parent / "downstream" / "benchmark-render.json"
                render = _load_completed_render(render_file, definition_sha256)
                render_outputs = render["outputs"]
                assert isinstance(render_outputs, Mapping)
                review_candidates[-1].update(
                    {
                        "converted_vocals": str(
                            _verified_output(render_outputs, "converted_vocals")
                        ),
                        "final_mix": str(_verified_output(render_outputs, "final_mix")),
                    }
                )
            key_candidates.append(
                {
                    "code": code,
                    "candidate_id": candidate_id,
                    "candidate_label": candidate.get("label", candidate_id),
                    "recipe_id": candidate.get("recipe_id", ""),
                }
            )
        review_clips.append(
            {
                "clip_id": clip_id,
                "title": clip.get("title", clip_id),
                "role": clip.get("role", ""),
                "source": clip.get("path", ""),
                "candidates": review_candidates,
            }
        )
        key_clips.append({"clip_id": clip_id, "candidates": key_candidates})

    review_dir = root / "review"
    prefix = "blind" if review_type == REVIEW_TYPE_SEPARATION else "conversion"
    review_file = review_dir / f"{prefix}-review.json"
    key_file = review_dir / f"{prefix}-key.json"
    generated_at = datetime.now(UTC).isoformat()
    write_json_atomic(
        review_file,
        {
            "schema": BLIND_REVIEW_SCHEMA,
            "review_type": review_type,
            "benchmark_id": benchmark.get("benchmark_id", ""),
            "title": benchmark.get("title", ""),
            "generated_at": generated_at,
            "benchmark_manifest": str(manifest_file),
            "definition_sha256": definition_sha256,
            "review_dimensions": benchmark.get("review_dimensions", []),
            "responses": str(review_dir / f"{prefix}-review-responses.json"),
            "clips": review_clips,
        },
    )
    write_json_atomic(
        key_file,
        {
            "schema": BLIND_REVIEW_KEY_SCHEMA,
            "review_type": review_type,
            "benchmark_id": benchmark.get("benchmark_id", ""),
            "generated_at": generated_at,
            "definition_sha256": definition_sha256,
            "clips": key_clips,
        },
    )
    return review_file, key_file


def load_blind_review(path: Path) -> dict[str, object]:
    data = _load_json(path.expanduser().resolve(), "blind review")
    if data.get("schema") != BLIND_REVIEW_SCHEMA:
        raise SeparationBenchmarkReviewError("Unsupported blind review schema.")
    _mapping_list(data.get("clips"), "clips")
    return dict(data)


def load_review_responses(path: Path) -> dict[str, object]:
    target = path.expanduser().resolve()
    if not target.is_file():
        return {
            "schema": BLIND_REVIEW_RESPONSES_SCHEMA,
            "updated_at": "",
            "ratings": {},
            "winners": {},
        }
    data = _load_json(target, "review responses")
    if data.get("schema") not in _SUPPORTED_RESPONSE_SCHEMAS:
        raise SeparationBenchmarkReviewError("Unsupported review response schema.")
    ratings = data.get("ratings")
    if not isinstance(ratings, Mapping):
        data["ratings"] = {}
    migrated = dict(data)
    migrated["schema"] = BLIND_REVIEW_RESPONSES_SCHEMA
    if not isinstance(migrated.get("winners"), Mapping):
        migrated["winners"] = {}
    return migrated


def save_review_responses(path: Path, responses: Mapping[str, object]) -> Path:
    target = path.expanduser().resolve()
    data = dict(responses)
    data["schema"] = BLIND_REVIEW_RESPONSES_SCHEMA
    data["updated_at"] = datetime.now(UTC).isoformat()
    write_json_atomic(target, data)
    return target


def _load_completed_result(path: Path, definition_sha256: str) -> Mapping[str, object]:
    data = _load_json(path, "benchmark result")
    if (
        data.get("status") != "completed"
        or data.get("definition_sha256") != definition_sha256
        or not isinstance(data.get("outputs"), Mapping)
    ):
        raise SeparationBenchmarkReviewError(f"Incomplete benchmark result: {path}")
    return data


def _load_completed_render(path: Path, definition_sha256: str) -> Mapping[str, object]:
    data = _load_json(path, "benchmark review render")
    if (
        data.get("status") != "completed"
        or data.get("definition_sha256") != definition_sha256
        or not isinstance(data.get("outputs"), Mapping)
    ):
        raise SeparationBenchmarkReviewError(f"Incomplete benchmark review render: {path}")
    return data


def _verified_output(outputs: Mapping[str, object], name: str) -> Path:
    return _verified_output_record(outputs.get(name), name)


def _verified_output_record(value: object, name: str) -> Path:
    if not isinstance(value, Mapping):
        raise SeparationBenchmarkReviewError(f"Missing benchmark output: {name}")
    path = _required_path(value.get("path"), f"{name} path")
    expected_hash = _required_text(value.get("sha256"), f"{name} sha256")
    if not path.is_file() or file_sha256(path) != expected_hash:
        raise SeparationBenchmarkReviewError(f"Benchmark output changed: {path}")
    return path


def _stage_anonymous_audio(source: Path, target: Path) -> Path:
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
        raise SeparationBenchmarkReviewError(
            f"Could not stage anonymous review audio: {target}"
        )
    return target


def _load_json(path: Path, label: str) -> dict[str, object]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SeparationBenchmarkReviewError(f"Could not read {label}: {path}") from exc
    if not isinstance(data, dict):
        raise SeparationBenchmarkReviewError(f"Invalid {label}: {path}")
    return data


def _mapping_list(value: object, label: str) -> tuple[Mapping[str, object], ...]:
    if not isinstance(value, list) or not value:
        raise SeparationBenchmarkReviewError(f"Review {label} must be a non-empty list.")
    if not all(isinstance(item, Mapping) for item in value):
        raise SeparationBenchmarkReviewError(f"Review {label} contains invalid items.")
    return tuple(value)  # type: ignore[return-value]


def _required_text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SeparationBenchmarkReviewError(f"Review {label} is required.")
    return value.strip()


def _required_path(value: object, label: str) -> Path:
    return Path(_required_text(value, label)).expanduser().resolve()
