from __future__ import annotations

import argparse
from pathlib import Path

from jang_app.services.separation_quality import measure_separation_quality, save_quality_report


def main() -> None:
    parser = argparse.ArgumentParser(description="Measure JJZero separation quality against reference stems.")
    parser.add_argument("reference_vocals", type=Path)
    parser.add_argument("reference_instrumental", type=Path)
    parser.add_argument("estimated_vocals", type=Path)
    parser.add_argument("estimated_instrumental", type=Path)
    parser.add_argument("--output", type=Path, default=Path("separation-quality.json"))
    args = parser.parse_args()

    report = measure_separation_quality(
        args.reference_vocals,
        args.reference_instrumental,
        args.estimated_vocals,
        args.estimated_instrumental,
    )
    output = save_quality_report(args.output, report)
    print(f"Mean SI-SDR: {report.mean_si_sdr_db:.2f} dB")
    print(f"Vocals SI-SDR: {report.vocals.si_sdr_db:.2f} dB")
    print(f"Instrumental SI-SDR: {report.instrumental.si_sdr_db:.2f} dB")
    print(f"Mixture residual RMS: {report.mixture_residual_rms:.8f}")
    print(output)


if __name__ == "__main__":
    main()
