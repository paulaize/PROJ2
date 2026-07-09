#!/usr/bin/env python
"""Generate visual QC for rigid post-to-pre T1 FLASH registration."""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import tempfile
from pathlib import Path

import numpy as np

_cache_root = Path(tempfile.gettempdir()) / "lys_bbb_mri_cache"
os.environ.setdefault("MPLCONFIGDIR", str(_cache_root / "matplotlib"))
os.environ.setdefault("XDG_CACHE_HOME", str(_cache_root / "xdg"))
for _cache_dir in (Path(os.environ["MPLCONFIGDIR"]), Path(os.environ["XDG_CACHE_HOME"])):
    _cache_dir.mkdir(parents=True, exist_ok=True)

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from lys_bbb.flash_pair import (
    load_float,
    montage_slices,
    register_post_to_pre,
    save_like,
    voxel_sizes,
    window,
)


def normalized_xcorr(a: np.ndarray, b: np.ndarray, mask: np.ndarray) -> float:
    av = a[mask & np.isfinite(a) & np.isfinite(b)]
    bv = b[mask & np.isfinite(a) & np.isfinite(b)]
    if av.size < 10:
        return float("nan")
    av = av - np.mean(av)
    bv = bv - np.mean(bv)
    denom = float(np.linalg.norm(av) * np.linalg.norm(bv))
    if denom <= 0:
        return float("nan")
    return float(np.dot(av, bv) / denom)


def foreground_mask(pre: np.ndarray, post: np.ndarray) -> np.ndarray:
    values = np.concatenate([
        pre[np.isfinite(pre)].ravel(),
        post[np.isfinite(post)].ravel(),
    ])
    if values.size == 0:
        return np.ones(pre.shape, dtype=bool)
    threshold = float(np.percentile(values, 15))
    return (pre > threshold) | (post > threshold)


def draw_slice(ax: plt.Axes, data: np.ndarray, k: int, *, vmin: float, vmax: float,
               cmap: str = "gray") -> None:
    ax.imshow(np.rot90(data[:, :, k]), cmap=cmap, vmin=vmin, vmax=vmax)
    ax.set_xticks([])
    ax.set_yticks([])


def write_registration_qc(pre: np.ndarray,
                          post: np.ndarray,
                          post_registered: np.ndarray,
                          out_png: Path,
                          *,
                          slice_start: int,
                          slice_stop: int,
                          n_slices: int = 6) -> None:
    ks = montage_slices(pre.shape, n_slices, slice_start, slice_stop)
    img_vmin, img_vmax = window(np.concatenate([pre[np.isfinite(pre)], post_registered[np.isfinite(post_registered)]]))
    raw_diff = np.abs(post - pre)
    reg_diff = np.abs(post_registered - pre)
    diff_values = np.concatenate([
        raw_diff[np.isfinite(raw_diff)].ravel(),
        reg_diff[np.isfinite(reg_diff)].ravel(),
    ])
    diff_vmax = float(np.percentile(diff_values, 98)) if diff_values.size else 1.0
    diff_vmax = max(diff_vmax, 1.0)

    fig, axes = plt.subplots(len(ks), 6, figsize=(13, max(7, len(ks) * 2.0)))
    for row, k in enumerate(ks):
        draw_slice(axes[row, 0], pre, k, vmin=img_vmin, vmax=img_vmax)
        draw_slice(axes[row, 1], post, k, vmin=img_vmin, vmax=img_vmax)
        draw_slice(axes[row, 2], raw_diff, k, vmin=0, vmax=diff_vmax, cmap="magma")
        draw_slice(axes[row, 3], pre, k, vmin=img_vmin, vmax=img_vmax)
        draw_slice(axes[row, 4], post_registered, k, vmin=img_vmin, vmax=img_vmax)
        draw_slice(axes[row, 5], reg_diff, k, vmin=0, vmax=diff_vmax, cmap="magma")
        axes[row, 0].set_ylabel(f"k={k}", fontsize=8)
        if row == 0:
            for ax, title in zip(
                axes[row],
                ["pre", "post raw", "|post-pre| raw", "pre", "post registered", "|post-pre| registered"],
            ):
                ax.set_title(title, fontsize=8)

    fig.suptitle("Pre/post registration QC: compare raw versus registered post", fontsize=10)
    fig.tight_layout()
    out_png.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_png, dpi=150, bbox_inches="tight")
    plt.close(fig)


def process_case(case_id: str,
                 pre_path: Path,
                 post_path: Path,
                 out_dir: Path,
                 *,
                 slice_start: int,
                 slice_stop: int,
                 n_slices: int,
                 save_registered: bool) -> dict[str, object]:
    pre_img, pre = load_float(pre_path)
    post_img, post = load_float(post_path)
    if pre.shape != post.shape:
        raise ValueError(f"{case_id}: pre/post shapes differ before registration: {pre.shape} vs {post.shape}")

    case_dir = out_dir / case_id
    case_dir.mkdir(parents=True, exist_ok=True)
    registered_path = case_dir / f"{case_id}_post_registered_to_pre.nii.gz"
    transform_path = case_dir / f"{case_id}_post_to_pre.tfm"
    qc_png = case_dir / f"{case_id}_registration_qc.png"

    with tempfile.TemporaryDirectory(prefix="lys_bbb_regqc_") as tmp:
        tmp_registered = registered_path if save_registered else Path(tmp) / f"{case_id}_post_registered_to_pre.nii.gz"
        registration_meta = register_post_to_pre(pre_path, post_path, tmp_registered, transform_path)
        _, post_registered = load_float(tmp_registered)
        if save_registered:
            save_like(post_registered, pre_img, registered_path)

    mask_before = foreground_mask(pre, post)
    mask_after = foreground_mask(pre, post_registered)
    before_xcorr = normalized_xcorr(pre, post, mask_before)
    after_xcorr = normalized_xcorr(pre, post_registered, mask_after)

    write_registration_qc(
        pre,
        post,
        post_registered,
        qc_png,
        slice_start=slice_start,
        slice_stop=slice_stop,
        n_slices=n_slices,
    )

    return {
        "case_id": case_id,
        "pre": str(pre_path),
        "post": str(post_path),
        "qc_png": str(qc_png),
        "transform": str(transform_path),
        "registered_post": str(registered_path) if save_registered else "",
        "pre_shape": "x".join(str(v) for v in pre.shape),
        "post_shape": "x".join(str(v) for v in post.shape),
        "voxel_sizes_mm": "x".join(f"{v:.4f}" for v in voxel_sizes(pre_img)),
        "before_xcorr": before_xcorr,
        "after_xcorr": after_xcorr,
        "registration_metric": registration_meta.get("metric"),
        "optimizer_stop": registration_meta.get("optimizer_stop"),
    }


def discover_cases(root: Path) -> list[tuple[str, Path, Path]]:
    cases: list[tuple[str, Path, Path]] = []
    for pre_path in sorted(root.glob("*/pre_coronal.nii.gz")):
        post_path = pre_path.with_name("post_coronal.nii.gz")
        if post_path.exists():
            cases.append((pre_path.parent.name, pre_path, post_path))
    return cases


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate visual QC for rigid post-to-pre registration on converted T1 FLASH pairs.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--input-root", type=Path, default=Path("output/test_mice"),
                        help="folder containing case folders with pre_coronal.nii.gz and post_coronal.nii.gz")
    parser.add_argument("-o", "--out-dir", type=Path, default=Path("derivatives/registration_qc"))
    parser.add_argument("--mask-slice-start", type=int, default=50)
    parser.add_argument("--mask-slice-stop", type=int, default=170)
    parser.add_argument("--n-slices", type=int, default=6)
    parser.add_argument("--save-registered", action="store_true",
                        help="also keep registered post NIfTI outputs; otherwise only QC PNGs/transforms/summary are kept")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    cases = discover_cases(args.input_root)
    if not cases:
        raise SystemExit(f"no pre/post cases found under {args.input_root}")

    rows = [
        process_case(
            case_id,
            pre_path,
            post_path,
            args.out_dir,
            slice_start=args.mask_slice_start,
            slice_stop=args.mask_slice_stop,
            n_slices=args.n_slices,
            save_registered=args.save_registered,
        )
        for case_id, pre_path, post_path in cases
    ]

    args.out_dir.mkdir(parents=True, exist_ok=True)
    summary_csv = args.out_dir / "registration_qc_summary.csv"
    with summary_csv.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    (args.out_dir / "registration_qc_summary.json").write_text(json.dumps(rows, indent=2) + "\n")

    print(f"cases: {len(rows)}")
    print(f"summary: {summary_csv}")
    for row in rows:
        print(f"{row['case_id']}: {row['qc_png']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
