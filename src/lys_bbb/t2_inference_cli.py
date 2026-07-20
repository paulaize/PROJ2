"""Command-line entry point for the inference-only T2 release adapter."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from lys_bbb.t2_inference import run_frozen_t2_ensemble
from lys_bbb.t2_model_release import validate_frozen_t2_model_release


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release", required=True, type=Path)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--work", required=True, type=Path)
    parser.add_argument(
        "--device", choices=("auto", "mps", "cuda", "cpu"), default="auto"
    )
    args = parser.parse_args()
    scans = {path.parent.name: path for path in sorted(args.input.rglob("scan.nii.gz"))}
    release = validate_frozen_t2_model_release(args.release)
    output = run_frozen_t2_ensemble(
        release,
        scans,
        work_root=args.work,
        output_root=args.output,
        device_name=args.device,
    )
    print(
        json.dumps(
            {
                "release_id": output.release_id,
                "device": output.device,
                "n_cases": len(output.cases),
                "summary": str(output.summary_path),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
