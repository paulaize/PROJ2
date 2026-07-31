"""Read-only preparation of native T2 probability data for live review."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import nibabel as nib
import numpy as np

from lys_bbb.mask_qc import orient_coronal_qc_slice
from lys_bbb.t2_review import validate_t2_probability_map


@dataclass(frozen=True)
class T2ThresholdPreviewData:
    """Validated arrays and display values for one case's live threshold preview."""

    scan: np.ndarray
    probability: np.ndarray
    intensity_range: tuple[float, float]
    spacing_mm: tuple[float, float, float]
    maximum_probability: float


def load_t2_threshold_preview(
    reference_path: Path,
    probability_path: Path,
    *,
    expected_probability_sha256: str | None,
) -> T2ThresholdPreviewData:
    """Validate and load one probability map with its native T2 reference."""

    validated = validate_t2_probability_map(
        probability_path,
        reference_path,
        expected_probability_sha256=expected_probability_sha256,
    )
    reference = nib.load(str(reference_path))
    scan = np.asarray(reference.dataobj, dtype=np.float32)
    finite = scan[np.isfinite(scan)]
    low, high = np.percentile(finite, (1, 99)) if finite.size else (0.0, 1.0)
    if high <= low:
        high = low + 1.0
    return T2ThresholdPreviewData(
        scan=scan,
        probability=validated.data,
        intensity_range=(float(low), float(high)),
        spacing_mm=tuple(float(value) for value in reference.header.get_zooms()[:3]),
        maximum_probability=validated.maximum_probability,
    )


def orient_t2_threshold_preview_slice(array: np.ndarray) -> np.ndarray:
    """Use the application's established native-coronal QC presentation."""

    return orient_coronal_qc_slice(array)
