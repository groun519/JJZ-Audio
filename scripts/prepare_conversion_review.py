from __future__ import annotations

import argparse
from pathlib import Path

from jang_app.services.separation_benchmark_review import build_conversion_review


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build a blind RVC conversion and final-mix review pack."
    )
    parser.add_argument("manifest", type=Path)
    args = parser.parse_args()
    review, key = build_conversion_review(args.manifest)
    print(f"Conversion review: {review}")
    print(f"Hidden key: {key}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
