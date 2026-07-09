"""Build a compact QC manifest for converted T1 FLASH sessions."""

from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path
from typing import Any

import nibabel as nib
import numpy as np
from scipy import ndimage as ndi

from lys_bbb.flash_cohort import parse_case_id, timepoint_sort_key
from lys_bbb.flash_pair import load_float, qc_mask, voxel_sizes


DEFAULT_MANUAL_MASK_PATTERNS = (
    "{case_id}_pre_manual_mask_done.nii.gz",
    "{case_id}_pre_manual_mask.nii.gz",
    "{case_id}_manual_mask.nii.gz",
)

DEFAULT_MBE_MASK_PATTERNS = (
    "{case_id}_mousebrainextractor_mask.nii.gz",
)

MANIFEST_FIELDS = [
    "case_id",
    "animal_id",
    "timepoint",
    "session_dir",
    "pre_path",
    "post_path",
    "pre_exists",
    "post_exists",
    "pre_shape",
    "post_shape",
    "voxel_sizes_mm",
    "pre_post_shape_match",
    "pre_post_affine_match",
    "pre_post_max_affine_diff",
    "pre_post_origin_distance_mm",
    "manual_mask_path",
    "manual_mask_done_name",
    "manual_mask_grid_ok",
    "manual_mask_voxels",
    "manual_mask_volume_mm3",
    "manual_mask_components",
    "manual_mask_largest_component_pct",
    "manual_mask_small_components",
    "manual_mask_qc_png",
    "mbe_mask_path",
    "mbe_mask_grid_ok",
    "mbe_mask_voxels",
    "mbe_mask_volume_mm3",
    "mbe_mask_components",
    "mbe_mask_largest_component_pct",
    "mbe_mask_small_components",
    "mbe_mask_qc_png",
    "manual_mbe_dice",
    "manual_mbe_xor_voxels",
    "registration_qc_png",
    "registration_transform",
    "registration_source_match",
    "registration_before_xcorr",
    "registration_after_xcorr",
    "registration_delta_xcorr",
    "qc_status",
    "qc_notes",
]


def csv_value(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, float) and math.isnan(value):
        return ""
    return value


def split_patterns(values: list[str] | None, defaults: tuple[str, ...]) -> list[str]:
    if not values:
        return list(defaults)
    patterns: list[str] = []
    for value in values:
        patterns.extend(part.strip() for part in value.split(",") if part.strip())
    return patterns


def discover_case_dirs(input_root: Path) -> list[Path]:
    return sorted(
        (path for path in input_root.iterdir() if path.is_dir()),
        key=lambda path: (
            parse_case_id(path.name).animal_id if parse_case_id(path.name) else path.name,
            timepoint_sort_key(parse_case_id(path.name).timepoint) if parse_case_id(path.name) else (10_000, ""),
            path.name,
        ),
    )


def find_existing_path(base_dir: Path | None, patterns: list[str], case_id: str) -> Path | None:
    if base_dir is None:
        return None
    parts = parse_case_id(case_id)
    animal_id = parts.animal_id if parts else ""
    timepoint = parts.timepoint if parts else ""
    for pattern in patterns:
        candidate = base_dir / pattern.format(
            case_id=case_id,
            animal_id=animal_id,
            timepoint=timepoint,
        )
        if candidate.exists():
            return candidate
    return None


def shape_text(shape: tuple[int, ...] | None) -> str:
    return "x".join(str(value) for value in shape) if shape else ""


def voxel_sizes_text(img: nib.Nifti1Image | None) -> str:
    if img is None:
        return ""
    return "x".join(f"{value:.4f}" for value in voxel_sizes(img))


def affine_comparison(
    ref_img: nib.Nifti1Image | None,
    other_img: nib.Nifti1Image | None,
    *,
    atol: float = 1e-3,
) -> dict[str, Any]:
    if ref_img is None or other_img is None:
        return {
            "shape_match": "",
            "affine_match": "",
            "max_affine_diff": "",
            "origin_distance_mm": "",
        }
    shape_match = ref_img.shape == other_img.shape
    diff = np.abs(ref_img.affine - other_img.affine)
    max_affine_diff = float(np.max(diff))
    origin_distance = float(np.linalg.norm(ref_img.affine[:3, 3] - other_img.affine[:3, 3]))
    return {
        "shape_match": shape_match,
        "affine_match": bool(shape_match and np.allclose(ref_img.affine, other_img.affine, atol=atol)),
        "max_affine_diff": max_affine_diff,
        "origin_distance_mm": origin_distance,
    }


def load_mask(path: Path) -> tuple[nib.Nifti1Image, np.ndarray]:
    img = nib.load(str(path))
    if len(img.shape) != 3:
        raise ValueError(f"expected 3D mask: {path}")
    return img, img.get_fdata(dtype=np.float32) > 0


def mask_metrics(mask: np.ndarray, voxel_volume_mm3: float, *, small_component_voxels: int = 100) -> dict[str, Any]:
    voxels = int(np.count_nonzero(mask))
    labels, n_components = ndi.label(mask)
    sizes = np.bincount(labels.ravel())[1:]
    largest = int(sizes.max()) if sizes.size else 0
    small_components = int(np.count_nonzero(sizes < small_component_voxels)) if sizes.size else 0
    largest_pct = float(100.0 * largest / voxels) if voxels else float("nan")
    return {
        "voxels": voxels,
        "volume_mm3": float(voxels * voxel_volume_mm3),
        "components": int(n_components),
        "largest_component_pct": largest_pct,
        "small_components": small_components,
    }


def dice_and_xor(a: np.ndarray, b: np.ndarray) -> tuple[float, int]:
    denom = int(np.count_nonzero(a) + np.count_nonzero(b))
    intersection = int(np.count_nonzero(a & b))
    xor_voxels = int(np.count_nonzero(a ^ b))
    dice = float(2.0 * intersection / denom) if denom else float("nan")
    return dice, xor_voxels


def read_registration_summary(path: Path | None) -> dict[str, dict[str, str]]:
    if path is None or not path.exists():
        return {}
    with path.open(newline="") as handle:
        return {row["case_id"]: row for row in csv.DictReader(handle) if row.get("case_id")}


def paths_match(a: str | Path, b: str | Path) -> bool:
    if not a or not b:
        return False
    path_a = Path(a)
    path_b = Path(b)
    try:
        return path_a.resolve() == path_b.resolve()
    except OSError:
        return path_a == path_b


def add_mask_info(
    row: dict[str, Any],
    *,
    prefix: str,
    mask_path: Path | None,
    pre_img: nib.Nifti1Image | None,
    pre_data: np.ndarray | None,
    out_dir: Path,
    write_qc: bool,
    mask_slice_start: int,
    mask_slice_stop: int,
) -> np.ndarray | None:
    row[f"{prefix}_mask_path"] = str(mask_path or "")
    row[f"{prefix}_mask_grid_ok"] = ""
    row[f"{prefix}_mask_voxels"] = ""
    row[f"{prefix}_mask_volume_mm3"] = ""
    row[f"{prefix}_mask_components"] = ""
    row[f"{prefix}_mask_largest_component_pct"] = ""
    row[f"{prefix}_mask_small_components"] = ""
    row[f"{prefix}_mask_qc_png"] = ""
    if prefix == "manual":
        row["manual_mask_done_name"] = bool(mask_path and "_done" in mask_path.name)

    if mask_path is None or pre_img is None:
        return None

    try:
        mask_img, mask = load_mask(mask_path)
        comparison = affine_comparison(pre_img, mask_img)
        grid_ok = bool(comparison["shape_match"] and comparison["affine_match"])
        row[f"{prefix}_mask_grid_ok"] = grid_ok
        if not grid_ok:
            return mask

        metrics = mask_metrics(mask, float(abs(np.linalg.det(pre_img.affine[:3, :3]))))
        row[f"{prefix}_mask_voxels"] = metrics["voxels"]
        row[f"{prefix}_mask_volume_mm3"] = metrics["volume_mm3"]
        row[f"{prefix}_mask_components"] = metrics["components"]
        row[f"{prefix}_mask_largest_component_pct"] = metrics["largest_component_pct"]
        row[f"{prefix}_mask_small_components"] = metrics["small_components"]
        if write_qc and pre_data is not None:
            qc_path = out_dir / "brain_masks" / prefix / f"{row['case_id']}_{prefix}_mask_qc.png"
            qc_mask(pre_data, mask, qc_path, slice_start=mask_slice_start, slice_stop=mask_slice_stop)
            row[f"{prefix}_mask_qc_png"] = str(qc_path)
        return mask
    except Exception as exc:
        row[f"{prefix}_mask_grid_ok"] = f"error: {type(exc).__name__}: {exc}"
        return None


def status_for_row(row: dict[str, Any]) -> tuple[str, str]:
    notes: list[str] = []
    if not row["pre_exists"] or not row["post_exists"]:
        return "missing_conversion", "missing pre or post converted image"
    if row["pre_post_shape_match"] is False:
        return "pre_post_grid_error", "pre/post shapes differ"
    if row["pre_post_affine_match"] is False:
        notes.append("pre/post affines differ; registration required")
    if not row["manual_mask_path"]:
        notes.append("missing corrected brain mask")
        return "needs_brain_mask", "; ".join(notes)
    if row["manual_mask_grid_ok"] is not True:
        notes.append("manual mask grid does not match pre image")
        return "mask_grid_error", "; ".join(notes)
    if row.get("manual_mbe_dice") not in ("", None):
        try:
            if float(row["manual_mbe_dice"]) >= 0.999:
                notes.append("manual mask is identical to MouseBrainExtractor pre-label")
        except (TypeError, ValueError):
            pass
    if not row.get("manual_mask_done_name"):
        notes.append("manual mask filename is not marked done")
    try:
        if int(row.get("manual_mask_components") or 0) > 1:
            notes.append("manual mask has multiple connected components")
    except (TypeError, ValueError):
        pass
    if not row.get("registration_qc_png"):
        notes.append("missing registration QC")
    elif row.get("registration_source_match") is False:
        notes.append("registration QC source paths differ from audited pre/post paths")
    if notes:
        return "needs_review", "; ".join(notes)
    return "ready_for_provisional_quantification", ""


def build_manifest_rows(
    input_root: Path,
    *,
    manual_mask_dir: Path | None,
    manual_mask_patterns: list[str],
    mbe_mask_dir: Path | None,
    mbe_mask_patterns: list[str],
    registration_summary: Path | None,
    out_dir: Path,
    write_mask_qc: bool,
    mask_slice_start: int,
    mask_slice_stop: int,
) -> list[dict[str, Any]]:
    registrations = read_registration_summary(registration_summary)
    rows: list[dict[str, Any]] = []
    for session_dir in discover_case_dirs(input_root):
        case_id = session_dir.name
        parts = parse_case_id(case_id)
        pre_path = session_dir / "pre_coronal.nii.gz"
        post_path = session_dir / "post_coronal.nii.gz"
        pre_exists = pre_path.exists()
        post_exists = post_path.exists()
        pre_img = post_img = None
        pre_data = None
        if pre_exists:
            pre_img, pre_data = load_float(pre_path)
        if post_exists:
            post_img = nib.load(str(post_path))

        comparison = affine_comparison(pre_img, post_img)
        row: dict[str, Any] = {
            "case_id": case_id,
            "animal_id": parts.animal_id if parts else "",
            "timepoint": parts.timepoint if parts else "",
            "session_dir": str(session_dir),
            "pre_path": str(pre_path if pre_exists else ""),
            "post_path": str(post_path if post_exists else ""),
            "pre_exists": pre_exists,
            "post_exists": post_exists,
            "pre_shape": shape_text(pre_img.shape if pre_img is not None else None),
            "post_shape": shape_text(post_img.shape if post_img is not None else None),
            "voxel_sizes_mm": voxel_sizes_text(pre_img),
            "pre_post_shape_match": comparison["shape_match"],
            "pre_post_affine_match": comparison["affine_match"],
            "pre_post_max_affine_diff": comparison["max_affine_diff"],
            "pre_post_origin_distance_mm": comparison["origin_distance_mm"],
        }

        manual_mask_path = find_existing_path(manual_mask_dir, manual_mask_patterns, case_id)
        mbe_mask_path = find_existing_path(mbe_mask_dir, mbe_mask_patterns, case_id)
        manual_mask = add_mask_info(
            row,
            prefix="manual",
            mask_path=manual_mask_path,
            pre_img=pre_img,
            pre_data=pre_data,
            out_dir=out_dir,
            write_qc=write_mask_qc,
            mask_slice_start=mask_slice_start,
            mask_slice_stop=mask_slice_stop,
        )
        mbe_mask = add_mask_info(
            row,
            prefix="mbe",
            mask_path=mbe_mask_path,
            pre_img=pre_img,
            pre_data=pre_data,
            out_dir=out_dir,
            write_qc=write_mask_qc,
            mask_slice_start=mask_slice_start,
            mask_slice_stop=mask_slice_stop,
        )
        row["manual_mbe_dice"] = ""
        row["manual_mbe_xor_voxels"] = ""
        if manual_mask is not None and mbe_mask is not None and manual_mask.shape == mbe_mask.shape:
            row["manual_mbe_dice"], row["manual_mbe_xor_voxels"] = dice_and_xor(manual_mask, mbe_mask)

        registration = registrations.get(case_id, {})
        row["registration_qc_png"] = registration.get("qc_png", "")
        row["registration_transform"] = registration.get("transform", "")
        row["registration_source_match"] = (
            paths_match(row["pre_path"], registration.get("pre", ""))
            and paths_match(row["post_path"], registration.get("post", ""))
            if registration
            else ""
        )
        row["registration_before_xcorr"] = registration.get("before_xcorr", "")
        row["registration_after_xcorr"] = registration.get("after_xcorr", "")
        row["registration_delta_xcorr"] = ""
        try:
            before = float(row["registration_before_xcorr"])
            after = float(row["registration_after_xcorr"])
            row["registration_delta_xcorr"] = after - before
        except (TypeError, ValueError):
            pass

        row["qc_status"], row["qc_notes"] = status_for_row(row)
        rows.append(row)
    return rows


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=MANIFEST_FIELDS, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: csv_value(row.get(field, "")) for field in MANIFEST_FIELDS})


def write_summary(path: Path, rows: list[dict[str, Any]]) -> dict[str, Any]:
    status_counts: dict[str, int] = {}
    for row in rows:
        status = str(row.get("qc_status", ""))
        status_counts[status] = status_counts.get(status, 0) + 1
    summary = {
        "n_cases": len(rows),
        "n_converted_pre_post": sum(1 for row in rows if row.get("pre_exists") and row.get("post_exists")),
        "n_with_manual_mask": sum(1 for row in rows if row.get("manual_mask_path")),
        "n_with_mbe_mask": sum(1 for row in rows if row.get("mbe_mask_path")),
        "n_with_registration_qc": sum(1 for row in rows if row.get("registration_qc_png")),
        "status_counts": status_counts,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(summary, indent=2) + "\n")
    return summary


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build a QC manifest for converted T1 FLASH cases and available brain masks.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--input-root", type=Path, default=Path("output/all_mice"))
    parser.add_argument("-o", "--out-dir", type=Path, default=Path("reports/qc"))
    parser.add_argument("--manual-mask-dir", type=Path, default=Path("derivatives/brain_seg/manual"))
    parser.add_argument("--manual-mask-pattern", action="append", default=None)
    parser.add_argument("--mbe-mask-dir", type=Path, default=Path("derivatives/brain_seg/mousebrainextractor"))
    parser.add_argument("--mbe-mask-pattern", action="append", default=None)
    parser.add_argument("--registration-summary", type=Path, default=Path("derivatives/registration_qc/test_mice/registration_qc_summary.csv"))
    parser.add_argument("--no-mask-qc", action="store_true", help="skip writing brain-mask QC PNGs")
    parser.add_argument("--mask-slice-start", type=int, default=50)
    parser.add_argument("--mask-slice-stop", type=int, default=170)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    rows = build_manifest_rows(
        args.input_root,
        manual_mask_dir=args.manual_mask_dir,
        manual_mask_patterns=split_patterns(args.manual_mask_pattern, DEFAULT_MANUAL_MASK_PATTERNS),
        mbe_mask_dir=args.mbe_mask_dir,
        mbe_mask_patterns=split_patterns(args.mbe_mask_pattern, DEFAULT_MBE_MASK_PATTERNS),
        registration_summary=args.registration_summary,
        out_dir=args.out_dir,
        write_mask_qc=not args.no_mask_qc,
        mask_slice_start=args.mask_slice_start,
        mask_slice_stop=args.mask_slice_stop,
    )
    manifest_path = args.out_dir / "qc_manifest.csv"
    summary_path = args.out_dir / "qc_summary.json"
    write_csv(manifest_path, rows)
    summary = write_summary(summary_path, rows)
    print(f"cases: {summary['n_cases']}")
    print(f"converted pre/post: {summary['n_converted_pre_post']}")
    print(f"manual masks: {summary['n_with_manual_mask']}")
    print(f"registration QC: {summary['n_with_registration_qc']}")
    print(f"manifest: {manifest_path}")
    print(f"summary: {summary_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
