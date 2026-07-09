"""SHERM-inspired mouse brain-mask generation and QC preview utilities."""

from __future__ import annotations

import os
from pathlib import Path
import tempfile
from typing import Any

import numpy as np

_cache_root = Path(tempfile.gettempdir()) / "lys_bbb_mri_cache"
os.environ.setdefault("MPLCONFIGDIR", str(_cache_root / "matplotlib"))
os.environ.setdefault("XDG_CACHE_HOME", str(_cache_root / "xdg"))
for _cache_dir in (Path(os.environ["MPLCONFIGDIR"]), Path(os.environ["XDG_CACHE_HOME"])):
    _cache_dir.mkdir(parents=True, exist_ok=True)

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import nibabel as nib
from scipy import ndimage as ndi
from skimage import filters, measure, morphology


def finite_percentile(data: np.ndarray, percentiles: list[float] | tuple[float, ...],
                      mask: np.ndarray | None = None) -> np.ndarray:
    values = data[mask] if mask is not None else data[np.isfinite(data)]
    values = values[np.isfinite(values)]
    if values.size == 0:
        return np.zeros(len(percentiles), dtype=np.float32)
    return np.percentile(values, percentiles)


def clamp_slice_range(shape: tuple[int, int, int],
                      slice_start: int | None,
                      slice_stop: int | None) -> tuple[int, int]:
    nz = shape[2]
    start = 0 if slice_start is None else max(0, int(slice_start))
    stop = nz - 1 if slice_stop is None else min(nz - 1, int(slice_stop))
    if start > stop:
        raise ValueError(f"empty mask slice range after clipping: {start}-{stop}")
    return start, stop


def coronal_slice_range_mask(shape: tuple[int, int, int],
                             slice_start: int | None,
                             slice_stop: int | None) -> np.ndarray:
    start, stop = clamp_slice_range(shape, slice_start, slice_stop)
    mask = np.zeros(shape, dtype=bool)
    mask[:, :, start:stop + 1] = True
    return mask


def voxel_sizes(img: nib.Nifti1Image) -> np.ndarray:
    return np.linalg.norm(img.affine[:3, :3], axis=0)


def load_float(path: Path) -> tuple[nib.Nifti1Image, np.ndarray]:
    img = nib.load(str(path))
    if len(img.shape) != 3:
        raise ValueError(f"expected a 3D NIfTI: {path}")
    return img, img.get_fdata(dtype=np.float32)


def save_like(data: np.ndarray, ref: nib.Nifti1Image, path: Path, dtype=np.float32) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    out = nib.Nifti1Image(data.astype(dtype, copy=False), ref.affine, ref.header.copy())
    out.set_data_dtype(dtype)
    nib.save(out, str(path))


def slice_ellipsoid_prior(shape: tuple[int, int, int],
                          slice_start: int | None,
                          slice_stop: int | None,
                          x_base: float,
                          x_weight: float,
                          y_base: float,
                          y_weight: float,
                          center_x: float | None = None,
                          center_y: float | None = None,
                          scale_x: float = 1.0,
                          scale_y: float = 1.0) -> np.ndarray:
    start, stop = clamp_slice_range(shape, slice_start, slice_stop)
    nx, ny, _ = shape
    xg, yg = np.ogrid[:nx, :ny]
    center_z = (start + stop) / 2.0
    half_range = max((stop - start) / 2.0, 1.0)
    z_scale = half_range * 1.1
    cx = (nx - 1) / 2.0 if center_x is None else float(center_x)
    base_cy = (ny - 1) / 2.0 if center_y is None else float(center_y)
    scale_x = max(float(scale_x), 0.2)
    scale_y = max(float(scale_y), 0.2)
    mask = np.zeros(shape, dtype=bool)
    for k in range(start, stop + 1):
        z_position = (k - center_z) / z_scale
        z_weight = max(0.0, 1.0 - z_position ** 2)
        cy = base_cy - 2.0 - 2.0 * z_position
        mask[:, :, k] = (
            ((xg - cx) / (nx * scale_x * (x_base + x_weight * z_weight))) ** 2
            + ((yg - cy) / (ny * scale_y * (y_base + y_weight * z_weight))) ** 2
            <= 1.0
        )
    return mask


def estimate_prior_center(scaled: np.ndarray,
                          slice_start: int,
                          slice_stop: int) -> tuple[float, float]:
    """Estimate a scan-specific center for the geometric brain priors.

    The estimate is deliberately coarse. It looks for a central high-signal
    connected component inside the default broad prior and uses its x/y
    centroid. If the estimate is unstable, the image center is returned.
    """
    shape = scaled.shape
    nx, ny, _ = shape
    fallback = ((nx - 1) / 2.0, (ny - 1) / 2.0)
    broad = slice_ellipsoid_prior(shape, slice_start, slice_stop, 0.36, 0.10, 0.19, 0.05)

    span = max(slice_stop - slice_start + 1, 1)
    central_start = slice_start + int(round(0.30 * span))
    central_stop = slice_start + int(round(0.70 * span))
    central = np.zeros(shape, dtype=bool)
    central[:, :, central_start:central_stop + 1] = True
    search = broad & central
    values = scaled[search & np.isfinite(scaled)]
    values = values[values > 0]
    if values.size < 100:
        return fallback

    try:
        threshold = float(filters.threshold_otsu(values))
    except ValueError:
        threshold = float(np.percentile(values, 60))
    threshold = max(threshold, float(np.percentile(values, 55)))

    foreground = (scaled >= threshold) & search
    foreground = morphology.opening(foreground, morphology.ball(1))
    labels = measure.label(foreground)
    if labels.max() == 0:
        return fallback

    image_center = np.array([(nx - 1) / 2.0, (ny - 1) / 2.0])
    best_score = -np.inf
    best_centroid: tuple[float, float] | None = None
    for region in measure.regionprops(labels):
        if region.area < 100:
            continue
        cx, cy, _ = region.centroid
        distance = np.linalg.norm((np.array([cx, cy]) - image_center) / np.array([nx, ny]))
        score = float(region.area) * (1.0 - min(distance, 0.9))
        if score > best_score:
            best_score = score
            best_centroid = (float(cx), float(cy))

    if best_centroid is None:
        return fallback
    cx, cy = best_centroid
    cx = float(np.clip(cx, nx * 0.35, nx * 0.65))
    cy = float(np.clip(cy, ny * 0.25, ny * 0.75))
    return cx, cy


def mean_slice_convexity(mask: np.ndarray) -> float:
    area = 0
    hull_area = 0
    for k in np.flatnonzero(mask.any(axis=(0, 1))):
        sl = mask[:, :, k]
        sl_area = int(np.count_nonzero(sl))
        if sl_area == 0:
            continue
        hull = morphology.convex_hull_image(sl)
        hull_count = int(np.count_nonzero(hull))
        if hull_count == 0:
            continue
        area += sl_area
        hull_area += hull_count
    return float(area / hull_area) if hull_area else 0.0


def best_centered_component(mask: np.ndarray, seed: np.ndarray) -> np.ndarray:
    labels = measure.label(mask)
    if labels.max() == 0:
        return mask
    best_label = 0
    best_score = -1.0
    for region in measure.regionprops(labels):
        component = labels == region.label
        score = np.count_nonzero(component & seed) + 0.002 * region.area
        if score > best_score:
            best_label = region.label
            best_score = score
    return labels == best_label


def clean_slice_protrusions(mask: np.ndarray,
                            slice_start: int,
                            slice_stop: int,
                            min_area: int = 100,
                            opening_radius: int = 1) -> np.ndarray:
    cleaned = mask.copy()
    footprint = morphology.disk(opening_radius) if opening_radius > 0 else None
    for k in range(slice_start, slice_stop + 1):
        sl = cleaned[:, :, k]
        if not sl.any():
            continue
        labels = measure.label(sl)
        filtered = np.zeros_like(sl, dtype=bool)
        for region in measure.regionprops(labels):
            if region.area >= max(1, int(min_area)):
                filtered[labels == region.label] = True
        if footprint is not None and filtered.any():
            opened = morphology.opening(filtered, footprint)
            if opened.any():
                filtered = opened
        if filtered.any():
            cleaned[:, :, k] = filtered
    return cleaned


def sherm_brain_mask(data: np.ndarray,
                     voxel_sizes_mm: tuple[float, float, float] | np.ndarray | None = None,
                     slice_start: int | None = 50,
                     slice_stop: int | None = 170,
                     brain_volume_range_mm3: tuple[float, float] = (180.0, 600.0),
                     max_candidates: int = 12,
                     consensus_fraction: float = 0.75,
                     auto_prior_center: bool = False,
                     prior_center_xy: tuple[float | None, float | None] | None = None,
                     prior_scale_xy: tuple[float, float] = (1.0, 1.0),
                     slice_cleanup_min_area: int = 100,
                     slice_cleanup_radius: int = 1) -> np.ndarray:
    """SHERM-inspired rodent skull stripping for coronal FLASH scans.

    The original SHERM implementation uses VLFeat MSERs, MATLAB morphology,
    animal-specific volume limits, and a learned polar shape descriptor. This
    Python implementation keeps the same practical structure without copying
    the MATLAB/GPL implementation: generate morphologically filtered channels,
    collect extremal connected regions, reject candidates by mouse-brain volume
    and shape, then form a consensus mask from the best candidates.
    """
    clean = np.nan_to_num(data, nan=0.0, posinf=0.0, neginf=0.0)
    start, stop = clamp_slice_range(clean.shape, slice_start, slice_stop)
    voxel_volume_mm3 = float(np.prod(voxel_sizes_mm)) if voxel_sizes_mm is not None else 1.0
    min_vox = max(150, int(brain_volume_range_mm3[0] / max(voxel_volume_mm3, 1e-9)))
    max_vox = max(min_vox + 1, int(brain_volume_range_mm3[1] / max(voxel_volume_mm3, 1e-9)))

    p01, p995 = finite_percentile(clean, [1, 99.5])
    if p995 <= p01:
        return slice_ellipsoid_prior(clean.shape, start, stop, 0.30, 0.13, 0.16, 0.06)
    scaled = np.clip((clean - p01) / (p995 - p01), 0, 1).astype(np.float32)
    scaled = ndi.gaussian_filter(scaled, sigma=(0.6, 0.6, 0.2))

    slice_mask = coronal_slice_range_mask(clean.shape, start, stop)
    if prior_center_xy is None:
        prior_center_xy = (None, None)
    center_x, center_y = prior_center_xy
    if auto_prior_center and (center_x is None or center_y is None):
        estimated_x, estimated_y = estimate_prior_center(scaled, start, stop)
        center_x = estimated_x if center_x is None else center_x
        center_y = estimated_y if center_y is None else center_y
    scale_x, scale_y = prior_scale_xy
    broad = slice_ellipsoid_prior(
        clean.shape, start, stop, 0.36, 0.10, 0.19, 0.05,
        center_x=center_x, center_y=center_y, scale_x=scale_x, scale_y=scale_y,
    )
    inner = slice_ellipsoid_prior(
        clean.shape, start, stop, 0.25, 0.09, 0.15, 0.055,
        center_x=center_x, center_y=center_y, scale_x=scale_x, scale_y=scale_y,
    )
    seed = slice_ellipsoid_prior(
        clean.shape, start, stop, 0.13, 0.08, 0.08, 0.05,
        center_x=center_x, center_y=center_y, scale_x=scale_x, scale_y=scale_y,
    )
    search_region = broad & slice_mask

    channels = [scaled]
    for radius in (1, 2, 3):
        footprint = morphology.ball(radius)
        opened = ndi.grey_opening(scaled, footprint=footprint)
        channels.append(opened)
        channels.append(ndi.grey_closing(opened, footprint=footprint))

    target_vox = 0.5 * (min_vox + max_vox)
    half_range = max(0.5 * (max_vox - min_vox), 1.0)
    candidates: list[tuple[float, np.ndarray]] = []
    seen: list[np.ndarray] = []
    for channel in channels:
        values = channel[search_region & np.isfinite(channel)]
        values = values[values > 0]
        if values.size < 100:
            continue
        try:
            otsu = float(filters.threshold_otsu(values))
        except ValueError:
            otsu = float(np.median(values))
        thresholds = np.unique(np.concatenate([
            np.percentile(values, [45, 50, 55, 60, 65, 70, 75]),
            np.array([otsu * 0.90, otsu, otsu * 1.10], dtype=np.float32),
        ]))
        for threshold in thresholds:
            foreground = (channel >= threshold) & search_region
            foreground = morphology.opening(foreground, morphology.ball(1))
            labels = measure.label(foreground)
            for region in measure.regionprops(labels):
                if region.area < min_vox or region.area > max_vox:
                    continue
                component = labels == region.label
                component = morphology.closing(component, morphology.ball(1))
                component = ndi.binary_fill_holes(component)
                component = best_centered_component(component, seed)
                voxels = int(np.count_nonzero(component))
                if voxels < min_vox or voxels > max_vox:
                    continue
                seed_overlap = np.count_nonzero(component & seed) / max(np.count_nonzero(seed), 1)
                inner_fraction = np.count_nonzero(component & inner) / max(voxels, 1)
                if seed_overlap < 0.40 or inner_fraction < 0.60:
                    continue
                convexity = mean_slice_convexity(component)
                if convexity < 0.60:
                    continue
                duplicate = False
                for existing in seen:
                    intersection = np.count_nonzero(component & existing)
                    union = np.count_nonzero(component | existing)
                    if union and intersection / union > 0.92:
                        duplicate = True
                        break
                if duplicate:
                    continue
                volume_score = max(0.0, 1.0 - abs(voxels - target_vox) / half_range)
                score = (
                    0.35 * volume_score
                    + 0.35 * inner_fraction
                    + 0.20 * convexity
                    + 0.10 * min(seed_overlap, 1.0)
                )
                candidates.append((score, component))
                seen.append(component)

    if not candidates:
        return slice_ellipsoid_prior(clean.shape, start, stop, 0.30, 0.13, 0.16, 0.06)

    candidates.sort(key=lambda item: item[0], reverse=True)
    selected = [mask for score, mask in candidates[:max_candidates]
                if score >= candidates[0][0] * 0.80]
    vote = np.zeros(clean.shape, dtype=np.uint16)
    for candidate in selected:
        vote += candidate.astype(np.uint16)
    consensus_fraction = float(np.clip(consensus_fraction, 0.05, 1.0))
    threshold = max(1, int(np.ceil(consensus_fraction * len(selected))))
    mask = vote >= threshold
    mask = morphology.closing(mask, morphology.ball(1))
    mask = ndi.binary_fill_holes(mask)
    mask = clean_slice_protrusions(
        mask,
        start,
        stop,
        min_area=slice_cleanup_min_area,
        opening_radius=slice_cleanup_radius,
    )
    mask = best_centered_component(mask, seed)
    mask &= slice_mask
    if np.count_nonzero(mask) < min_vox:
        mask = candidates[0][1]
    return mask.astype(bool)


def montage_slices(shape: tuple[int, int, int], n: int = 9,
                   slice_start: int | None = None,
                   slice_stop: int | None = None) -> np.ndarray:
    start, stop = clamp_slice_range(shape, slice_start, slice_stop)
    return np.linspace(start, stop, n).astype(int)


def window(data: np.ndarray, mask: np.ndarray | None = None) -> tuple[float, float]:
    p1, p995 = finite_percentile(data, [1, 99.5], mask=mask)
    if p995 <= p1:
        p995 = p1 + 1.0
    return float(p1), float(p995)


def draw_slice(ax: plt.Axes, data: np.ndarray, k: int, *,
               cmap: str, vmin: float, vmax: float) -> None:
    ax.imshow(np.rot90(data[:, :, k]), cmap=cmap, vmin=vmin, vmax=vmax)
    ax.set_xticks([])
    ax.set_yticks([])


def write_sherm_mask_qc(pre: np.ndarray, mask: np.ndarray, path: Path,
                        slice_start: int | None = None,
                        slice_stop: int | None = None,
                        n_slices: int = 9) -> None:
    ks = montage_slices(pre.shape, n_slices, slice_start, slice_stop)
    vmin, vmax = window(pre, mask)
    n_cols = min(3, max(1, n_slices))
    n_rows = int(np.ceil(len(ks) / n_cols))
    fig, axes = plt.subplots(n_rows, n_cols, figsize=(3 * n_cols, 3 * n_rows))
    axes_array = np.atleast_1d(axes).ravel()
    for ax, k in zip(axes_array, ks):
        draw_slice(ax, pre, k, cmap="gray", vmin=vmin, vmax=vmax)
        ax.contour(np.rot90(mask[:, :, k]), levels=[0.5], colors="lime", linewidths=0.6)
        ax.set_title(f"k={k}", fontsize=8)
    for ax in axes_array[len(ks):]:
        ax.axis("off")
    fig.suptitle("SHERM brain mask overlay", fontsize=10)
    fig.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)


def default_qc_path(coronal_nifti: Path) -> Path:
    name = coronal_nifti.name
    if name.endswith(".nii.gz"):
        stem = name[:-7]
    else:
        stem = coronal_nifti.stem
    return coronal_nifti.with_name(f"{stem}_sherm_mask_qc.png")


def preview_sherm_segmentation(coronal_nifti: Path,
                               qc_png: Path | None = None,
                               *,
                               write_mask: bool = False,
                               mask_path: Path | None = None,
                               slice_start: int | None = 50,
                               slice_stop: int | None = 170,
                               brain_volume_range_mm3: tuple[float, float] = (180.0, 600.0),
                               max_candidates: int = 12,
                               consensus_fraction: float = 0.75,
                               auto_prior_center: bool = False,
                               prior_center_xy: tuple[float | None, float | None] | None = None,
                               prior_scale_xy: tuple[float, float] = (1.0, 1.0),
                               slice_cleanup_min_area: int = 100,
                               slice_cleanup_radius: int = 1,
                               n_slices: int = 9) -> dict[str, Any]:
    """Run SHERM on one native coronal NIfTI and write minimal tuning outputs.

    By default this writes only a PNG overlay. Set ``write_mask=True`` to also
    write a binary NIfTI mask on the same grid as ``coronal_nifti``.
    """
    img, data = load_float(coronal_nifti)
    mask = sherm_brain_mask(
        data,
        voxel_sizes_mm=voxel_sizes(img),
        slice_start=slice_start,
        slice_stop=slice_stop,
        brain_volume_range_mm3=brain_volume_range_mm3,
        max_candidates=max_candidates,
        consensus_fraction=consensus_fraction,
        auto_prior_center=auto_prior_center,
        prior_center_xy=prior_center_xy,
        prior_scale_xy=prior_scale_xy,
        slice_cleanup_min_area=slice_cleanup_min_area,
        slice_cleanup_radius=slice_cleanup_radius,
    )
    qc_path = default_qc_path(coronal_nifti) if qc_png is None else qc_png
    write_sherm_mask_qc(
        data,
        mask,
        qc_path,
        slice_start=slice_start,
        slice_stop=slice_stop,
        n_slices=n_slices,
    )

    written_mask_path = None
    if write_mask:
        if mask_path is None:
            name = coronal_nifti.name
            stem = name[:-7] if name.endswith(".nii.gz") else coronal_nifti.stem
            mask_path = coronal_nifti.with_name(f"{stem}_sherm_mask.nii.gz")
        save_like(mask.astype(np.uint8), img, mask_path, dtype=np.uint8)
        written_mask_path = mask_path

    return {
        "qc_png": qc_path,
        "mask_path": written_mask_path,
        "mask_voxels": int(np.count_nonzero(mask)),
        "slice_start": int(clamp_slice_range(data.shape, slice_start, slice_stop)[0]),
        "slice_stop": int(clamp_slice_range(data.shape, slice_start, slice_stop)[1]),
        "brain_volume_range_mm3": tuple(float(v) for v in brain_volume_range_mm3),
        "consensus_fraction": float(consensus_fraction),
        "auto_prior_center": bool(auto_prior_center),
        "prior_center_xy": None if prior_center_xy is None else tuple(
            None if v is None else float(v) for v in prior_center_xy
        ),
        "prior_scale_xy": tuple(float(v) for v in prior_scale_xy),
        "slice_cleanup_min_area": int(slice_cleanup_min_area),
        "slice_cleanup_radius": int(slice_cleanup_radius),
    }
