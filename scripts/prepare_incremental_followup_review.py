from __future__ import annotations

import argparse
from pathlib import Path

from jang_app.services.separation_incremental_followup import (
    build_incremental_followup,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build a focused RVC follow-up for advancing separation candidates."
    )
    parser.add_argument("challenger_manifest", type=Path)
    parser.add_argument("--baseline-manifest", type=Path, required=True)
    parser.add_argument("--analysis", type=Path, required=True)
    args = parser.parse_args()
    result, review, key = build_incremental_followup(
        args.challenger_manifest,
        args.baseline_manifest,
        args.analysis,
    )
    print(f"Follow-up result: {result}")
    print(f"Follow-up review: {review}")
    print(f"Hidden key: {key}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
