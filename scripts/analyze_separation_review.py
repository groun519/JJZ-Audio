from __future__ import annotations

import argparse
from pathlib import Path

from jang_app.services.separation_benchmark_analysis import (
    analyze_conversion_review,
    analyze_hybrid_review,
    analyze_separation_review,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Analyze a completed blind separation review.")
    parser.add_argument("review_dir", type=Path, help="Directory containing the review files.")
    parser.add_argument(
        "--type",
        choices=("separation", "conversion", "hybrid"),
        default="separation",
    )
    args = parser.parse_args()
    review_dir = args.review_dir.expanduser().resolve()
    analyzers = {
        "separation": analyze_separation_review,
        "conversion": analyze_conversion_review,
        "hybrid": analyze_hybrid_review,
    }
    prefixes = {"separation": "blind", "conversion": "conversion", "hybrid": "hybrid"}
    analyzer = analyzers[args.type]
    prefix = prefixes[args.type]
    json_path, markdown_path = analyzer(
        review_dir / f"{prefix}-key.json",
        review_dir / f"{prefix}-review-responses.json",
        review_dir,
    )
    print(f"Analysis JSON: {json_path}")
    print(f"Analysis report: {markdown_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
