#!/usr/bin/env python
"""CLI for previewing SHERM-inspired brain masks on one coronal image."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


SHERM_DIR = Path(__file__).resolve().parent
if str(SHERM_DIR) not in sys.path:
    sys.path.insert(0, str(SHERM_DIR))

from sherm import preview_sherm_segmentation


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Preview SHERM brain extraction for one native coronal NIfTI.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("coronal_nifti", type=Path, help="native coronal pre-contrast NIfTI")
    parser.add_argument("-o", "--qc-png", type=Path, default=None,
                        help="output mask-overlay PNG")
    parser.add_argument("--write-mask", action="store_true",
                        help="also write a binary NIfTI mask")
    parser.add_argument("--mask-path", type=Path, default=None,
                        help="output path for --write-mask")
    parser.add_argument("--mask-slice-start", type=int, default=50)
    parser.add_argument("--mask-slice-stop", type=int, default=170)
    parser.add_argument("--brain-volume-min-mm3", type=float, default=180.0)
    parser.add_argument("--brain-volume-max-mm3", type=float, default=600.0)
    parser.add_argument("--max-candidates", type=int, default=12)
    parser.add_argument("--consensus-fraction", type=float, default=0.75,
                        help="fraction of selected candidates required for a voxel to enter the mask")
    parser.add_argument("--auto-prior-center", action="store_true",
                        help="enable scan-specific prior center estimation; disabled by default because bright skull/scalp can bias the estimate")
    parser.add_argument("--no-auto-prior-center", action="store_true",
                        help="deprecated no-op kept for compatibility; auto prior centering is already disabled by default")
    parser.add_argument("--prior-center-x", type=float, default=None,
                        help="manual x voxel coordinate for the ellipsoid prior center")
    parser.add_argument("--prior-center-y", type=float, default=None,
                        help="manual y voxel coordinate for the ellipsoid prior center")
    parser.add_argument("--prior-scale-x", type=float, default=1.0,
                        help="multiply ellipsoid prior width")
    parser.add_argument("--prior-scale-y", type=float, default=1.0,
                        help="multiply ellipsoid prior height")
    parser.add_argument("--slice-cleanup-min-area", type=int, default=100,
                        help="minimum 2D object area kept during slice cleanup")
    parser.add_argument("--slice-cleanup-radius", type=int, default=1,
                        help="2D opening radius used during slice cleanup; 0 disables opening")
    parser.add_argument("--n-slices", type=int, default=9,
                        help="number of slices in the preview montage")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    result = preview_sherm_segmentation(
        args.coronal_nifti,
        args.qc_png,
        write_mask=args.write_mask,
        mask_path=args.mask_path,
        slice_start=args.mask_slice_start,
        slice_stop=args.mask_slice_stop,
        brain_volume_range_mm3=(
            args.brain_volume_min_mm3,
            args.brain_volume_max_mm3,
        ),
        max_candidates=args.max_candidates,
        consensus_fraction=args.consensus_fraction,
        auto_prior_center=args.auto_prior_center and not args.no_auto_prior_center,
        prior_center_xy=(args.prior_center_x, args.prior_center_y),
        prior_scale_xy=(args.prior_scale_x, args.prior_scale_y),
        slice_cleanup_min_area=args.slice_cleanup_min_area,
        slice_cleanup_radius=args.slice_cleanup_radius,
        n_slices=args.n_slices,
    )
    print(f"qc: {result['qc_png']}")
    if result["mask_path"] is not None:
        print(f"mask: {result['mask_path']}")
    print(f"mask voxels: {result['mask_voxels']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
