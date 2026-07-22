# ruff: noqa: E402
"""Single-session pre/post T1 FLASH gadolinium-enhancement processing."""

from __future__ import annotations

import argparse
import csv
import json
import os
from dataclasses import dataclass
from pathlib import Path
import shutil
import tempfile
from typing import Any

import numpy as np

_cache_root = Path(tempfile.gettempdir()) / "lys_bbb_mri_cache"
os.environ.setdefault("MPLCONFIGDIR", str(_cache_root / "matplotlib"))
os.environ.setdefault("XDG_CACHE_HOME", str(_cache_root / "xdg"))
for _cache_dir in (Path(os.environ["MPLCONFIGDIR"]), Path(os.environ["XDG_CACHE_HOME"])):
    _cache_dir.mkdir(parents=True, exist_ok=True)

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import nibabel as nib
from scipy import ndimage as ndi

from lys_bbb.t1_registration import register_post_to_pre


@dataclass(frozen=True)
class FlashPairRequest:
    """Typed inputs for one pre/post T1 enhancement calculation."""

    pre: Path
    post: Path
    out_dir: Path
    mask: Path | None
    session_id: str | None = None
    mask_slice_start: int | None = 50
    mask_slice_stop: int | None = 170
    no_register: bool = False
    bias_method: str = "smooth"
    bias_sigma_mm: float = 2.0
    normalization: str = "median"
    save_intermediates: bool = False
    save_all_maps: bool = False


def voxel_sizes(img: nib.Nifti1Image) -> np.ndarray:
    return np.linalg.norm(img.affine[:3, :3], axis=0)


def load_float(path: Path) -> tuple[nib.Nifti1Image, np.ndarray]:
    img = nib.load(str(path))
    if len(img.shape) != 3:
        raise ValueError(f"expected a 3D NIfTI: {path}")
    return img, img.get_fdata(dtype=np.float32)


def save_like(data: np.ndarray, ref: nib.Nifti1Image, path: Path, dtype=np.float32) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    out = nib.Nifti1Image(data.astype(dtype, copy=False), ref.affine, ref.header.copy())
    out.set_data_dtype(dtype)
    nib.save(out, str(path))


def finite_percentile(data: np.ndarray, percentiles: list[float] | tuple[float, ...],
                      mask: np.ndarray | None = None) -> np.ndarray:
    values = data[mask] if mask is not None else data[np.isfinite(data)]
    values = values[np.isfinite(values)]
    if values.size == 0:
        return np.zeros(len(percentiles), dtype=np.float32)
    return np.percentile(values, percentiles)


def clamp_slice_range(shape: tuple[int, int, int],
                      slice_start: int | None,
                      slice_stop: int | None) -> tuple[int, int]:
    nz = shape[2]
    start = 0 if slice_start is None else max(0, int(slice_start))
    stop = nz - 1 if slice_stop is None else min(nz - 1, int(slice_stop))
    if start > stop:
        raise ValueError(f"empty mask slice range after clipping: {start}-{stop}")
    return start, stop


def smooth_bias_correct(data: np.ndarray, mask: np.ndarray, img: nib.Nifti1Image,
                        sigma_mm: float = 2.0) -> tuple[np.ndarray, np.ndarray]:
    vox = voxel_sizes(img)
    sigma_vox = np.maximum(sigma_mm / np.maximum(vox, 1e-6), 1.0)
    positive = np.clip(np.nan_to_num(data, nan=0.0), 0, None)
    mask_float = mask.astype(np.float32)
    numerator = ndi.gaussian_filter(positive * mask_float, sigma=sigma_vox)
    denominator = ndi.gaussian_filter(mask_float, sigma=sigma_vox)
    field = numerator / np.maximum(denominator, 1e-6)
    field_values = field[mask & np.isfinite(field) & (field > 0)]
    if field_values.size == 0:
        raise ValueError("cannot estimate bias field inside mask")
    field_floor = np.percentile(field_values, 5)
    field = np.maximum(field, field_floor)
    field_scale = np.median(field_values)
    corrected = positive / field * field_scale
    return corrected.astype(np.float32), field.astype(np.float32)


def normalize_pair(pre: np.ndarray, post: np.ndarray, mask: np.ndarray,
                   method: str) -> tuple[np.ndarray, np.ndarray, dict[str, Any]]:
    if method == "none":
        return pre.astype(np.float32), post.astype(np.float32), {
            "method": method,
            "pre_scale": 1.0,
            "post_scale": 1.0,
        }
    if method != "median":
        raise ValueError(f"unknown normalization method: {method}")
    pre_values = pre[mask & np.isfinite(pre) & (pre > 0)]
    post_values = post[mask & np.isfinite(post) & (post > 0)]
    if pre_values.size == 0 or post_values.size == 0:
        raise ValueError("cannot normalize: no positive masked voxels")
    pre_scale = float(np.median(pre_values))
    post_scale = float(np.median(post_values))
    return (
        (pre / max(pre_scale, 1e-6)).astype(np.float32),
        (post / max(post_scale, 1e-6)).astype(np.float32),
        {"method": method, "pre_scale": pre_scale, "post_scale": post_scale},
    )


def enhancement_maps(pre_norm: np.ndarray, post_norm: np.ndarray,
                     mask: np.ndarray) -> dict[str, np.ndarray]:
    pre_masked = pre_norm[mask & np.isfinite(pre_norm) & (pre_norm > 0)]
    eps = max(float(np.percentile(pre_masked, 1)) * 0.1, 1e-6) if pre_masked.size else 1e-6
    diff = post_norm - pre_norm
    ratio = post_norm / np.maximum(pre_norm, eps)
    percent = 100.0 * diff / np.maximum(pre_norm, eps)
    for arr in (diff, ratio, percent):
        arr[~mask] = np.nan
    return {
        "post_minus_pre": diff.astype(np.float32),
        "post_over_pre": ratio.astype(np.float32),
        "percent_enhancement": percent.astype(np.float32),
    }


def stats_for(values: np.ndarray) -> dict[str, float | int]:
    values = values[np.isfinite(values)]
    if values.size == 0:
        return {
            "n_voxels": 0,
            "mean": np.nan,
            "std": np.nan,
            "p05": np.nan,
            "p25": np.nan,
            "median": np.nan,
            "p75": np.nan,
            "p95": np.nan,
        }
    p05, p25, p50, p75, p95 = np.percentile(values, [5, 25, 50, 75, 95])
    return {
        "n_voxels": int(values.size),
        "mean": float(np.mean(values)),
        "std": float(np.std(values)),
        "p05": float(p05),
        "p25": float(p25),
        "median": float(p50),
        "p75": float(p75),
        "p95": float(p95),
    }


def write_summary_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "region",
        "metric",
        "volume_mm3",
        "n_voxels",
        "mean",
        "std",
        "p05",
        "p25",
        "median",
        "p75",
        "p95",
        "pct_gt_10",
        "pct_gt_25",
        "pct_gt_50",
    ]
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def summary_rows(maps: dict[str, np.ndarray], mask: np.ndarray,
                 voxel_volume_mm3: float) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    volume_mm3 = float(np.count_nonzero(mask) * voxel_volume_mm3)
    for name, data in maps.items():
        values = data[mask]
        row = {
            "region": "brain_mask",
            "metric": name,
            "volume_mm3": volume_mm3,
            **stats_for(values),
        }
        if name == "percent_enhancement":
            finite = values[np.isfinite(values)]
            denom = max(finite.size, 1)
            row["pct_gt_10"] = float(np.count_nonzero(finite > 10) / denom * 100.0)
            row["pct_gt_25"] = float(np.count_nonzero(finite > 25) / denom * 100.0)
            row["pct_gt_50"] = float(np.count_nonzero(finite > 50) / denom * 100.0)
        else:
            row["pct_gt_10"] = ""
            row["pct_gt_25"] = ""
            row["pct_gt_50"] = ""
        rows.append(row)
    return rows


def window(data: np.ndarray, mask: np.ndarray | None = None) -> tuple[float, float]:
    p1, p995 = finite_percentile(data, [1, 99.5], mask=mask)
    if p995 <= p1:
        p995 = p1 + 1.0
    return float(p1), float(p995)


def montage_slices(shape: tuple[int, int, int], n: int = 9,
                   slice_start: int | None = None,
                   slice_stop: int | None = None) -> np.ndarray:
    start, stop = clamp_slice_range(shape, slice_start, slice_stop)
    return np.linspace(start, stop, n).astype(int)


def draw_slice(ax: plt.Axes, data: np.ndarray, k: int, *,
               cmap: str, vmin: float, vmax: float) -> None:
    ax.imshow(np.rot90(data[:, :, k]), cmap=cmap, vmin=vmin, vmax=vmax)
    ax.set_xticks([])
    ax.set_yticks([])


def qc_mask(pre: np.ndarray, mask: np.ndarray, path: Path,
            slice_start: int | None = None,
            slice_stop: int | None = None) -> None:
    ks = montage_slices(pre.shape, 9, slice_start, slice_stop)
    vmin, vmax = window(pre, mask)
    fig, axes = plt.subplots(3, 3, figsize=(9, 9))
    for ax, k in zip(axes.ravel(), ks):
        draw_slice(ax, pre, k, cmap="gray", vmin=vmin, vmax=vmax)
        ax.contour(np.rot90(mask[:, :, k]), levels=[0.5], colors="lime", linewidths=0.6)
        ax.set_title(f"k={k}", fontsize=8)
    fig.suptitle("Brain mask overlay on pre", fontsize=10)
    fig.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)


def qc_enhancement(pre: np.ndarray, post: np.ndarray, percent: np.ndarray,
                   mask: np.ndarray, path: Path,
                   slice_start: int | None = None,
                   slice_stop: int | None = None) -> None:
    ks = montage_slices(pre.shape, 6, slice_start, slice_stop)
    img_vmin, img_vmax = window(np.concatenate([pre[mask], post[mask]]))
    finite_percent = percent[mask & np.isfinite(percent)]
    lim = float(np.percentile(np.abs(finite_percent), 98)) if finite_percent.size else 100.0
    lim = max(lim, 10.0)
    fig, axes = plt.subplots(len(ks), 3, figsize=(8, max(8, len(ks) * 2.1)))
    for row, k in enumerate(ks):
        draw_slice(axes[row, 0], pre, k, cmap="gray", vmin=img_vmin, vmax=img_vmax)
        draw_slice(axes[row, 1], post, k, cmap="gray", vmin=img_vmin, vmax=img_vmax)
        draw_slice(axes[row, 2], percent, k, cmap="coolwarm", vmin=-lim, vmax=lim)
        axes[row, 0].contour(np.rot90(mask[:, :, k]), levels=[0.5], colors="lime", linewidths=0.4)
        axes[row, 1].contour(np.rot90(mask[:, :, k]), levels=[0.5], colors="lime", linewidths=0.4)
        axes[row, 2].contour(np.rot90(mask[:, :, k]), levels=[0.5], colors="black", linewidths=0.4)
        axes[row, 0].set_ylabel(f"k={k}", fontsize=8)
        if row == 0:
            axes[row, 0].set_title("pre norm", fontsize=9)
            axes[row, 1].set_title("post norm", fontsize=9)
            axes[row, 2].set_title("% enhancement", fontsize=9)
    fig.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)


def process_pair_request(request: FlashPairRequest) -> dict[str, Any]:
    """Process one image pair from a typed application-facing request."""

    out_dir = request.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    session_id = request.session_id or out_dir.name

    pre_img, pre = load_float(request.pre)
    temp_registered_dir = None
    if request.save_intermediates:
        post_registered_path = out_dir / f"{session_id}_post_registered.nii.gz"
    else:
        temp_registered_dir = Path(tempfile.mkdtemp(prefix="lys_bbb_flash_"))
        post_registered_path = temp_registered_dir / f"{session_id}_post_registered.nii.gz"
    transform_path = out_dir / f"{session_id}_post_to_pre.tfm"
    if request.no_register:
        post_img, post = load_float(request.post)
        if pre.shape != post.shape or not np.allclose(pre_img.affine, post_img.affine, atol=1e-3):
            raise ValueError("--no-register requires matching pre/post shape and affine")
        if request.save_intermediates:
            save_like(post, pre_img, post_registered_path)
        else:
            post_registered_path = request.post
        registration_meta = {"method": "none", "transform_path": ""}
    else:
        registration_meta = {
            "method": "SimpleITK rigid Mattes mutual information",
            **register_post_to_pre(
                request.pre,
                request.post,
                post_registered_path,
                transform_path,
            ),
        }
    _, post_registered = load_float(post_registered_path)
    if temp_registered_dir is not None:
        shutil.rmtree(temp_registered_dir, ignore_errors=True)

    if request.mask is None:
        raise ValueError(
            "a corrected or predicted pre-space brain mask is required; pass --mask"
        )
    mask_img, mask_data = load_float(request.mask)
    if mask_data.shape != pre.shape or not np.allclose(mask_img.affine, pre_img.affine, atol=1e-3):
        raise ValueError("provided mask must match pre image shape and affine")
    mask = mask_data > 0
    mask_source = str(request.mask)
    save_like(mask.astype(np.uint8), pre_img, out_dir / f"{session_id}_mask.nii.gz", dtype=np.uint8)

    if request.bias_method == "none":
        pre_corr = np.clip(pre, 0, None).astype(np.float32)
        post_corr = np.clip(post_registered, 0, None).astype(np.float32)
        pre_field = None
        post_field = None
    elif request.bias_method == "smooth":
        pre_corr, pre_field = smooth_bias_correct(
            pre,
            mask,
            pre_img,
            sigma_mm=request.bias_sigma_mm,
        )
        post_corr, post_field = smooth_bias_correct(post_registered, mask, pre_img,
                                                    sigma_mm=request.bias_sigma_mm)
    else:
        raise ValueError(f"unknown bias method: {request.bias_method}")

    if request.save_intermediates:
        save_like(pre_corr, pre_img, out_dir / f"{session_id}_pre_biascorr.nii.gz")
        save_like(post_corr, pre_img, out_dir / f"{session_id}_post_registered_biascorr.nii.gz")
        if pre_field is not None and post_field is not None:
            save_like(pre_field, pre_img, out_dir / f"{session_id}_pre_biasfield.nii.gz")
            save_like(post_field, pre_img, out_dir / f"{session_id}_post_registered_biasfield.nii.gz")

    pre_norm, post_norm, norm_meta = normalize_pair(
        pre_corr,
        post_corr,
        mask,
        request.normalization,
    )
    if request.save_intermediates:
        save_like(pre_norm, pre_img, out_dir / f"{session_id}_pre_norm.nii.gz")
        save_like(post_norm, pre_img, out_dir / f"{session_id}_post_registered_norm.nii.gz")

    maps = enhancement_maps(pre_norm, post_norm, mask)
    saved_maps = ["percent_enhancement"]
    save_like(
        maps["percent_enhancement"],
        pre_img,
        out_dir / f"{session_id}_percent_enhancement.nii.gz",
    )
    if request.save_all_maps:
        for name in ("post_minus_pre", "post_over_pre"):
            save_like(data=maps[name], ref=pre_img, path=out_dir / f"{session_id}_{name}.nii.gz")
            saved_maps.append(name)

    rows = summary_rows(
        {
            "pre_norm": pre_norm,
            "post_norm": post_norm,
            **maps,
        },
        mask,
        float(np.prod(voxel_sizes(pre_img))),
    )
    write_summary_csv(out_dir / f"{session_id}_summary.csv", rows)

    qc_mask(
        pre_norm,
        mask,
        out_dir / f"{session_id}_mask_qc.png",
        slice_start=request.mask_slice_start,
        slice_stop=request.mask_slice_stop,
    )
    qc_enhancement(pre_norm, post_norm, maps["percent_enhancement"], mask,
                   out_dir / f"{session_id}_enhancement_qc.png",
                   slice_start=request.mask_slice_start,
                   slice_stop=request.mask_slice_stop)

    metadata = {
        "session_id": session_id,
        "pre": str(request.pre),
        "post": str(request.post),
        "post_registered": (
            str(post_registered_path) if request.save_intermediates else ""
        ),
        "mask_source": mask_source,
        "mask_mode": "provided_pre_space_mask",
        "mask_slice_start": request.mask_slice_start,
        "mask_slice_stop": request.mask_slice_stop,
        "bias_method": request.bias_method,
        "bias_sigma_mm": request.bias_sigma_mm,
        "normalization": norm_meta,
        "registration": registration_meta,
        "save_intermediates": bool(request.save_intermediates),
        "save_all_maps": bool(request.save_all_maps),
        "saved_nifti_maps": saved_maps,
        "outputs_are": "semi-quantitative T1-weighted gadolinium enhancement, not T1, Ktrans, or absolute permeability",
        "voxel_sizes_mm": [float(v) for v in voxel_sizes(pre_img)],
        "mask_voxels": int(np.count_nonzero(mask)),
    }
    (out_dir / f"{session_id}_metadata.json").write_text(json.dumps(metadata, indent=2) + "\n")
    return metadata


def process_pair(args: argparse.Namespace) -> dict[str, Any]:
    """Compatibility adapter for the command-line and cohort entry points."""

    return process_pair_request(
        FlashPairRequest(
            pre=args.pre,
            post=args.post,
            out_dir=args.out_dir,
            mask=args.mask,
            session_id=args.session_id,
            mask_slice_start=args.mask_slice_start,
            mask_slice_stop=args.mask_slice_stop,
            no_register=args.no_register,
            bias_method=args.bias_method,
            bias_sigma_mm=args.bias_sigma_mm,
            normalization=args.normalization,
            save_intermediates=args.save_intermediates,
            save_all_maps=args.save_all_maps,
        )
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Quantify pre/post T1-FLASH gadolinium enhancement from native coronal NIfTI files.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--pre", type=Path, required=True, help="native pre-contrast coronal NIfTI")
    parser.add_argument("--post", type=Path, required=True, help="native post-contrast coronal NIfTI")
    parser.add_argument("-o", "--out-dir", type=Path, required=True)
    parser.add_argument("--session-id", default=None)
    parser.add_argument(
        "--mask",
        type=Path,
        required=True,
        help="corrected or predicted binary brain mask on the pre-contrast image grid",
    )
    parser.add_argument("--mask-slice-start", type=int, default=50,
                        help="first coronal slice shown in mask/enhancement QC")
    parser.add_argument("--mask-slice-stop", type=int, default=170,
                        help="last coronal slice shown in mask/enhancement QC")
    parser.add_argument("--no-register", action="store_true", help="skip rigid post-to-pre registration")
    parser.add_argument("--bias-method", choices=["smooth", "none"], default="smooth")
    parser.add_argument("--bias-sigma-mm", type=float, default=2.0)
    parser.add_argument("--normalization", choices=["median", "none"], default="median")
    parser.add_argument("--save-intermediates", action="store_true",
                        help="save heavy debug NIfTIs: registered post, bias fields, "
                             "bias-corrected images, and normalized images")
    parser.add_argument("--save-all-maps", action="store_true",
                        help="also save post_minus_pre and post_over_pre NIfTI maps. "
                             "The percent_enhancement map is always saved.")
    return parser.parse_args(argv)

def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    metadata = process_pair(args)
    print(f"done: {metadata['session_id']}")
    print(f"out: {args.out_dir}")
    print(f"mask voxels: {metadata['mask_voxels']}")
    print("metric: semi-quantitative T1-weighted gadolinium enhancement")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
