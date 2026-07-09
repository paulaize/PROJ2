"""Shared helpers for external/cloud brain-mask pre-label scripts."""

from __future__ import annotations

from pathlib import Path

import nibabel as nib
import numpy as np
from nibabel.processing import resample_from_to


def voxel_sizes(img: nib.Nifti1Image) -> np.ndarray:
    return np.linalg.norm(img.affine[:3, :3], axis=0)


def auto_mbe_dataset_type(img: nib.Nifti1Image) -> str:
    vox = voxel_sizes(img)
    return "invivo_aniso" if float(np.max(vox) / max(np.min(vox), 1e-9)) > 3.0 else "invivo_iso"


def load_3d(path: Path) -> nib.Nifti1Image:
    img = nib.load(str(path))
    if len(img.shape) != 3:
        raise ValueError(f"expected a 3D NIfTI: {path}")
    return img


def grid_matches(a: nib.Nifti1Image, b: nib.Nifti1Image) -> bool:
    return a.shape == b.shape and np.allclose(a.affine, b.affine, atol=1e-3)


def binarize_to_reference(raw_mask_path: Path,
                          reference_path: Path,
                          output_path: Path,
                          *,
                          threshold: float = 0.0,
                          allow_resample: bool = False) -> dict[str, object]:
    ref_img = load_3d(reference_path)
    raw_img = load_3d(raw_mask_path)
    resampled = False
    if not grid_matches(ref_img, raw_img):
        if not allow_resample:
            raise ValueError(
                f"external mask grid does not match reference image: "
                f"reference shape={ref_img.shape}, mask shape={raw_img.shape}"
            )
        raw_img = resample_from_to(raw_img, ref_img, order=0)
        resampled = True

    data = raw_img.get_fdata(dtype=np.float32)
    mask = np.isfinite(data) & (data > threshold)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    out = nib.Nifti1Image(mask.astype(np.uint8), ref_img.affine, ref_img.header.copy())
    out.set_data_dtype(np.uint8)
    nib.save(out, str(output_path))
    return {
        "output_path": str(output_path),
        "mask_voxels": int(np.count_nonzero(mask)),
        "resampled": resampled,
        "threshold": float(threshold),
    }
