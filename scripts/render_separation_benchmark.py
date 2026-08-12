from __future__ import annotations

import argparse
from pathlib import Path

from jang_app.services.separation_benchmark_render import render_prepared_benchmark


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Render fixed RVC conversions and mixes for a separation benchmark."
    )
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--candidate", action="append", default=[])
    parser.add_argument("--clip", action="append", default=[])
    parser.add_argument("--no-resume", action="store_true")
    parser.add_argument("--continue-on-error", action="store_true")
    args = parser.parse_args()

    def report(candidate: str, clip: str, stage: str, completed: int, total: int) -> None:
        print(f"[{completed}/{total}] {candidate}/{clip}: {stage}", flush=True)

    progress = render_prepared_benchmark(
        args.manifest,
        candidate_ids=tuple(args.candidate),
        clip_ids=tuple(args.clip),
        resume=not args.no_resume,
        continue_on_error=args.continue_on_error,
        progress=report,
    )
    print(f"Render progress: {progress}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
