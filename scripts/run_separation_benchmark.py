from __future__ import annotations

import argparse
from pathlib import Path

from jang_app.services.separation_benchmark_runner import run_prepared_benchmark


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run a prepared JJZero Audio separation benchmark sequentially."
    )
    parser.add_argument("manifest", type=Path)
    parser.add_argument(
        "--candidate",
        action="append",
        default=[],
        help="Run one candidate ID. Repeat to set the execution order.",
    )
    parser.add_argument(
        "--clip",
        action="append",
        default=[],
        help="Run one clip ID. Repeat to set the execution order.",
    )
    parser.add_argument("--restart", action="store_true", help="Re-run completed items.")
    parser.add_argument("--continue-on-error", action="store_true")
    args = parser.parse_args()

    def report(
        candidate_id: str,
        clip_id: str,
        percent: int,
        completed: int,
        total: int,
    ) -> None:
        print(
            f"[{completed + 1}/{total}] {candidate_id} / {clip_id}: {percent}%",
            flush=True,
        )

    result = run_prepared_benchmark(
        args.manifest,
        candidate_ids=args.candidate,
        clip_ids=args.clip,
        resume=not args.restart,
        continue_on_error=args.continue_on_error,
        progress=report,
    )
    print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
