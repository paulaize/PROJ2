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
from typing import Any, Callable

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


METHODS: dict[str, Callable[..., tuple[np.ndarray, dict[str, Any]]]] = {
    "rs2_m_seam": refine_direct_seam,
    "rs2_marker_watershed": refine_watershed,
    "rs2_random_walker": refine_random_walker,
}
