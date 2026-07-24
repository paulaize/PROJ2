"""QC renderers for the staged major-region atlas workflow."""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

import nibabel as nib
import numpy as np
from scipy import ndimage

from lys_bbb.atlas_mapping import major_region_boundary, validate_major_label_array
from lys_bbb.atlas_release import inspect_nifti_geometry, require_same_physical_grid
from lys_bbb.hashing import sha256_file


@dataclass(frozen=True)
class AllSliceQC:
    montage_path: Path
    montage_sha256: str
    slice_paths: tuple[Path, ...]
    manifest_path: Path
    manifest_sha256: str


def create_atlas_to_t1_qc(
    *,
    native_pre_t1_path: Path,
    approved_brain_mask_path: Path,
    warped_atlas_intensity_path: Path,
    warped_atlas_support_path: Path,
    output_path: Path,
    candidate: str,
    transform_summary: dict[str, object],
    slice_count: int = 9,
) -> Path:
    """Show one atlas candidate against the full native pre-T1 reference."""

    _configure_matplotlib()
    import matplotlib.pyplot as plt

    pre_image = nib.load(str(native_pre_t1_path))
    pre = pre_image.get_fdata(dtype=np.float32)
    mask = np.asanyarray(nib.load(str(approved_brain_mask_path)).dataobj) != 0
    atlas = nib.load(str(warped_atlas_intensity_path)).get_fdata(dtype=np.float32)
    atlas_support = (
        np.asanyarray(nib.load(str(warped_atlas_support_path)).dataobj) != 0
    )
    for path, name in (
        (approved_brain_mask_path, "approved pre-T1 brain mask"),
        (warped_atlas_intensity_path, "warped atlas intensity"),
        (warped_atlas_support_path, "warped atlas support"),
    ):
        require_same_physical_grid(
            inspect_nifti_geometry(native_pre_t1_path),
            inspect_nifti_geometry(path),
            names=("native pre-T1", name),
            affine_atol=1e-4,
        )
    support = np.where(mask.any(axis=(0, 1)))[0]
    slices = np.linspace(support.min(), support.max(), slice_count).astype(int)
    figure, axes = plt.subplots(3, 3, figsize=(12, 10), squeeze=False)
    atlas_edges = _edges(atlas)
    vmin, vmax = _window(pre[mask])
    for axis, index in zip(axes.ravel(), slices, strict=True):
        axis.imshow(np.rot90(pre[:, :, index]), cmap="gray", vmin=vmin, vmax=vmax)
        axis.contour(
            np.rot90(mask[:, :, index]), levels=[0.5], colors="lime", linewidths=0.6
        )
        _contour(axis, atlas_support[:, :, index], "cyan", 0.55)
        edge = np.rot90(atlas_edges[:, :, index])
        axis.contour(edge, levels=[np.percentile(edge, 80)], colors="magenta", linewidths=0.5)
        axis.set_title(f"native pre-T1 slice {index}", fontsize=8)
        axis.axis("off")
    determinant = transform_summary.get("determinant", "n/a")
    figure.suptitle(
        f"PROVISIONAL atlas→pre-T1 {candidate} QC · determinant {determinant}",
        fontsize=11,
    )
    figure.tight_layout()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(output_path, dpi=150, bbox_inches="tight")
    plt.close(figure)
    return output_path


def create_t1_to_t2_all_slice_qc(
    *,
    native_t2_path: Path,
    transformed_t1_path: Path,
    transformed_t1_brain_mask_path: Path,
    t2_registration_support_mask_path: Path | None,
    native_lesion_mask_path: Path | None,
    output_directory: Path,
    transform_summary: dict[str, object],
) -> AllSliceQC:
    """Render T2, T1 edges, brain boundaries, and lesion on every T2 slice."""

    _configure_matplotlib()
    import matplotlib.pyplot as plt

    output_directory.mkdir(parents=True, exist_ok=True)
    slices_dir = output_directory / "slices"
    slices_dir.mkdir()
    reference_geometry = inspect_nifti_geometry(native_t2_path)
    t2_image = nib.load(str(native_t2_path))
    t2 = t2_image.get_fdata(dtype=np.float32)
    transformed_t1 = nib.load(str(transformed_t1_path)).get_fdata(dtype=np.float32)
    t1_mask = np.asanyarray(nib.load(str(transformed_t1_brain_mask_path)).dataobj) != 0
    for path, name in (
        (transformed_t1_path, "transformed pre-T1"),
        (transformed_t1_brain_mask_path, "transformed T1 brain mask"),
    ):
        require_same_physical_grid(
            reference_geometry,
            inspect_nifti_geometry(path),
            names=("native T2", name),
            affine_atol=1e-4,
        )
    t2_support = _optional_binary_on_grid(
        t2_registration_support_mask_path, native_t2_path
    )
    lesion = _optional_binary_on_grid(native_lesion_mask_path, native_t2_path)
    t1_edges = _edges(transformed_t1)
    vmin, vmax = _window(t2)
    slice_paths: list[Path] = []
    adjacent_consistency: list[float | None] = []
    for index in range(t2.shape[2]):
        path = slices_dir / f"slice_{index:03d}.png"
        figure, axes = plt.subplots(1, 3, figsize=(11, 3.6))
        panels = (
            (axes[0], "Native T2"),
            (axes[1], "T2 + transformed T1 edges"),
            (axes[2], "Brain support + lesion"),
        )
        for axis, title in panels:
            axis.imshow(
                np.rot90(t2[:, :, index]), cmap="gray", vmin=vmin, vmax=vmax
            )
            axis.set_title(title, fontsize=8)
            axis.axis("off")
        edge = np.rot90(t1_edges[:, :, index])
        level = np.percentile(edge, 80) if np.any(edge) else 1.0
        axes[1].contour(edge, levels=[level], colors="magenta", linewidths=0.55)
        _contour(axes[2], t1_mask[:, :, index], "lime", 0.8)
        if t2_support is not None:
            _contour(axes[2], t2_support[:, :, index], "cyan", 0.65)
        if lesion is not None:
            _contour(axes[2], lesion[:, :, index], "red", 1.0)
        previous = t1_mask[:, :, index - 1] if index else None
        adjacent_consistency.append(
            _dice(previous, t1_mask[:, :, index]) if previous is not None else None
        )
        figure.suptitle(
            f"DRAFT pre-T1→T2 QC · original T2 slice {index + 1}/{t2.shape[2]}",
            fontsize=10,
        )
        figure.tight_layout()
        figure.savefig(path, dpi=140, bbox_inches="tight")
        plt.close(figure)
        slice_paths.append(path)
    montage = output_directory / "all_original_t2_slices_qc.png"
    _write_montage(slice_paths, montage, columns=3)
    manifest = {
        "scientific_status": "DRAFT_REVIEW_REQUIRED",
        "native_t2_sha256": sha256_file(native_t2_path),
        "native_t2_orientation": reference_geometry.orientation,
        "original_t2_slice_count": int(t2.shape[2]),
        "all_original_slices_rendered": True,
        "slice_paths": [str(path) for path in slice_paths],
        "slice_sha256": {path.name: sha256_file(path) for path in slice_paths},
        "transformed_t1_sha256": sha256_file(transformed_t1_path),
        "transformed_t1_brain_mask_sha256": sha256_file(
            transformed_t1_brain_mask_path
        ),
        "t2_support_mask_sha256": (
            sha256_file(t2_registration_support_mask_path)
            if t2_registration_support_mask_path is not None
            else None
        ),
        "native_lesion_sha256": (
            sha256_file(native_lesion_mask_path)
            if native_lesion_mask_path is not None
            else None
        ),
        "adjacent_slice_brain_mask_dice": adjacent_consistency,
        "transform_summary": transform_summary,
    }
    manifest_path = output_directory / "t1_to_t2_qc_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return AllSliceQC(
        montage_path=montage,
        montage_sha256=sha256_file(montage),
        slice_paths=tuple(slice_paths),
        manifest_path=manifest_path,
        manifest_sha256=sha256_file(manifest_path),
    )


def create_composite_all_slice_qc(
    *,
    native_t2_path: Path,
    major_labels_path: Path,
    native_lesion_mask_path: Path,
    allowed_major_region_ids: frozenset[int],
    output_directory: Path,
) -> AllSliceQC:
    """Render only major-region boundaries and native lesion on every T2 slice."""

    _configure_matplotlib()
    import matplotlib.pyplot as plt

    output_directory.mkdir(parents=True, exist_ok=True)
    slices_dir = output_directory / "slices"
    slices_dir.mkdir()
    reference_geometry = inspect_nifti_geometry(native_t2_path)
    for path, name in (
        (major_labels_path, "major labels"),
        (native_lesion_mask_path, "native lesion mask"),
    ):
        require_same_physical_grid(
            reference_geometry,
            inspect_nifti_geometry(path),
            names=("native T2", name),
            affine_atol=1e-4,
        )
    t2 = nib.load(str(native_t2_path)).get_fdata(dtype=np.float32)
    labels = validate_major_label_array(
        np.asanyarray(nib.load(str(major_labels_path)).dataobj),
        allowed_major_region_ids,
    )
    lesion_data = np.asanyarray(nib.load(str(native_lesion_mask_path)).dataobj)
    if not set(float(value) for value in np.unique(lesion_data)).issubset({0.0, 1.0}):
        raise ValueError("The native lesion mask must be binary")
    lesion = lesion_data != 0
    boundary = major_region_boundary(labels)
    vmin, vmax = _window(t2)
    slice_paths: list[Path] = []
    adjacent_consistency: list[float | None] = []
    for index in range(t2.shape[2]):
        path = slices_dir / f"slice_{index:03d}.png"
        figure, axis = plt.subplots(figsize=(5.2, 5.2))
        axis.imshow(np.rot90(t2[:, :, index]), cmap="gray", vmin=vmin, vmax=vmax)
        _contour(axis, boundary[:, :, index], "yellow", 0.55)
        _contour(axis, lesion[:, :, index], "red", 1.1)
        axis.set_title(
            f"DRAFT major regions + native lesion · slice {index + 1}/{t2.shape[2]}",
            fontsize=9,
        )
        axis.axis("off")
        figure.tight_layout()
        figure.savefig(path, dpi=140, bbox_inches="tight")
        plt.close(figure)
        slice_paths.append(path)
        previous = labels[:, :, index - 1] != 0 if index else None
        adjacent_consistency.append(
            _dice(previous, labels[:, :, index] != 0) if previous is not None else None
        )
    montage = output_directory / "composite_all_original_t2_slices_qc.png"
    _write_montage(slice_paths, montage, columns=3)
    manifest = {
        "scientific_status": "DRAFT_REVIEW_REQUIRED",
        "native_t2_sha256": sha256_file(native_t2_path),
        "major_labels_sha256": sha256_file(major_labels_path),
        "native_lesion_sha256": sha256_file(native_lesion_mask_path),
        "native_lesion_resampled": False,
        "fine_labels_rendered": False,
        "original_t2_slice_count": int(t2.shape[2]),
        "all_original_slices_rendered": True,
        "slice_paths": [str(path) for path in slice_paths],
        "slice_sha256": {path.name: sha256_file(path) for path in slice_paths},
        "adjacent_slice_major_support_dice": adjacent_consistency,
        "orientation": reference_geometry.orientation,
    }
    manifest_path = output_directory / "composite_qc_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return AllSliceQC(
        montage_path=montage,
        montage_sha256=sha256_file(montage),
        slice_paths=tuple(slice_paths),
        manifest_path=manifest_path,
        manifest_sha256=sha256_file(manifest_path),
    )


def validate_jacobian(jacobian_path: Path, support_mask_path: Path) -> dict[str, object]:
    """Reject folding and report deformation percentiles without scientific thresholds."""

    require_same_physical_grid(
        inspect_nifti_geometry(jacobian_path),
        inspect_nifti_geometry(support_mask_path),
        names=("Jacobian", "Jacobian support mask"),
        affine_atol=1e-4,
    )
    jacobian = nib.load(str(jacobian_path)).get_fdata(dtype=np.float32)
    support = np.asanyarray(nib.load(str(support_mask_path)).dataobj) != 0
    values = jacobian[support]
    if not values.size or not np.isfinite(values).all():
        raise ValueError("Jacobian support is empty or non-finite")
    nonpositive = int(np.count_nonzero(values <= 0))
    if nonpositive:
        raise ValueError("Nonpositive Jacobians indicate folding")
    percentiles = np.percentile(values, [0, 1, 5, 50, 95, 99, 100])
    return {
        "nonpositive_voxels": nonpositive,
        "percentiles": {
            key: float(value)
            for key, value in zip(
                ("p0", "p1", "p5", "p50", "p95", "p99", "p100"),
                percentiles,
                strict=True,
            )
        },
        "automatic_scientific_acceptance": "not_claimed",
    }


def _edges(data: np.ndarray) -> np.ndarray:
    return np.sqrt(sum(ndimage.sobel(data, axis=axis) ** 2 for axis in range(3)))


def _window(data: np.ndarray) -> tuple[float, float]:
    values = data[np.isfinite(data)]
    if not values.size:
        return 0.0, 1.0
    low, high = np.percentile(values, [1.0, 99.5])
    return float(low), float(max(high, low + 1e-6))


def _optional_binary_on_grid(path: Path | None, reference: Path) -> np.ndarray | None:
    if path is None:
        return None
    require_same_physical_grid(
        inspect_nifti_geometry(reference),
        inspect_nifti_geometry(path),
        names=("native T2", path.name),
        affine_atol=1e-4,
    )
    data = np.asanyarray(nib.load(str(path)).dataobj)
    if not set(float(value) for value in np.unique(data)).issubset({0.0, 1.0}):
        raise ValueError(f"Expected a binary QC mask: {path}")
    return data != 0


def _contour(axis, data: np.ndarray, color: str, width: float) -> None:
    if np.any(data) and np.any(~data):
        axis.contour(
            np.rot90(data.astype(np.uint8)),
            levels=[0.5],
            colors=color,
            linewidths=width,
        )


def _dice(first: np.ndarray, second: np.ndarray) -> float:
    denominator = int(np.count_nonzero(first)) + int(np.count_nonzero(second))
    if denominator == 0:
        return 1.0
    return 2.0 * int(np.count_nonzero(first & second)) / denominator


def _write_montage(paths: list[Path], output_path: Path, *, columns: int) -> None:
    import matplotlib.pyplot as plt

    rows = (len(paths) + columns - 1) // columns
    figure, axes = plt.subplots(
        rows, columns, figsize=(columns * 4.0, rows * 3.0), squeeze=False
    )
    for axis in axes.ravel():
        axis.axis("off")
    for axis, path in zip(axes.ravel(), paths, strict=False):
        axis.imshow(plt.imread(path))
        axis.axis("off")
    figure.tight_layout(pad=0.15)
    figure.savefig(output_path, dpi=120, bbox_inches="tight")
    plt.close(figure)


def _configure_matplotlib() -> None:
    root = Path(tempfile.gettempdir()) / "lys_bbb_atlas_cache"
    os.environ.setdefault("MPLCONFIGDIR", str(root / "matplotlib"))
    os.environ.setdefault("XDG_CACHE_HOME", str(root / "xdg"))
    Path(os.environ["MPLCONFIGDIR"]).mkdir(parents=True, exist_ok=True)
    Path(os.environ["XDG_CACHE_HOME"]).mkdir(parents=True, exist_ok=True)
    import matplotlib

    matplotlib.use("Agg")
