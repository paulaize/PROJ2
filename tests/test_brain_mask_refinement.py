import numpy as np

from lys_bbb.brain_mask_refinement import (
    GapRefinementConfig,
    assess_mask_regularity,
    detect_gap_volume,
    refine_direct_seam,
    robust_normalize,
)


def synthetic_brain_and_cap() -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    shape = (72, 96, 9)
    xx, yy = np.meshgrid(np.arange(shape[0]), np.arange(shape[1]), indexing="ij")
    image = np.zeros(shape, dtype=np.float32)
    mask = np.zeros(shape, dtype=bool)
    brain_reference = np.zeros(shape, dtype=bool)
    for z in range(shape[2]):
        brain = ((xx - 36) / 24) ** 2 + ((yy - 43) / 29) ** 2 <= 1
        seam = 68 - (np.abs(xx - 36) / 8).astype(int)
        cap = (np.abs(xx - 36) <= 20) & (yy > seam) & (yy <= 82)
        raw = brain | cap
        image[:, :, z][brain] = 0.62
        image[:, :, z][cap] = 0.88
        # The raw network mask crosses this image-dark separating line.
        line = raw & (np.abs(yy - seam) <= 1)
        image[:, :, z][line] = 0.03
        mask[:, :, z] = raw
        brain_reference[:, :, z] = brain & ~line
    return image, mask, brain_reference


def test_dark_gap_seam_removes_cap_without_adding_voxels() -> None:
    image, raw, brain_reference = synthetic_brain_and_cap()
    config = GapRefinementConfig(
        max_search_depth_mm=3.0,
        min_valley_contrast=0.08,
        min_confident_width_fraction=0.18,
    )
    normalized = robust_normalize(image, raw)
    gaps = detect_gap_volume(normalized, raw, (0.15, 0.08, 0.08), config)
    refined, stats = refine_direct_seam(raw, gaps, config)

    assert stats["status"] == "corrected"
    assert stats["removed_voxels"] > 0
    assert not np.any(refined & ~raw)
    assert np.count_nonzero(refined & brain_reference) / np.count_nonzero(brain_reference) > 0.97
    assert np.count_nonzero(refined & ~brain_reference) < np.count_nonzero(raw & ~brain_reference) * 0.2


def test_no_intensity_valley_leaves_mask_unchanged() -> None:
    _, raw, _ = synthetic_brain_and_cap()
    image = np.where(raw, 1.0, 0.0).astype(np.float32)
    config = GapRefinementConfig()
    normalized = robust_normalize(image + np.linspace(0, 0.01, image.size).reshape(image.shape), raw)
    gaps = detect_gap_volume(normalized, raw, (0.15, 0.08, 0.08), config)
    refined, stats = refine_direct_seam(raw, gaps, config)

    assert stats["status"] == "unchanged_no_confident_correction"
    assert np.array_equal(refined, raw)


def synthetic_smooth_ellipsoid() -> np.ndarray:
    coordinates = np.indices((64, 64, 25), dtype=np.float64)
    return (
        ((coordinates[0] - 31.5) / 23.0) ** 2
        + ((coordinates[1] - 31.5) / 26.0) ** 2
        + ((coordinates[2] - 12.0) / 10.0) ** 2
        <= 1.0
    )


def test_mask_regularity_reports_physical_smooth_profile() -> None:
    mask = synthetic_smooth_ellipsoid()

    report = assess_mask_regularity(mask, (0.08, 0.08, 0.5))

    assert report.connected_components == 1
    assert report.internal_empty_slices == ()
    assert report.abrupt_area_pairs == ()
    assert report.abrupt_centroid_pairs == ()
    assert report.one_slice_outlier_slices == ()
    assert report.surface_area_mm2 > 0
    assert report.volume_mm3 == np.count_nonzero(mask) * 0.08 * 0.08 * 0.5
    assert report.warnings == ()


def test_mask_regularity_flags_one_slice_centroid_jump() -> None:
    mask = synthetic_smooth_ellipsoid()
    shifted_slice = np.roll(mask[:, :, 12], shift=14, axis=0)
    mask[:, :, 12] = shifted_slice

    report = assess_mask_regularity(mask, (0.08, 0.08, 0.5))

    assert report.abrupt_centroid_pairs
    assert "abrupt_centroid_motion" in report.warnings


def test_mask_regularity_flags_isolated_one_slice_notch() -> None:
    mask = synthetic_smooth_ellipsoid()
    mask[:, 30:, 12] = False

    report = assess_mask_regularity(mask, (0.08, 0.08, 0.5))

    assert report.one_slice_outlier_slices == (12,)
    assert "isolated_one_slice_area_outlier" in report.warnings


def test_mask_regularity_flags_disconnected_island_without_editing_mask() -> None:
    mask = synthetic_smooth_ellipsoid()
    mask[0:2, 0:2, 12] = True
    original = mask.copy()

    report = assess_mask_regularity(mask, (0.08, 0.08, 0.5))

    assert report.connected_components == 2
    assert "disconnected_components" in report.warnings
    assert np.array_equal(mask, original)
