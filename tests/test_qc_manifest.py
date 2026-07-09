"""Tests for QC manifest helper functions."""

from __future__ import annotations

import numpy as np

from lys_bbb.qc_manifest import affine_comparison, dice_and_xor, mask_metrics, status_for_row


class DummyImage:
    def __init__(self, shape, affine):
        self.shape = shape
        self.affine = affine


def test_mask_metrics_counts_components_and_volume():
    mask = np.zeros((5, 5, 5), dtype=bool)
    mask[1:3, 1:3, 1:3] = True
    mask[4, 4, 4] = True

    metrics = mask_metrics(mask, voxel_volume_mm3=0.5, small_component_voxels=2)

    assert metrics["voxels"] == 9
    assert metrics["volume_mm3"] == 4.5
    assert metrics["components"] == 2
    assert metrics["small_components"] == 1
    assert metrics["largest_component_pct"] == 8 / 9 * 100.0


def test_dice_and_xor_for_identical_and_partially_different_masks():
    a = np.array([True, True, False, False])
    b = np.array([True, False, True, False])

    dice, xor_voxels = dice_and_xor(a, b)

    assert dice == 0.5
    assert xor_voxels == 2
    assert dice_and_xor(a, a) == (1.0, 0)


def test_affine_comparison_reports_origin_distance():
    ref = DummyImage((2, 2, 2), np.eye(4))
    other_affine = np.eye(4)
    other_affine[:3, 3] = [3.0, 4.0, 0.0]
    other = DummyImage((2, 2, 2), other_affine)

    comparison = affine_comparison(ref, other)

    assert comparison["shape_match"] is True
    assert comparison["affine_match"] is False
    assert comparison["max_affine_diff"] == 4.0
    assert comparison["origin_distance_mm"] == 5.0


def test_status_for_row_marks_unchanged_prelabel_for_review():
    row = {
        "pre_exists": True,
        "post_exists": True,
        "pre_post_shape_match": True,
        "pre_post_affine_match": True,
        "manual_mask_path": "manual.nii.gz",
        "manual_mask_grid_ok": True,
        "manual_mask_done_name": False,
        "manual_mask_components": 3,
        "manual_mbe_dice": 1.0,
        "registration_qc_png": "",
        "registration_source_match": "",
    }

    status, notes = status_for_row(row)

    assert status == "needs_review"
    assert "identical to MouseBrainExtractor" in notes
    assert "not marked done" in notes
    assert "multiple connected components" in notes
    assert "missing registration QC" in notes


def test_status_for_row_flags_registration_source_mismatch():
    row = {
        "pre_exists": True,
        "post_exists": True,
        "pre_post_shape_match": True,
        "pre_post_affine_match": True,
        "manual_mask_path": "manual_done.nii.gz",
        "manual_mask_grid_ok": True,
        "manual_mask_done_name": True,
        "manual_mask_components": 1,
        "manual_mbe_dice": 0.9,
        "registration_qc_png": "registration.png",
        "registration_source_match": False,
    }

    status, notes = status_for_row(row)

    assert status == "needs_review"
    assert "registration QC source paths differ" in notes
