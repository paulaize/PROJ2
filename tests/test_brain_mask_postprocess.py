"""Tests for candidate brain-mask post-processing."""

from __future__ import annotations

import nibabel as nib
import numpy as np

from lys_bbb.brain_mask_postprocess import postprocess_mask, postprocess_masks


def test_postprocess_mask_keeps_largest_component():
    mask = np.zeros((6, 6, 6), dtype=bool)
    mask[1:4, 1:4, 1:4] = True
    mask[5, 5, 5] = True

    processed, metrics = postprocess_mask(mask, keep_largest=True, fill_holes=False)

    assert metrics["input_components"] == 2
    assert metrics["output_components"] == 1
    assert metrics["input_voxels"] == 28
    assert metrics["output_voxels"] == 27
    assert metrics["removed_voxels"] == 1
    assert processed[5, 5, 5] == 0


def test_postprocess_masks_writes_clean_mask(tmp_path):
    input_root = tmp_path / "output"
    case_dir = input_root / "C25S1_D1"
    case_dir.mkdir(parents=True)
    mask_dir = tmp_path / "masks"
    mask_dir.mkdir()
    out_dir = tmp_path / "clean"
    affine = np.eye(4)
    pre = np.ones((5, 5, 5), dtype=np.float32)
    mask = np.zeros((5, 5, 5), dtype=np.uint8)
    mask[1:4, 1:4, 1:4] = 1
    mask[4, 4, 4] = 1
    nib.save(nib.Nifti1Image(pre, affine), case_dir / "pre_coronal.nii.gz")
    nib.save(nib.Nifti1Image(mask, affine), mask_dir / "C25S1_D1.nii.gz")

    rows = postprocess_masks(
        input_root,
        mask_dir=mask_dir,
        mask_patterns=["{case_id}.nii.gz"],
        output_dir=out_dir,
        output_pattern="{case_id}.nii.gz",
        keep_largest=True,
        fill_holes=False,
        min_voxels=1,
    )

    assert rows[0]["status"] == "ready"
    assert rows[0]["input_components"] == 2
    assert rows[0]["output_components"] == 1
    out = nib.load(str(out_dir / "C25S1_D1.nii.gz")).get_fdata() > 0
    assert np.count_nonzero(out) == 27


def test_postprocess_masks_rejects_bad_grid(tmp_path):
    input_root = tmp_path / "output"
    case_dir = input_root / "C25S1_D1"
    case_dir.mkdir(parents=True)
    mask_dir = tmp_path / "masks"
    mask_dir.mkdir()
    nib.save(nib.Nifti1Image(np.ones((4, 4, 4), dtype=np.float32), np.eye(4)), case_dir / "pre_coronal.nii.gz")
    nib.save(nib.Nifti1Image(np.ones((5, 4, 4), dtype=np.uint8), np.eye(4)), mask_dir / "C25S1_D1.nii.gz")

    rows = postprocess_masks(
        input_root,
        mask_dir=mask_dir,
        mask_patterns=["{case_id}.nii.gz"],
        output_dir=tmp_path / "clean",
        output_pattern="{case_id}.nii.gz",
        keep_largest=True,
        fill_holes=False,
        min_voxels=1,
    )

    assert rows[0]["status"] == "failed"
    assert "grid" in rows[0]["message"]


def test_postprocess_masks_treats_missing_candidate_as_nonfatal(tmp_path):
    input_root = tmp_path / "output"
    case_dir = input_root / "C25S1_D1"
    case_dir.mkdir(parents=True)
    nib.save(nib.Nifti1Image(np.ones((4, 4, 4), dtype=np.float32), np.eye(4)), case_dir / "pre_coronal.nii.gz")

    rows = postprocess_masks(
        input_root,
        mask_dir=tmp_path / "masks",
        mask_patterns=["{case_id}.nii.gz"],
        output_dir=tmp_path / "clean",
        output_pattern="{case_id}.nii.gz",
        keep_largest=True,
        fill_holes=False,
        min_voxels=1,
    )

    assert rows[0]["status"] == "missing_mask"
    assert rows[0]["message"] == "missing candidate mask"
