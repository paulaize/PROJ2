"""Focused tests for managed NIfTI input validation."""

from __future__ import annotations

import hashlib
from pathlib import Path

import nibabel as nib
import numpy as np

from lys_bbb.input_validation import validate_managed_nifti


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_managed_nifti_passes_when_geometry_and_checksum_match(
    tmp_path: Path,
) -> None:
    path = tmp_path / "input.nii.gz"
    nib.save(
        nib.Nifti1Image(np.ones((3, 4, 5), dtype=np.float32), np.eye(4)),
        path,
    )

    result = validate_managed_nifti(
        path,
        expected_sha256=_sha256(path),
        expected_shape=(3, 4, 5),
        expected_spacing_mm=(1.0, 1.0, 1.0),
        expected_axis_codes=("R", "A", "S"),
    )

    assert result.valid
    assert result.issues == ()
    assert result.shape == (3, 4, 5)


def test_managed_nifti_reports_provenance_changes(tmp_path: Path) -> None:
    path = tmp_path / "input.nii.gz"
    nib.save(
        nib.Nifti1Image(np.ones((4, 4, 5), dtype=np.float32), np.eye(4)),
        path,
    )

    result = validate_managed_nifti(
        path,
        expected_sha256="0" * 64,
        expected_shape=(3, 4, 5),
        expected_spacing_mm=(1.0, 1.0, 1.0),
        expected_axis_codes=("R", "A", "S"),
    )

    assert not result.valid
    assert {issue.code for issue in result.issues} == {
        "INPUT_CHECKSUM_CHANGED",
        "INPUT_SHAPE_CHANGED",
    }


def test_managed_nifti_reports_a_missing_file(tmp_path: Path) -> None:
    result = validate_managed_nifti(
        tmp_path / "missing.nii.gz",
        expected_sha256=None,
        expected_shape=(),
        expected_spacing_mm=(),
        expected_axis_codes=(),
    )

    assert not result.valid
    assert result.issues[0].code == "INPUT_FILE_MISSING"
