#!/usr/bin/env python
"""Package pre-contrast images for cloud MouseBrainExtractor pre-labeling."""

from __future__ import annotations

import argparse
import csv
import random
import shutil
import zipfile
from pathlib import Path


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def discover_cases(input_root: Path,
                   requested: list[str],
                   random_count: int | None,
                   seed: int) -> list[str]:
    if requested:
        return requested
    cases = sorted(p.name for p in input_root.iterdir() if (p / "pre_coronal.nii.gz").exists())
    if random_count is not None:
        if random_count <= 0:
            raise ValueError("--random-count must be positive")
        rng = random.Random(seed)
        cases = sorted(rng.sample(cases, min(random_count, len(cases))))
    return cases


def copy_case(case_id: str,
              input_root: Path,
              package_root: Path,
              include_manual: bool) -> dict[str, str]:
    image = input_root / case_id / "pre_coronal.nii.gz"
    if not image.exists():
        raise FileNotFoundError(f"missing pre image for {case_id}: {image}")

    image_out = package_root / "inputs" / case_id / "pre_coronal.nii.gz"
    image_out.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(image, image_out)

    row = {
        "case_id": case_id,
        "image": str(image_out.relative_to(package_root)),
        "manual": "",
    }

    if include_manual:
        manual = project_root() / "derivatives/brain_seg/manual" / f"{case_id}_pre_manual_mask.nii.gz"
        if manual.exists():
            manual_out = package_root / "manual" / manual.name
            manual_out.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(manual, manual_out)
            row["manual"] = str(manual_out.relative_to(package_root))

    return row


def copy_cloud_scripts(package_root: Path, include_packager: bool = False) -> None:
    source_dir = Path(__file__).resolve().parent
    target_dir = package_root / "scripts" / "cloud_mbe"
    target_dir.mkdir(parents=True, exist_ok=True)
    script_names = [
        "external_mask_utils.py",
        "run_mousebrainextractor.py",
        "run_mbe_batch.py",
    ]
    if include_packager:
        script_names.append("prepare_cloud_mbe_package.py")
    for name in script_names:
        script = source_dir / name
        if not script.exists():
            raise FileNotFoundError(f"missing cloud runtime script: {script}")
        shutil.copy2(script, target_dir / script.name)


def zip_dir(source_dir: Path, zip_path: Path) -> None:
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(source_dir.rglob("*")):
            if path.is_file():
                zf.write(path, path.relative_to(source_dir.parent))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Prepare a small upload package for cloud MouseBrainExtractor inference. "
            "MouseBrainExtractor outputs are pre-labels for manual correction, not final masks."
        )
    )
    parser.add_argument("--input-root", type=Path, default=Path("output/all_mice"))
    parser.add_argument("--case", action="append", default=[],
                        help="case id to include; repeat for multiple cases. Default: all converted cases")
    parser.add_argument("--random-count", type=int, default=None,
                        help="randomly select this many cases from all converted cases")
    parser.add_argument("--seed", type=int, default=20260625,
                        help="random seed used with --random-count")
    parser.add_argument("--out-dir", type=Path, default=Path("derivatives/cloud_mbe"))
    parser.add_argument("--package-name", default="mbe_cloud_inputs")
    parser.add_argument("--include-manual", action="store_true",
                        help="include available corrected manual masks for cloud-side benchmarking")
    parser.add_argument("--no-scripts", action="store_true",
                        help="do not include scripts/cloud_mbe in the upload package")
    parser.add_argument("--include-packager", action="store_true",
                        help="also include prepare_cloud_mbe_package.py inside the upload package")
    parser.add_argument("--no-zip", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    package_root = args.out_dir / args.package_name
    if package_root.exists():
        shutil.rmtree(package_root)
    package_root.mkdir(parents=True, exist_ok=True)

    selected_cases = discover_cases(args.input_root, args.case, args.random_count, args.seed)
    rows = [
        copy_case(
            case_id,
            args.input_root,
            package_root,
            include_manual=args.include_manual,
        )
        for case_id in selected_cases
    ]

    manifest = package_root / "manifest.csv"
    with manifest.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["case_id", "image", "manual"])
        writer.writeheader()
        writer.writerows(rows)

    if not args.no_scripts:
        copy_cloud_scripts(package_root, include_packager=args.include_packager)

    (package_root / "selection.txt").write_text("\n".join(selected_cases) + "\n")

    print(f"package folder: {package_root}")
    print(f"cases: {len(rows)}")
    print("selected:")
    for case_id in selected_cases:
        print(f"  {case_id}")
    print(f"manifest: {manifest}")
    if not args.no_zip:
        zip_path = args.out_dir / f"{args.package_name}.zip"
        zip_dir(package_root, zip_path)
        print(f"zip: {zip_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
