from __future__ import annotations

import argparse
from pathlib import Path

from jang_app.services.separation_incremental_analysis import (
    analyze_incremental_review,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Analyze a completed baseline-anchored separation review."
    )
    parser.add_argument("key", type=Path)
    parser.add_argument("responses", type=Path)
    args = parser.parse_args()
    analysis, report = analyze_incremental_review(args.key, args.responses)
    print(f"Analysis JSON: {analysis}")
    print(f"Analysis report: {report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
