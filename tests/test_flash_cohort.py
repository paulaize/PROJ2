"""Tests for cohort discovery, correction, and D1/D7 delta metrics."""

from __future__ import annotations

import numpy as np

from lys_bbb.flash_cohort import (
    build_delta_rows,
    discover_sessions,
    hemisphere_masks,
    parse_case_id,
    quantify_enhancement,
)


def test_parse_case_id_extracts_animal_timepoint_and_suffix():
    parts = parse_case_id("C23S3_D1_bis")

    assert parts is not None
    assert parts.animal_id == "C23S3"
    assert parts.timepoint == "D1"
    assert parts.suffix == "bis"


def test_discover_sessions_finds_converted_pre_post_folders(tmp_path):
    case_dir = tmp_path / "C25S1_D7"
    case_dir.mkdir()
    (case_dir / "pre_coronal.nii.gz").touch()
    (case_dir / "post_coronal.nii.gz").touch()
    ignored_dir = tmp_path / "not_a_case"
    ignored_dir.mkdir()
    (ignored_dir / "pre_coronal.nii.gz").touch()
    (ignored_dir / "post_coronal.nii.gz").touch()

    sessions = discover_sessions(tmp_path)

    assert len(sessions) == 1
    assert sessions[0].case_id == "C25S1_D7"
    assert sessions[0].animal_id == "C25S1"
    assert sessions[0].timepoint == "D7"


def test_discover_sessions_applies_brain_mask_source_override(tmp_path):
    case_dir = tmp_path / "C25S1_D7"
    case_dir.mkdir()
    (case_dir / "pre_coronal.nii.gz").touch()
    (case_dir / "post_coronal.nii.gz").touch()
    overrides = {
        "C25S1_D7": {
            "brain_mask_path": "masks/C25S1_D7.nii.gz",
            "brain_mask_source": "nnunet",
        }
    }

    sessions = discover_sessions(tmp_path, overrides=overrides)

    assert str(sessions[0].brain_mask_path) == "masks/C25S1_D7.nii.gz"
    assert sessions[0].brain_mask_source == "nnunet"


def test_hemisphere_masks_map_left_to_low_x_when_axis0_increases_rightward():
    brain = np.zeros((6, 2, 2), dtype=bool)
    brain[1:5, :, :] = True
    affine = np.diag([1.0, 1.0, 1.0, 1.0])

    ipsi, contra, axis0 = hemisphere_masks(brain, affine, "left")

    assert axis0 == "R"
    assert ipsi[1:3].all()
    assert not ipsi[3:5].any()
    assert contra[3:5].all()
    assert not contra[1:3].any()


def test_quantify_enhancement_uses_mirrored_contralateral_reference():
    ce = np.zeros((6, 3, 1), dtype=np.float32)
    brain = np.ones_like(ce, dtype=bool)
    lesion = np.zeros_like(brain)
    lesion[1, 1, 0] = True
    ce[1, 1, 0] = 40.0
    ce[4, 1, 0] = 5.0
    affine = np.diag([1.0, 1.0, 1.0, 1.0])

    metrics = quantify_enhancement(
        ce,
        brain,
        affine=affine,
        voxel_volume_mm3=0.5,
        lesion_mask=lesion,
        ipsilateral_side="left",
        reference_mode="mirrored_roi",
        threshold_method="contra_p95",
    )

    assert metrics["roi_type"] == "lesion_mask"
    assert metrics["reference_mode"] == "mirrored_roi"
    assert metrics["reference_ce_median_pct"] == 5.0
    assert metrics["mean_corrected_ce_pct"] == 35.0
    assert metrics["enhancing_volume_mm3"] == 0.5
    assert metrics["pct_lesion_enhancing"] == 100.0
    np.testing.assert_allclose(
        metrics["bbb_leakage_index_pct"],
        ((1.4 / 1.05) - 1.0) * 100.0,
        rtol=1e-6,
    )


def test_quantify_enhancement_without_side_reports_uncorrected_whole_brain_metrics():
    ce = np.array([0.0, 5.0, 20.0, 30.0], dtype=np.float32).reshape((4, 1, 1))
    brain = np.ones_like(ce, dtype=bool)
    affine = np.diag([1.0, 1.0, 1.0, 1.0])

    metrics = quantify_enhancement(
        ce,
        brain,
        affine=affine,
        voxel_volume_mm3=2.0,
        threshold_corrected_ce_pct=10.0,
    )

    assert metrics["roi_type"] == "brain_mask"
    assert metrics["reference_mode"] == "none"
    assert metrics["threshold_method"] == "absolute_ce_gt"
    assert metrics["enhancing_volume_mm3"] == 4.0
    assert metrics["pct_roi_enhancing"] == 50.0
    assert np.isnan(metrics["bbb_leakage_index_pct"])


def test_build_delta_rows_skips_animals_with_duplicate_timepoints():
    rows = [
        {
            "row_type": "session",
            "status": "processed",
            "animal_id": "C1S1",
            "timepoint": "D1",
            "mean_corrected_ce_pct": 10.0,
            "enhancing_volume_mm3": 1.0,
        },
        {
            "row_type": "session",
            "status": "processed",
            "animal_id": "C1S1",
            "timepoint": "D7",
            "mean_corrected_ce_pct": 15.0,
            "enhancing_volume_mm3": 2.5,
        },
        {
            "row_type": "session",
            "status": "processed",
            "animal_id": "C2S1",
            "timepoint": "D1",
            "mean_corrected_ce_pct": 5.0,
        },
        {
            "row_type": "session",
            "status": "processed",
            "animal_id": "C2S1",
            "timepoint": "D1",
            "mean_corrected_ce_pct": 6.0,
        },
        {
            "row_type": "session",
            "status": "processed",
            "animal_id": "C2S1",
            "timepoint": "D7",
            "mean_corrected_ce_pct": 7.0,
        },
    ]

    deltas, warnings = build_delta_rows(rows)

    assert len(deltas) == 1
    assert deltas[0]["case_id"] == "C1S1_D7-D1"
    assert deltas[0]["mean_corrected_ce_pct"] == 5.0
    assert deltas[0]["enhancing_volume_mm3"] == 1.5
    assert warnings == ["skipping D7-D1 delta for C2S1: 2 D1 row(s), 1 D7 row(s)"]
