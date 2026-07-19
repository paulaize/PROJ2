import numpy as np

from lys_bbb.brain_mask_refinement import (
    GapRefinementConfig,
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
