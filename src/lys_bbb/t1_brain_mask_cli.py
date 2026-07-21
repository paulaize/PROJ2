"""Generate one local automatic T1 brain-mask draft for mandatory human review."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from lys_bbb.t1_brain_mask import (
    build_t1_brain_mask_draft,
    run_local_t1_brain_mask,
)
from lys_bbb.t1_brain_mask_release import validate_t1_brain_mask_release


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path, help="Native pre-Gd T1 NIfTI.")
    parser.add_argument("--output", required=True, type=Path, help="New output directory.")
    parser.add_argument("--case-id", default=None)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument(
        "--release",
        type=Path,
        help="Validated local RS2 release; runs RS2 and M-seam cleanup.",
    )
    source.add_argument(
        "--raw-mask",
        type=Path,
        help="Existing raw RS2 mask; skips model inference and applies M-seam cleanup.",
    )
    parser.add_argument(
        "--device",
        choices=("auto", "mps", "cuda", "cpu"),
        default="auto",
        help="Model device; ignored with --raw-mask.",
    )
    parser.add_argument(
        "--disable-tta",
        action="store_true",
        help=(
            "Disable eight-way mirroring for a faster, lower-memory but separately "
            "recorded draft-generation variant."
        ),
    )
    args = parser.parse_args(argv)
    if args.raw_mask is not None and args.disable_tta:
        parser.error("--disable-tta only applies when model inference uses --release")
    if args.release is not None:
        release = validate_t1_brain_mask_release(args.release)
        output = run_local_t1_brain_mask(
            release,
            args.input,
            args.output,
            case_id=args.case_id,
            device_name=args.device,
            disable_tta=args.disable_tta,
        )
    else:
        output = build_t1_brain_mask_draft(
            args.input,
            args.raw_mask,
            args.output,
            case_id=args.case_id,
        )
    print(
        json.dumps(
            {
                "case_id": output.case_id,
                "draft_mask": str(output.draft_mask),
                "raw_rs2_mask": str(output.raw_rs2_mask),
                "qc_preview": str(output.qc_preview),
                "metadata": str(output.metadata_path),
                "volume_mm3": output.volume_mm3,
                "regularity_warnings": list(output.regularity_warnings),
                "approved": False,
                "human_review_required": True,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
