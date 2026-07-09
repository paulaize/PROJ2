"""Validate brain-mask candidates from manual labels or model predictions."""

from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path
from typing import Any

import nibabel as nib
import numpy as np

from lys_bbb.flash_cohort import parse_case_id, timepoint_sort_key
from lys_bbb.flash_pair import load_float, qc_mask, voxel_sizes
from lys_bbb.mask_workflow import as_float
from lys_bbb.qc_manifest import (
    affine_comparison,
    find_existing_path,
    load_mask,
    mask_metrics,
    paths_match,
    read_registration_summary,
    split_patterns,
)


DEFAULT_MASK_PATTERNS = (
    "{case_id}.nii.gz",
    "{case_id}_brain_mask.nii.gz",
    "{case_id}_pred.nii.gz",
    "{case_id}_pre_manual_mask_done.nii.gz",
    "{case_id}_pre_manual_mask.nii.gz",
)


BRAIN_MASK_FIELDS = [
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
    "brain_mask_path",
    "brain_mask_source",
    "brain_mask_grid_ok",
    "brain_mask_voxels",
    "brain_mask_volume_mm3",
    "brain_mask_components",
    "brain_mask_largest_component_pct",
    "brain_mask_small_components",
    "brain_mask_qc_png",
    "brain_mask_status",
    "brain_mask_notes",
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


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: csv_value(row.get(field, "")) for field in fields})


def discover_case_dirs(input_root: Path) -> list[Path]:
    return sorted(
        (path for path in input_root.iterdir() if path.is_dir()),
        key=lambda path: (
            parse_case_id(path.name).animal_id if parse_case_id(path.name) else path.name,
            timepoint_sort_key(parse_case_id(path.name).timepoint) if parse_case_id(path.name) else (10_000, ""),
            path.name,
        ),
    )


def shape_text(shape: tuple[int, ...] | None) -> str:
    return "x".join(str(value) for value in shape) if shape else ""


def voxel_sizes_text(img: nib.Nifti1Image | None) -> str:
    if img is None:
        return ""
    return "x".join(f"{value:.4f}" for value in voxel_sizes(img))


def candidate_status(
    row: dict[str, Any],
    *,
    max_components: int,
    min_largest_component_pct: float,
    min_volume_mm3: float | None,
    max_volume_mm3: float | None,
) -> tuple[str, str]:
    if not row.get("pre_exists") or not row.get("post_exists"):
        return "missing_conversion", "missing pre or post converted image"
    if not row.get("brain_mask_path"):
        return "missing_brain_mask", "missing brain-mask candidate"
    if row.get("brain_mask_grid_ok") is not True:
        return "mask_grid_error", "brain mask grid does not match pre image"

    notes: list[str] = []
    components = row.get("brain_mask_components")
    if components not in ("", None) and int(components) > max_components:
        notes.append(f"components {components} > {max_components}")
    largest_pct = as_float(row.get("brain_mask_largest_component_pct"))
    if largest_pct is not None and largest_pct < min_largest_component_pct:
        notes.append(f"largest component {largest_pct:.2f}% < {min_largest_component_pct:.2f}%")
    volume = as_float(row.get("brain_mask_volume_mm3"))
    if volume is not None and min_volume_mm3 is not None and volume < min_volume_mm3:
        notes.append(f"volume {volume:.2f} mm3 < {min_volume_mm3:.2f} mm3")
    if volume is not None and max_volume_mm3 is not None and volume > max_volume_mm3:
        notes.append(f"volume {volume:.2f} mm3 > {max_volume_mm3:.2f} mm3")
    if notes:
        return "needs_review", "; ".join(notes)
    return "ready_candidate", ""


def combined_qc_status(row: dict[str, Any]) -> tuple[str, str]:
    notes = [row.get("brain_mask_notes", "")]
    status = row.get("brain_mask_status", "")
    if status not in {"ready_candidate", ""}:
        return str(status), "; ".join(note for note in notes if note)
    if not row.get("registration_qc_png"):
        notes.append("missing registration QC")
        return "needs_review", "; ".join(note for note in notes if note)
    if row.get("registration_source_match") is False:
        notes.append("registration QC source paths differ from audited pre/post paths")
        return "needs_review", "; ".join(note for note in notes if note)
    return "ready_for_analysis_manifest", "; ".join(note for note in notes if note)


def add_candidate_mask(
    row: dict[str, Any],
    *,
    mask_path: Path | None,
    mask_source: str,
    pre_img: nib.Nifti1Image | None,
    pre_data: np.ndarray | None,
    out_dir: Path,
    write_qc: bool,
    mask_slice_start: int,
    mask_slice_stop: int,
) -> None:
    row["brain_mask_path"] = str(mask_path or "")
    row["brain_mask_source"] = mask_source
    row["brain_mask_grid_ok"] = ""
    row["brain_mask_voxels"] = ""
    row["brain_mask_volume_mm3"] = ""
    row["brain_mask_components"] = ""
    row["brain_mask_largest_component_pct"] = ""
    row["brain_mask_small_components"] = ""
    row["brain_mask_qc_png"] = ""

    if mask_path is None or pre_img is None:
        return

    try:
        mask_img, mask = load_mask(mask_path)
        comparison = affine_comparison(pre_img, mask_img)
        grid_ok = bool(comparison["shape_match"] and comparison["affine_match"])
        row["brain_mask_grid_ok"] = grid_ok
        if not grid_ok:
            return

        metrics = mask_metrics(mask, float(abs(np.linalg.det(pre_img.affine[:3, :3]))))
        row["brain_mask_voxels"] = metrics["voxels"]
        row["brain_mask_volume_mm3"] = metrics["volume_mm3"]
        row["brain_mask_components"] = metrics["components"]
        row["brain_mask_largest_component_pct"] = metrics["largest_component_pct"]
        row["brain_mask_small_components"] = metrics["small_components"]
        if write_qc and pre_data is not None:
            qc_path = out_dir / "brain_masks" / mask_source / f"{row['case_id']}_{mask_source}_brain_mask_qc.png"
            qc_mask(pre_data, mask, qc_path, slice_start=mask_slice_start, slice_stop=mask_slice_stop)
            row["brain_mask_qc_png"] = str(qc_path)
    except Exception as exc:
        row["brain_mask_grid_ok"] = f"error: {type(exc).__name__}: {exc}"


def build_brain_mask_manifest_rows(
    input_root: Path,
    *,
    mask_dir: Path | None,
    mask_patterns: list[str],
    mask_source: str,
    registration_summary: Path | None,
    out_dir: Path,
    write_mask_qc: bool,
    mask_slice_start: int,
    mask_slice_stop: int,
    max_components: int,
    min_largest_component_pct: float,
    min_volume_mm3: float | None,
    max_volume_mm3: float | None,
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
        }
        mask_path = find_existing_path(mask_dir, mask_patterns, case_id)
        add_candidate_mask(
            row,
            mask_path=mask_path,
            mask_source=mask_source,
            pre_img=pre_img,
            pre_data=pre_data,
            out_dir=out_dir,
            write_qc=write_mask_qc,
            mask_slice_start=mask_slice_start,
            mask_slice_stop=mask_slice_stop,
        )
        row["brain_mask_status"], row["brain_mask_notes"] = candidate_status(
            row,
            max_components=max_components,
            min_largest_component_pct=min_largest_component_pct,
            min_volume_mm3=min_volume_mm3,
            max_volume_mm3=max_volume_mm3,
        )

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
        row["qc_status"], row["qc_notes"] = combined_qc_status(row)
        rows.append(row)
    return rows


def write_summary(path: Path, rows: list[dict[str, Any]]) -> dict[str, Any]:
    status_counts: dict[str, int] = {}
    for row in rows:
        status = str(row.get("brain_mask_status", ""))
        status_counts[status] = status_counts.get(status, 0) + 1
    summary = {
        "n_cases": len(rows),
        "n_with_candidate_mask": sum(1 for row in rows if row.get("brain_mask_path")),
        "n_ready_candidate": status_counts.get("ready_candidate", 0),
        "status_counts": status_counts,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(summary, indent=2) + "\n")
    return summary


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate candidate brain masks from manual labels or model predictions.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--input-root", type=Path, default=Path("output/all_mice"))
    parser.add_argument("--mask-dir", type=Path, default=Path("derivatives/brain_seg/nnunet_preds"))
    parser.add_argument("--mask-pattern", action="append", default=None)
    parser.add_argument("--mask-source", default="nnunet")
    parser.add_argument("--registration-summary", type=Path, default=Path("reports/qc/registration_all_mice/registration_qc_summary.csv"))
    parser.add_argument("-o", "--out-dir", type=Path, default=Path("reports/qc"))
    parser.add_argument("--manifest-name", default="brain_mask_manifest.csv")
    parser.add_argument("--summary-name", default="brain_mask_manifest_summary.json")
    parser.add_argument("--no-mask-qc", action="store_true")
    parser.add_argument("--mask-slice-start", type=int, default=50)
    parser.add_argument("--mask-slice-stop", type=int, default=170)
    parser.add_argument("--max-components", type=int, default=1)
    parser.add_argument("--min-largest-component-pct", type=float, default=99.0)
    parser.add_argument("--min-volume-mm3", type=float, default=None)
    parser.add_argument("--max-volume-mm3", type=float, default=None)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    rows = build_brain_mask_manifest_rows(
        args.input_root,
        mask_dir=args.mask_dir,
        mask_patterns=split_patterns(args.mask_pattern, DEFAULT_MASK_PATTERNS),
        mask_source=args.mask_source,
        registration_summary=args.registration_summary,
        out_dir=args.out_dir,
        write_mask_qc=not args.no_mask_qc,
        mask_slice_start=args.mask_slice_start,
        mask_slice_stop=args.mask_slice_stop,
        max_components=args.max_components,
        min_largest_component_pct=args.min_largest_component_pct,
        min_volume_mm3=args.min_volume_mm3,
        max_volume_mm3=args.max_volume_mm3,
    )
    manifest_path = args.out_dir / args.manifest_name
    summary_path = args.out_dir / args.summary_name
    write_csv(manifest_path, rows, BRAIN_MASK_FIELDS)
    summary = write_summary(summary_path, rows)
    print(f"cases: {summary['n_cases']}")
    print(f"candidate masks: {summary['n_with_candidate_mask']}")
    print(f"ready candidates: {summary['n_ready_candidate']}")
    print(f"manifest: {manifest_path}")
    print(f"summary: {summary_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
