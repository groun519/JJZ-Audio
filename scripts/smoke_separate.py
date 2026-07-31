from __future__ import annotations

import argparse
from pathlib import Path

from jang_app.config import SEPARATION_OUTPUT_DIR
from jang_app.pipeline.separate import separate_audio


def main() -> None:
    parser = argparse.ArgumentParser(description="Run one source-separation smoke test.")
    parser.add_argument("input", type=Path, help="Audio file to separate.")
    parser.add_argument("--output", type=Path, default=SEPARATION_OUTPUT_DIR, help="Output root directory.")
    args = parser.parse_args()

    result = separate_audio(args.input, args.output)
    print(f"Job folder: {result.job_dir}")
    print(f"Vocals: {result.vocals_path}")
    print(f"Instrumental: {result.accompaniment_path}")


if __name__ == "__main__":
    main()
