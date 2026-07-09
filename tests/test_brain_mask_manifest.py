"""Tests for candidate brain-mask validation."""

from __future__ import annotations

import nibabel as nib
import numpy as np

from lys_bbb.brain_mask_manifest import (
    build_brain_mask_manifest_rows,
    candidate_status,
)


def test_candidate_status_marks_missing_and_review_masks():
    missing = {"pre_exists": True, "post_exists": True, "brain_mask_path": ""}
    assert candidate_status(
        missing,
        max_components=1,
        min_largest_component_pct=99.0,
        min_volume_mm3=None,
        max_volume_mm3=None,
    )[0] == "missing_brain_mask"

    review = {
        "pre_exists": True,
        "post_exists": True,
        "brain_mask_path": "mask.nii.gz",
        "brain_mask_grid_ok": True,
        "brain_mask_components": 3,
        "brain_mask_largest_component_pct": 95.0,
        "brain_mask_volume_mm3": 500.0,
    }
    status, notes = candidate_status(
        review,
        max_components=1,
        min_largest_component_pct=99.0,
        min_volume_mm3=400.0,
        max_volume_mm3=700.0,
    )

    assert status == "needs_review"
    assert "components" in notes
    assert "largest component" in notes


def test_build_brain_mask_manifest_validates_grid_and_metrics(tmp_path):
    input_root = tmp_path / "output"
    case_dir = input_root / "C25S1_D1"
    case_dir.mkdir(parents=True)
    mask_dir = tmp_path / "masks"
    mask_dir.mkdir()
    affine = np.diag([0.1, 0.1, 0.2, 1.0])
    pre = np.ones((6, 6, 6), dtype=np.float32)
    post = np.ones((6, 6, 6), dtype=np.float32) * 2
    mask = np.zeros((6, 6, 6), dtype=np.uint8)
    mask[1:5, 1:5, 1:5] = 1
    nib.save(nib.Nifti1Image(pre, affine), case_dir / "pre_coronal.nii.gz")
    nib.save(nib.Nifti1Image(post, affine), case_dir / "post_coronal.nii.gz")
    nib.save(nib.Nifti1Image(mask, affine), mask_dir / "C25S1_D1.nii.gz")

    rows = build_brain_mask_manifest_rows(
        input_root,
        mask_dir=mask_dir,
        mask_patterns=["{case_id}.nii.gz"],
        mask_source="nnunet",
        registration_summary=None,
        out_dir=tmp_path / "reports",
        write_mask_qc=False,
        mask_slice_start=0,
        mask_slice_stop=5,
        max_components=1,
        min_largest_component_pct=99.0,
        min_volume_mm3=None,
        max_volume_mm3=None,
    )

    assert rows[0]["case_id"] == "C25S1_D1"
    assert rows[0]["brain_mask_source"] == "nnunet"
    assert rows[0]["brain_mask_grid_ok"] is True
    assert rows[0]["brain_mask_components"] == 1
    assert rows[0]["brain_mask_status"] == "ready_candidate"
    assert rows[0]["qc_status"] == "needs_review"


def test_build_brain_mask_manifest_flags_bad_mask_grid(tmp_path):
    input_root = tmp_path / "output"
    case_dir = input_root / "C25S1_D1"
    case_dir.mkdir(parents=True)
    mask_dir = tmp_path / "masks"
    mask_dir.mkdir()
    affine = np.eye(4)
    nib.save(nib.Nifti1Image(np.ones((4, 4, 4), dtype=np.float32), affine), case_dir / "pre_coronal.nii.gz")
    nib.save(nib.Nifti1Image(np.ones((4, 4, 4), dtype=np.float32), affine), case_dir / "post_coronal.nii.gz")
    nib.save(nib.Nifti1Image(np.ones((5, 4, 4), dtype=np.uint8), affine), mask_dir / "C25S1_D1.nii.gz")

    rows = build_brain_mask_manifest_rows(
        input_root,
        mask_dir=mask_dir,
        mask_patterns=["{case_id}.nii.gz"],
        mask_source="nnunet",
        registration_summary=None,
        out_dir=tmp_path / "reports",
        write_mask_qc=False,
        mask_slice_start=0,
        mask_slice_stop=3,
        max_components=1,
        min_largest_component_pct=99.0,
        min_volume_mm3=None,
        max_volume_mm3=None,
    )

    assert rows[0]["brain_mask_grid_ok"] is False
    assert rows[0]["brain_mask_status"] == "mask_grid_error"
