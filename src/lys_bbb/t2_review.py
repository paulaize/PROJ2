"""Qt-free validation and measurement of reviewed native-space T2 lesion masks."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import nibabel as nib
import numpy as np

from lys_bbb.t2_model_release import sha256_file


@dataclass(frozen=True)
class T2MaskMeasurement:
    """Validated geometry and deterministic native-space lesion measurement."""

    mask_path: Path
    mask_sha256: str
    shape: tuple[int, int, int]
    spacing_mm: tuple[float, float, float]
    axis_codes: tuple[str, str, str]
    lesion_voxel_count: int
    lesion_volume_mm3: float


def validate_and_measure_t2_mask(
    mask_path: Path | str,
    reference_t2_path: Path | str,
    *,
    expected_mask_sha256: str | None = None,
) -> T2MaskMeasurement:
    """Validate an exact binary mask on the native T2 grid and measure its volume.

    No resampling, reorientation, thresholding, label coercion, or postprocessing is
    performed. An empty binary mask is valid and represents zero lesion volume.
    """

    mask_file = Path(mask_path).expanduser().resolve()
    reference_file = Path(reference_t2_path).expanduser().resolve()
    if not reference_file.is_file():
        raise FileNotFoundError(f"The native T2 reference is unavailable: {reference_file}")
    if not mask_file.is_file():
        raise FileNotFoundError(f"The lesion mask is unavailable: {mask_file}")

    try:
        reference = nib.load(str(reference_file))
        mask_image = nib.load(str(mask_file))
    except (OSError, ValueError) as exc:
        raise ValueError(f"The T2 scan or lesion mask is not a readable NIfTI: {exc}") from exc

    if reference.ndim != 3:
        raise ValueError(
            f"The native T2 reference must be three-dimensional; received {reference.shape}."
        )
    if mask_image.ndim != 3:
        raise ValueError(
            f"The lesion mask must be three-dimensional; received {mask_image.shape}."
        )
    if mask_image.shape != reference.shape:
        raise ValueError(
            "The lesion mask dimensions do not match the native T2 scan: "
            f"expected {reference.shape}, received {mask_image.shape}."
        )
    if not np.isfinite(reference.affine).all() or np.linalg.det(reference.affine[:3, :3]) == 0:
        raise ValueError("The native T2 reference has an invalid affine.")
    if not np.isfinite(mask_image.affine).all() or np.linalg.det(mask_image.affine[:3, :3]) == 0:
        raise ValueError("The lesion mask has an invalid affine.")
    if not np.allclose(mask_image.affine, reference.affine, rtol=1e-5, atol=1e-5):
        raise ValueError(
            "The lesion mask affine does not match the native T2 scan. "
            "Do not resample or reorient the corrected mask during review."
        )

    reference_spacing = tuple(
        float(value) for value in reference.header.get_zooms()[:3]
    )
    mask_spacing = tuple(float(value) for value in mask_image.header.get_zooms()[:3])
    if not np.allclose(mask_spacing, reference_spacing, rtol=0, atol=1e-5):
        raise ValueError(
            "The lesion mask voxel spacing does not match the native T2 scan: "
            f"expected {reference_spacing}, received {mask_spacing}."
        )

    mask_data = np.asanyarray(mask_image.dataobj)
    if not np.isfinite(mask_data).all():
        raise ValueError("The lesion mask contains non-finite values.")
    labels = set(np.unique(mask_data).tolist())
    if not labels <= {0, 1}:
        raise ValueError(
            "The lesion mask must be binary with labels 0 and 1; "
            f"received labels {sorted(labels)[:10]}."
        )

    mask_sha256 = sha256_file(mask_file)
    if expected_mask_sha256 is not None and mask_sha256 != expected_mask_sha256:
        raise ValueError(
            "The lesion mask changed after it was registered. Import the changed file "
            "as a new corrected artifact before review."
        )
    lesion_voxel_count = int(np.count_nonzero(mask_data))
    lesion_volume_mm3 = float(lesion_voxel_count * np.prod(reference_spacing))
    return T2MaskMeasurement(
        mask_path=mask_file,
        mask_sha256=mask_sha256,
        shape=tuple(int(value) for value in mask_image.shape),
        spacing_mm=reference_spacing,
        axis_codes=tuple(str(value) for value in nib.aff2axcodes(reference.affine)),
        lesion_voxel_count=lesion_voxel_count,
        lesion_volume_mm3=lesion_volume_mm3,
    )
