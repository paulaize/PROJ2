"""Batch D1/D7 T1 FLASH gadolinium-enhancement quantification."""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import nibabel as nib
import numpy as np

from lys_bbb.flash_pair import load_float, process_pair, voxel_sizes


CASE_ID_RE = re.compile(r"^(?P<animal_id>C\d+S\d+)_(?P<timepoint>D\d+)(?:_(?P<suffix>.+))?$")
DEFAULT_BRAIN_MASK_PATTERNS = (
    "{case_id}_pre_manual_mask_done.nii.gz",
    "{case_id}_pre_manual_mask.nii.gz",
    "{case_id}_manual_mask.nii.gz",
)
DEFAULT_LESION_MASK_PATTERNS = (
    "{case_id}_lesion_mask.nii.gz",
    "{case_id}_lesion.nii.gz",
    "{case_id}_roi.nii.gz",
)


SESSION_FIELDS = [
    "row_type",
    "case_id",
    "animal_id",
    "group",
    "timepoint",
    "status",
    "notes",
    "session_dir",
    "pre_path",
    "post_path",
    "session_output_dir",
    "percent_enhancement_map",
    "mask_qc_png",
    "enhancement_qc_png",
    "brain_mask_path",
    "brain_mask_source",
    "lesion_mask_path",
    "roi_type",
    "reference_mode",
    "ipsilateral_side",
    "orientation_axis0",
    "voxel_volume_mm3",
    "brain_volume_mm3",
    "lesion_volume_mm3",
    "analysis_roi_volume_mm3",
    "n_roi_voxels",
    "n_enhancing_voxels",
    "mean_ce_pct",
    "median_ce_pct",
    "p95_ce_pct",
    "mean_corrected_ce_pct",
    "median_corrected_ce_pct",
    "p95_corrected_ce_pct",
    "enhancing_volume_mm3",
    "pct_lesion_enhancing",
    "pct_roi_enhancing",
    "integrated_leakage_burden_pct_mm3",
    "thresholded_integrated_leakage_burden_pct_mm3",
    "bbb_leakage_index_pct",
    "ipsi_contra_post_pre_ratio",
    "reference_ce_mean_pct",
    "reference_ce_std_pct",
    "reference_ce_median_pct",
    "reference_ce_p95_pct",
    "enhancement_threshold_ce_pct",
    "threshold_method",
    "registration_metric",
    "registration_method",
    "mask_voxels",
    "outputs_are",
]


DELTA_NUMERIC_FIELDS = [
    "brain_volume_mm3",
    "lesion_volume_mm3",
    "analysis_roi_volume_mm3",
    "mean_ce_pct",
    "median_ce_pct",
    "p95_ce_pct",
    "mean_corrected_ce_pct",
    "median_corrected_ce_pct",
    "p95_corrected_ce_pct",
    "enhancing_volume_mm3",
    "pct_lesion_enhancing",
    "pct_roi_enhancing",
    "integrated_leakage_burden_pct_mm3",
    "thresholded_integrated_leakage_burden_pct_mm3",
    "bbb_leakage_index_pct",
    "ipsi_contra_post_pre_ratio",
]


@dataclass(frozen=True)
class CaseParts:
    case_id: str
    animal_id: str
    timepoint: str
    suffix: str


@dataclass
class SessionSpec:
    case_id: str
    animal_id: str
    timepoint: str
    session_dir: Path
    pre_path: Path
    post_path: Path
    group: str = ""
    include: bool = True
    ipsilateral_side: str = ""
    brain_mask_path: Path | None = None
    lesion_mask_path: Path | None = None
    notes: str = ""


def parse_case_id(case_id: str) -> CaseParts | None:
    match = CASE_ID_RE.match(case_id)
    if match is None:
        return None
    return CaseParts(
        case_id=case_id,
        animal_id=match.group("animal_id"),
        timepoint=match.group("timepoint"),
        suffix=match.group("suffix") or "",
    )


def timepoint_sort_key(timepoint: str) -> tuple[int, str]:
    if len(timepoint) > 1 and timepoint[0].upper() == "D" and timepoint[1:].isdigit():
        return int(timepoint[1:]), timepoint
    return 10_000, timepoint


def truthy(value: Any, default: bool = True) -> bool:
    if value is None or value == "":
        return default
    return str(value).strip().lower() not in {"0", "false", "f", "no", "n", "exclude", "excluded"}


def split_patterns(values: list[str] | None, defaults: tuple[str, ...]) -> list[str]:
    if not values:
        return list(defaults)
    patterns: list[str] = []
    for value in values:
        patterns.extend(part.strip() for part in value.split(",") if part.strip())
    return patterns


def resolve_optional_path(value: Any, base_dir: Path) -> Path | None:
    if value is None or str(value).strip() == "":
        return None
    path = Path(str(value).strip()).expanduser()
    if path.is_absolute():
        return path
    candidate = base_dir / path
    return candidate if candidate.exists() else path


def read_session_overrides(path: Path | None) -> dict[str, dict[str, Any]]:
    if path is None:
        return {}
    overrides: dict[str, dict[str, Any]] = {}
    base_dir = path.parent
    with path.open(newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            key = row.get("case_id") or ""
            if not key:
                animal_id = row.get("animal_id") or row.get("animal") or ""
                timepoint = row.get("timepoint") or ""
                if animal_id and timepoint:
                    key = f"{animal_id}_{timepoint}"
            if not key:
                continue
            cleaned = {k: v for k, v in row.items() if k is not None}
            for path_key in ("brain_mask", "brain_mask_path", "mask", "lesion_mask", "lesion_mask_path"):
                if path_key in cleaned:
                    resolved = resolve_optional_path(cleaned[path_key], base_dir)
                    cleaned[path_key] = str(resolved) if resolved is not None else ""
            overrides[key] = cleaned
    return overrides


def find_mask_path(mask_dir: Path | None, patterns: list[str], spec: SessionSpec) -> Path | None:
    if mask_dir is None:
        return None
    for pattern in patterns:
        candidate = mask_dir / pattern.format(
            case_id=spec.case_id,
            animal_id=spec.animal_id,
            timepoint=spec.timepoint,
        )
        if candidate.exists():
            return candidate
    return None


def apply_overrides(spec: SessionSpec, overrides: dict[str, dict[str, Any]]) -> SessionSpec:
    row = overrides.get(spec.case_id) or overrides.get(f"{spec.animal_id}_{spec.timepoint}") or {}
    if not row:
        return spec
    spec.group = row.get("group", spec.group) or spec.group
    spec.include = truthy(row.get("include", row.get("status")), default=True)
    spec.ipsilateral_side = (
        row.get("ipsilateral_side")
        or row.get("lesion_side")
        or row.get("stroke_side")
        or spec.ipsilateral_side
        or ""
    )
    brain_mask = row.get("brain_mask_path") or row.get("brain_mask") or row.get("mask")
    lesion_mask = row.get("lesion_mask_path") or row.get("lesion_mask")
    if brain_mask:
        spec.brain_mask_path = Path(brain_mask)
    if lesion_mask:
        spec.lesion_mask_path = Path(lesion_mask)
    note = row.get("notes") or row.get("note") or ""
    if note:
        spec.notes = note
    return spec


def discover_sessions(
    input_root: Path,
    *,
    overrides: dict[str, dict[str, Any]] | None = None,
    brain_mask_dir: Path | None = None,
    brain_mask_patterns: list[str] | None = None,
    lesion_mask_dir: Path | None = None,
    lesion_mask_patterns: list[str] | None = None,
    ipsilateral_side: str = "",
) -> list[SessionSpec]:
    overrides = overrides or {}
    brain_mask_patterns = brain_mask_patterns or list(DEFAULT_BRAIN_MASK_PATTERNS)
    lesion_mask_patterns = lesion_mask_patterns or list(DEFAULT_LESION_MASK_PATTERNS)
    sessions: list[SessionSpec] = []
    for session_dir in sorted(p for p in input_root.iterdir() if p.is_dir()):
        parts = parse_case_id(session_dir.name)
        pre_path = session_dir / "pre_coronal.nii.gz"
        post_path = session_dir / "post_coronal.nii.gz"
        if parts is None or not pre_path.exists() or not post_path.exists():
            continue
        spec = SessionSpec(
            case_id=parts.case_id,
            animal_id=parts.animal_id,
            timepoint=parts.timepoint,
            session_dir=session_dir,
            pre_path=pre_path,
            post_path=post_path,
            ipsilateral_side=ipsilateral_side or "",
        )
        spec = apply_overrides(spec, overrides)
        if spec.brain_mask_path is None:
            spec.brain_mask_path = find_mask_path(brain_mask_dir, brain_mask_patterns, spec)
        if spec.lesion_mask_path is None:
            spec.lesion_mask_path = find_mask_path(lesion_mask_dir, lesion_mask_patterns, spec)
        sessions.append(spec)
    return sorted(
        sessions,
        key=lambda spec: (spec.animal_id, timepoint_sort_key(spec.timepoint), spec.case_id),
    )


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: csv_value(row.get(field, "")) for field in fieldnames})


def csv_value(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, float) and math.isnan(value):
        return ""
    return value


def session_manifest_rows(sessions: list[SessionSpec]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for spec in sessions:
        rows.append(
            {
                "case_id": spec.case_id,
                "animal_id": spec.animal_id,
                "timepoint": spec.timepoint,
                "group": spec.group,
                "include": spec.include,
                "ipsilateral_side": spec.ipsilateral_side,
                "pre_path": str(spec.pre_path),
                "post_path": str(spec.post_path),
                "brain_mask_path": str(spec.brain_mask_path or ""),
                "lesion_mask_path": str(spec.lesion_mask_path or ""),
                "notes": spec.notes,
            }
        )
    return rows


def load_matching_mask(mask_path: Path, ref_img: nib.Nifti1Image, *, label: str) -> np.ndarray:
    mask_img, mask_data = load_float(mask_path)
    if mask_data.shape != ref_img.shape or not np.allclose(mask_img.affine, ref_img.affine, atol=1e-3):
        raise ValueError(f"{label} must match percent-enhancement image shape and affine: {mask_path}")
    return mask_data > 0


def brain_bbox_midline(brain_mask: np.ndarray) -> tuple[int, int, int]:
    xs = np.flatnonzero(np.any(brain_mask, axis=(1, 2)))
    if xs.size == 0:
        raise ValueError("empty brain mask")
    x_min = int(xs[0])
    x_max = int(xs[-1])
    return x_min, x_max, (x_min + x_max) // 2


def hemisphere_masks(
    brain_mask: np.ndarray,
    affine: np.ndarray,
    ipsilateral_side: str,
) -> tuple[np.ndarray, np.ndarray, str]:
    side = ipsilateral_side.lower().replace("_", "-")
    if side not in {"left", "right", "low-x", "high-x"}:
        raise ValueError("ipsilateral side must be one of: left, right, low-x, high-x")

    x_min, x_max, x_mid = brain_bbox_midline(brain_mask)
    x_index = np.arange(brain_mask.shape[0])[:, None, None]
    low_x = (x_index >= x_min) & (x_index <= x_mid)
    high_x = (x_index > x_mid) & (x_index <= x_max)

    axis0_code = nib.aff2axcodes(affine)[0]
    if side in {"left", "right"}:
        if axis0_code == "R":
            use_low_x = side == "left"
        elif axis0_code == "L":
            use_low_x = side == "right"
        else:
            raise ValueError(
                f"cannot map anatomical side {side!r} because NIfTI axis 0 code is {axis0_code!r}; "
                "use low-x or high-x instead"
            )
    else:
        use_low_x = side == "low-x"

    ipsi = brain_mask & (low_x if use_low_x else high_x)
    contra = brain_mask & (high_x if use_low_x else low_x)
    return ipsi, contra, axis0_code


def mirrored_roi_reference(roi_mask: np.ndarray, brain_mask: np.ndarray, contra_mask: np.ndarray) -> np.ndarray:
    x_min, x_max, _ = brain_bbox_midline(brain_mask)
    mirrored = np.zeros_like(roi_mask, dtype=bool)
    slab = roi_mask[x_min:x_max + 1, :, :]
    mirrored[x_min:x_max + 1, :, :] = np.flip(slab, axis=0)
    return mirrored & brain_mask & contra_mask


def finite_values(data: np.ndarray, mask: np.ndarray) -> np.ndarray:
    values = data[mask]
    return values[np.isfinite(values)]


def safe_stat(values: np.ndarray, func: str) -> float:
    values = values[np.isfinite(values)]
    if values.size == 0:
        return float("nan")
    if func == "mean":
        return float(np.mean(values))
    if func == "std":
        return float(np.std(values))
    if func == "median":
        return float(np.median(values))
    if func == "p95":
        return float(np.percentile(values, 95))
    raise ValueError(f"unknown statistic: {func}")


def compute_threshold(
    ce_map: np.ndarray,
    reference_mask: np.ndarray | None,
    reference_median: float,
    threshold_method: str,
    threshold_corrected_ce_pct: float,
) -> tuple[float, str]:
    if reference_mask is None or not np.any(reference_mask):
        return float(threshold_corrected_ce_pct), "absolute_ce_gt"
    reference_values = finite_values(ce_map, reference_mask)
    if reference_values.size == 0:
        return float(reference_median + threshold_corrected_ce_pct), "corrected_gt"
    method = "contra_p95" if threshold_method == "auto" else threshold_method
    if method == "contra_p95":
        return float(np.percentile(reference_values, 95)), method
    if method == "contra_mean_2sd":
        return float(np.mean(reference_values) + 2.0 * np.std(reference_values)), method
    if method == "corrected_gt":
        return float(reference_median + threshold_corrected_ce_pct), method
    raise ValueError(f"unknown threshold method: {threshold_method}")


def quantify_enhancement(
    ce_map: np.ndarray,
    brain_mask: np.ndarray,
    *,
    affine: np.ndarray,
    voxel_volume_mm3: float,
    lesion_mask: np.ndarray | None = None,
    ipsilateral_side: str = "",
    reference_mode: str = "mirrored_roi",
    threshold_method: str = "auto",
    threshold_corrected_ce_pct: float = 10.0,
) -> dict[str, Any]:
    brain_mask = brain_mask & np.isfinite(ce_map)
    if not np.any(brain_mask):
        raise ValueError("brain mask has no finite enhancement voxels")

    reference_mask: np.ndarray | None = None
    orientation_axis0 = nib.aff2axcodes(affine)[0]
    if ipsilateral_side:
        ipsi_mask, contra_mask, orientation_axis0 = hemisphere_masks(brain_mask, affine, ipsilateral_side)
        if lesion_mask is None:
            roi_mask = ipsi_mask
            roi_type = "ipsilateral_brain_half"
        else:
            roi_mask = lesion_mask & brain_mask
            roi_type = "lesion_mask"
        if reference_mode == "mirrored_roi" and lesion_mask is not None:
            reference_mask = mirrored_roi_reference(roi_mask, brain_mask, contra_mask)
            if not np.any(reference_mask):
                reference_mask = contra_mask
                reference_mode_used = "contralateral_hemisphere_fallback"
            else:
                reference_mode_used = "mirrored_roi"
        elif reference_mode == "contralateral_hemisphere":
            reference_mask = contra_mask
            reference_mode_used = "contralateral_hemisphere"
        else:
            raise ValueError(f"unknown reference mode: {reference_mode}")
    else:
        roi_mask = (lesion_mask & brain_mask) if lesion_mask is not None else brain_mask
        roi_type = "lesion_mask" if lesion_mask is not None else "brain_mask"
        reference_mode_used = "none"

    roi_values = finite_values(ce_map, roi_mask)
    if roi_values.size == 0:
        raise ValueError("analysis ROI has no finite enhancement voxels")

    reference_values = finite_values(ce_map, reference_mask) if reference_mask is not None else np.array([])
    reference_median = safe_stat(reference_values, "median") if reference_values.size else 0.0
    corrected = ce_map - reference_median
    corrected_values = finite_values(corrected, roi_mask)

    threshold_raw, threshold_method_used = compute_threshold(
        ce_map,
        reference_mask,
        reference_median,
        threshold_method,
        threshold_corrected_ce_pct,
    )
    enhancing_mask = roi_mask & np.isfinite(ce_map) & (ce_map > threshold_raw) & (corrected > 0)
    positive_corrected = corrected_values[corrected_values > 0]
    thresholded_corrected = corrected[enhancing_mask]
    thresholded_corrected = thresholded_corrected[np.isfinite(thresholded_corrected)]
    thresholded_corrected = thresholded_corrected[thresholded_corrected > 0]

    brain_voxels = int(np.count_nonzero(brain_mask))
    roi_voxels = int(np.count_nonzero(roi_mask & np.isfinite(ce_map)))
    enhancing_voxels = int(np.count_nonzero(enhancing_mask))
    lesion_voxels = int(np.count_nonzero(lesion_mask & brain_mask)) if lesion_mask is not None else 0

    ratio_map = 1.0 + ce_map / 100.0
    ratio_roi = finite_values(ratio_map, roi_mask)
    ratio_ref = finite_values(ratio_map, reference_mask) if reference_mask is not None else np.array([])
    if ratio_ref.size and np.nanmedian(ratio_ref) != 0:
        ipsi_contra_ratio = float(np.nanmedian(ratio_roi) / np.nanmedian(ratio_ref))
        bbb_index = float((ipsi_contra_ratio - 1.0) * 100.0)
    else:
        ipsi_contra_ratio = float("nan")
        bbb_index = float("nan")

    roi_volume_mm3 = float(roi_voxels * voxel_volume_mm3)
    lesion_volume_mm3 = float(lesion_voxels * voxel_volume_mm3) if lesion_mask is not None else float("nan")
    enhancing_volume_mm3 = float(enhancing_voxels * voxel_volume_mm3)

    return {
        "roi_type": roi_type,
        "reference_mode": reference_mode_used,
        "orientation_axis0": orientation_axis0,
        "voxel_volume_mm3": float(voxel_volume_mm3),
        "brain_volume_mm3": float(brain_voxels * voxel_volume_mm3),
        "lesion_volume_mm3": lesion_volume_mm3,
        "analysis_roi_volume_mm3": roi_volume_mm3,
        "n_roi_voxels": roi_voxels,
        "n_enhancing_voxels": enhancing_voxels,
        "mean_ce_pct": safe_stat(roi_values, "mean"),
        "median_ce_pct": safe_stat(roi_values, "median"),
        "p95_ce_pct": safe_stat(roi_values, "p95"),
        "mean_corrected_ce_pct": safe_stat(corrected_values, "mean"),
        "median_corrected_ce_pct": safe_stat(corrected_values, "median"),
        "p95_corrected_ce_pct": safe_stat(corrected_values, "p95"),
        "enhancing_volume_mm3": enhancing_volume_mm3,
        "pct_lesion_enhancing": (
            float(enhancing_voxels / lesion_voxels * 100.0) if lesion_voxels else float("nan")
        ),
        "pct_roi_enhancing": float(enhancing_voxels / roi_voxels * 100.0) if roi_voxels else float("nan"),
        "integrated_leakage_burden_pct_mm3": float(np.sum(positive_corrected) * voxel_volume_mm3),
        "thresholded_integrated_leakage_burden_pct_mm3": (
            float(np.sum(thresholded_corrected) * voxel_volume_mm3)
        ),
        "bbb_leakage_index_pct": bbb_index,
        "ipsi_contra_post_pre_ratio": ipsi_contra_ratio,
        "reference_ce_mean_pct": safe_stat(reference_values, "mean") if reference_values.size else float("nan"),
        "reference_ce_std_pct": safe_stat(reference_values, "std") if reference_values.size else float("nan"),
        "reference_ce_median_pct": reference_median if reference_values.size else float("nan"),
        "reference_ce_p95_pct": safe_stat(reference_values, "p95") if reference_values.size else float("nan"),
        "enhancement_threshold_ce_pct": threshold_raw,
        "threshold_method": threshold_method_used,
    }


def process_session(spec: SessionSpec, args: argparse.Namespace) -> dict[str, Any]:
    if spec.brain_mask_path is None:
        raise ValueError(
            "missing brain mask; provide --brain-mask-dir, --brain-mask-pattern, "
            "or a roi-manifest brain_mask column"
        )
    session_out = args.out_dir / spec.animal_id / spec.timepoint / spec.case_id
    pair_args = argparse.Namespace(
        pre=spec.pre_path,
        post=spec.post_path,
        out_dir=session_out,
        session_id=spec.case_id,
        mask=spec.brain_mask_path,
        mask_slice_start=args.mask_slice_start,
        mask_slice_stop=args.mask_slice_stop,
        no_register=args.no_register,
        bias_method=args.bias_method,
        bias_sigma_mm=args.bias_sigma_mm,
        normalization=args.normalization,
        save_intermediates=args.save_intermediates,
        save_all_maps=args.save_all_maps,
    )
    metadata = process_pair(pair_args)

    ce_path = session_out / f"{spec.case_id}_percent_enhancement.nii.gz"
    brain_mask_path = session_out / f"{spec.case_id}_mask.nii.gz"
    ce_img, ce_map = load_float(ce_path)
    brain_mask = load_matching_mask(brain_mask_path, ce_img, label="brain mask")
    lesion_mask = (
        load_matching_mask(spec.lesion_mask_path, ce_img, label="lesion mask")
        if spec.lesion_mask_path is not None
        else None
    )
    metrics = quantify_enhancement(
        ce_map,
        brain_mask,
        affine=ce_img.affine,
        voxel_volume_mm3=float(np.prod(voxel_sizes(ce_img))),
        lesion_mask=lesion_mask,
        ipsilateral_side=spec.ipsilateral_side,
        reference_mode=args.reference_mode,
        threshold_method=args.threshold_method,
        threshold_corrected_ce_pct=args.threshold_corrected_ce_pct,
    )

    registration = metadata.get("registration", {})
    return {
        "row_type": "session",
        "case_id": spec.case_id,
        "animal_id": spec.animal_id,
        "group": spec.group,
        "timepoint": spec.timepoint,
        "status": "processed",
        "notes": spec.notes,
        "session_dir": str(spec.session_dir),
        "pre_path": str(spec.pre_path),
        "post_path": str(spec.post_path),
        "session_output_dir": str(session_out),
        "percent_enhancement_map": str(ce_path),
        "mask_qc_png": str(session_out / f"{spec.case_id}_mask_qc.png"),
        "enhancement_qc_png": str(session_out / f"{spec.case_id}_enhancement_qc.png"),
        "brain_mask_path": str(spec.brain_mask_path or brain_mask_path),
        "brain_mask_source": metadata.get("mask_source", ""),
        "lesion_mask_path": str(spec.lesion_mask_path or ""),
        "ipsilateral_side": spec.ipsilateral_side,
        "registration_metric": registration.get("metric", ""),
        "registration_method": registration.get("method", ""),
        "mask_voxels": metadata.get("mask_voxels", ""),
        "outputs_are": metadata.get(
            "outputs_are",
            "semi-quantitative T1-weighted gadolinium enhancement, not T1, Ktrans, or absolute permeability",
        ),
        **metrics,
    }


def failure_row(spec: SessionSpec, args: argparse.Namespace, exc: Exception) -> dict[str, Any]:
    return {
        "row_type": "session",
        "case_id": spec.case_id,
        "animal_id": spec.animal_id,
        "group": spec.group,
        "timepoint": spec.timepoint,
        "status": "failed",
        "notes": f"{spec.notes}; {type(exc).__name__}: {exc}".strip("; "),
        "session_dir": str(spec.session_dir),
        "pre_path": str(spec.pre_path),
        "post_path": str(spec.post_path),
        "session_output_dir": str(args.out_dir / spec.animal_id / spec.timepoint / spec.case_id),
        "brain_mask_path": str(spec.brain_mask_path or ""),
        "lesion_mask_path": str(spec.lesion_mask_path or ""),
        "ipsilateral_side": spec.ipsilateral_side,
        "outputs_are": "semi-quantitative T1-weighted gadolinium enhancement, not T1, Ktrans, or absolute permeability",
    }


def as_float(value: Any) -> float:
    if value in ("", None):
        return float("nan")
    try:
        return float(value)
    except (TypeError, ValueError):
        return float("nan")


def build_delta_rows(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[str]]:
    usable = [row for row in rows if row.get("row_type") == "session" and row.get("status") == "processed"]
    by_animal: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for row in usable:
        by_animal.setdefault(str(row["animal_id"]), {}).setdefault(str(row["timepoint"]), []).append(row)

    deltas: list[dict[str, Any]] = []
    warnings: list[str] = []
    for animal_id, by_timepoint in sorted(by_animal.items()):
        d1_rows = by_timepoint.get("D1", [])
        d7_rows = by_timepoint.get("D7", [])
        if not d1_rows or not d7_rows:
            continue
        if len(d1_rows) != 1 or len(d7_rows) != 1:
            warnings.append(
                f"skipping D7-D1 delta for {animal_id}: "
                f"{len(d1_rows)} D1 row(s), {len(d7_rows)} D7 row(s)"
            )
            continue
        d1 = d1_rows[0]
        d7 = d7_rows[0]
        delta = {field: "" for field in SESSION_FIELDS}
        delta.update(
            {
                "row_type": "delta",
                "case_id": f"{animal_id}_D7-D1",
                "animal_id": animal_id,
                "group": d7.get("group") or d1.get("group", ""),
                "timepoint": "D7-D1",
                "status": "computed",
                "notes": "D7 minus D1; blank fields are non-numeric or unavailable",
                "outputs_are": d7.get("outputs_are", ""),
            }
        )
        for field in DELTA_NUMERIC_FIELDS:
            d1_value = as_float(d1.get(field))
            d7_value = as_float(d7.get(field))
            if np.isfinite(d1_value) and np.isfinite(d7_value):
                delta[field] = d7_value - d1_value
        deltas.append(delta)
    return deltas, warnings


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Batch quantify semi-quantitative BBB gadolinium enhancement from converted "
            "pre/post T1-FLASH D1/D7 mouse sessions."
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "input_root",
        nargs="?",
        type=Path,
        default=Path("output/all_mice"),
        help="folder containing case folders such as C25S1_D1/pre_coronal.nii.gz",
    )
    parser.add_argument("-o", "--out-dir", type=Path, default=Path("derivatives/flash_v1_cohort"))
    parser.add_argument(
        "--roi-manifest",
        type=Path,
        default=None,
        help=(
            "optional CSV with case_id or animal_id/timepoint plus optional group, include, "
            "ipsilateral_side, brain_mask, and lesion_mask columns"
        ),
    )
    parser.add_argument(
        "--brain-mask-dir",
        type=Path,
        default=None,
        help=(
            "folder containing corrected or predicted pre-space brain masks; "
            "required for processing unless the ROI manifest supplies masks"
        ),
    )
    parser.add_argument(
        "--brain-mask-pattern",
        action="append",
        default=None,
        help="mask filename pattern; may be repeated or comma-separated. Supports {case_id}, {animal_id}, {timepoint}",
    )
    parser.add_argument("--lesion-mask-dir", type=Path, default=None)
    parser.add_argument(
        "--lesion-mask-pattern",
        action="append",
        default=None,
        help="lesion ROI filename pattern; may be repeated or comma-separated",
    )
    parser.add_argument(
        "--ipsilateral-side",
        choices=["left", "right", "low-x", "high-x"],
        default="",
        help=(
            "stroke/leakage side used for ipsi/contra correction. Anatomical left/right uses NIfTI axis 0; "
            "low-x/high-x avoids anatomical assumptions."
        ),
    )
    parser.add_argument(
        "--reference-mode",
        choices=["mirrored_roi", "contralateral_hemisphere"],
        default="mirrored_roi",
        help="contralateral reference for correction when ipsilateral side is available",
    )
    parser.add_argument(
        "--threshold-method",
        choices=["auto", "contra_p95", "contra_mean_2sd", "corrected_gt"],
        default="auto",
        help="auto uses contra_p95 when a reference exists, otherwise absolute CE > threshold",
    )
    parser.add_argument(
        "--threshold-corrected-ce-pct",
        type=float,
        default=10.0,
        help="absolute/corrected CE percent threshold used when no contralateral distribution is available or method=corrected_gt",
    )
    parser.add_argument("--mask-slice-start", type=int, default=50,
                        help="first coronal slice shown in mask/enhancement QC")
    parser.add_argument("--mask-slice-stop", type=int, default=170,
                        help="last coronal slice shown in mask/enhancement QC")
    parser.add_argument("--no-register", action="store_true", help="skip rigid post-to-pre registration")
    parser.add_argument("--bias-method", choices=["smooth", "none"], default="smooth")
    parser.add_argument("--bias-sigma-mm", type=float, default=2.0)
    parser.add_argument("--normalization", choices=["median", "none"], default="median")
    parser.add_argument("--save-intermediates", action="store_true")
    parser.add_argument("--save-all-maps", action="store_true")
    parser.add_argument("--limit-sessions", type=int, default=None)
    parser.add_argument("--dry-run", action="store_true", help="only discover sessions and write cohort_sessions.csv")
    parser.add_argument("--fail-fast", action="store_true")
    return parser.parse_args(argv)


def write_metadata(
    args: argparse.Namespace,
    sessions: list[SessionSpec],
    rows: list[dict[str, Any]],
    delta_warnings: list[str],
) -> None:
    failures = [row for row in rows if row.get("status") == "failed"]
    metadata = {
        "input_root": str(args.input_root),
        "out_dir": str(args.out_dir),
        "n_discovered_sessions": len(sessions),
        "n_included_sessions": sum(1 for spec in sessions if spec.include),
        "n_processed_sessions": sum(1 for row in rows if row.get("status") == "processed"),
        "n_failed_sessions": len(failures),
        "threshold_method": args.threshold_method,
        "threshold_corrected_ce_pct": args.threshold_corrected_ce_pct,
        "reference_mode": args.reference_mode,
        "ipsilateral_side_default": args.ipsilateral_side,
        "bias_method": args.bias_method,
        "normalization": args.normalization,
        "mask_slice_start": args.mask_slice_start,
        "mask_slice_stop": args.mask_slice_stop,
        "outputs_are": "semi-quantitative T1-weighted gadolinium enhancement, not T1, Ktrans, ve, vp, or absolute permeability",
        "delta_warnings": delta_warnings,
        "failures": [
            {"case_id": row.get("case_id", ""), "notes": row.get("notes", "")}
            for row in failures
        ],
    }
    (args.out_dir / "cohort_metadata.json").write_text(json.dumps(metadata, indent=2) + "\n")


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    overrides = read_session_overrides(args.roi_manifest)
    sessions = discover_sessions(
        args.input_root,
        overrides=overrides,
        brain_mask_dir=args.brain_mask_dir,
        brain_mask_patterns=split_patterns(args.brain_mask_pattern, DEFAULT_BRAIN_MASK_PATTERNS),
        lesion_mask_dir=args.lesion_mask_dir,
        lesion_mask_patterns=split_patterns(args.lesion_mask_pattern, DEFAULT_LESION_MASK_PATTERNS),
        ipsilateral_side=args.ipsilateral_side,
    )
    if args.limit_sessions is not None:
        sessions = sessions[:args.limit_sessions]
    args.out_dir.mkdir(parents=True, exist_ok=True)
    write_csv(
        args.out_dir / "cohort_sessions.csv",
        session_manifest_rows(sessions),
        [
            "case_id",
            "animal_id",
            "timepoint",
            "group",
            "include",
            "ipsilateral_side",
            "pre_path",
            "post_path",
            "brain_mask_path",
            "lesion_mask_path",
            "notes",
        ],
    )

    if not sessions:
        print(f"no converted pre/post sessions found under: {args.input_root}")
        return 2
    if args.dry_run:
        write_metadata(args, sessions, [], [])
        print(f"discovered sessions: {len(sessions)}")
        print(f"session manifest: {args.out_dir / 'cohort_sessions.csv'}")
        return 0

    rows: list[dict[str, Any]] = []
    for spec in sessions:
        if not spec.include:
            continue
        try:
            rows.append(process_session(spec, args))
            print(f"processed: {spec.case_id}")
        except Exception as exc:
            rows.append(failure_row(spec, args, exc))
            print(f"FAILED {spec.case_id}: {exc}")
            if args.fail_fast:
                break

    delta_rows, delta_warnings = build_delta_rows(rows)
    all_rows = rows + delta_rows
    write_csv(args.out_dir / "cohort_quantification.csv", all_rows, SESSION_FIELDS)
    write_metadata(args, sessions, rows, delta_warnings)
    print(f"sessions discovered: {len(sessions)}")
    print(f"sessions processed: {sum(1 for row in rows if row.get('status') == 'processed')}")
    print(f"sessions failed: {sum(1 for row in rows if row.get('status') == 'failed')}")
    print(f"delta rows: {len(delta_rows)}")
    print(f"combined csv: {args.out_dir / 'cohort_quantification.csv'}")
    print("metric: semi-quantitative T1-weighted gadolinium enhancement")
    return 1 if any(row.get("status") == "failed" for row in rows) else 0


if __name__ == "__main__":
    raise SystemExit(main())
