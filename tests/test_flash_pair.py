"""Tests for single-pair enhancement maps and mask-required behavior."""

from __future__ import annotations

import numpy as np
import nibabel as nib
import pytest

from lys_bbb.flash_pair import (
    enhancement_maps,
    montage_slices,
    normalize_pair,
    parse_args,
)
from lys_bbb.t1_enhancement import (
    T1EnhancementConfig,
    T1EnhancementRequest,
    run_t1_enhancement,
)
from lys_bbb.t1_registration import T1RegistrationConfig


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


def test_typed_enhancement_contract_consumes_registered_image_without_registration(
    tmp_path,
):
    affine = np.diag([0.1, 0.1, 0.5, 1.0])
    pre_data = np.full((4, 5, 6), 100.0, dtype=np.float32)
    registered_post_data = np.full((4, 5, 6), 110.0, dtype=np.float32)
    mask_data = np.ones((4, 5, 6), dtype=np.uint8)
    pre = tmp_path / "pre.nii.gz"
    registered_post = tmp_path / "post_registered.nii.gz"
    mask = tmp_path / "mask.nii.gz"
    nib.save(nib.Nifti1Image(pre_data, affine), pre)
    nib.save(nib.Nifti1Image(registered_post_data, affine), registered_post)
    nib.save(nib.Nifti1Image(mask_data, affine), mask)

    output = run_t1_enhancement(
        T1EnhancementRequest(
            case_id="Mouse-01",
            pre_t1_path=pre,
            registered_post_t1_path=registered_post,
            approved_brain_mask_path=mask,
            output_directory=tmp_path / "out",
            config=T1EnhancementConfig(
                bias_method="none",
                normalization="none",
            ),
        )
    )

    assert output.percent_enhancement_map.is_file()
    assert output.metadata["registration_recomputed"] is False
    assert output.metadata["registration"]["method"] == "none"
    assert output.method_spec_sha256 == T1EnhancementConfig(
        bias_method="none",
        normalization="none",
    ).method_spec_sha256


def test_registration_method_spec_is_stable_and_parameter_sensitive():
    default = T1RegistrationConfig()
    same = T1RegistrationConfig()
    changed = T1RegistrationConfig(iterations=151)

    assert default.method_spec_sha256 == same.method_spec_sha256
    assert default.method_spec_sha256 != changed.method_spec_sha256
