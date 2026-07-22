"""Reusable native-slice QC rendering for binary MRI masks."""

from __future__ import annotations

from pathlib import Path

import nibabel as nib
import numpy as np


def create_native_mask_qc_preview(
    scan_path: Path,
    mask_path: Path,
    output_path: Path,
) -> Path:
    """Create a reflected coronal montage and one PNG for every native slice."""

    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    scan = np.asanyarray(nib.load(str(scan_path)).dataobj, dtype=np.float32)
    mask = np.asanyarray(nib.load(str(mask_path)).dataobj) > 0
    if scan.shape != mask.shape or scan.ndim != 3:
        raise ValueError("Mask QC requires matching three-dimensional scan and mask.")
    areas = mask.sum(axis=(0, 1))
    centre = int(np.argmax(areas)) if np.any(areas) else scan.shape[2] // 2
    slices = sorted(
        {max(0, centre - 1), centre, min(scan.shape[2] - 1, centre + 1)}
    )
    while len(slices) < 3:
        slices.append(slices[-1])
    finite = scan[np.isfinite(scan)]
    low, high = np.percentile(finite, (1, 99)) if finite.size else (0.0, 1.0)
    if high <= low:
        high = low + 1.0
    qc_slice_directory = output_path.parent / "qc_slices"
    qc_slice_directory.mkdir(parents=True, exist_ok=True)
    for stale_slice in qc_slice_directory.glob("slice_*.png"):
        stale_slice.unlink()
    for slice_index in range(scan.shape[2]):
        figure, axis = plt.subplots(1, 1, figsize=(5.2, 5.2), facecolor="#101b2b")
        image_slice = orient_coronal_qc_slice(scan[:, :, slice_index])
        mask_slice = orient_coronal_qc_slice(mask[:, :, slice_index])
        axis.imshow(image_slice, cmap="gray", vmin=low, vmax=high)
        if np.any(mask_slice):
            axis.contour(mask_slice, levels=[0.5], colors=["#20d3b0"], linewidths=1.3)
        axis.axis("off")
        figure.tight_layout(pad=0)
        figure.savefig(
            qc_slice_directory / f"slice_{slice_index + 1:04d}.png",
            dpi=120,
            bbox_inches="tight",
            pad_inches=0,
            facecolor=figure.get_facecolor(),
        )
        plt.close(figure)
    figure, axes = plt.subplots(1, 3, figsize=(8.4, 2.8), facecolor="#101b2b")
    for axis, slice_index in zip(axes, slices, strict=True):
        image_slice = orient_coronal_qc_slice(scan[:, :, slice_index])
        mask_slice = orient_coronal_qc_slice(mask[:, :, slice_index])
        axis.imshow(image_slice, cmap="gray", vmin=low, vmax=high)
        if np.any(mask_slice):
            axis.contour(mask_slice, levels=[0.5], colors=["#20d3b0"], linewidths=1.2)
        axis.set_title(f"Slice {slice_index + 1}", color="white", fontsize=9)
        axis.axis("off")
    figure.tight_layout(pad=0.6)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(
        output_path,
        dpi=130,
        bbox_inches="tight",
        facecolor=figure.get_facecolor(),
    )
    plt.close(figure)
    return output_path


def orient_coronal_qc_slice(array: np.ndarray) -> np.ndarray:
    """Rotate to the established coronal view and reflect vertically (about x)."""

    return np.flipud(np.rot90(array))
