from __future__ import annotations

import json
from collections import Counter
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path

from jang_app.services.managed_files import write_json_atomic
from jang_app.services.separation_incremental_review import (
    COMPARISON_VALUES,
    IncrementalSeparationReviewError,
    load_incremental_responses,
)


INCREMENTAL_ANALYSIS_SCHEMA = 1


def analyze_incremental_review(
    key_path: Path,
    responses_path: Path,
    output_dir: Path | None = None,
) -> tuple[Path, Path]:
    key_file = key_path.expanduser().resolve()
    responses_file = responses_path.expanduser().resolve()
    key = _load_json(key_file, "incremental key")
    if key.get("schema") != 1 or key.get("review_type") != "incremental-separation":
        raise IncrementalSeparationReviewError("Unsupported incremental review key.")
    responses = load_incremental_responses(responses_file)
    comparisons = _mapping(responses.get("comparisons"), "comparisons")
    notes = _mapping(responses.get("notes"), "notes")

    clip_results: list[dict[str, object]] = []
    summary: dict[str, Counter[str]] = {}
    expected_keys: set[str] = set()
    for clip in _mapping_list(key.get("clips"), "clips"):
        clip_id = _required_text(clip.get("clip_id"), "clip_id")
        stages = _mapping(clip.get("stages"), f"{clip_id} stages")
        stage_results: dict[str, object] = {}
        for stage, stage_value in stages.items():
            stage_data = _mapping(stage_value, f"{clip_id} {stage}")
            candidates = _mapping_list(
                stage_data.get("candidates"), f"{clip_id} {stage} candidates"
            )
            reference = candidates[0]
            if reference.get("code") != "A" or reference.get("role") != "reference":
                raise IncrementalSeparationReviewError(
                    f"Invalid reference for {clip_id}:{stage}."
                )
            decisions: list[dict[str, object]] = []
            advancing: list[dict[str, object]] = []
            for candidate in candidates[1:]:
                code = _required_text(candidate.get("code"), "candidate code")
                response_key = f"{clip_id}:{stage}:{code}"
                expected_keys.add(response_key)
                decision = comparisons.get(response_key)
                if decision not in COMPARISON_VALUES:
                    continue
                row = {
                    "code": code,
                    "candidate_id": _required_text(
                        candidate.get("candidate_id"), "candidate_id"
                    ),
                    "candidate_label": candidate.get("candidate_label", ""),
                    "decision": decision,
                }
                decisions.append(row)
                summary.setdefault(row["candidate_id"], Counter())[str(decision)] += 1
                if decision == "better":
                    advancing.append(row)
            stage_results[str(stage)] = {
                "reference": {
                    "candidate_id": _required_text(
                        reference.get("candidate_id"), "reference candidate_id"
                    ),
                    "candidate_label": reference.get("candidate_label", ""),
                },
                "decisions": decisions,
                "advancing": advancing,
                "selected_candidate_id": (
                    advancing[0]["candidate_id"]
                    if len(advancing) == 1
                    else _required_text(
                        reference.get("candidate_id"), "reference candidate_id"
                    )
                    if not advancing
                    else ""
                ),
                "note": str(notes.get(f"{clip_id}:{stage}", "")),
            }
        clip_results.append({"clip_id": clip_id, "stages": stage_results})

    missing = sorted(
        response_key
        for response_key in expected_keys
        if comparisons.get(response_key) not in COMPARISON_VALUES
    )
    unexpected = sorted(set(comparisons) - expected_keys)
    if missing:
        raise IncrementalSeparationReviewError(
            f"Incremental review is incomplete: {len(missing)} decisions missing."
        )
    if unexpected:
        raise IncrementalSeparationReviewError(
            f"Incremental review contains unknown decisions: {unexpected[0]}"
        )

    target_dir = (
        output_dir.expanduser().resolve()
        if output_dir is not None
        else responses_file.parent
    )
    json_path = target_dir / "incremental-review-analysis.json"
    markdown_path = target_dir / "incremental-review-analysis.md"
    analysis = {
        "schema": INCREMENTAL_ANALYSIS_SCHEMA,
        "review_type": "incremental-separation",
        "benchmark_id": key.get("benchmark_id", ""),
        "analyzed_at": datetime.now(UTC).isoformat(),
        "source": {"key": str(key_file), "responses": str(responses_file)},
        "complete": True,
        "decision_count": len(expected_keys),
        "clip_results": clip_results,
        "candidate_summary": [
            {
                "candidate_id": candidate_id,
                "better": counts["better"],
                "same": counts["same"],
                "worse": counts["worse"],
            }
            for candidate_id, counts in sorted(summary.items())
        ],
    }
    write_json_atomic(json_path, analysis)
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.write_text(_markdown_report(analysis), encoding="utf-8")
    return json_path, markdown_path


def _markdown_report(analysis: Mapping[str, object]) -> str:
    lines = [
        "# Incremental Separation Review",
        "",
        f"- Decisions: {analysis.get('decision_count', 0)}",
        "- Advancement rule: only `better` advances to the RVC follow-up.",
        "",
        "| Clip | Stage | Reference | Advancing candidate |",
        "| --- | --- | --- | --- |",
    ]
    for clip in _mapping_list(analysis.get("clip_results"), "clip_results"):
        clip_id = _required_text(clip.get("clip_id"), "clip_id")
        stages = _mapping(clip.get("stages"), "stages")
        for stage, value in stages.items():
            stage_data = _mapping(value, "stage")
            reference = _mapping(stage_data.get("reference"), "reference")
            advancing = _mapping_list_allow_empty(stage_data.get("advancing"))
            advancing_text = ", ".join(
                _required_text(item.get("candidate_id"), "candidate_id")
                for item in advancing
            ) or "-"
            lines.append(
                f"| {clip_id} | {stage} | {reference.get('candidate_id', '')} | "
                f"{advancing_text} |"
            )
    lines.extend(["", "## Candidate Summary", ""])
    for candidate in _mapping_list(
        analysis.get("candidate_summary"), "candidate_summary"
    ):
        lines.append(
            f"- `{candidate.get('candidate_id', '')}`: "
            f"better {candidate.get('better', 0)}, "
            f"same {candidate.get('same', 0)}, "
            f"worse {candidate.get('worse', 0)}"
        )
    return "\n".join(lines) + "\n"


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
