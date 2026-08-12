from __future__ import annotations

import argparse
from pathlib import Path

from jang_app.services.separation_benchmark_review import build_hybrid_review


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build a blind final-mix review from rendered hybrid candidates."
    )
    parser.add_argument("hybrid_manifest", type=Path)
    args = parser.parse_args()
    review, key = build_hybrid_review(args.hybrid_manifest)
    print(f"Hybrid review: {review}")
    print(f"Hidden key: {key}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
