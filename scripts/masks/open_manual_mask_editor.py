#!/usr/bin/env python
"""Open pre-contrast images with MouseBrainExtractor pre-labels in ITK-SNAP."""

from __future__ import annotations

import argparse
import csv
import shutil
import subprocess
import sys
from pathlib import Path

import nibabel as nib
import numpy as np


def discover_itksnap() -> Path | None:
    candidates = [
        shutil.which("itksnap"),
        shutil.which("ITK-SNAP"),
        "/Applications/ITK-SNAP.app/Contents/MacOS/ITK-SNAP",
        "/Applications/ITK-SNAP.app/Contents/MacOS/itksnap",
    ]
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return Path(candidate)
    return None


def case_from_mask(mask_path: Path, suffix: str) -> str:
    name = mask_path.name
    if not name.endswith(suffix):
        raise ValueError(f"Unexpected prelabel name: {mask_path}")
    return name[: -len(suffix)]


def load_grid(path: Path) -> tuple[tuple[int, ...], np.ndarray]:
    img = nib.load(str(path))
    return img.shape, img.affine


def validate_grid(image_path: Path, mask_path: Path) -> None:
    image_shape, image_affine = load_grid(image_path)
    mask_shape, mask_affine = load_grid(mask_path)
    if image_shape != mask_shape:
        raise ValueError(
            f"Shape mismatch for {mask_path.name}: image {image_shape}, mask {mask_shape}"
        )
    if not np.allclose(image_affine, mask_affine, atol=1e-3):
        raise ValueError(f"Affine mismatch for {mask_path.name}")


def copy_prelabel(prelabel: Path, manual_mask: Path, overwrite: bool) -> str:
    manual_mask.parent.mkdir(parents=True, exist_ok=True)
    if manual_mask.exists() and not overwrite:
        return "existing_manual"
    shutil.copy2(prelabel, manual_mask)
    return "copied_prelabel"


def find_cases(prelabel_dir: Path,
               input_root: Path,
               manual_dir: Path,
               filters: list[str],
               prelabel_glob: str,
               prelabel_suffix: str) -> list[dict[str, Path | str]]:
    filters_lc = [f.lower() for f in filters]
    cases: list[dict[str, Path | str]] = []
    for prelabel in sorted(prelabel_dir.glob(prelabel_glob)):
        case_id = case_from_mask(prelabel, prelabel_suffix)
        if filters_lc and not any(f in case_id.lower() for f in filters_lc):
            continue
        image = input_root / case_id / "pre_coronal.nii.gz"
        manual_mask = manual_dir / f"{case_id}_pre_manual_mask.nii.gz"
        cases.append({
            "case_id": case_id,
            "image": image,
            "prelabel": prelabel,
            "manual_mask": manual_mask,
        })
    return cases


def write_manifest(records: list[dict[str, str]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["case_id", "image", "prelabel", "manual_mask", "status", "message"],
        )
        writer.writeheader()
        writer.writerows(records)


def itksnap_command(viewer: Path, image: Path, mask: Path) -> list[str]:
    return [str(viewer), "-g", str(image), "-s", str(mask)]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Open pre-contrast NIfTI scans with editable prelabel masks for "
            "manual correction in ITK-SNAP."
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--input-root", type=Path, default=Path("output/all_mice"),
                        help="folder containing <case>/pre_coronal.nii.gz")
    parser.add_argument("--prelabel-dir", type=Path,
                        default=Path("derivatives/brain_seg/mousebrainextractor"),
                        help="folder containing editable prelabel masks")
    parser.add_argument("--prelabel-glob", default="*_mousebrainextractor_mask.nii.gz",
                        help="glob used to find prelabel masks")
    parser.add_argument("--prelabel-suffix", default="_mousebrainextractor_mask.nii.gz",
                        help="filename suffix removed to infer case id")
    parser.add_argument("--manual-dir", type=Path, default=Path("derivatives/brain_seg/manual"),
                        help="folder where editable manual masks are stored")
    parser.add_argument("--case", action="append", default=[],
                        help="case substring to open; pass multiple times for multiple cases")
    parser.add_argument("--limit", type=int, default=None,
                        help="maximum number of queued cases")
    parser.add_argument("--start-at", type=int, default=0,
                        help="zero-based index into the discovered queue")
    parser.add_argument("--viewer", type=Path, default=None,
                        help="path to ITK-SNAP executable")
    parser.add_argument("--overwrite-manual", action="store_true",
                        help="replace existing manual masks with the selected prelabel")
    parser.add_argument("--skip-existing", action="store_true",
                        help="skip cases that already have a manual mask")
    parser.add_argument("--dry-run", action="store_true",
                        help="validate the queue and print commands without copying masks or launching a viewer")
    parser.add_argument("--no-prompt", action="store_true",
                        help="launch queued cases without waiting for Enter between cases")
    parser.add_argument("--manifest", type=Path, default=None,
                        help="queue manifest path; default is <manual-dir>/manual_mask_editing_queue.csv")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    input_root = args.input_root.expanduser()
    prelabel_dir = args.prelabel_dir.expanduser()
    manual_dir = args.manual_dir.expanduser()
    manifest = args.manifest.expanduser() if args.manifest else manual_dir / "manual_mask_editing_queue.csv"

    cases = find_cases(
        prelabel_dir,
        input_root,
        manual_dir,
        args.case,
        args.prelabel_glob,
        args.prelabel_suffix,
    )
    cases = cases[max(args.start_at, 0):]
    if args.limit is not None:
        cases = cases[: max(args.limit, 0)]

    if not cases:
        print("No matching prelabels found.", file=sys.stderr)
        return 1

    viewer: Path | None = args.viewer.expanduser() if args.viewer else discover_itksnap()
    if viewer is None and not args.dry_run:
        print(
            "Could not find ITK-SNAP. Install it, add it to PATH, or pass "
            "--viewer /path/to/executable.",
            file=sys.stderr,
        )
        print("Use --dry-run to print the commands without launching.")
        return 1

    records: list[dict[str, str]] = []
    prepared: list[dict[str, Path | str]] = []
    for case in cases:
        case_id = str(case["case_id"])
        image = Path(case["image"])
        prelabel = Path(case["prelabel"])
        manual_mask = Path(case["manual_mask"])
        try:
            if not image.exists():
                raise FileNotFoundError(f"missing image: {image}")
            if not prelabel.exists():
                raise FileNotFoundError(f"missing prelabel: {prelabel}")
            if args.dry_run:
                validate_grid(image, prelabel)
                status = "dry_run"
                prepared.append(case)
            elif args.skip_existing and manual_mask.exists():
                status = "skipped_existing"
            else:
                status = copy_prelabel(prelabel, manual_mask, overwrite=args.overwrite_manual)
                validate_grid(image, manual_mask)
                prepared.append(case)
            message = ""
        except Exception as exc:
            status = "failed"
            message = str(exc)

        records.append({
            "case_id": case_id,
            "image": str(image),
            "prelabel": str(prelabel),
            "manual_mask": str(manual_mask),
            "status": status,
            "message": message,
        })
        print(f"{status:>18}  {case_id}")
        if message:
            print(f"  {message}")

    if args.dry_run:
        print("\nmanifest: not written in --dry-run mode")
    else:
        write_manifest(records, manifest)
        print(f"\nmanifest: {manifest}")

    failed = [r for r in records if r["status"] == "failed"]
    if failed:
        print(f"failed cases: {len(failed)}", file=sys.stderr)

    for index, case in enumerate(prepared, start=1):
        image = Path(case["image"])
        manual_mask = Path(case["manual_mask"])
        case_id = str(case["case_id"])
        cmd = itksnap_command(viewer, image, manual_mask) if viewer else [
            "ITK-SNAP", "-g", str(image), "-s", str(manual_mask)
        ]
        print(f"\n[{index}/{len(prepared)}] {case_id}")
        print(" ".join(f"'{part}'" if " " in part else part for part in cmd))
        if args.dry_run:
            continue
        subprocess.Popen(cmd)
        if not args.no_prompt and index < len(prepared):
            input("After saving this mask in the viewer, press Enter to open the next case...")

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
