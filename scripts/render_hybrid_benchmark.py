from __future__ import annotations

import argparse
from pathlib import Path

from jang_app.services.separation_benchmark_hybrid import render_hybrid_benchmark


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Render final mixes for a hybrid separation comparison."
    )
    parser.add_argument("manifest", type=Path)
    parser.add_argument("plan", type=Path)
    args = parser.parse_args()
    result = render_hybrid_benchmark(args.manifest, args.plan)
    print(f"Hybrid benchmark: {result}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
