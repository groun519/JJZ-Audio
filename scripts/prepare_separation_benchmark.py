from __future__ import annotations

import argparse
from pathlib import Path

from jang_app.services.separation_benchmark import prepare_benchmark
from jang_app.services.settings import load_app_settings


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Prepare fixed audio clips for a JJZero Audio separation benchmark."
    )
    parser.add_argument("--definition", type=Path, required=True)
    parser.add_argument("--workspace-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument(
        "--source",
        action="append",
        default=[],
        metavar="KEY=PATH",
        help="Resolve an external benchmark source without storing it in the definition.",
    )
    args = parser.parse_args()
    overrides = dict(_parse_source(value) for value in args.source)
    manifest = prepare_benchmark(
        args.definition,
        args.workspace_root,
        args.output_root,
        load_app_settings().rvc,
        source_overrides=overrides,
    )
    print(manifest)
    return 0


def _parse_source(value: str) -> tuple[str, Path]:
    key, separator, path = value.partition("=")
    if not separator or not key.strip() or not path.strip():
        raise argparse.ArgumentTypeError(f"Invalid source override: {value}")
    return key.strip(), Path(path.strip())


if __name__ == "__main__":
    raise SystemExit(main())
