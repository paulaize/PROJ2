#!/usr/bin/env python
"""Benchmark automatic brain masks against a corrected manual mask."""

from __future__ import annotations

import argparse
import csv
import os
from pathlib import Path
import tempfile

_cache_root = Path(tempfile.gettempdir()) / "lys_bbb_mri_cache"
os.environ.setdefault("MPLCONFIGDIR", str(_cache_root / "matplotlib"))
os.environ.setdefault("XDG_CACHE_HOME", str(_cache_root / "xdg"))
for _cache_dir in (Path(os.environ["MPLCONFIGDIR"]), Path(os.environ["XDG_CACHE_HOME"])):
    _cache_dir.mkdir(parents=True, exist_ok=True)

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import nibabel as nib
import numpy as np
from scipy import ndimage as ndi


def load_mask(path: Path) -> tuple[nib.Nifti1Image, np.ndarray]:
    img = nib.load(str(path))
    if len(img.shape) != 3:
        raise ValueError(f"expected 3D NIfTI mask: {path}")
    return img, img.get_fdata(dtype=np.float32) > 0


def load_image(path: Path) -> tuple[nib.Nifti1Image, np.ndarray]:
    img = nib.load(str(path))
    if len(img.shape) != 3:
        raise ValueError(f"expected 3D NIfTI image: {path}")
    return img, img.get_fdata(dtype=np.float32)


def voxel_sizes(img: nib.Nifti1Image) -> np.ndarray:
    return np.linalg.norm(img.affine[:3, :3], axis=0)


def validate_grid(ref_img: nib.Nifti1Image, pred_img: nib.Nifti1Image, name: str) -> None:
    if ref_img.shape != pred_img.shape:
        raise ValueError(f"{name}: shape mismatch, manual {ref_img.shape}, prediction {pred_img.shape}")
    if not np.allclose(ref_img.affine, pred_img.affine, atol=1e-3):
        raise ValueError(f"{name}: affine mismatch; resample/register prediction before benchmarking")


def surface(mask: np.ndarray) -> np.ndarray:
    if not mask.any():
        return mask.copy()
    eroded = ndi.binary_erosion(mask, structure=np.ones((3, 3, 3), dtype=bool))
    return mask & ~eroded


def surface_distances_mm(reference: np.ndarray,
                         prediction: np.ndarray,
                         spacing_mm: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    ref_surface = surface(reference)
    pred_surface = surface(prediction)
    if not ref_surface.any() or not pred_surface.any():
        return np.array([], dtype=np.float32), np.array([], dtype=np.float32)
    ref_distmap = ndi.distance_transform_edt(~ref_surface, sampling=spacing_mm)
    pred_distmap = ndi.distance_transform_edt(~pred_surface, sampling=spacing_mm)
    pred_to_ref = ref_distmap[pred_surface]
    ref_to_pred = pred_distmap[ref_surface]
    return pred_to_ref.astype(np.float32), ref_to_pred.astype(np.float32)


def metrics_for(manual: np.ndarray,
                pred: np.ndarray,
                voxel_volume_mm3: float,
                spacing_mm: np.ndarray) -> dict[str, float | int]:
    manual_n = int(np.count_nonzero(manual))
    pred_n = int(np.count_nonzero(pred))
    tp = int(np.count_nonzero(manual & pred))
    fp = int(np.count_nonzero(~manual & pred))
    fn = int(np.count_nonzero(manual & ~pred))
    union = int(np.count_nonzero(manual | pred))
    dice = 2.0 * tp / max(manual_n + pred_n, 1)
    jaccard = tp / max(union, 1)
    precision = tp / max(tp + fp, 1)
    recall = tp / max(tp + fn, 1)
    pred_to_ref, ref_to_pred = surface_distances_mm(manual, pred, spacing_mm)
    all_surface = np.concatenate([pred_to_ref, ref_to_pred])
    if all_surface.size:
        mean_surface = float(np.mean(all_surface))
        hd95 = float(np.percentile(all_surface, 95))
    else:
        mean_surface = float("nan")
        hd95 = float("nan")
    return {
        "manual_voxels": manual_n,
        "prediction_voxels": pred_n,
        "manual_volume_mm3": manual_n * voxel_volume_mm3,
        "prediction_volume_mm3": pred_n * voxel_volume_mm3,
        "volume_difference_mm3": (pred_n - manual_n) * voxel_volume_mm3,
        "volume_difference_pct": 100.0 * (pred_n - manual_n) / max(manual_n, 1),
        "dice": dice,
        "jaccard": jaccard,
        "precision": precision,
        "recall": recall,
        "false_positive_mm3": fp * voxel_volume_mm3,
        "false_negative_mm3": fn * voxel_volume_mm3,
        "mean_surface_distance_mm": mean_surface,
        "hausdorff95_mm": hd95,
    }


def montage_slices(mask: np.ndarray, n: int) -> np.ndarray:
    used = np.flatnonzero(mask.any(axis=(0, 1)))
    if used.size == 0:
        return np.linspace(0, mask.shape[2] - 1, n).astype(int)
    return np.linspace(int(used[0]), int(used[-1]), n).astype(int)


def window(data: np.ndarray, mask: np.ndarray) -> tuple[float, float]:
    values = data[mask & np.isfinite(data)]
    if values.size < 100:
        values = data[np.isfinite(data)]
    if values.size == 0:
        return 0.0, 1.0
    vmin, vmax = np.percentile(values, [1, 99.5])
    if vmax <= vmin:
        vmax = vmin + 1.0
    return float(vmin), float(vmax)


def write_qc(image: np.ndarray,
             manual: np.ndarray,
             pred: np.ndarray,
             path: Path,
             title: str,
             n_slices: int = 9) -> None:
    ks = montage_slices(manual | pred, n_slices)
    vmin, vmax = window(image, manual | pred)
    n_cols = 3
    n_rows = int(np.ceil(len(ks) / n_cols))
    fig, axes = plt.subplots(n_rows, n_cols, figsize=(3.2 * n_cols, 3.2 * n_rows))
    for ax, k in zip(np.atleast_1d(axes).ravel(), ks):
        ax.imshow(np.rot90(image[:, :, k]), cmap="gray", vmin=vmin, vmax=vmax)
        ax.contour(np.rot90(manual[:, :, k]), levels=[0.5], colors="lime", linewidths=0.8)
        ax.contour(np.rot90(pred[:, :, k]), levels=[0.5], colors="magenta", linewidths=0.8)
        ax.set_title(f"k={k}", fontsize=8)
        ax.set_xticks([])
        ax.set_yticks([])
    for ax in np.atleast_1d(axes).ravel()[len(ks):]:
        ax.axis("off")
    fig.suptitle(f"{title}: manual=green, prediction=magenta", fontsize=10)
    fig.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)


def parse_prediction(text: str) -> tuple[str, Path]:
    if "=" in text:
        name, path = text.split("=", 1)
        return name.strip(), Path(path.strip())
    path = Path(text)
    return path.stem.replace(".nii", ""), path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Benchmark automatic brain masks against one corrected manual NIfTI mask."
    )
    parser.add_argument("--image", type=Path, required=True,
                        help="reference pre_coronal image for QC overlays")
    parser.add_argument("--manual", type=Path, required=True,
                        help="corrected binary manual mask")
    parser.add_argument("--prediction", action="append", required=True,
                        help="prediction mask path, or name=path; can be passed multiple times")
    parser.add_argument("-o", "--out-dir", type=Path, default=Path("derivatives/brain_seg/benchmarks"),
                        help="output folder for CSV and QC PNGs")
    parser.add_argument("--case-id", default=None,
                        help="case id for output naming; default inferred from manual filename")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    image_img, image_data = load_image(args.image)
    manual_img, manual = load_mask(args.manual)
    validate_grid(image_img, manual_img, "manual")

    case_id = args.case_id
    if case_id is None:
        case_id = args.manual.name.replace("_pre_manual_mask.nii.gz", "").replace(".nii.gz", "")
    spacing = voxel_sizes(manual_img)
    voxel_volume = float(np.prod(spacing))
    args.out_dir.mkdir(parents=True, exist_ok=True)

    rows = []
    for pred_arg in args.prediction:
        name, pred_path = parse_prediction(pred_arg)
        pred_img, pred = load_mask(pred_path)
        validate_grid(manual_img, pred_img, name)
        row = {
            "case_id": case_id,
            "method": name,
            "prediction_path": str(pred_path),
            **metrics_for(manual, pred, voxel_volume, spacing),
        }
        rows.append(row)
        qc_path = args.out_dir / f"{case_id}_{name}_vs_manual_qc.png"
        write_qc(image_data, manual, pred, qc_path, title=f"{case_id} {name}")
        print(f"{name}: Dice={row['dice']:.3f}, precision={row['precision']:.3f}, "
              f"recall={row['recall']:.3f}, vol_diff={row['volume_difference_pct']:.1f}%")
        print(f"  qc: {qc_path}")

    csv_path = args.out_dir / f"{case_id}_mask_benchmark.csv"
    with csv_path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    print(f"csv: {csv_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
