#!/usr/bin/env python
"""Run MouseBrainExtractor for one case and save a binary pre-label mask."""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import os
import subprocess
import sys
from pathlib import Path

import nibabel as nib

if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from external_mask_utils import auto_mbe_dataset_type, binarize_to_reference


def check_python_monai_compatibility() -> None:
    if sys.version_info < (3, 12):
        return
    try:
        monai_version = importlib.metadata.version("monai")
    except importlib.metadata.PackageNotFoundError:
        monai_version = "not installed"
    raise RuntimeError(
        "MouseBrainExtractor should be run with Python 3.10/3.11. "
        f"Detected Python {sys.version_info.major}.{sys.version_info.minor}, MONAI {monai_version}."
    )


def checkpoint_for(weights_root: Path, dstype: str) -> Path:
    return weights_root / dstype / "checkpoint_best.pth"


def validate_setup(mbe_root: Path, weights_root: Path, dstype: str) -> tuple[Path, Path]:
    script = mbe_root / "bin" / "run_mbe_predict_skullstrip.py"
    weights = checkpoint_for(weights_root, dstype)
    if not script.exists() or not weights.exists():
        raise FileNotFoundError(
            "MouseBrainExtractor setup incomplete.\n"
            f"Missing script or weights:\n  {script}\n  {weights}\n"
            "On Colab, clone MouseBrainExtractor and extract MBE_weights first."
        )
    return script, weights


def output_paths(out_dir: Path, case_id: str) -> tuple[Path, Path, Path]:
    raw = out_dir / f"{case_id}_mousebrainextractor_raw.nii.gz"
    mask = out_dir / f"{case_id}_mousebrainextractor_mask.nii.gz"
    posenc = out_dir / f"{case_id}_mousebrainextractor_posenc.nii.gz"
    return raw, mask, posenc


def postprocessed_path(raw_output: Path) -> Path:
    return Path(str(raw_output).split(".nii")[0] + ".pp.nii.gz")


def build_command(script: Path,
                  image: Path,
                  raw_output: Path,
                  posenc: Path,
                  weights: Path,
                  dstype: str,
                  batch_rois: int,
                  device: str) -> list[str]:
    cmd = [
        sys.executable,
        str(script),
        "-i", str(image),
        "--gen_posenc", str(posenc),
        "-o", str(raw_output),
        "-n", str(weights),
        "--device", device,
        "--pp",
    ]
    if dstype in {"invivo_iso", "invivo_aniso"}:
        cmd.extend(["--dstype", "invivo"])
    elif dstype == "exvivo":
        cmd.extend(["--dstype", "exvivo"])
    if dstype == "invivo_aniso":
        cmd.extend(["-d", "2", "--patch_size", "128"])
    cmd.extend(["-b", str(batch_rois)])
    return cmd


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run MouseBrainExtractor from source and save a binary NIfTI pre-label mask. "
            "Outputs must be manually corrected before final quantification or nnU-Net training."
        )
    )
    parser.add_argument("--image", type=Path, required=True)
    parser.add_argument("--case-id", required=True)
    parser.add_argument("--out-dir", type=Path,
                        default=Path("derivatives/brain_seg/external/mousebrainextractor"))
    parser.add_argument("--mbe-root", type=Path, default=Path("external/MouseBrainExtractor"))
    parser.add_argument("--weights-root", type=Path, default=Path("external/MBE_weights"))
    parser.add_argument("--dstype", choices=["auto", "invivo_iso", "invivo_aniso", "exvivo"],
                        default="auto")
    parser.add_argument("--batch-rois", type=int, default=1)
    parser.add_argument("--device", choices=["cpu", "cuda"], default="cuda")
    parser.add_argument("--threshold", type=float, default=0.0)
    parser.add_argument("--allow-resample", action="store_true")
    parser.add_argument("--strict-openmp", action="store_true")
    parser.add_argument("--threads", type=int, default=1)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    image = args.image.expanduser()
    out_dir = args.out_dir.expanduser()
    out_dir.mkdir(parents=True, exist_ok=True)

    img = nib.load(str(image))
    dstype = auto_mbe_dataset_type(img) if args.dstype == "auto" else args.dstype
    mbe_root = args.mbe_root.expanduser()
    weights_root = args.weights_root.expanduser()
    script = mbe_root / "bin" / "run_mbe_predict_skullstrip.py"
    weights = checkpoint_for(weights_root, dstype)
    raw_output, mask_output, posenc = output_paths(out_dir, args.case_id)
    cmd = build_command(script, image, raw_output, posenc, weights, dstype, args.batch_rois, args.device)

    print(f"case: {args.case_id}")
    print(f"dstype: {dstype}")
    print("command:")
    print(" ".join(str(part) for part in cmd))
    if args.dry_run:
        print(f"setup script exists: {script.exists()} ({script})")
        print(f"weights exist: {weights.exists()} ({weights})")
        print(f"raw output: {raw_output}")
        print(f"binary pre-label mask: {mask_output}")
        return 0

    check_python_monai_compatibility()
    script, weights = validate_setup(mbe_root, weights_root, dstype)
    cmd = build_command(script, image, raw_output, posenc, weights, dstype, args.batch_rois, args.device)

    env = os.environ.copy()
    threads = str(max(1, int(args.threads)))
    env.setdefault("OMP_NUM_THREADS", threads)
    env.setdefault("MKL_NUM_THREADS", threads)
    env.setdefault("NUMEXPR_NUM_THREADS", threads)
    if not args.strict_openmp:
        env.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")

    subprocess.run(cmd, check=True, env=env)
    source_output = postprocessed_path(raw_output)
    if not source_output.exists():
        source_output = raw_output
    meta = binarize_to_reference(
        source_output,
        image,
        mask_output,
        threshold=args.threshold,
        allow_resample=args.allow_resample,
    )
    meta.update({
        "case_id": args.case_id,
        "method": "MouseBrainExtractor",
        "image": str(image),
        "raw_output": str(raw_output),
        "source_output": str(source_output),
        "dstype": dstype,
        "weights": str(weights),
        "command": [str(part) for part in cmd],
    })
    meta_path = out_dir / f"{args.case_id}_mousebrainextractor_metadata.json"
    meta_path.write_text(json.dumps(meta, indent=2) + "\n")
    print(f"pre-label mask: {mask_output}")
    print(f"metadata: {meta_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
