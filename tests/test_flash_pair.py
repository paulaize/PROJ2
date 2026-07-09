"""Tests for single-pair enhancement maps and mask-required behavior."""

from __future__ import annotations

import numpy as np
import pytest

from lys_bbb.flash_pair import (
    enhancement_maps,
    montage_slices,
    normalize_pair,
    parse_args,
)


def test_median_normalization_scales_each_image_inside_mask():
    mask = np.array([True, True, False])
    pre = np.array([2.0, 4.0, 100.0], dtype=np.float32)
    post = np.array([10.0, 20.0, 100.0], dtype=np.float32)

    pre_norm, post_norm, meta = normalize_pair(pre, post, mask, "median")

    assert meta["pre_scale"] == 3.0
    assert meta["post_scale"] == 15.0
    np.testing.assert_allclose(np.median(pre_norm[mask]), 1.0)
    np.testing.assert_allclose(np.median(post_norm[mask]), 1.0)


def test_enhancement_maps_are_masked_and_formula_based():
    mask = np.array([True, True, False])
    pre = np.array([1.0, 2.0, 1.0], dtype=np.float32)
    post = np.array([1.5, 1.0, 5.0], dtype=np.float32)

    maps = enhancement_maps(pre, post, mask)

    np.testing.assert_allclose(maps["post_minus_pre"][:2], [0.5, -1.0])
    np.testing.assert_allclose(maps["post_over_pre"][:2], [1.5, 0.5])
    np.testing.assert_allclose(maps["percent_enhancement"][:2], [50.0, -50.0])
    assert np.isnan(maps["post_minus_pre"][2])
    assert np.isnan(maps["post_over_pre"][2])
    assert np.isnan(maps["percent_enhancement"][2])


def test_montage_slices_uses_requested_coronal_range():
    slices = montage_slices((24, 36, 40), n=4, slice_start=10, slice_stop=20)

    np.testing.assert_array_equal(slices, [10, 13, 16, 20])


def test_pair_cli_requires_pre_space_brain_mask():
    with pytest.raises(SystemExit):
        parse_args([
            "--pre",
            "pre_coronal.nii.gz",
            "--post",
            "post_coronal.nii.gz",
            "-o",
            "out",
        ])
