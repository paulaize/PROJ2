#!/usr/bin/env python
"""Package pre-Gd T1 images and optional reference masks for Colab benchmarking."""

from __future__ import annotations

import argparse
import csv
import json
import random
import shutil
import zipfile
from pathlib import Path


DEFAULT_IMAGE_NAME = "pre_coronal.nii.gz"
DEFAULT_REFERENCE_PATTERNS = (
    "{case_id}_pre_manual_mask_done.nii.gz",
    "{case_id}_pre_manual_mask.nii.gz",
)


def discover_cases(input_root: Path) -> list[str]:
    return sorted(
        path.name
        for path in input_root.iterdir()
        if path.is_dir() and (path / DEFAULT_IMAGE_NAME).is_file()
    )


def select_cases(
    available: list[str],
    requested: list[str],
    random_count: int | None,
    seed: int,
) -> list[str]:
    if requested:
        missing = sorted(set(requested) - set(available))
        if missing:
            raise ValueError(f"unknown or unconverted cases: {', '.join(missing)}")
        selected = sorted(set(requested))
    else:
        selected = list(available)

    if random_count is not None:
        if random_count <= 0:
            raise ValueError("--random-count must be positive")
        selected = sorted(random.Random(seed).sample(selected, min(random_count, len(selected))))
    return selected


def read_case_file(path: Path) -> list[str]:
    """Read one case ID per line, ignoring blank lines and comments."""
    return [
        line.strip()
        for line in path.read_text().splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


def find_reference(case_id: str, reference_dir: Path | None) -> Path | None:
    if reference_dir is None:
        return None
    for pattern in DEFAULT_REFERENCE_PATTERNS:
        candidate = reference_dir / pattern.format(case_id=case_id)
        if candidate.is_file():
            return candidate
    return None


def zip_directory(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(source.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(source.parent))


def build_package(
    *,
    input_root: Path,
    package_root: Path,
    cases: list[str],
    reference_dir: Path | None,
    require_reference: bool,
    seed: int,
    overwrite: bool = False,
) -> list[dict[str, str]]:
    if package_root.exists():
        if not overwrite:
            raise FileExistsError(f"package already exists: {package_root}")
        shutil.rmtree(package_root)
    package_root.mkdir(parents=True)

    rows: list[dict[str, str]] = []
    for case_id in cases:
        source_image = input_root / case_id / DEFAULT_IMAGE_NAME
        image_out = package_root / "images" / f"{case_id}_pre_t1.nii.gz"
        image_out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_image, image_out)

        reference = find_reference(case_id, reference_dir)
        if require_reference and reference is None:
            raise FileNotFoundError(f"no reference-mask candidate found for {case_id}")

        reference_rel = ""
        if reference is not None:
            reference_out = package_root / "references" / f"{case_id}_brain_mask.nii.gz"
            reference_out.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(reference, reference_out)
            reference_rel = str(reference_out.relative_to(package_root))

        rows.append(
            {
                "case_id": case_id,
                "image": str(image_out.relative_to(package_root)),
                "reference_mask": reference_rel,
            }
        )

    manifest = package_root / "benchmark_manifest.csv"
    with manifest.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=["case_id", "image", "reference_mask"])
        writer.writeheader()
        writer.writerows(rows)

    metadata = {
        "purpose": "Open-weight T1 mouse brain-extraction benchmark",
        "input_space": "native pre-Gd coronal T1",
        "case_count": len(rows),
        "cases": [row["case_id"] for row in rows],
        "selection_seed": seed,
        "warning": "Reference masks must be human-reviewed before quantitative scoring.",
    }
    (package_root / "package_metadata.json").write_text(json.dumps(metadata, indent=2) + "\n")
    return rows


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Create a model-neutral upload package for comparing brain-extraction "
            "models in Google Colab."
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--input-root", type=Path, default=Path("output/all_mice"))
    parser.add_argument("--reference-dir", type=Path, default=None)
    parser.add_argument("--case", action="append", default=[])
    parser.add_argument(
        "--case-file",
        type=Path,
        default=None,
        help="Text file containing one case ID per line; blank lines and # comments are ignored.",
    )
    parser.add_argument("--random-count", type=int, default=None)
    parser.add_argument("--seed", type=int, default=20260717)
    parser.add_argument("--out-dir", type=Path, default=Path("derivatives/brain_extraction/colab"))
    parser.add_argument("--package-name", default="t1_brain_extraction_benchmark")
    parser.add_argument("--require-reference", action="store_true")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--no-zip", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    input_root = args.input_root.expanduser()
    available = discover_cases(input_root)
    requested = list(args.case)
    if args.case_file:
        requested.extend(read_case_file(args.case_file.expanduser()))
    selected = select_cases(available, requested, args.random_count, args.seed)
    if not selected:
        raise ValueError(f"no converted cases found under {input_root}")

    package_root = args.out_dir.expanduser() / args.package_name
    rows = build_package(
        input_root=input_root,
        package_root=package_root,
        cases=selected,
        reference_dir=args.reference_dir.expanduser() if args.reference_dir else None,
        require_reference=args.require_reference,
        seed=args.seed,
        overwrite=args.overwrite,
    )
    print(f"package: {package_root}")
    print(f"cases: {len(rows)}")
    if not args.no_zip:
        zip_path = args.out_dir.expanduser() / f"{args.package_name}.zip"
        zip_directory(package_root, zip_path)
        print(f"zip: {zip_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
