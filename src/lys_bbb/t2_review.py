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


@dataclass(frozen=True)
class T2ProbabilityMap:
    """Validated lesion probabilities on one native T2 grid."""

    probability_path: Path
    probability_sha256: str
    data: np.ndarray
    maximum_probability: float


def validate_t2_probability_map(
    probability_path: Path | str,
    reference_t2_path: Path | str,
    *,
    expected_probability_sha256: str | None = None,
) -> T2ProbabilityMap:
    """Load a finite [0, 1] probability map matching the native T2 geometry."""

    probability_file = Path(probability_path).expanduser().resolve()
    reference_file = Path(reference_t2_path).expanduser().resolve()
    if not reference_file.is_file():
        raise FileNotFoundError(f"The native T2 reference is unavailable: {reference_file}")
    if not probability_file.is_file():
        raise FileNotFoundError(
            f"The lesion probability map is unavailable: {probability_file}"
        )

    probability_sha256 = sha256_file(probability_file)
    if (
        expected_probability_sha256 is not None
        and probability_sha256 != expected_probability_sha256
    ):
        raise ValueError(
            "The lesion probability map changed after it was registered. "
            "Re-run inference before adjusting its threshold."
        )
    try:
        reference = nib.load(str(reference_file))
        probability_image = nib.load(str(probability_file))
    except (OSError, ValueError) as exc:
        raise ValueError(
            f"The T2 scan or lesion probability map is not a readable NIfTI: {exc}"
        ) from exc
    if reference.ndim != 3 or probability_image.ndim != 3:
        raise ValueError("T2 probability review requires three-dimensional images.")
    if probability_image.shape != reference.shape:
        raise ValueError(
            "The lesion probability dimensions do not match the native T2 scan: "
            f"expected {reference.shape}, received {probability_image.shape}."
        )
    if not np.allclose(
        probability_image.affine,
        reference.affine,
        rtol=1e-5,
        atol=1e-5,
    ):
        raise ValueError(
            "The lesion probability affine does not match the native T2 scan."
        )
    probability_spacing = probability_image.header.get_zooms()[:3]
    reference_spacing = reference.header.get_zooms()[:3]
    if not np.allclose(
        probability_spacing,
        reference_spacing,
        rtol=0,
        atol=1e-5,
    ):
        raise ValueError(
            "The lesion probability spacing does not match the native T2 scan."
        )

    data = np.asarray(probability_image.dataobj, dtype=np.float32)
    if not np.isfinite(data).all():
        raise ValueError("The lesion probability map contains non-finite values.")
    if data.size and (float(data.min()) < 0.0 or float(data.max()) > 1.0):
        raise ValueError("The lesion probability map contains values outside [0, 1].")
    return T2ProbabilityMap(
        probability_path=probability_file,
        probability_sha256=probability_sha256,
        data=data,
        maximum_probability=float(data.max()) if data.size else 0.0,
    )


def save_thresholded_t2_probability(
    probability: T2ProbabilityMap,
    reference_t2_path: Path | str,
    output_path: Path | str,
    *,
    threshold: float,
) -> Path:
    """Save a binary native-grid mask without postprocessing."""

    if not 0.0 < threshold < 1.0:
        raise ValueError(f"The case-specific probability threshold is invalid: {threshold}.")
    reference = nib.load(str(Path(reference_t2_path).expanduser().resolve()))
    mask = (probability.data >= threshold).astype(np.uint8)
    header = reference.header.copy()
    header.set_data_dtype(np.uint8)
    output = Path(output_path).expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    nib.save(nib.Nifti1Image(mask, reference.affine, header), str(output))
    return output


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
