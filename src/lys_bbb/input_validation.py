"""Validate managed NIfTI inputs against their recorded conversion provenance."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

import nibabel as nib
import numpy as np


@dataclass(frozen=True)
class NiftiInputIssue:
    code: str
    severity: str
    message: str
    technical_detail: str | None = None


@dataclass(frozen=True)
class NiftiInputValidation:
    path: Path
    shape: tuple[int, ...]
    spacing_mm: tuple[float, ...]
    axis_codes: tuple[str, ...]
    sha256: str | None
    issues: tuple[NiftiInputIssue, ...]

    @property
    def valid(self) -> bool:
        return not any(issue.severity == "error" for issue in self.issues)


def validate_managed_nifti(
    path: Path,
    *,
    expected_sha256: str | None,
    expected_shape: tuple[int, ...],
    expected_spacing_mm: tuple[float, ...],
    expected_axis_codes: tuple[str, ...],
) -> NiftiInputValidation:
    """Check one managed input without loading its complete voxel array."""

    resolved = path.expanduser().resolve()
    if not resolved.is_file():
        return NiftiInputValidation(
            path=resolved,
            shape=(),
            spacing_mm=(),
            axis_codes=(),
            sha256=None,
            issues=(
                NiftiInputIssue(
                    "INPUT_FILE_MISSING",
                    "error",
                    "The converted NIfTI file is missing.",
                    str(resolved),
                ),
            ),
        )

    try:
        image = nib.load(resolved)
    except Exception as exc:
        return NiftiInputValidation(
            path=resolved,
            shape=(),
            spacing_mm=(),
            axis_codes=(),
            sha256=None,
            issues=(
                NiftiInputIssue(
                    "INPUT_NIFTI_UNREADABLE",
                    "error",
                    "The converted file is not a readable NIfTI image.",
                    str(exc),
                ),
            ),
        )

    shape = tuple(int(value) for value in image.shape)
    spacing = tuple(float(value) for value in image.header.get_zooms()[:3])
    raw_axis_codes = nib.aff2axcodes(image.affine)
    axis_codes = tuple(str(value) for value in raw_axis_codes if value is not None)
    issues: list[NiftiInputIssue] = []

    if len(shape) != 3 or any(value <= 0 for value in shape):
        issues.append(
            NiftiInputIssue(
                "INPUT_NOT_3D",
                "error",
                "The input must contain one three-dimensional MRI volume.",
                f"Received shape: {shape}",
            )
        )
    if image.affine.shape != (4, 4) or not np.isfinite(image.affine).all():
        issues.append(
            NiftiInputIssue(
                "INPUT_AFFINE_INVALID",
                "error",
                "The NIfTI spatial transform is invalid.",
            )
        )
    if (
        len(spacing) != 3
        or not np.isfinite(np.asarray(spacing)).all()
        or any(value <= 0 for value in spacing)
    ):
        issues.append(
            NiftiInputIssue(
                "INPUT_SPACING_INVALID",
                "error",
                "The NIfTI voxel spacing is invalid.",
                f"Received spacing: {spacing}",
            )
        )
    if len(axis_codes) != 3:
        issues.append(
            NiftiInputIssue(
                "INPUT_ORIENTATION_INVALID",
                "error",
                "The NIfTI orientation cannot be determined from its affine.",
            )
        )

    if expected_shape and shape != expected_shape:
        issues.append(
            NiftiInputIssue(
                "INPUT_SHAPE_CHANGED",
                "error",
                "The NIfTI dimensions changed after conversion.",
                f"Recorded {expected_shape}; found {shape}",
            )
        )
    if expected_spacing_mm and (
        len(spacing) != len(expected_spacing_mm)
        or not np.allclose(
            spacing,
            expected_spacing_mm,
            rtol=1e-5,
            atol=1e-6,
        )
    ):
        issues.append(
            NiftiInputIssue(
                "INPUT_SPACING_CHANGED",
                "error",
                "The NIfTI spacing changed after conversion.",
                f"Recorded {expected_spacing_mm}; found {spacing}",
            )
        )
    if expected_axis_codes and axis_codes != expected_axis_codes:
        issues.append(
            NiftiInputIssue(
                "INPUT_ORIENTATION_CHANGED",
                "error",
                "The NIfTI orientation changed after conversion.",
                f"Recorded {expected_axis_codes}; found {axis_codes}",
            )
        )

    actual_sha256 = _sha256_file(resolved)
    if expected_sha256 and actual_sha256 != expected_sha256:
        issues.append(
            NiftiInputIssue(
                "INPUT_CHECKSUM_CHANGED",
                "error",
                "The managed NIfTI file changed after conversion.",
                f"Recorded {expected_sha256}; found {actual_sha256}",
            )
        )

    return NiftiInputValidation(
        path=resolved,
        shape=shape,
        spacing_mm=spacing,
        axis_codes=axis_codes,
        sha256=actual_sha256,
        issues=tuple(issues),
    )


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()
