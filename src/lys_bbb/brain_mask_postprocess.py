"""Post-process candidate brain masks before QC and quantification."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any

import nibabel as nib
import numpy as np
from scipy import ndimage as ndi

from lys_bbb.flash_cohort import parse_case_id, timepoint_sort_key
from lys_bbb.qc_manifest import affine_comparison, find_existing_path, split_patterns


DEFAULT_INPUT_PATTERNS = (
    "{case_id}.nii.gz",
    "{case_id}_brain_mask.nii.gz",
    "{case_id}_pred.nii.gz",
    "{case_id}_pre_manual_mask_done.nii.gz",
    "{case_id}_pre_manual_mask.nii.gz",
)


POSTPROCESS_FIELDS = [
    "case_id",
    "animal_id",
    "timepoint",
    "status",
    "input_mask",
    "output_mask",
    "input_voxels",
    "output_voxels",
    "input_components",
    "output_components",
    "removed_voxels",
    "kept_largest_component",
    "filled_holes",
    "message",
]


def discover_case_dirs(input_root: Path) -> list[Path]:
    return sorted(
        (path for path in input_root.iterdir() if path.is_dir()),
        key=lambda path: (
            parse_case_id(path.name).animal_id if parse_case_id(path.name) else path.name,
            timepoint_sort_key(parse_case_id(path.name).timepoint) if parse_case_id(path.name) else (10_000, ""),
            path.name,
        ),
    )


def component_count(mask: np.ndarray) -> int:
    _labels, n_components = ndi.label(mask)
    return int(n_components)


def keep_largest_component(mask: np.ndarray) -> np.ndarray:
    labels, n_components = ndi.label(mask)
    if n_components <= 1:
        return mask
    sizes = np.bincount(labels.ravel())
    if sizes.size <= 1:
        return mask
    sizes[0] = 0
    largest_label = int(np.argmax(sizes))
    return labels == largest_label


def postprocess_mask(
    mask: np.ndarray,
    *,
    keep_largest: bool = True,
    fill_holes: bool = False,
    min_voxels: int = 1,
) -> tuple[np.ndarray, dict[str, Any]]:
    mask = mask.astype(bool)
    input_voxels = int(np.count_nonzero(mask))
    input_components = component_count(mask)
    processed = mask
    if keep_largest:
        processed = keep_largest_component(processed)
    if fill_holes:
        processed = ndi.binary_fill_holes(processed)
    output_voxels = int(np.count_nonzero(processed))
    if output_voxels < min_voxels:
        raise ValueError(f"post-processed mask has {output_voxels} voxels, below minimum {min_voxels}")
    output_components = component_count(processed)
    return processed.astype(np.uint8), {
        "input_voxels": input_voxels,
        "output_voxels": output_voxels,
        "input_components": input_components,
        "output_components": output_components,
        "removed_voxels": int(input_voxels - output_voxels),
        "kept_largest_component": bool(keep_largest),
        "filled_holes": bool(fill_holes),
    }


def save_mask_like(mask: np.ndarray, reference: nib.Nifti1Image, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    out = nib.Nifti1Image(mask.astype(np.uint8, copy=False), reference.affine, reference.header.copy())
    out.set_data_dtype(np.uint8)
    nib.save(out, str(path))


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=POSTPROCESS_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def process_case(
    session_dir: Path,
    *,
    mask_dir: Path,
    mask_patterns: list[str],
    output_dir: Path,
    output_pattern: str,
    keep_largest: bool,
    fill_holes: bool,
    min_voxels: int,
) -> dict[str, Any]:
    case_id = session_dir.name
    parts = parse_case_id(case_id)
    row: dict[str, Any] = {
        "case_id": case_id,
        "animal_id": parts.animal_id if parts else "",
        "timepoint": parts.timepoint if parts else "",
        "status": "ready",
        "input_mask": "",
        "output_mask": "",
        "input_voxels": "",
        "output_voxels": "",
        "input_components": "",
        "output_components": "",
        "removed_voxels": "",
        "kept_largest_component": bool(keep_largest),
        "filled_holes": bool(fill_holes),
        "message": "",
    }
    try:
        pre_path = session_dir / "pre_coronal.nii.gz"
        if not pre_path.exists():
            row["status"] = "missing_conversion"
            row["message"] = f"missing pre image: {pre_path}"
            return row
        mask_path = find_existing_path(mask_dir, mask_patterns, case_id)
        if mask_path is None:
            row["status"] = "missing_mask"
            row["message"] = "missing candidate mask"
            return row
        row["input_mask"] = str(mask_path)
        pre_img = nib.load(str(pre_path))
        mask_img = nib.load(str(mask_path))
        comparison = affine_comparison(pre_img, mask_img)
        if not (comparison["shape_match"] and comparison["affine_match"]):
            raise ValueError("candidate mask grid does not match pre image")
        processed, metrics = postprocess_mask(
            mask_img.get_fdata(dtype=np.float32) > 0,
            keep_largest=keep_largest,
            fill_holes=fill_holes,
            min_voxels=min_voxels,
        )
        out_path = output_dir / output_pattern.format(
            case_id=case_id,
            animal_id=row["animal_id"],
            timepoint=row["timepoint"],
        )
        save_mask_like(processed, pre_img, out_path)
        row["output_mask"] = str(out_path)
        row.update(metrics)
    except Exception as exc:
        row["status"] = "failed"
        row["message"] = str(exc)
    return row


def postprocess_masks(
    input_root: Path,
    *,
    mask_dir: Path,
    mask_patterns: list[str],
    output_dir: Path,
    output_pattern: str,
    keep_largest: bool,
    fill_holes: bool,
    min_voxels: int,
) -> list[dict[str, Any]]:
    return [
        process_case(
            session_dir,
            mask_dir=mask_dir,
            mask_patterns=mask_patterns,
            output_dir=output_dir,
            output_pattern=output_pattern,
            keep_largest=keep_largest,
            fill_holes=fill_holes,
            min_voxels=min_voxels,
        )
        for session_dir in discover_case_dirs(input_root)
    ]


def write_summary(path: Path, rows: list[dict[str, Any]]) -> dict[str, Any]:
    summary = {
        "n_cases": len(rows),
        "n_ready": sum(1 for row in rows if row.get("status") == "ready"),
        "n_failed": sum(1 for row in rows if row.get("status") == "failed"),
        "n_missing_mask": sum(1 for row in rows if row.get("status") == "missing_mask"),
        "n_missing_conversion": sum(1 for row in rows if row.get("status") == "missing_conversion"),
        "total_removed_voxels": sum(int(row.get("removed_voxels") or 0) for row in rows),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(summary, indent=2) + "\n")
    return summary


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Post-process candidate brain masks on the native pre-Gd T1 grid.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--input-root", type=Path, default=Path("output/all_mice"))
    parser.add_argument("--mask-dir", type=Path, required=True)
    parser.add_argument("--mask-pattern", action="append", default=None)
    parser.add_argument("-o", "--output-dir", type=Path, default=Path("derivatives/brain_seg/processed_masks"))
    parser.add_argument("--output-pattern", default="{case_id}.nii.gz")
    parser.add_argument("--summary-csv", type=Path, default=Path("reports/qc/brain_mask_postprocess.csv"))
    parser.add_argument("--summary-json", type=Path, default=Path("reports/qc/brain_mask_postprocess_summary.json"))
    parser.add_argument("--no-keep-largest", action="store_true")
    parser.add_argument("--fill-holes", action="store_true")
    parser.add_argument("--min-voxels", type=int, default=1)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    rows = postprocess_masks(
        args.input_root,
        mask_dir=args.mask_dir,
        mask_patterns=split_patterns(args.mask_pattern, DEFAULT_INPUT_PATTERNS),
        output_dir=args.output_dir,
        output_pattern=args.output_pattern,
        keep_largest=not args.no_keep_largest,
        fill_holes=args.fill_holes,
        min_voxels=args.min_voxels,
    )
    write_csv(args.summary_csv, rows)
    summary = write_summary(args.summary_json, rows)
    print(f"cases: {summary['n_cases']}")
    print(f"ready: {summary['n_ready']}")
    print(f"missing masks: {summary['n_missing_mask']}")
    print(f"missing conversions: {summary['n_missing_conversion']}")
    print(f"failed: {summary['n_failed']}")
    print(f"summary csv: {args.summary_csv}")
    print(f"summary json: {args.summary_json}")
    return 1 if summary["n_failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
