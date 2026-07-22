"""Validation of reviewed brain masks on the native pre-Gd T1 grid."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import nibabel as nib
import numpy as np

from lys_bbb.t1_brain_mask_release import sha256_file


@dataclass(frozen=True)
class T1BrainMaskMeasurement:
    """Validated native-grid facts for one T1 brain mask."""

    mask_path: Path
    mask_sha256: str
    shape: tuple[int, int, int]
    spacing_mm: tuple[float, float, float]
    axis_codes: tuple[str, str, str]
    foreground_voxels: int
    volume_mm3: float


def validate_t1_brain_mask(
    mask_path: Path | str,
    reference_t1_path: Path | str,
    *,
    expected_mask_sha256: str | None = None,
) -> T1BrainMaskMeasurement:
    """Validate an unchanged, non-empty binary mask on the native pre-Gd T1 grid."""

    mask_file = Path(mask_path).expanduser().resolve()
    reference_file = Path(reference_t1_path).expanduser().resolve()
    if not reference_file.is_file():
        raise FileNotFoundError(
            f"The native pre-Gd T1 reference is unavailable: {reference_file}"
        )
    if not mask_file.is_file():
        raise FileNotFoundError(f"The T1 brain mask is unavailable: {mask_file}")
    try:
        reference = nib.load(str(reference_file))
        mask_image = nib.load(str(mask_file))
    except (OSError, ValueError) as exc:
        raise ValueError(f"The pre-Gd T1 or brain mask is not a readable NIfTI: {exc}") from exc
    if reference.ndim != 3:
        raise ValueError(
            f"The native pre-Gd T1 must be three-dimensional; received {reference.shape}."
        )
    if mask_image.ndim != 3:
        raise ValueError(
            f"The T1 brain mask must be three-dimensional; received {mask_image.shape}."
        )
    if mask_image.shape != reference.shape:
        raise ValueError(
            "The T1 brain-mask dimensions do not match the native pre-Gd T1: "
            f"expected {reference.shape}, received {mask_image.shape}."
        )
    for image, label in ((reference, "pre-Gd T1"), (mask_image, "brain mask")):
        if not np.isfinite(image.affine).all() or np.linalg.det(image.affine[:3, :3]) == 0:
            raise ValueError(f"The {label} has an invalid affine.")
    if not np.allclose(mask_image.affine, reference.affine, rtol=1e-5, atol=1e-5):
        raise ValueError(
            "The T1 brain-mask affine does not match the native pre-Gd T1. "
            "Do not resample or reorient the corrected mask during review."
        )
    reference_spacing = tuple(float(value) for value in reference.header.get_zooms()[:3])
    mask_spacing = tuple(float(value) for value in mask_image.header.get_zooms()[:3])
    if not np.allclose(mask_spacing, reference_spacing, rtol=0, atol=1e-5):
        raise ValueError(
            "The T1 brain-mask spacing does not match the native pre-Gd T1: "
            f"expected {reference_spacing}, received {mask_spacing}."
        )
    mask_data = np.asanyarray(mask_image.dataobj)
    if not np.isfinite(mask_data).all():
        raise ValueError("The T1 brain mask contains non-finite values.")
    labels = set(np.unique(mask_data).tolist())
    if not labels <= {0, 1}:
        raise ValueError(
            "The T1 brain mask must be binary with labels 0 and 1; "
            f"received labels {sorted(labels)[:10]}."
        )
    foreground_voxels = int(np.count_nonzero(mask_data))
    if foreground_voxels == 0:
        raise ValueError("The T1 brain mask is empty.")
    mask_sha256 = sha256_file(mask_file)
    if expected_mask_sha256 is not None and mask_sha256 != expected_mask_sha256:
        raise ValueError(
            "The T1 brain mask changed after it was registered. Import the changed "
            "file as a new corrected artifact before approval."
        )
    return T1BrainMaskMeasurement(
        mask_path=mask_file,
        mask_sha256=mask_sha256,
        shape=tuple(int(value) for value in mask_image.shape),
        spacing_mm=reference_spacing,
        axis_codes=tuple(str(value) for value in nib.aff2axcodes(reference.affine)),
        foreground_voxels=foreground_voxels,
        volume_mm3=float(foreground_voxels * np.prod(reference_spacing)),
    )
