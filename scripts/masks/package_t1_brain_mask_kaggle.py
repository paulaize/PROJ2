#!/usr/bin/env python3
"""Package manually corrected pre-Gd T1 brain masks for the Kaggle notebook."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import shutil
from datetime import datetime
from pathlib import Path

import nibabel as nib
import numpy as np


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MASK_DIR = ROOT / "derivatives/brain_seg/manual_rs2_m_seam"
DEFAULT_IMAGE_DIR = (
    ROOT
    / "derivatives/brain_extraction/colab"
    / "t1_brain_extraction_all_mice_34/images"
)
DEFAULT_OUTPUT = (
    ROOT
    / "derivatives/brain_seg/kaggle"
    / "LYS_T1_brainmask_manual_holdout_16_2_2_20260731"
)
FIRST_CORRECTED_MASK = "C23S2_D7_pre_manual_mask.nii.gz"
MASK_SUFFIX = "_pre_manual_mask.nii.gz"
CASE_PATTERN = re.compile(r"^(C\d+S\d+)_D\d+(?:_bis)?$")
VALIDATION_CASES = {"C24S5_D1", "C24S5_D7"}
TEST_CASES = {"C25S1_D1", "C25S1_D7"}

MANIFEST_FIELDS = [
    "case_id",
    "animal_id",
    "split",
    "modality",
    "acquisition_role",
    "image",
    "mask",
    "include_for_nnunet",
    "mask_review",
    "reviewer",
    "reviewed_at",
    "image_sha256",
    "mask_sha256",
]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def display_path(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def corrected_masks(mask_dir: Path, first_mask_name: str) -> list[Path]:
    boundary = mask_dir / first_mask_name
    if not boundary.is_file():
        raise FileNotFoundError(f"First corrected mask not found: {boundary}")
    boundary_mtime_ns = boundary.stat().st_mtime_ns
    selected = sorted(
        path
        for path in mask_dir.glob(f"*{MASK_SUFFIX}")
        if path.stat().st_mtime_ns >= boundary_mtime_ns
    )
    if not selected or selected[0].name != first_mask_name:
        names = [path.name for path in selected]
        if first_mask_name not in names:
            raise RuntimeError("The inclusive correction boundary was not selected")
    return selected


def case_and_animal(mask_path: Path) -> tuple[str, str]:
    if not mask_path.name.endswith(MASK_SUFFIX):
        raise ValueError(f"Unexpected mask filename: {mask_path.name}")
    case_id = mask_path.name[: -len(MASK_SUFFIX)]
    match = CASE_PATTERN.fullmatch(case_id)
    if match is None:
        raise ValueError(f"Cannot assign animal ID for case: {case_id}")
    return case_id, match.group(1)


def split_for_case(case_id: str) -> str:
    if case_id in VALIDATION_CASES:
        return "validation"
    if case_id in TEST_CASES:
        return "test"
    return "train"


def validate_pair(image_path: Path, mask_path: Path) -> dict[str, object]:
    image = nib.load(image_path)
    mask = nib.load(mask_path)
    if len(image.shape) != 3 or len(mask.shape) != 3:
        raise ValueError(f"Expected 3-D image/mask: {image_path}, {mask_path}")
    if image.shape != mask.shape:
        raise ValueError(
            f"Shape mismatch for {mask_path.name}: {image.shape} != {mask.shape}"
        )
    if not np.allclose(image.affine, mask.affine, atol=1e-5, rtol=1e-5):
        raise ValueError(f"Affine mismatch for {mask_path.name}")

    image_data = np.asanyarray(image.dataobj)
    if not np.isfinite(image_data).all():
        raise ValueError(f"Non-finite image values in {image_path.name}")
    mask_data = np.asanyarray(mask.dataobj)
    unique = np.unique(mask_data)
    if not set(unique.tolist()) <= {0, 1}:
        raise ValueError(
            f"Mask is not binary for {mask_path.name}: {unique.tolist()}"
        )
    foreground = int(np.count_nonzero(mask_data))
    if foreground == 0:
        raise ValueError(f"Empty mask: {mask_path.name}")
    return {
        "shape": list(image.shape),
        "spacing_mm": [float(value) for value in image.header.get_zooms()[:3]],
        "foreground_voxels": foreground,
    }


def write_manifest(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=MANIFEST_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def build_package(
    *,
    mask_dir: Path,
    image_dir: Path,
    output_dir: Path,
    first_mask_name: str,
    reviewer: str,
    overwrite: bool,
    expected_split_counts: dict[str, int] | None = None,
) -> tuple[Path, Path]:
    masks = corrected_masks(mask_dir, first_mask_name)
    if output_dir.exists():
        if not overwrite:
            raise FileExistsError(
                f"Output already exists (pass --overwrite): {output_dir}"
            )
        shutil.rmtree(output_dir)
    image_output = output_dir / "images"
    label_output = output_dir / "labels"
    image_output.mkdir(parents=True)
    label_output.mkdir()

    rows: list[dict[str, str]] = []
    audit: list[dict[str, object]] = []
    for source_mask in masks:
        case_id, animal_id = case_and_animal(source_mask)
        split = split_for_case(case_id)
        source_image = image_dir / f"{case_id}_pre_t1.nii.gz"
        if not source_image.is_file():
            raise FileNotFoundError(f"Matching pre-Gd T1 not found: {source_image}")
        geometry = validate_pair(source_image, source_mask)

        relative_image = Path("images") / f"{case_id}_pre_t1.nii.gz"
        relative_mask = Path("labels") / f"{case_id}_brain_mask.nii.gz"
        destination_image = output_dir / relative_image
        destination_mask = output_dir / relative_mask
        shutil.copy2(source_image, destination_image)
        shutil.copy2(source_mask, destination_mask)

        reviewed_at = datetime.fromtimestamp(
            source_mask.stat().st_mtime
        ).astimezone().isoformat(timespec="seconds")
        rows.append(
            {
                "case_id": case_id,
                "animal_id": animal_id,
                "split": split,
                "modality": "T1w",
                "acquisition_role": "pre_gd",
                "image": relative_image.as_posix(),
                "mask": relative_mask.as_posix(),
                "include_for_nnunet": "no" if split == "test" else "yes",
                "mask_review": "approved",
                "reviewer": reviewer,
                "reviewed_at": reviewed_at,
                "image_sha256": sha256(destination_image),
                "mask_sha256": sha256(destination_mask),
            }
        )
        audit.append(
            {
                "case_id": case_id,
                "animal_id": animal_id,
                "split": split,
                "source_image": display_path(source_image),
                "source_mask": display_path(source_mask),
                "source_mask_mtime": reviewed_at,
                **geometry,
            }
        )

    if len({row["case_id"] for row in rows}) != len(rows):
        raise RuntimeError("Duplicate case IDs in selected labels")
    split_counts = {
        split: sum(row["split"] == split for row in rows)
        for split in ("train", "validation", "test")
    }
    if (
        expected_split_counts is not None
        and split_counts != expected_split_counts
    ):
        raise RuntimeError(f"Unexpected split counts: {split_counts}")
    animal_splits: dict[str, set[str]] = {}
    for row in rows:
        animal_splits.setdefault(row["animal_id"], set()).add(row["split"])
    leakage = {
        animal_id: sorted(splits)
        for animal_id, splits in animal_splits.items()
        if len(splits) != 1
    }
    if leakage:
        raise RuntimeError(f"Animal leakage across splits: {leakage}")
    write_manifest(output_dir / "training_manifest.csv", rows)
    (output_dir / "package_audit.json").write_text(
        json.dumps(
            {
                "selection": {
                    "rule": "mask mtime at or after the named first correction",
                    "first_corrected_mask": first_mask_name,
                    "inclusive": True,
                },
                "case_count": len(rows),
                "animal_group_count": len({row["animal_id"] for row in rows}),
                "split_counts": split_counts,
                "split_assignment": {
                    "validation_animal": "C24S5",
                    "test_animal": "C25S1",
                    "animal_grouped": True,
                },
                "cases": audit,
            },
            indent=2,
        )
        + "\n"
    )
    archive = Path(
        shutil.make_archive(
            str(output_dir),
            "zip",
            root_dir=output_dir.parent,
            base_dir=output_dir.name,
        )
    )
    return output_dir, archive


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Package corrected T1 masks selected from an inclusive named "
            "mtime boundary."
        )
    )
    parser.add_argument("--mask-dir", type=Path, default=DEFAULT_MASK_DIR)
    parser.add_argument("--image-dir", type=Path, default=DEFAULT_IMAGE_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--first-corrected-mask",
        default=FIRST_CORRECTED_MASK,
    )
    parser.add_argument("--reviewer", default="Paul-Andreas Laize")
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    package, archive = build_package(
        mask_dir=args.mask_dir.resolve(),
        image_dir=args.image_dir.resolve(),
        output_dir=args.output_dir.resolve(),
        first_mask_name=args.first_corrected_mask,
        reviewer=args.reviewer,
        overwrite=args.overwrite,
        expected_split_counts={"train": 16, "validation": 2, "test": 2},
    )
    rows = list(csv.DictReader((package / "training_manifest.csv").open()))
    print(f"Package: {package}")
    print(f"Archive: {archive}")
    print(f"Cases: {len(rows)}")
    print(f"Animal groups: {len({row['animal_id'] for row in rows})}")
    print(f"Archive SHA-256: {sha256(archive)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
