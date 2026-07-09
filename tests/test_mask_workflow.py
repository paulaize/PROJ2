"""Tests for manual mask workflow and nnU-Net preparation helpers."""

from __future__ import annotations

from pathlib import Path

import nibabel as nib
import numpy as np

from lys_bbb.mask_workflow import (
    build_manual_worklist_rows,
    build_nnunet_manifest_rows,
    prepare_nnunet_dataset,
)


def base_qc_row(case_id: str = "C25S1_D1") -> dict[str, object]:
    return {
        "case_id": case_id,
        "animal_id": "C25S1",
        "timepoint": "D1",
        "pre_exists": True,
        "post_exists": True,
        "pre_path": f"output/all_mice/{case_id}/pre_coronal.nii.gz",
        "post_path": f"output/all_mice/{case_id}/post_coronal.nii.gz",
        "manual_mask_path": "",
        "manual_mask_done_name": "",
        "manual_mask_grid_ok": "",
        "manual_mask_components": "",
        "mbe_mask_path": f"derivatives/brain_seg/mousebrainextractor/{case_id}_mousebrainextractor_mask.nii.gz",
        "manual_mbe_dice": "",
        "registration_qc_png": f"reports/qc/registration_all_mice/{case_id}/{case_id}_registration_qc.png",
        "registration_source_match": True,
        "registration_after_xcorr": "0.75",
        "qc_status": "needs_brain_mask",
        "qc_notes": "missing corrected brain mask",
    }


def test_worklist_marks_missing_manual_mask_as_next_action():
    rows = build_manual_worklist_rows([base_qc_row()], manual_dir=Path("derivatives/brain_seg/manual"))

    assert rows[0]["manual_status"] == "needs_manual_mask"
    assert rows[0]["mask_priority"] == "P1"
    assert rows[0]["include_for_quantification"] == "no"
    assert rows[0]["suggested_manual_mask"].endswith("C25S1_D1_pre_manual_mask.nii.gz")


def test_nnunet_manifest_excludes_review_masks_by_default():
    row = base_qc_row()
    row.update({
        "manual_mask_path": "derivatives/brain_seg/manual/C25S1_D1_pre_manual_mask.nii.gz",
        "manual_mask_grid_ok": True,
        "manual_mask_done_name": False,
        "manual_mask_components": 1,
        "manual_mbe_dice": 0.95,
    })

    default_rows = build_nnunet_manifest_rows([row])
    review_rows = build_nnunet_manifest_rows([row], include_review_labels=True)

    assert default_rows[0]["split"] == "test"
    assert default_rows[0]["mask"] == ""
    assert review_rows[0]["split"] == "train"
    assert review_rows[0]["mask"].endswith("C25S1_D1_pre_manual_mask.nii.gz")


def test_nnunet_prepare_dry_run_validates_train_grid(tmp_path):
    image = tmp_path / "pre.nii.gz"
    mask = tmp_path / "mask.nii.gz"
    data = np.zeros((4, 4, 4), dtype=np.float32)
    mask_data = np.zeros((4, 4, 4), dtype=np.uint8)
    mask_data[1:3, 1:3, 1:3] = 1
    affine = np.eye(4)
    nib.save(nib.Nifti1Image(data, affine), image)
    nib.save(nib.Nifti1Image(mask_data, affine), mask)

    records = prepare_nnunet_dataset(
        [{"case_id": "C25S1_D1", "image": str(image), "mask": str(mask), "split": "train"}],
        nnunet_raw=tmp_path / "nnUNet_raw",
        dry_run=True,
    )

    assert records[0]["status"] == "ready"
    assert not (tmp_path / "nnUNet_raw").exists()


def test_nnunet_prepare_reports_grid_failure(tmp_path):
    image = tmp_path / "pre.nii.gz"
    mask = tmp_path / "mask.nii.gz"
    nib.save(nib.Nifti1Image(np.zeros((4, 4, 4), dtype=np.float32), np.eye(4)), image)
    nib.save(nib.Nifti1Image(np.zeros((5, 4, 4), dtype=np.uint8), np.eye(4)), mask)

    records = prepare_nnunet_dataset(
        [{"case_id": "C25S1_D1", "image": str(image), "mask": str(mask), "split": "train"}],
        nnunet_raw=tmp_path / "nnUNet_raw",
        dry_run=True,
    )

    assert records[0]["status"] == "failed"
    assert "shape mismatch" in records[0]["message"]
