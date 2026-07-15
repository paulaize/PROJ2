"""Tests for manual mask workflow and nnU-Net preparation helpers."""

from __future__ import annotations

from pathlib import Path

import nibabel as nib
import numpy as np

from scripts.masks.open_manual_mask_editor import find_cases
from lys_bbb.mask_workflow import (
    build_manual_worklist_rows,
    build_nnunet_manifest_rows,
    comparison_slices,
    prepare_nnunet_dataset,
    write_manual_dashboard,
    write_mask_comparison_qc,
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


def test_worklist_preserves_reviews_and_requires_human_passes_for_gates():
    row = base_qc_row()
    row.update({
        "manual_mask_path": "derivatives/brain_seg/manual/C25S1_D1_pre_manual_mask_done.nii.gz",
        "manual_mask_grid_ok": True,
        "manual_mask_done_name": True,
        "manual_mask_components": 1,
        "manual_mbe_dice": 0.95,
    })
    previous = {
        "C25S1_D1": {
            "registration_review": "approved",
            "mask_review": "passed",
            "review_notes": "checked slices 50-170",
        }
    }

    rows = build_manual_worklist_rows(
        [row],
        manual_dir=Path("derivatives/brain_seg/manual"),
        previous_rows=previous,
    )

    assert rows[0]["manual_status"] == "ready_candidate"
    assert rows[0]["registration_review"] == "pass"
    assert rows[0]["mask_review"] == "pass"
    assert rows[0]["review_notes"] == "checked slices 50-170"
    assert rows[0]["include_for_quantification"] == "yes"
    assert rows[0]["include_for_nnunet"] == "yes"

    no_reviews = build_manual_worklist_rows(
        [row],
        manual_dir=Path("derivatives/brain_seg/manual"),
    )
    assert no_reviews[0]["include_for_quantification"] == "no"
    assert no_reviews[0]["include_for_nnunet"] == "no"


def test_nnunet_manifest_respects_explicit_mask_approval():
    row = base_qc_row()
    row.update({
        "manual_mask_path": "derivatives/brain_seg/manual/C25S1_D1_pre_manual_mask_done.nii.gz",
        "manual_mask_grid_ok": True,
        "manual_mask_done_name": True,
        "manual_mask_components": 1,
        "manual_mbe_dice": 0.95,
    })

    unapproved = build_nnunet_manifest_rows([row], approved_case_ids=set())
    approved = build_nnunet_manifest_rows([row], approved_case_ids={"C25S1_D1"})

    assert unapproved[0]["split"] == "test"
    assert unapproved[0]["mask"] == ""
    assert approved[0]["split"] == "train"


def test_comparison_slices_prioritizes_edited_slices():
    manual = np.zeros((4, 4, 12), dtype=bool)
    prelabel = np.zeros_like(manual)
    manual[1:3, 1:3, 3] = True
    manual[1:3, 1:3, 8] = True
    prelabel[1:3, 1:3, 3] = True

    slices = comparison_slices(
        manual,
        prelabel,
        n_slices=4,
        slice_start=0,
        slice_stop=11,
    )

    assert slices.tolist() == [8]


def test_comparison_qc_and_dashboard_show_edit_and_review_context(tmp_path):
    image = tmp_path / "pre.nii.gz"
    manual = tmp_path / "manual.nii.gz"
    prelabel = tmp_path / "prelabel.nii.gz"
    qc_png = tmp_path / "comparison.png"
    data = np.arange(8 * 8 * 12, dtype=np.float32).reshape((8, 8, 12))
    manual_data = np.zeros_like(data, dtype=np.uint8)
    prelabel_data = np.zeros_like(data, dtype=np.uint8)
    manual_data[2:6, 2:6, 2:10] = 1
    prelabel_data[1:6, 2:6, 2:10] = 1
    affine = np.eye(4)
    nib.save(nib.Nifti1Image(data, affine), image)
    nib.save(nib.Nifti1Image(manual_data, affine), manual)
    nib.save(nib.Nifti1Image(prelabel_data, affine), prelabel)

    metrics = write_mask_comparison_qc(
        image,
        manual,
        prelabel,
        qc_png,
        case_id="C25S1_D1",
        slice_start=0,
        slice_stop=11,
    )

    assert qc_png.exists()
    assert metrics["removed_voxels"] > 0
    assert metrics["added_voxels"] == 0

    dashboard = tmp_path / "dashboard.html"
    write_manual_dashboard(
        dashboard,
        [{
            "case_id": "C25S1_D1",
            "animal_id": "C25S1",
            "timepoint": "D1",
            "mask_priority": "P2",
            "manual_status": "needs_correction_or_review",
            "manual_action": "review edits",
            "pre_image": str(image),
            "current_manual_mask": str(manual),
            "mbe_prelabel": str(prelabel),
            "manual_vs_mbe_qc_png": str(qc_png),
            "manual_vs_mbe_qc_error": "",
            "manual_mask_qc_png": "",
            "mbe_mask_qc_png": "",
            "registration_qc_png": "",
            "registration_after_xcorr": "0.75",
            "manual_mbe_dice": "0.9",
            "manual_mbe_xor_voxels": "32",
            "manual_mask_components": "1",
            "manual_mask_largest_component_pct": "100",
            "manual_mask_small_components": "0",
            "qc_notes": "",
            "mask_review": "review",
            "registration_review": "pass",
            "review_notes": "fix inferior edge",
            "include_for_quantification": "no",
            "include_for_nnunet": "no",
            "editor_command": "open editor C25S1_D1",
        }],
        cwd=tmp_path,
        worklist_path=tmp_path / "worklist.csv",
    )
    dashboard_text = dashboard.read_text()
    assert "added voxels are cyan" in dashboard_text
    assert "fix inferior edge" in dashboard_text
    assert "Copy editor command" in dashboard_text
    assert 'id="case-search"' in dashboard_text


def test_editor_queue_prefers_existing_done_mask(tmp_path):
    input_root = tmp_path / "input"
    prelabel_dir = tmp_path / "prelabels"
    manual_dir = tmp_path / "manual"
    case_id = "C25S1_D1"
    (input_root / case_id).mkdir(parents=True)
    prelabel_dir.mkdir()
    manual_dir.mkdir()
    (input_root / case_id / "pre_coronal.nii.gz").touch()
    (prelabel_dir / f"{case_id}_mousebrainextractor_mask.nii.gz").touch()
    done_mask = manual_dir / f"{case_id}_pre_manual_mask_done.nii.gz"
    done_mask.touch()

    cases = find_cases(
        prelabel_dir,
        input_root,
        manual_dir,
        [],
        "*_mousebrainextractor_mask.nii.gz",
        "_mousebrainextractor_mask.nii.gz",
    )

    assert cases[0]["manual_mask"] == done_mask
    assert cases[0]["manual_mask_is_done"] is True


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
