from __future__ import annotations

import argparse
import json
from pathlib import Path

from audio_separator.separator import Separator


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run a local RoFormer checkpoint and YAML without a registry entry."
    )
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--overlap", type=int, default=8)
    args = parser.parse_args()

    source = args.input.expanduser().resolve()
    checkpoint = args.checkpoint.expanduser().resolve()
    config = args.config.expanduser().resolve()
    output_dir = args.output_dir.expanduser().resolve()
    for path in (source, checkpoint, config):
        if not path.is_file():
            raise FileNotFoundError(path)
    output_dir.mkdir(parents=True, exist_ok=True)

    separator = Separator(
        model_file_dir=str(checkpoint.parent),
        output_dir=str(output_dir),
        output_format="WAV",
        sample_rate=44_100,
        mdxc_params={
            "segment_size": 256,
            "batch_size": 1,
            "overlap": max(2, args.overlap),
        },
    )
    separator.download_model_files = lambda _filename: (
        checkpoint.name,
        "MDXC",
        checkpoint.stem,
        str(checkpoint),
        str(config),
    )
    separator.load_model(checkpoint.name)
    _patch_single_target_roformer(separator.model_instance)
    outputs = separator.separate(str(source))
    report = {
        "schema": 1,
        "source": str(source),
        "checkpoint": str(checkpoint),
        "config": str(config),
        "outputs": [str(output_dir / output) for output in outputs],
    }
    (output_dir / "candidate.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


def _patch_single_target_roformer(model_instance: object) -> None:
    config = getattr(model_instance, "model_data_cfgdict", None)
    if config is None or not getattr(model_instance, "is_roformer", False):
        return
    target = str(config.training.target_instrument or "")
    if not target:
        return
    original_demix = model_instance.demix

    def compatible_demix(mix):
        result = original_demix(mix)
        if isinstance(result, dict):
            return result
        primary = str(getattr(model_instance, "primary_stem_name", target))
        secondary = str(
            getattr(
                model_instance,
                "secondary_stem_name",
                "Vocals" if primary.casefold() != "vocals" else "Instrumental",
            )
        )
        return {primary: result, secondary: mix - result}

    model_instance.demix = compatible_demix


if __name__ == "__main__":
    raise SystemExit(main())
