"""Focused tests for the isolated MouseBSE desktop experiment."""

from __future__ import annotations

from pathlib import Path

import nibabel as nib
import numpy as np
import pytest

from scripts.brain_extraction.run_mousebse_test import (
    mousebse_command,
    standardize_mask,
    validate_case_id,
)


def test_mousebse_command_keeps_native_orientation(tmp_path: Path):
    command = mousebse_command(
        tmp_path / "mousebse",
        tmp_path / "input.nii.gz",
        tmp_path / "stripped.nii.gz",
        tmp_path / "mask.nii.gz",
        diffusion_constant=50,
        diffusion_iterations=10,
        edge_sigma=0.64,
        erosion_radius=1,
        closing_size=8,
        dilation_radius=0,
    )

    assert "--norotate" in command
    assert command[command.index("--mask") + 1].endswith("mask.nii.gz")
    assert command[command.index("-c") + 1] == "8"


def test_standardize_mask_preserves_grid_and_creates_binary_copy(tmp_path: Path):
    input_path = tmp_path / "input.nii.gz"
    raw_path = tmp_path / "raw.nii.gz"
    output_path = tmp_path / "binary.nii.gz"
    affine = np.array(
        [
            [0.15, 0.0, 0.0, -4.0],
            [0.0, 0.08, 0.0, -3.0],
            [0.0, 0.0, -0.08, 5.0],
            [0.0, 0.0, 0.0, 1.0],
        ]
    )
    image = np.arange(8 * 9 * 10, dtype=np.float32).reshape((8, 9, 10))
    mask = np.zeros_like(image, dtype=np.uint8)
    mask[2:6, 2:7, 2:8] = 255
    nib.save(nib.Nifti1Image(image, affine), input_path)
    nib.save(nib.Nifti1Image(mask, affine), raw_path)

    metrics = standardize_mask(input_path, raw_path, output_path)

    output = nib.load(str(output_path))
    assert output.shape == image.shape
    assert np.allclose(output.affine, affine)
    assert output.get_data_dtype() == np.dtype(np.uint8)
    assert np.array_equal(np.unique(np.asanyarray(output.dataobj)), [0, 1])
    assert metrics["raw_values"] == [0.0, 255.0]
    assert metrics["connected_components"] == 1


def test_standardize_mask_rejects_affine_change(tmp_path: Path):
    input_path = tmp_path / "input.nii.gz"
    raw_path = tmp_path / "raw.nii.gz"
    output_path = tmp_path / "binary.nii.gz"
    data = np.zeros((5, 6, 7), dtype=np.uint8)
    data[1:4, 1:5, 1:6] = 1
    nib.save(nib.Nifti1Image(data, np.eye(4)), input_path)
    changed_affine = np.eye(4)
    changed_affine[0, 3] = 1
    nib.save(nib.Nifti1Image(data, changed_affine), raw_path)

    with pytest.raises(ValueError, match="changed the image affine"):
        standardize_mask(input_path, raw_path, output_path)


@pytest.mark.parametrize("case_id", ["../escape", "a/b", "", "case id"])
def test_validate_case_id_rejects_unsafe_ids(case_id: str):
    with pytest.raises(ValueError):
        validate_case_id(case_id)
