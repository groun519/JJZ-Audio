from __future__ import annotations

import argparse
from pathlib import Path

from jang_app.services.separation_incremental_review import build_incremental_review


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Prepare a baseline-anchored incremental separation review."
    )
    parser.add_argument("challenger_manifest", type=Path)
    parser.add_argument("--baseline-manifest", type=Path, required=True)
    parser.add_argument("--baseline-vocal", required=True)
    parser.add_argument(
        "--baseline-instrumental",
        action="append",
        default=[],
        metavar="CLIP=CANDIDATE",
    )
    parser.add_argument("--challenger", action="append", default=[])
    args = parser.parse_args()
    instrumental = dict(_parse_assignment(value) for value in args.baseline_instrumental)
    review, key = build_incremental_review(
        args.challenger_manifest,
        args.baseline_manifest,
        baseline_vocal_candidate_id=args.baseline_vocal,
        baseline_instrumental_candidate_ids=instrumental,
        challenger_candidate_ids=tuple(args.challenger),
    )
    print(f"Incremental review: {review}")
    print(f"Hidden key: {key}")
    return 0


def _parse_assignment(value: str) -> tuple[str, str]:
    clip_id, separator, candidate_id = value.partition("=")
    if not separator or not clip_id.strip() or not candidate_id.strip():
        raise argparse.ArgumentTypeError(f"Invalid assignment: {value}")
    return clip_id.strip(), candidate_id.strip()


if __name__ == "__main__":
    raise SystemExit(main())
