"""Experimental T1-guided refinements for an RS2-Net brain-mask pre-label.

These functions are deliberately conservative research utilities.  They never turn an
automatic prediction into an approved mask and they leave slices unchanged when a
plausible superior brain--skull intensity valley cannot be detected.

Arrays passed to this module use anatomical R/S/A order: left-to-right, inferior-to-
superior, and posterior-to-anterior.  The Colab notebook performs and records the
orientation conversion before calling these functions.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

import numpy as np
from scipy import ndimage as ndi


@dataclass(frozen=True)
class GapRefinementConfig:
    """Parameters expressed primarily in physical millimetres."""

    max_search_depth_mm: float = 2.8
    min_cap_thickness_mm: float = 0.30
    valley_window_mm: float = 0.32
    line_smoothing_mm: float = 0.10
    min_valley_contrast: float = 0.10
    min_confident_width_fraction: float = 0.22
    central_fraction: float = 0.75
    max_column_jump_mm: float = 0.55
    lateral_extension_mm: float = 0.75
    extend_seam_to_mask_edges: bool = True
    seed_margin_mm: float = 0.24
    min_slice_removed_fraction: float = 0.01
    max_slice_removed_fraction: float = 0.35
    min_corrected_slices: int = 3


@dataclass(frozen=True)
class MaskRegularityConfig:
    """Conservative warning thresholds for a 3-D mouse-brain mask.

    These checks describe suspicious geometry; they never edit, accept, or reject a
    mask. End slices below ``profile_area_fraction`` of the maximum cross-sectional
    area are excluded from local-change checks because a normal brain tapers there.
    """

    profile_area_fraction: float = 0.20
    max_adjacent_area_change_fraction: float = 0.55
    max_one_slice_area_deviation_fraction: float = 0.30
    max_centroid_step_mm: float = 0.75
    min_compactness: float = 0.05


@dataclass(frozen=True)
class MSeamCleanupConfig:
    """Conservative physical rules for stabilising an M-seam draft mask.

    The cleanup is deliberately restricted to two failure modes observed during the
    frozen ten-case review: small in-plane islands in established brain-containing
    slices and short shape outlier runs bracketed by similar masks.  Interpolated
    repairs are always intersected with the immutable raw RS2 prediction, so the
    cleanup can never invent foreground outside the model prediction.
    """

    profile_area_fraction: float = 0.20
    max_secondary_component_fraction: float = 0.12
    max_secondary_component_area_mm2: float = 4.0
    consensus_half_window_mm: float = 0.70
    min_shape_disagreement_fraction: float = 0.035
    max_repair_run_mm: float = 0.60
    min_flank_dice: float = 0.92
    max_flank_area_change_fraction: float = 0.18
    max_slice_change_fraction: float = 0.12


@dataclass(frozen=True)
class MSeamCleanupReport:
    """Auditable changes made to one automatic M-seam draft mask."""

    input_foreground_voxels: int
    output_foreground_voxels: int
    disconnected_voxels_removed: int
    in_plane_island_voxels_removed: int
    in_plane_cleaned_slices: tuple[int, ...]
    candidate_outlier_slices: tuple[int, ...]
    outlier_score_by_slice: tuple[tuple[int, float], ...]
    repaired_slice_runs: tuple[tuple[int, int], ...]
    skipped_slice_runs: tuple[tuple[int, int, str], ...]
    voxels_added_from_raw_rs2: int
    voxels_removed_by_run_repair: int
    changed_voxels: int
    subset_of_raw_rs2: bool
    configuration: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable representation for provenance metadata."""

        return asdict(self)


@dataclass(frozen=True)
class MaskRegularityReport:
    """Physical and slice-profile measurements used to guide human review."""

    foreground_voxels: int
    volume_mm3: float
    connected_components: int
    occupied_slice_range: tuple[int, int]
    internal_empty_slices: tuple[int, ...]
    slice_area_mm2: tuple[float, ...]
    centroid_rs_mm: tuple[tuple[float, float] | None, ...]
    max_adjacent_area_change_fraction: float
    abrupt_area_pairs: tuple[tuple[int, int], ...]
    max_centroid_step_mm: float
    abrupt_centroid_pairs: tuple[tuple[int, int], ...]
    one_slice_outlier_slices: tuple[int, ...]
    surface_area_mm2: float
    surface_to_volume_ratio_mm_inverse: float
    compactness: float
    warnings: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable representation for provenance metadata."""

        return asdict(self)


@dataclass
class SliceGap:
    """A detected superior separating line for one coronal slice."""

    valid: bool
    seam: np.ndarray
    x_start: int = 0
    x_stop: int = 0
    confidence: float = 0.0
    coverage: float = 0.0
    reason: str = ""


def _voxel_face_surface_area(mask: np.ndarray, spacing: np.ndarray) -> float:
    """Estimate physical surface area by counting exposed voxel faces."""

    padded = np.pad(np.asarray(mask, dtype=np.int8), 1)
    surface_area = 0.0
    for axis in range(3):
        exposed_faces = int(np.count_nonzero(np.diff(padded, axis=axis)))
        face_area = float(np.prod(np.delete(spacing, axis)))
        surface_area += exposed_faces * face_area
    return surface_area


def assess_mask_regularity(
    mask_rsa: np.ndarray,
    spacing_rsa: tuple[float, float, float],
    config: MaskRegularityConfig | None = None,
) -> MaskRegularityReport:
    """Measure 3-D regularity without changing or approving the supplied mask.

    The report looks for disconnected islands, internal empty slices, sudden changes
    in coronal area or centroid, and isolated one-slice area deviations. Surface and
    compactness measurements are expressed in physical units so anisotropic scans are
    not treated as isotropic voxel grids.
    """

    mask = np.asarray(mask_rsa, dtype=bool)
    if mask.ndim != 3:
        raise ValueError("Mask regularity assessment requires a three-dimensional mask")
    if not mask.any():
        raise ValueError("Mask regularity assessment requires a non-empty mask")
    spacing = np.asarray(spacing_rsa, dtype=np.float64)
    if spacing.shape != (3,) or not np.all(np.isfinite(spacing)) or np.any(spacing <= 0):
        raise ValueError("Mask spacing must contain three finite positive values")
    config = config or MaskRegularityConfig()

    foreground_voxels = int(np.count_nonzero(mask))
    voxel_volume = float(np.prod(spacing))
    volume_mm3 = foreground_voxels * voxel_volume
    _, connected_components = ndi.label(mask)

    counts = np.count_nonzero(mask, axis=(0, 1)).astype(np.float64)
    areas = counts * float(spacing[0] * spacing[1])
    occupied = np.flatnonzero(counts)
    first_slice, last_slice = int(occupied[0]), int(occupied[-1])
    internal_empty = tuple(
        int(index)
        for index in range(first_slice, last_slice + 1)
        if counts[index] == 0
    )

    centroid_rs: list[tuple[float, float] | None] = []
    for slice_index in range(mask.shape[2]):
        coordinates = np.argwhere(mask[:, :, slice_index])
        if coordinates.size == 0:
            centroid_rs.append(None)
            continue
        centroid = coordinates.mean(axis=0) * spacing[:2]
        centroid_rs.append((float(centroid[0]), float(centroid[1])))

    profile = areas >= float(areas.max() * config.profile_area_fraction)
    area_changes: list[tuple[tuple[int, int], float]] = []
    centroid_steps: list[tuple[tuple[int, int], float]] = []
    for left in range(mask.shape[2] - 1):
        right = left + 1
        if not (profile[left] and profile[right]):
            continue
        denominator = max(float((areas[left] + areas[right]) / 2.0), np.finfo(float).eps)
        area_change = float(abs(areas[right] - areas[left]) / denominator)
        area_changes.append(((left, right), area_change))
        left_centroid, right_centroid = centroid_rs[left], centroid_rs[right]
        if left_centroid is not None and right_centroid is not None:
            centroid_step = float(
                np.linalg.norm(np.asarray(right_centroid) - np.asarray(left_centroid))
            )
            centroid_steps.append(((left, right), centroid_step))

    abrupt_area_pairs = tuple(
        pair
        for pair, change in area_changes
        if change > config.max_adjacent_area_change_fraction
    )
    abrupt_centroid_pairs = tuple(
        pair
        for pair, step in centroid_steps
        if step > config.max_centroid_step_mm
    )

    one_slice_outliers: list[int] = []
    for index in range(1, mask.shape[2] - 1):
        if not (profile[index - 1] and profile[index] and profile[index + 1]):
            continue
        neighbour_area = float((areas[index - 1] + areas[index + 1]) / 2.0)
        neighbour_disagreement = abs(
            float(areas[index - 1]) - float(areas[index + 1])
        ) / max(neighbour_area, np.finfo(float).eps)
        if neighbour_disagreement > config.max_one_slice_area_deviation_fraction:
            continue
        deviation = abs(float(areas[index]) - neighbour_area) / max(
            neighbour_area, np.finfo(float).eps
        )
        if deviation > config.max_one_slice_area_deviation_fraction:
            one_slice_outliers.append(index)

    surface_area = _voxel_face_surface_area(mask, spacing)
    surface_to_volume = surface_area / volume_mm3
    compactness = float(36.0 * np.pi * volume_mm3**2 / surface_area**3)

    warnings: list[str] = []
    if connected_components > 1:
        warnings.append("disconnected_components")
    if internal_empty:
        warnings.append("internal_empty_slices")
    if abrupt_area_pairs:
        warnings.append("abrupt_cross_section_change")
    if abrupt_centroid_pairs:
        warnings.append("abrupt_centroid_motion")
    if one_slice_outliers:
        warnings.append("isolated_one_slice_area_outlier")
    if compactness < config.min_compactness:
        warnings.append("low_physical_compactness")

    return MaskRegularityReport(
        foreground_voxels=foreground_voxels,
        volume_mm3=volume_mm3,
        connected_components=int(connected_components),
        occupied_slice_range=(first_slice, last_slice),
        internal_empty_slices=internal_empty,
        slice_area_mm2=tuple(float(value) for value in areas),
        centroid_rs_mm=tuple(centroid_rs),
        max_adjacent_area_change_fraction=max(
            (change for _, change in area_changes), default=0.0
        ),
        abrupt_area_pairs=abrupt_area_pairs,
        max_centroid_step_mm=max((step for _, step in centroid_steps), default=0.0),
        abrupt_centroid_pairs=abrupt_centroid_pairs,
        one_slice_outlier_slices=tuple(one_slice_outliers),
        surface_area_mm2=surface_area,
        surface_to_volume_ratio_mm_inverse=surface_to_volume,
        compactness=compactness,
        warnings=tuple(warnings),
    )


def robust_normalize(image: np.ndarray, mask: np.ndarray) -> np.ndarray:
    """Scale finite masked intensities to [0, 1] using robust cohort-independent limits."""

    image = np.asarray(image, dtype=np.float32)
    mask = np.asarray(mask, dtype=bool)
    values = image[mask & np.isfinite(image)]
    if values.size < 100:
        raise ValueError("Too few finite foreground voxels for robust normalization")
    low, high = np.percentile(values, (2.0, 98.0))
    if not np.isfinite(low) or not np.isfinite(high) or high <= low:
        raise ValueError(f"Invalid robust intensity limits: {low}, {high}")
    normalized = np.clip((image - low) / (high - low), 0.0, 1.0)
    normalized[~np.isfinite(normalized)] = 0.0
    return normalized.astype(np.float32, copy=False)


def _longest_true_run(values: np.ndarray) -> tuple[int, int]:
    padded = np.pad(np.asarray(values, dtype=np.int8), 1)
    changes = np.diff(padded)
    starts = np.flatnonzero(changes == 1)
    stops = np.flatnonzero(changes == -1)
    if starts.size == 0:
        return 0, 0
    lengths = stops - starts
    index = int(np.argmax(lengths))
    return int(starts[index]), int(stops[index])


def detect_dark_gap(
    normalized_slice: np.ndarray,
    mask_slice: np.ndarray,
    spacing_rs: tuple[float, float],
    config: GapRefinementConfig,
) -> SliceGap:
    """Detect a smooth dark superior valley in a single R/S coronal slice."""

    image = np.asarray(normalized_slice, dtype=np.float32)
    mask = np.asarray(mask_slice, dtype=bool)
    if image.ndim != 2 or image.shape != mask.shape:
        raise ValueError("The image and mask slice must be matching two-dimensional arrays")
    occupied_x = np.flatnonzero(mask.any(axis=1))
    empty_seam = np.full(mask.shape[0], np.nan, dtype=np.float32)
    if occupied_x.size < 8:
        return SliceGap(False, empty_seam, reason="too_little_foreground")

    spacing_s = float(spacing_rs[1])
    max_depth = max(4, int(round(config.max_search_depth_mm / spacing_s)))
    min_cap = max(2, int(round(config.min_cap_thickness_mm / spacing_s)))
    window = max(2, int(round(config.valley_window_mm / spacing_s)))
    sigma = max(0.5, config.line_smoothing_mm / spacing_s)
    max_jump = max(2, int(round(config.max_column_jump_mm / spacing_s)))

    smooth = ndi.gaussian_filter1d(image, sigma=sigma, axis=1, mode="nearest")
    candidates = empty_seam.copy()
    contrasts = np.zeros(mask.shape[0], dtype=np.float32)
    tops = np.full(mask.shape[0], -1, dtype=np.int32)

    for x in occupied_x:
        ys = np.flatnonzero(mask[x])
        bottom, top = int(ys[0]), int(ys[-1])
        tops[x] = top
        lower = max(bottom + 1, top - max_depth)
        upper = top - min_cap
        if upper <= lower + 1:
            continue
        best_y = None
        best_contrast = -np.inf
        for y in range(lower, upper + 1):
            below = smooth[x, max(bottom, y - window) : y]
            above = smooth[x, y + 1 : min(top + 1, y + 1 + window)]
            if below.size < 2 or above.size < 2:
                continue
            contrast = min(float(np.mean(below)), float(np.mean(above))) - float(smooth[x, y])
            if contrast > best_contrast:
                best_y, best_contrast = y, contrast
        if best_y is not None:
            candidates[x] = best_y
            contrasts[x] = max(0.0, best_contrast)

    x0, x1 = int(occupied_x[0]), int(occupied_x[-1]) + 1
    width = x1 - x0
    central_margin = int(round(width * (1.0 - config.central_fraction) / 2.0))
    central = np.zeros(mask.shape[0], dtype=bool)
    central[x0 + central_margin : x1 - central_margin] = True
    good = np.isfinite(candidates) & (contrasts >= config.min_valley_contrast) & central
    good = ndi.binary_closing(good, structure=np.ones(5, dtype=bool))

    # Suppress isolated dark structures that jump away from the dominant superior line.
    finite = np.where(np.isfinite(candidates), candidates, 0.0)
    support = np.isfinite(candidates).astype(np.float32)
    smoothed_numerator = ndi.gaussian_filter1d(finite, sigma=2.0, mode="nearest")
    smoothed_denominator = ndi.gaussian_filter1d(support, sigma=2.0, mode="nearest")
    trend = np.divide(
        smoothed_numerator,
        smoothed_denominator,
        out=np.full_like(smoothed_numerator, np.nan),
        where=smoothed_denominator > 1e-3,
    )
    good &= np.abs(candidates - trend) <= max_jump

    run_start, run_stop = _longest_true_run(good[x0:x1])
    run_start += x0
    run_stop += x0
    run_width = run_stop - run_start
    required_width = max(6, int(round(width * config.min_confident_width_fraction)))
    if run_width < required_width:
        return SliceGap(False, empty_seam, reason="insufficient_continuous_dark_gap")

    # Interpolate between supported columns and extrapolate only a small physical margin.
    # This removes thin cap remnants at the ends of an otherwise convincing M-shaped gap
    # without extending the cut across the lateral cortex.
    support_x = np.flatnonzero(good[run_start:run_stop]) + run_start
    if config.extend_seam_to_mask_edges:
        run_start, run_stop = x0, x1
    else:
        extension = max(0, int(round(config.lateral_extension_mm / float(spacing_rs[0]))))
        run_start = max(x0, run_start - extension)
        run_stop = min(x1, run_stop + extension)
    seam = empty_seam.copy()
    seam[run_start:run_stop] = np.interp(
        np.arange(run_start, run_stop), support_x, candidates[support_x]
    )
    seam[run_start:run_stop] = ndi.median_filter(seam[run_start:run_stop], size=5, mode="nearest")
    confidence = float(np.median(contrasts[support_x]))
    coverage = float(run_width / width)
    return SliceGap(True, seam, run_start, run_stop, confidence, coverage, "ok")


def detect_gap_volume(
    normalized_rsa: np.ndarray,
    mask_rsa: np.ndarray,
    spacing_rsa: tuple[float, float, float],
    config: GapRefinementConfig,
) -> list[SliceGap]:
    """Detect candidate seams independently across posterior--anterior slices."""

    gaps = [
        detect_dark_gap(normalized_rsa[:, :, z], mask_rsa[:, :, z], spacing_rsa[:2], config)
        for z in range(mask_rsa.shape[2])
    ]
    valid = np.asarray([gap.valid for gap in gaps], dtype=bool)
    labels, count = ndi.label(valid)
    for label_id in range(1, count + 1):
        indices = np.flatnonzero(labels == label_id)
        if indices.size < config.min_corrected_slices:
            for index in indices:
                gaps[index].valid = False
                gaps[index].reason = "insufficient_continuity_across_slices"
    return gaps


def _slice_markers(
    mask_slice: np.ndarray,
    gap: SliceGap,
    spacing_s: float,
    config: GapRefinementConfig,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return brain seed, cap seed, and the local refinement domain."""

    mask = np.asarray(mask_slice, dtype=bool)
    brain = np.zeros_like(mask)
    cap = np.zeros_like(mask)
    domain = np.zeros_like(mask)
    margin = max(2, int(round(config.seed_margin_mm / spacing_s)))
    for x in range(gap.x_start, gap.x_stop):
        if not np.isfinite(gap.seam[x]):
            continue
        y = int(round(float(gap.seam[x])))
        domain[x] = mask[x]
        brain[x, : max(0, y - margin + 1)] = mask[x, : max(0, y - margin + 1)]
        cap[x, min(mask.shape[1], y + margin) :] = mask[x, min(mask.shape[1], y + margin) :]
    return brain, cap, domain


def _accept_slice(raw: np.ndarray, candidate: np.ndarray, config: GapRefinementConfig) -> bool:
    raw_count = int(np.count_nonzero(raw))
    if raw_count == 0:
        return False
    removed = int(np.count_nonzero(raw & ~candidate))
    fraction = removed / raw_count
    return config.min_slice_removed_fraction <= fraction <= config.max_slice_removed_fraction


def _largest_component(mask: np.ndarray) -> np.ndarray:
    labels, count = ndi.label(mask)
    if count <= 1:
        return np.asarray(mask, dtype=bool)
    sizes = np.bincount(labels.ravel())
    sizes[0] = 0
    return labels == int(np.argmax(sizes))


def _largest_fully_connected_component(mask: np.ndarray) -> tuple[np.ndarray, int]:
    """Keep the largest component using full connectivity and report removed voxels."""

    foreground = np.asarray(mask, dtype=bool)
    structure = ndi.generate_binary_structure(foreground.ndim, foreground.ndim)
    labels, count = ndi.label(foreground, structure=structure)
    if count <= 1:
        return foreground.copy(), 0
    sizes = np.bincount(labels.ravel())
    sizes[0] = 0
    largest = labels == int(np.argmax(sizes))
    return largest, int(np.count_nonzero(foreground & ~largest))


def _prune_small_in_plane_islands(
    mask: np.ndarray,
    spacing_rs: tuple[float, float],
    config: MSeamCleanupConfig,
) -> tuple[np.ndarray, tuple[int, ...], int]:
    """Remove small secondary 2-D components only in the established brain body.

    Comparable bilateral components at the normally tapering ends are preserved.  A
    slice is changed only when the main component is within the central area profile
    and all secondary components are small both relative to it and in physical area.
    """

    output = np.asarray(mask, dtype=bool).copy()
    counts = np.count_nonzero(output, axis=(0, 1))
    if not np.any(counts):
        return output, (), 0
    body_threshold = float(counts.max() * config.profile_area_fraction)
    pixel_area_mm2 = float(spacing_rs[0] * spacing_rs[1])
    structure = ndi.generate_binary_structure(2, 2)
    cleaned_slices: list[int] = []
    removed_voxels = 0
    for slice_index in range(output.shape[2]):
        slice_mask = output[:, :, slice_index]
        if int(np.count_nonzero(slice_mask)) < body_threshold:
            continue
        labels, component_count = ndi.label(slice_mask, structure=structure)
        if component_count <= 1:
            continue
        sizes = np.bincount(labels.ravel())
        sizes[0] = 0
        largest_label = int(np.argmax(sizes))
        largest_size = int(sizes[largest_label])
        secondary_size = int(sizes.sum() - largest_size)
        if largest_size == 0 or secondary_size == 0:
            continue
        relative_size = secondary_size / largest_size
        secondary_area = secondary_size * pixel_area_mm2
        if (
            relative_size > config.max_secondary_component_fraction
            or secondary_area > config.max_secondary_component_area_mm2
        ):
            continue
        output[:, :, slice_index] = labels == largest_label
        cleaned_slices.append(slice_index)
        removed_voxels += secondary_size
    return output, tuple(cleaned_slices), removed_voxels


def _dice(left: np.ndarray, right: np.ndarray) -> float:
    left = np.asarray(left, dtype=bool)
    right = np.asarray(right, dtype=bool)
    denominator = int(np.count_nonzero(left)) + int(np.count_nonzero(right))
    if denominator == 0:
        return 1.0
    return float(2 * np.count_nonzero(left & right) / denominator)


def _signed_distance(mask: np.ndarray, spacing: tuple[float, float]) -> np.ndarray:
    foreground = np.asarray(mask, dtype=bool)
    return ndi.distance_transform_edt(foreground, sampling=spacing) - ndi.distance_transform_edt(
        ~foreground, sampling=spacing
    )


def _true_runs(values: np.ndarray) -> list[tuple[int, int]]:
    """Return inclusive start/stop indices for all true runs."""

    padded = np.pad(np.asarray(values, dtype=np.int8), 1)
    changes = np.diff(padded)
    starts = np.flatnonzero(changes == 1)
    stops = np.flatnonzero(changes == -1) - 1
    return [(int(start), int(stop)) for start, stop in zip(starts, stops, strict=True)]


def stabilize_m_seam_mask(
    m_seam_mask_rsa: np.ndarray,
    raw_rs2_mask_rsa: np.ndarray,
    spacing_rsa: tuple[float, float, float],
    config: MSeamCleanupConfig | None = None,
) -> tuple[np.ndarray, MSeamCleanupReport]:
    """Clean observed M-seam topology failures without approving the result.

    First, true disconnected 3-D islands and sufficiently small in-plane islands are
    removed.  Second, a longitudinal majority profile identifies short abnormal shape
    runs.  A run is repaired only when it is bracketed by highly similar slices; its
    masks are interpolated between the flanks using physical signed-distance fields.
    Every repair remains a subset of the immutable raw RS2 mask.
    """

    candidate = np.asarray(m_seam_mask_rsa, dtype=bool)
    raw = np.asarray(raw_rs2_mask_rsa, dtype=bool)
    if candidate.ndim != 3 or candidate.shape != raw.shape:
        raise ValueError("M-seam cleanup requires matching three-dimensional masks")
    if not candidate.any() or not raw.any():
        raise ValueError("M-seam cleanup requires non-empty masks")
    if np.any(candidate & ~raw):
        raise ValueError("The M-seam mask must be a subset of the raw RS2 prediction")
    spacing = np.asarray(spacing_rsa, dtype=np.float64)
    if spacing.shape != (3,) or not np.all(np.isfinite(spacing)) or np.any(spacing <= 0):
        raise ValueError("M-seam cleanup spacing must contain three finite positive values")
    config = config or MSeamCleanupConfig()

    input_voxels = int(np.count_nonzero(candidate))
    output, disconnected_removed = _largest_fully_connected_component(candidate)
    output, island_slices, island_removed = _prune_small_in_plane_islands(
        output, (float(spacing[0]), float(spacing[1])), config
    )
    output, newly_disconnected = _largest_fully_connected_component(output)
    disconnected_removed += newly_disconnected

    counts = np.count_nonzero(output, axis=(0, 1)).astype(np.float64)
    profile = counts >= float(counts.max() * config.profile_area_fraction)
    radius = max(2, int(np.ceil(config.consensus_half_window_mm / spacing[2])))
    scores = np.zeros(output.shape[2], dtype=np.float64)
    outliers = np.zeros(output.shape[2], dtype=bool)
    for slice_index in range(radius, output.shape[2] - radius):
        if not profile[slice_index]:
            continue
        neighbourhood = output[:, :, slice_index - radius : slice_index + radius + 1]
        consensus = np.count_nonzero(neighbourhood, axis=2) > neighbourhood.shape[2] // 2
        union = int(np.count_nonzero(output[:, :, slice_index] | consensus))
        if union == 0:
            continue
        score = float(np.count_nonzero(output[:, :, slice_index] ^ consensus) / union)
        scores[slice_index] = score
        outliers[slice_index] = score >= config.min_shape_disagreement_fraction

    # Join two suspicious parts separated by one unflagged slice. This is limited to
    # the detection mask; every resulting run must still pass the anatomical flank and
    # maximum-change gates below.
    outliers = ndi.binary_closing(outliers, structure=np.ones(3, dtype=bool))
    max_run_slices = max(1, int(np.floor(config.max_repair_run_mm / spacing[2])))
    repaired_runs: list[tuple[int, int]] = []
    skipped_runs: list[tuple[int, int, str]] = []
    added_voxels = 0
    removed_voxels = 0
    for start, stop in _true_runs(outliers):
        run_length = stop - start + 1
        if run_length > max_run_slices:
            skipped_runs.append((start, stop, "run_too_long"))
            continue
        left_index, right_index = start - 1, stop + 1
        if left_index < 0 or right_index >= output.shape[2]:
            skipped_runs.append((start, stop, "missing_flank"))
            continue
        if not (profile[left_index] and profile[right_index]):
            skipped_runs.append((start, stop, "outside_stable_brain_profile"))
            continue
        left = output[:, :, left_index]
        right = output[:, :, right_index]
        flank_dice = _dice(left, right)
        left_area = int(np.count_nonzero(left))
        right_area = int(np.count_nonzero(right))
        mean_area = max((left_area + right_area) / 2.0, np.finfo(float).eps)
        flank_area_change = abs(left_area - right_area) / mean_area
        if flank_dice < config.min_flank_dice:
            skipped_runs.append((start, stop, "flank_shape_mismatch"))
            continue
        if flank_area_change > config.max_flank_area_change_fraction:
            skipped_runs.append((start, stop, "flank_area_mismatch"))
            continue

        left_distance = _signed_distance(left, (float(spacing[0]), float(spacing[1])))
        right_distance = _signed_distance(right, (float(spacing[0]), float(spacing[1])))
        replacements: list[tuple[int, np.ndarray, int, int]] = []
        rejected_reason = ""
        for offset, slice_index in enumerate(range(start, stop + 1), start=1):
            weight = offset / (run_length + 1)
            interpolated = ((1.0 - weight) * left_distance + weight * right_distance) >= 0
            interpolated &= raw[:, :, slice_index]
            interpolated, _ = _largest_fully_connected_component(interpolated)
            if not interpolated.any():
                rejected_reason = "empty_interpolation"
                break
            current = output[:, :, slice_index]
            union = max(int(np.count_nonzero(current | interpolated)), 1)
            changed_fraction = np.count_nonzero(current ^ interpolated) / union
            if changed_fraction > config.max_slice_change_fraction:
                rejected_reason = "repair_exceeds_change_limit"
                break
            additions = int(np.count_nonzero(interpolated & ~current))
            removals = int(np.count_nonzero(current & ~interpolated))
            replacements.append((slice_index, interpolated, additions, removals))
        if rejected_reason:
            skipped_runs.append((start, stop, rejected_reason))
            continue
        for slice_index, replacement, additions, removals in replacements:
            output[:, :, slice_index] = replacement
            added_voxels += additions
            removed_voxels += removals
        repaired_runs.append((start, stop))

    output, final_disconnected = _largest_fully_connected_component(output)
    disconnected_removed += final_disconnected
    if np.any(output & ~raw):
        raise RuntimeError("M-seam cleanup created foreground outside the raw RS2 mask")
    changed_voxels = int(np.count_nonzero(candidate ^ output))
    scored_slices = tuple(
        (int(index), float(scores[index])) for index in np.flatnonzero(outliers)
    )
    report = MSeamCleanupReport(
        input_foreground_voxels=input_voxels,
        output_foreground_voxels=int(np.count_nonzero(output)),
        disconnected_voxels_removed=disconnected_removed,
        in_plane_island_voxels_removed=island_removed,
        in_plane_cleaned_slices=island_slices,
        candidate_outlier_slices=tuple(int(index) for index in np.flatnonzero(outliers)),
        outlier_score_by_slice=scored_slices,
        repaired_slice_runs=tuple(repaired_runs),
        skipped_slice_runs=tuple(skipped_runs),
        voxels_added_from_raw_rs2=added_voxels,
        voxels_removed_by_run_repair=removed_voxels,
        changed_voxels=changed_voxels,
        subset_of_raw_rs2=not bool(np.any(output & ~raw)),
        configuration=asdict(config),
    )
    return output, report


def refine_direct_seam(
    mask_rsa: np.ndarray,
    gaps: list[SliceGap],
    config: GapRefinementConfig,
) -> tuple[np.ndarray, dict[str, Any]]:
    """Remove only RS2 voxels superior to each accepted dark-gap seam."""

    raw = np.asarray(mask_rsa, dtype=bool)
    output = raw.copy()
    accepted: list[int] = []
    rejected: list[int] = []
    for z, gap in enumerate(gaps):
        if not gap.valid:
            continue
        candidate = raw[:, :, z].copy()
        for x in range(gap.x_start, gap.x_stop):
            if np.isfinite(gap.seam[x]):
                candidate[x, int(np.floor(gap.seam[x])) + 1 :] = False
        candidate = _largest_component(candidate)
        if _accept_slice(raw[:, :, z], candidate, config):
            output[:, :, z] = candidate
            accepted.append(z)
        else:
            rejected.append(z)
    if len(accepted) < config.min_corrected_slices:
        output = raw.copy()
        accepted = []
    output = _largest_component(output)
    return output, _method_stats("rs2_m_seam", raw, output, gaps, accepted, rejected, config)


def refine_watershed(
    normalized_rsa: np.ndarray,
    mask_rsa: np.ndarray,
    gaps: list[SliceGap],
    spacing_rsa: tuple[float, float, float],
    config: GapRefinementConfig,
) -> tuple[np.ndarray, dict[str, Any]]:
    """Use marker-controlled watershed to place the cut on an image gradient."""

    from skimage.segmentation import watershed

    image = np.asarray(normalized_rsa, dtype=np.float32)
    raw = np.asarray(mask_rsa, dtype=bool)
    output = raw.copy()
    accepted: list[int] = []
    rejected: list[int] = []
    for z, gap in enumerate(gaps):
        if not gap.valid:
            continue
        brain_seed, cap_seed, domain = _slice_markers(raw[:, :, z], gap, spacing_rsa[1], config)
        if not brain_seed.any() or not cap_seed.any():
            rejected.append(z)
            continue
        gradient = ndi.gaussian_gradient_magnitude(image[:, :, z], sigma=1.0)
        markers = np.zeros(raw.shape[:2], dtype=np.uint8)
        markers[brain_seed] = 1
        markers[cap_seed] = 2
        labels = watershed(gradient, markers=markers, mask=domain)
        candidate = raw[:, :, z].copy()
        candidate[domain & (labels == 2)] = False
        candidate = _largest_component(candidate)
        if _accept_slice(raw[:, :, z], candidate, config):
            output[:, :, z] = candidate
            accepted.append(z)
        else:
            rejected.append(z)
    if len(accepted) < config.min_corrected_slices:
        output = raw.copy()
        accepted = []
    output = _largest_component(output)
    return output, _method_stats("rs2_marker_watershed", raw, output, gaps, accepted, rejected, config)


def refine_random_walker(
    normalized_rsa: np.ndarray,
    mask_rsa: np.ndarray,
    gaps: list[SliceGap],
    spacing_rsa: tuple[float, float, float],
    config: GapRefinementConfig,
    beta: float = 180.0,
) -> tuple[np.ndarray, dict[str, Any]]:
    """Use marker-based random walker within small per-slice superior crops."""

    from skimage.segmentation import random_walker

    image = np.asarray(normalized_rsa, dtype=np.float32)
    raw = np.asarray(mask_rsa, dtype=bool)
    output = raw.copy()
    accepted: list[int] = []
    rejected: list[int] = []
    errors: dict[int, str] = {}
    for z, gap in enumerate(gaps):
        if not gap.valid:
            continue
        brain_seed, cap_seed, domain = _slice_markers(raw[:, :, z], gap, spacing_rsa[1], config)
        if not brain_seed.any() or not cap_seed.any():
            rejected.append(z)
            continue
        coordinates = np.argwhere(domain)
        x0, y0 = np.maximum(coordinates.min(axis=0) - 2, 0)
        x1, y1 = np.minimum(coordinates.max(axis=0) + 3, np.array(domain.shape))
        crop_domain = domain[x0:x1, y0:y1]
        labels = np.full(crop_domain.shape, -1, dtype=np.int8)
        labels[crop_domain] = 0
        labels[brain_seed[x0:x1, y0:y1]] = 1
        labels[cap_seed[x0:x1, y0:y1]] = 2
        try:
            result = random_walker(
                image[x0:x1, y0:y1, z], labels, beta=beta, mode="cg_j", tol=1e-3
            )
        except Exception as exc:  # Leave this experimental slice unchanged and report it.
            errors[z] = f"{type(exc).__name__}: {exc}"
            rejected.append(z)
            continue
        candidate = raw[:, :, z].copy()
        local_cap = crop_domain & (result == 2)
        candidate_crop = candidate[x0:x1, y0:y1]
        candidate_crop[local_cap] = False
        candidate = _largest_component(candidate)
        if _accept_slice(raw[:, :, z], candidate, config):
            output[:, :, z] = candidate
            accepted.append(z)
        else:
            rejected.append(z)
    if len(accepted) < config.min_corrected_slices:
        output = raw.copy()
        accepted = []
    output = _largest_component(output)
    stats = _method_stats("rs2_random_walker", raw, output, gaps, accepted, rejected, config)
    stats["beta"] = beta
    stats["slice_errors"] = errors
    return output, stats


def _method_stats(
    method: str,
    raw: np.ndarray,
    output: np.ndarray,
    gaps: list[SliceGap],
    accepted: list[int],
    rejected: list[int],
    config: GapRefinementConfig,
) -> dict[str, Any]:
    raw_count = int(np.count_nonzero(raw))
    output_count = int(np.count_nonzero(output))
    return {
        "method": method,
        "status": "corrected" if accepted else "unchanged_no_confident_correction",
        "raw_foreground_voxels": raw_count,
        "output_foreground_voxels": output_count,
        "removed_voxels": raw_count - output_count,
        "removed_fraction": (raw_count - output_count) / raw_count if raw_count else 0.0,
        "detected_gap_slices": [index for index, gap in enumerate(gaps) if gap.valid],
        "corrected_slices": accepted,
        "rejected_slices": rejected,
        "configuration": asdict(config),
    }
