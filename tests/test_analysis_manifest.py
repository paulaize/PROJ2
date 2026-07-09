"""Tests for final analysis manifest gating."""

from __future__ import annotations

from lys_bbb.analysis_manifest import build_analysis_manifest_rows


def qc_row(case_id: str = "C25S1_D1") -> dict[str, object]:
    return {
        "case_id": case_id,
        "animal_id": "C25S1",
        "timepoint": "D1",
        "pre_exists": True,
        "post_exists": True,
        "pre_path": f"output/all_mice/{case_id}/pre_coronal.nii.gz",
        "post_path": f"output/all_mice/{case_id}/post_coronal.nii.gz",
        "manual_mask_path": f"derivatives/brain_seg/manual/{case_id}_pre_manual_mask_done.nii.gz",
        "manual_mask_grid_ok": True,
        "manual_mask_done_name": True,
        "manual_mask_components": 1,
        "manual_mbe_dice": 0.9,
        "manual_mask_qc_png": f"reports/qc/brain_masks/manual/{case_id}_manual_mask_qc.png",
        "registration_qc_png": f"reports/qc/registration_all_mice/{case_id}/{case_id}_registration_qc.png",
        "registration_source_match": True,
        "registration_after_xcorr": 0.75,
        "qc_notes": "",
    }


def test_analysis_manifest_includes_clean_done_mask_with_registration():
    rows = build_analysis_manifest_rows([qc_row()])

    assert rows[0]["include"] == "yes"
    assert rows[0]["qc_gate"] == "ready_for_provisional_quantification"
    assert rows[0]["brain_mask_path"].endswith("_pre_manual_mask_done.nii.gz")
    assert rows[0]["registration_status"] == "registration_ready"


def test_analysis_manifest_excludes_unchanged_or_unmarked_mask():
    row = qc_row()
    row["manual_mask_done_name"] = False
    row["manual_mbe_dice"] = 1.0

    rows = build_analysis_manifest_rows([row])

    assert rows[0]["include"] == "no"
    assert rows[0]["qc_gate"] == "mask_needs_review"
    assert rows[0]["brain_mask_path"] == ""
    assert "unchanged" in rows[0]["qc_notes"]


def test_analysis_manifest_preserves_side_group_lesion_and_review_fields():
    previous = [{
        "case_id": "C25S1_D1",
        "group": "treated",
        "ipsilateral_side": "left",
        "lesion_mask_path": "lesions/C25S1_D1.nii.gz",
        "review_status": "fail",
        "review_notes": "registration visually failed",
    }]

    rows = build_analysis_manifest_rows([qc_row()], previous_rows=previous)

    assert rows[0]["group"] == "treated"
    assert rows[0]["ipsilateral_side"] == "left"
    assert rows[0]["lesion_mask_path"] == "lesions/C25S1_D1.nii.gz"
    assert rows[0]["include"] == "no"
    assert rows[0]["qc_gate"] == "excluded_by_review"
    assert rows[0]["review_notes"] == "registration visually failed"


def test_analysis_manifest_can_disable_auto_include():
    rows = build_analysis_manifest_rows([qc_row()], auto_include_ready=False)

    assert rows[0]["qc_gate"] == "ready_for_provisional_quantification"
    assert rows[0]["include"] == "no"


def test_analysis_manifest_accepts_generic_model_brain_mask_fields():
    row = qc_row()
    row.pop("manual_mask_path")
    row.pop("manual_mask_done_name")
    row.pop("manual_mask_components")
    row["brain_mask_path"] = "derivatives/brain_seg/nnunet_preds/C25S1_D1.nii.gz"
    row["brain_mask_source"] = "nnunet"
    row["brain_mask_grid_ok"] = True
    row["brain_mask_status"] = "ready_candidate"
    row["brain_mask_components"] = 1
    row["brain_mask_qc_png"] = "reports/qc/brain_masks/nnunet/C25S1_D1_qc.png"

    rows = build_analysis_manifest_rows([row])

    assert rows[0]["include"] == "yes"
    assert rows[0]["brain_mask_path"].endswith("C25S1_D1.nii.gz")
    assert rows[0]["brain_mask_source"] == "nnunet"
    assert rows[0]["brain_mask_qc_png"].endswith("C25S1_D1_qc.png")


def test_analysis_manifest_testing_mode_can_include_review_level_masks():
    row = qc_row()
    row.pop("manual_mask_path")
    row["brain_mask_path"] = "derivatives/brain_seg/manual/C25S1_D1_pre_manual_mask.nii.gz"
    row["brain_mask_source"] = "manual_test"
    row["brain_mask_grid_ok"] = True
    row["brain_mask_status"] = "needs_review"
    row["brain_mask_notes"] = "components 3 > 1"

    final_rows = build_analysis_manifest_rows([row])
    testing_rows = build_analysis_manifest_rows([row], allow_review_masks_for_testing=True)

    assert final_rows[0]["include"] == "no"
    assert final_rows[0]["brain_mask_path"] == ""
    assert testing_rows[0]["include"] == "yes"
    assert testing_rows[0]["qc_gate"] == "testing_review_mask"
    assert testing_rows[0]["analysis_mode"] == "testing_nonfinal_masks"


def test_analysis_manifest_does_not_final_include_testing_sources_even_if_ready():
    row = qc_row()
    row.pop("manual_mask_path")
    row["brain_mask_path"] = "derivatives/brain_seg/manual_test_cleaned/C25S1_D1.nii.gz"
    row["brain_mask_source"] = "manual_test_cleaned"
    row["brain_mask_grid_ok"] = True
    row["brain_mask_status"] = "ready_candidate"
    row["brain_mask_components"] = 1

    final_rows = build_analysis_manifest_rows([row])
    testing_rows = build_analysis_manifest_rows([row], allow_review_masks_for_testing=True)

    assert final_rows[0]["include"] == "no"
    assert final_rows[0]["qc_gate"] == "testing_mask_source"
    assert testing_rows[0]["include"] == "yes"
    assert testing_rows[0]["qc_gate"] == "testing_review_mask"
