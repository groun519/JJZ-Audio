from __future__ import annotations

import json
from collections import Counter
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path

from jang_app.services.managed_files import write_json_atomic
from jang_app.services.separation_benchmark_review import SeparationBenchmarkReviewError


SEPARATION_REVIEW_ANALYSIS_SCHEMA = 1
_ISSUE_POINTS = {"none": 0, "some": 1, "severe": 2}
_DECISION_POINTS = {"keep": 0, "repair": 1, "reject": 2}
_SEPARATION_STEM_ISSUES = {
    "vocals": (
        "vocal_missing",
        "vocal_unwanted_sound",
        "vocal_effect_residue",
        "vocal_damage",
    ),
    "instrumental": (
        "instrumental_vocal_residue",
        "instrumental_effect_residue",
        "instrumental_damage",
        "instrumental_artifacts",
    ),
}
_CONVERSION_STEM_ISSUES = {
    "converted_vocals": (
        "converted_missing",
        "converted_pitch",
        "converted_timbre",
        "converted_artifacts",
    ),
    "final_mix": (
        "mix_original_vocal",
        "mix_vocal_clarity",
        "mix_balance",
        "mix_naturalness",
    ),
}
_HYBRID_STEM_ISSUES = {
    "final_mix": (
        "mix_original_vocal",
        "mix_vocal_clarity",
        "mix_balance",
        "mix_naturalness",
    ),
}


def analyze_separation_review(
    key_path: Path,
    responses_path: Path,
    output_dir: Path | None = None,
) -> tuple[Path, Path]:
    return _analyze_review(
        key_path,
        responses_path,
        output_dir,
        review_type="separation",
        stem_issues=_SEPARATION_STEM_ISSUES,
        output_prefix="blind",
    )


def analyze_conversion_review(
    key_path: Path,
    responses_path: Path,
    output_dir: Path | None = None,
) -> tuple[Path, Path]:
    return _analyze_review(
        key_path,
        responses_path,
        output_dir,
        review_type="conversion",
        stem_issues=_CONVERSION_STEM_ISSUES,
        output_prefix="conversion",
    )


def analyze_hybrid_review(
    key_path: Path,
    responses_path: Path,
    output_dir: Path | None = None,
) -> tuple[Path, Path]:
    return _analyze_review(
        key_path,
        responses_path,
        output_dir,
        review_type="hybrid",
        stem_issues=_HYBRID_STEM_ISSUES,
        output_prefix="hybrid",
    )


def _analyze_review(
    key_path: Path,
    responses_path: Path,
    output_dir: Path | None,
    *,
    review_type: str,
    stem_issues: Mapping[str, tuple[str, ...]],
    output_prefix: str,
) -> tuple[Path, Path]:
    key_file = key_path.expanduser().resolve()
    responses_file = responses_path.expanduser().resolve()
    key = _load_json(key_file, "blind review key")
    responses = _load_json(responses_file, "blind review responses")
    clips = _mapping_list(key.get("clips"), "key clips")
    ratings = _required_mapping(responses.get("ratings"), "ratings")
    winners = _required_mapping(responses.get("winners"), "winners")

    expected_ratings = sum(
        len(_mapping_list(clip.get("candidates"), "clip candidates"))
        for clip in clips
    )
    if len(ratings) != expected_ratings:
        raise SeparationBenchmarkReviewError(
            f"Review is incomplete: {len(ratings)} of {expected_ratings} ratings saved."
        )
    if len(winners) != len(clips):
        raise SeparationBenchmarkReviewError(
            f"Review is incomplete: {len(winners)} of {len(clips)} winners saved."
        )

    candidate_totals: dict[str, dict[str, object]] = {}
    clip_results: list[dict[str, object]] = []
    for clip in clips:
        clip_id = _required_text(clip.get("clip_id"), "clip_id")
        candidate_keys = _candidate_lookup(clip)
        selected_code = _required_text(winners.get(clip_id), f"winner for {clip_id}")
        if selected_code not in candidate_keys:
            raise SeparationBenchmarkReviewError(
                f"Unknown winner code for {clip_id}: {selected_code}"
            )

        candidates: list[dict[str, object]] = []
        for code, identity in candidate_keys.items():
            rating_key = f"{clip_id}:{code}"
            rating = ratings.get(rating_key)
            if not isinstance(rating, Mapping):
                raise SeparationBenchmarkReviewError(f"Missing rating: {rating_key}")
            candidate_result = _analyze_candidate(identity, rating, stem_issues)
            candidates.append(candidate_result)
            _merge_candidate_total(candidate_totals, candidate_result, stem_issues)

        selected = _identity_record(candidate_keys[selected_code])
        selected_id = str(selected["candidate_id"])
        stem_recommendations = {
            stem: _recommend_stem(
                candidates,
                stem,
                preferred_candidate_id=selected_id,
            )
            for stem in stem_issues
        }
        _candidate_total(candidate_totals, selected, stem_issues)["overall_wins"] = int(
            _candidate_total(candidate_totals, selected, stem_issues)["overall_wins"]
        ) + 1
        clip_results.append(
            {
                "clip_id": clip_id,
                "selected_winner": selected,
                "stem_recommendations": stem_recommendations,
                "hybrid_recommended": any(
                    item["candidate_id"] != selected_id
                    for item in stem_recommendations.values()
                )
                or len(
                    {
                        item["candidate_id"] for item in stem_recommendations.values()
                    }
                )
                > 1,
                "candidates": candidates,
            }
        )

    summaries = [
        _finalize_candidate_total(value, stem_issues)
        for value in candidate_totals.values()
    ]
    summaries.sort(key=lambda item: str(item["candidate_label"]).casefold())
    analysis = {
        "schema": SEPARATION_REVIEW_ANALYSIS_SCHEMA,
        "review_type": review_type,
        "benchmark_id": key.get("benchmark_id", ""),
        "analyzed_at": datetime.now(UTC).isoformat(),
        "source": {"key": str(key_file), "responses": str(responses_file)},
        "complete": True,
        "rating_count": len(ratings),
        "clip_count": len(clips),
        "clip_results": clip_results,
        "candidate_summary": summaries,
    }
    destination = (output_dir or responses_file.parent).expanduser().resolve()
    destination.mkdir(parents=True, exist_ok=True)
    json_path = destination / f"{output_prefix}-review-analysis.json"
    markdown_path = destination / f"{output_prefix}-review-analysis.md"
    write_json_atomic(json_path, analysis)
    markdown_path.write_text(_render_markdown(analysis), encoding="utf-8")
    return json_path, markdown_path


def _analyze_candidate(
    identity: Mapping[str, object],
    rating: Mapping[str, object],
    stem_issues: Mapping[str, tuple[str, ...]],
) -> dict[str, object]:
    issues = _required_mapping(rating.get("issues"), "rating issues")
    decisions = _required_mapping(rating.get("decisions"), "rating decisions")
    stems: dict[str, object] = {}
    for stem, issue_names in stem_issues.items():
        values = [
            _required_choice(issues.get(name), _ISSUE_POINTS, name)
            for name in issue_names
        ]
        decision = _required_choice(decisions.get(stem), _DECISION_POINTS, stem)
        stems[stem] = {
            "decision": decision,
            "issue_points": sum(_ISSUE_POINTS[value] for value in values),
            "severe_count": values.count("severe"),
            "some_count": values.count("some"),
            "issues": {name: value for name, value in zip(issue_names, values, strict=True)},
        }
    return {
        **_identity_record(identity),
        "stems": stems,
        "notes": str(rating.get("notes", "")).strip(),
    }


def _recommend_stem(
    candidates: list[dict[str, object]],
    stem: str,
    *,
    preferred_candidate_id: str,
) -> dict[str, object]:
    def rank(candidate: dict[str, object]) -> tuple[int, int, int, int, int, str]:
        stem_result = _required_mapping(
            _required_mapping(candidate.get("stems"), "candidate stems").get(stem),
            stem,
        )
        decision = _required_text(stem_result.get("decision"), "decision")
        return (
            _DECISION_POINTS[decision],
            int(stem_result["issue_points"]),
            int(stem_result["severe_count"]),
            int(stem_result["some_count"]),
            0 if str(candidate["candidate_id"]) == preferred_candidate_id else 1,
            str(candidate["candidate_id"]),
        )

    selected = min(candidates, key=rank)
    stem_result = _required_mapping(
        _required_mapping(selected.get("stems"), "candidate stems").get(stem), stem
    )
    return {**_identity_record(selected), **dict(stem_result)}


def _merge_candidate_total(
    totals: dict[str, dict[str, object]],
    candidate: Mapping[str, object],
    stem_issues: Mapping[str, tuple[str, ...]],
) -> None:
    total = _candidate_total(totals, candidate, stem_issues)
    stems = _required_mapping(candidate.get("stems"), "candidate stems")
    for stem in stem_issues:
        result = _required_mapping(stems.get(stem), stem)
        stem_total = _required_mapping(total["stems"], "total stems")[stem]
        assert isinstance(stem_total, dict)
        stem_total["issue_points"] = int(stem_total["issue_points"]) + int(
            result["issue_points"]
        )
        stem_total["severe_count"] = int(stem_total["severe_count"]) + int(
            result["severe_count"]
        )
        decisions = stem_total["decisions"]
        assert isinstance(decisions, Counter)
        decisions.update([str(result["decision"])])


def _candidate_total(
    totals: dict[str, dict[str, object]],
    identity: Mapping[str, object],
    stem_issues: Mapping[str, tuple[str, ...]],
) -> dict[str, object]:
    candidate_id = _required_text(identity.get("candidate_id"), "candidate_id")
    if candidate_id not in totals:
        totals[candidate_id] = {
            **_identity_record(identity),
            "overall_wins": 0,
            "stems": {
                stem: {
                    "issue_points": 0,
                    "severe_count": 0,
                    "decisions": Counter(),
                }
                for stem in stem_issues
            },
        }
    else:
        identity_record = _identity_record(identity)
        for key in ("recipe_id", "vocal_candidate_id", "instrumental_candidate_id"):
            incoming = identity_record.get(key, "")
            if incoming and totals[candidate_id].get(key) != incoming:
                totals[candidate_id][key] = "varies"
    return totals[candidate_id]


def _finalize_candidate_total(
    total: dict[str, object], stem_issues: Mapping[str, tuple[str, ...]]
) -> dict[str, object]:
    result = dict(total)
    stems = _required_mapping(result.get("stems"), "total stems")
    result["stems"] = {
        stem: {
            **dict(_required_mapping(stems.get(stem), stem)),
            "decisions": dict(
                _required_mapping(stems.get(stem), stem).get("decisions", {})
            ),
        }
        for stem in stem_issues
    }
    return result


def _candidate_lookup(clip: Mapping[str, object]) -> dict[str, Mapping[str, object]]:
    result: dict[str, Mapping[str, object]] = {}
    for candidate in _mapping_list(clip.get("candidates"), "clip candidates"):
        code = _required_text(candidate.get("code"), "candidate code")
        result[code] = candidate
    return result


def _identity_record(identity: Mapping[str, object]) -> dict[str, str]:
    candidate_id = _required_text(identity.get("candidate_id"), "candidate_id")
    record = {
        "candidate_id": candidate_id,
        "candidate_label": str(identity.get("candidate_label", candidate_id)),
        "recipe_id": str(identity.get("recipe_id", "")),
    }
    for key in ("vocal_candidate_id", "instrumental_candidate_id"):
        value = str(identity.get(key, "")).strip()
        if value:
            record[key] = value
    return record


def _render_markdown(analysis: Mapping[str, object]) -> str:
    clips = _mapping_list(analysis.get("clip_results"), "clip results")
    summaries = _mapping_list(analysis.get("candidate_summary"), "candidate summary")
    review_type = str(analysis.get("review_type", "separation"))
    if review_type == "conversion":
        stem_labels = {
            "converted_vocals": "Converted vocals",
            "final_mix": "Final mix",
        }
        report_title = "# Blind Conversion Review Analysis"
    elif review_type == "hybrid":
        stem_labels = {"final_mix": "Final mix"}
        report_title = "# Blind Hybrid Review Analysis"
    else:
        stem_labels = {"vocals": "Vocals", "instrumental": "Instrumental"}
        report_title = "# Blind Separation Review Analysis"
    stem_names = tuple(stem_labels)
    lines = [
        report_title,
        "",
        f"Benchmark: `{analysis.get('benchmark_id', '')}`  ",
        f"Ratings: {analysis.get('rating_count', 0)} across {analysis.get('clip_count', 0)} clips",
        "",
        "## Clip Results",
        "",
        "| Clip | Selected winner | "
        + " | ".join(f"Recommended {stem_labels[name].lower()}" for name in stem_names)
        + " | Cross-candidate |",
        "| --- | --- | " + " | ".join("---" for _name in stem_names) + " | --- |",
    ]
    for clip in clips:
        selected = _required_mapping(clip.get("selected_winner"), "selected winner")
        recommendations = _required_mapping(
            clip.get("stem_recommendations"), "stem recommendations"
        )
        recommended = [
            _required_mapping(recommendations.get(stem), stem) for stem in stem_names
        ]
        lines.append(
            "| "
            + str(clip.get("clip_id", ""))
            + " | "
            + _display_candidate(selected, review_type)
            + " | "
            + " | ".join(
                _display_candidate(item, review_type) for item in recommended
            )
            + " | "
            + ("Yes" if clip.get("hybrid_recommended") else "No")
            + " |"
        )
    notes_written = False
    for clip in clips:
        candidates = _mapping_list(clip.get("candidates"), "clip candidates")
        candidates_with_notes = [
            candidate for candidate in candidates if str(candidate.get("notes", "")).strip()
        ]
        if not candidates_with_notes:
            continue
        if not notes_written:
            lines.extend(["", "## Reviewer Notes", ""])
            notes_written = True
        lines.append(f"### {clip.get('clip_id', '')}")
        lines.append("")
        for candidate in candidates_with_notes:
            note = str(candidate.get("notes", "")).strip().replace("\n", "<br>")
            lines.append(
                f"- **{_display_candidate(candidate, review_type)}:** {note}"
            )
        lines.append("")
    lines.extend(
        [
            "",
            "## Candidate Summary",
            "",
            "Issue points are descriptive only: none=0, some=1, severe=2. Lower is better.",
            "",
            "| Candidate | Wins | "
            + " | ".join(
                f"{stem_labels[name]} issues | {stem_labels[name]} decisions"
                for name in stem_names
            )
            + " |",
            "| --- | ---: | "
            + " | ".join("---: | ---" for _name in stem_names)
            + " |",
        ]
    )
    for summary in summaries:
        stems = _required_mapping(summary.get("stems"), "summary stems")
        stem_results = [
            _required_mapping(stems.get(stem), stem) for stem in stem_names
        ]
        lines.append(
            "| "
            + str(summary.get("candidate_label", ""))
            + " | "
            + str(summary.get("overall_wins", 0))
            + " | "
            + " | ".join(
                f"{result.get('issue_points', 0)} | {_format_decisions(result.get('decisions'))}"
                for result in stem_results
            )
            + " |"
        )
    lines.append("")
    return "\n".join(lines)


def _format_decisions(value: object) -> str:
    decisions = _required_mapping(value, "decisions")
    return ", ".join(
        f"{name} {int(decisions.get(name, 0))}" for name in ("keep", "repair", "reject")
    )


def _display_candidate(candidate: Mapping[str, object], review_type: str) -> str:
    label = str(candidate.get("candidate_label", ""))
    if review_type != "hybrid":
        return label
    vocal = str(candidate.get("vocal_candidate_id", "")).strip()
    instrumental = str(candidate.get("instrumental_candidate_id", "")).strip()
    if not vocal or not instrumental:
        return label
    return f"{label} (`{vocal}` + `{instrumental}`)"


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
        raise SeparationBenchmarkReviewError(f"{label} must be a non-empty list.")
    if not all(isinstance(item, Mapping) for item in value):
        raise SeparationBenchmarkReviewError(f"{label} contains invalid items.")
    return tuple(value)  # type: ignore[return-value]


def _required_mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise SeparationBenchmarkReviewError(f"{label} must be an object.")
    return value


def _required_text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SeparationBenchmarkReviewError(f"{label} is required.")
    return value.strip()


def _required_choice(
    value: object, choices: Mapping[str, int], label: str
) -> str:
    text = _required_text(value, label)
    if text not in choices:
        raise SeparationBenchmarkReviewError(f"Unsupported {label}: {text}")
    return text
