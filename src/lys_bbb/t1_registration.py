"""Typed pre/post T1 registration contract for CLI and desktop callers.

The registered post-Gd image is a durable scientific artifact.  Callers provide all
output paths explicitly so the application can commit them atomically and later
quantification can consume the exact reviewed image instead of recomputing a transform.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path

import nibabel as nib
import numpy as np
from scipy import ndimage

from lys_bbb.hashing import sha256_file
from lys_bbb.qc_orientation import (
    annotate_coronal_orientation,
    orient_native_coronal_qc_slice,
)


T1_REGISTRATION_METHOD_VERSION = "sitk_rigid_mattes_v1"


@dataclass(frozen=True)
class T1RegistrationConfig:
    histogram_bins: int = 50
    sampling_percentage: float = 0.2
    sampling_seed: int = 42
    learning_rate: float = 2.0
    minimum_step: float = 1e-4
    iterations: int = 150
    relaxation_factor: float = 0.5
    gradient_tolerance: float = 1e-6
    shrink_factors: tuple[int, ...] = (4, 2, 1)
    smoothing_sigmas_mm: tuple[float, ...] = (2.0, 1.0, 0.0)
    interpolation: str = "linear"

    def __post_init__(self) -> None:
        if self.histogram_bins < 2:
            raise ValueError("histogram bins must be at least 2")
        if not 0 < self.sampling_percentage <= 1:
            raise ValueError("sampling percentage must be in (0, 1]")
        if self.iterations < 1:
            raise ValueError("registration iterations must be positive")
        if len(self.shrink_factors) != len(self.smoothing_sigmas_mm):
            raise ValueError("registration pyramid factors and sigmas must align")
        if any(factor < 1 for factor in self.shrink_factors):
            raise ValueError("registration shrink factors must be positive")
        if any(sigma < 0 for sigma in self.smoothing_sigmas_mm):
            raise ValueError("registration smoothing sigmas cannot be negative")
        if self.interpolation != "linear":
            raise ValueError("the frozen registration method requires linear interpolation")

    def method_spec(self) -> dict[str, object]:
        return {
            "method_version": T1_REGISTRATION_METHOD_VERSION,
            "transform": "Euler3D rigid",
            "initializer": "geometry centres",
            "metric": "Mattes mutual information",
            "sampling_strategy": "random",
            "optimizer": "RegularStepGradientDescent",
            "config": asdict(self),
            "reference_space": "native pre-Gd T1",
            "moving_image": "post-Gd T1",
        }

    @property
    def method_spec_sha256(self) -> str:
        payload = json.dumps(
            self.method_spec(),
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()


@dataclass(frozen=True)
class T1RegistrationRequest:
    case_id: str
    pre_t1_path: Path
    post_t1_path: Path
    brain_mask_path: Path
    registered_post_path: Path
    transform_path: Path
    qc_preview_path: Path
    config: T1RegistrationConfig = T1RegistrationConfig()
    qc_slice_start: int | None = None
    qc_slice_stop: int | None = None
    qc_slice_count: int = 6


@dataclass(frozen=True)
class T1RegistrationOutput:
    case_id: str
    registered_post_path: Path
    registered_post_sha256: str
    transform_path: Path
    transform_sha256: str
    qc_preview_path: Path
    qc_preview_sha256: str
    before_xcorr: float
    after_xcorr: float
    registration_metric: float
    optimizer_stop: str
    method_version: str
    method_spec_sha256: str
    metadata: dict[str, object]

def load_float(path: Path) -> tuple[nib.Nifti1Image, np.ndarray]:
    image = nib.load(str(path))
    if len(image.shape) != 3:
        raise ValueError(f"expected a 3D NIfTI: {path}")
    return image, image.get_fdata(dtype=np.float32)


def normalized_xcorr(a: np.ndarray, b: np.ndarray, mask: np.ndarray) -> float:
    finite = mask & np.isfinite(a) & np.isfinite(b)
    av = a[finite]
    bv = b[finite]
    if av.size < 10:
        return float("nan")
    av = av - np.mean(av)
    bv = bv - np.mean(bv)
    denominator = float(np.linalg.norm(av) * np.linalg.norm(bv))
    if denominator <= 0:
        return float("nan")
    return float(np.dot(av, bv) / denominator)


def _register(
    pre_path: Path,
    post_path: Path,
    registered_post_path: Path,
    transform_path: Path,
    config: T1RegistrationConfig,
) -> tuple[float, str]:
    import SimpleITK as sitk

    fixed = sitk.Cast(sitk.ReadImage(str(pre_path)), sitk.sitkFloat32)
    moving = sitk.Cast(sitk.ReadImage(str(post_path)), sitk.sitkFloat32)
    initial = sitk.CenteredTransformInitializer(
        fixed,
        moving,
        sitk.Euler3DTransform(),
        sitk.CenteredTransformInitializerFilter.GEOMETRY,
    )
    registration = sitk.ImageRegistrationMethod()
    registration.SetMetricAsMattesMutualInformation(
        numberOfHistogramBins=config.histogram_bins
    )
    registration.SetMetricSamplingStrategy(registration.RANDOM)
    registration.SetMetricSamplingPercentage(
        config.sampling_percentage,
        seed=config.sampling_seed,
    )
    registration.SetInterpolator(sitk.sitkLinear)
    registration.SetOptimizerAsRegularStepGradientDescent(
        learningRate=config.learning_rate,
        minStep=config.minimum_step,
        numberOfIterations=config.iterations,
        relaxationFactor=config.relaxation_factor,
        gradientMagnitudeTolerance=config.gradient_tolerance,
    )
    registration.SetOptimizerScalesFromPhysicalShift()
    registration.SetShrinkFactorsPerLevel(list(config.shrink_factors))
    registration.SetSmoothingSigmasPerLevel(list(config.smoothing_sigmas_mm))
    registration.SmoothingSigmasAreSpecifiedInPhysicalUnitsOn()
    registration.SetInitialTransform(initial, inPlace=False)
    final_transform = registration.Execute(fixed, moving)
    registered = sitk.Resample(
        moving,
        fixed,
        final_transform,
        sitk.sitkLinear,
        0.0,
        moving.GetPixelID(),
    )
    registered_post_path.parent.mkdir(parents=True, exist_ok=True)
    transform_path.parent.mkdir(parents=True, exist_ok=True)
    sitk.WriteImage(registered, str(registered_post_path))
    sitk.WriteTransform(final_transform, str(transform_path))
    return (
        float(registration.GetMetricValue()),
        registration.GetOptimizerStopConditionDescription(),
    )


def register_post_to_pre(
    pre_path: Path,
    post_path: Path,
    out_path: Path,
    transform_path: Path,
    config: T1RegistrationConfig | None = None,
) -> dict[str, object]:
    """Compatibility wrapper used by the existing pair and cohort CLIs."""

    selected = config or T1RegistrationConfig()
    metric, optimizer_stop = _register(
        pre_path,
        post_path,
        out_path,
        transform_path,
        selected,
    )
    return {
        "metric": metric,
        "optimizer_stop": optimizer_stop,
        "transform_path": str(transform_path),
        "method_version": T1_REGISTRATION_METHOD_VERSION,
        "method_spec_sha256": selected.method_spec_sha256,
    }


def _montage_slices(
    shape: tuple[int, ...],
    count: int,
    start: int | None,
    stop: int | None,
) -> np.ndarray:
    first = 0 if start is None else max(0, int(start))
    last = shape[2] - 1 if stop is None else min(shape[2] - 1, int(stop))
    if first > last:
        raise ValueError(f"empty registration QC slice range: {first}-{last}")
    return np.linspace(first, last, count).astype(int)


def _alignment_qc_slices(
    brain_mask: np.ndarray,
    count: int,
    start: int | None,
    stop: int | None,
) -> np.ndarray:
    areas = np.count_nonzero(brain_mask, axis=(0, 1))
    substantial = np.flatnonzero(areas >= max(1, 0.15 * float(areas.max())))
    if not substantial.size:
        return _montage_slices(brain_mask.shape, count, start, stop)
    first = int(substantial.min()) if start is None else max(int(substantial.min()), start)
    last = int(substantial.max()) if stop is None else min(int(substantial.max()), stop)
    if first > last:
        raise ValueError(f"empty registration QC slice range: {first}-{last}")
    return np.linspace(first, last, count).astype(int)


def _normalize_for_alignment_qc(
    data: np.ndarray, brain_mask: np.ndarray
) -> np.ndarray:
    valid = brain_mask & np.isfinite(data)
    values = data[valid]
    if not values.size:
        values = data[np.isfinite(data)]
    if not values.size:
        return np.zeros(data.shape, dtype=np.float32)
    low, high = np.percentile(values, (1.0, 99.5))
    high = max(float(high), float(low) + 1e-6)
    normalized = (np.nan_to_num(data, nan=float(low)) - float(low)) / (
        high - float(low)
    )
    return np.clip(normalized, 0.0, 1.0).astype(np.float32, copy=False)


def _fusion_rgb(fixed: np.ndarray, moving: np.ndarray) -> np.ndarray:
    """Encode fixed as cyan and moving as magenta; agreement becomes neutral."""

    return np.stack(
        (
            moving,
            fixed,
            (fixed + moving) * 0.5,
        ),
        axis=-1,
    )


def _edge_overlap_rgb(
    fixed: np.ndarray,
    moving: np.ndarray,
    brain_mask: np.ndarray,
) -> np.ndarray:
    fixed_gradient = ndimage.gaussian_gradient_magnitude(fixed, sigma=0.8)
    moving_gradient = ndimage.gaussian_gradient_magnitude(moving, sigma=0.8)

    def strongest_edges(gradient: np.ndarray) -> np.ndarray:
        values = gradient[brain_mask & np.isfinite(gradient)]
        if not values.size or float(values.max()) <= 0:
            return np.zeros(gradient.shape, dtype=bool)
        edges = gradient >= np.percentile(values, 85)
        return ndimage.binary_dilation(edges & brain_mask, iterations=1)

    fixed_edges = strongest_edges(fixed_gradient)
    moving_edges = strongest_edges(moving_gradient)
    rgb = np.zeros((*fixed.shape, 3), dtype=np.float32)
    rgb[fixed_edges] += np.array((0.0, 1.0, 1.0), dtype=np.float32)
    rgb[moving_edges] += np.array((1.0, 0.0, 1.0), dtype=np.float32)
    return np.clip(rgb, 0.0, 1.0)


def _checkerboard(
    fixed: np.ndarray,
    moving: np.ndarray,
    *,
    tiles: int = 10,
) -> np.ndarray:
    tile = max(4, min(fixed.shape) // tiles)
    rows, columns = np.indices(fixed.shape)
    choose_moving = ((rows // tile) + (columns // tile)) % 2 == 1
    return np.where(choose_moving, moving, fixed)


def create_registration_qc(
    pre: np.ndarray,
    post: np.ndarray,
    registered_post: np.ndarray,
    brain_mask: np.ndarray,
    output_path: Path,
    *,
    slice_start: int | None,
    slice_stop: int | None,
    slice_count: int,
    affine: np.ndarray | None = None,
    before_xcorr: float | None = None,
    after_xcorr: float | None = None,
) -> Path:
    cache_root = Path(tempfile.gettempdir()) / "lys_irm_mri_cache"
    os.environ.setdefault("MPLCONFIGDIR", str(cache_root / "matplotlib"))
    os.environ.setdefault("XDG_CACHE_HOME", str(cache_root / "xdg"))
    Path(os.environ["MPLCONFIGDIR"]).mkdir(parents=True, exist_ok=True)
    Path(os.environ["XDG_CACHE_HOME"]).mkdir(parents=True, exist_ok=True)
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    slices = _alignment_qc_slices(
        brain_mask,
        slice_count,
        slice_start,
        slice_stop,
    )
    display_affine = np.eye(4) if affine is None else affine
    pre_normalized = _normalize_for_alignment_qc(pre, brain_mask)
    registered_normalized = _normalize_for_alignment_qc(
        registered_post, brain_mask
    )
    raw_available = post.shape == pre.shape
    raw_normalized = (
        _normalize_for_alignment_qc(post, brain_mask)
        if raw_available
        else None
    )

    figure, axes = plt.subplots(
        len(slices),
        6,
        figsize=(15, max(7, len(slices) * 2.25)),
        squeeze=False,
    )
    for row, index in enumerate(slices):
        fixed = orient_native_coronal_qc_slice(
            pre_normalized[:, :, index], display_affine
        )
        registered = orient_native_coronal_qc_slice(
            registered_normalized[:, :, index], display_affine
        )
        mask_slice = orient_native_coronal_qc_slice(
            brain_mask[:, :, index], display_affine
        )
        raw = (
            orient_native_coronal_qc_slice(
                raw_normalized[:, :, index], display_affine
            )
            if raw_normalized is not None
            else None
        )
        before_panels = (
            _fusion_rgb(fixed, raw) if raw is not None else None,
            (
                _edge_overlap_rgb(fixed, raw, mask_slice)
                if raw is not None
                else None
            ),
            _checkerboard(fixed, raw) if raw is not None else None,
        )
        after_panels = (
            _fusion_rgb(fixed, registered),
            _edge_overlap_rgb(fixed, registered, mask_slice),
            _checkerboard(fixed, registered),
        )
        panels = (
            before_panels[0],
            after_panels[0],
            before_panels[1],
            after_panels[1],
            before_panels[2],
            after_panels[2],
        )
        for column, panel in enumerate(panels):
            axis = axes[row, column]
            if panel is None:
                axis.set_facecolor("black")
                axis.text(
                    0.5,
                    0.5,
                    "Before QC unavailable\n(different native grids)",
                    color="white",
                    fontsize=7,
                    ha="center",
                    va="center",
                    transform=axis.transAxes,
                )
            else:
                axis.imshow(
                    panel,
                    cmap="gray" if panel.ndim == 2 else None,
                    vmin=0.0,
                    vmax=1.0,
                )
                if panel.ndim == 2 and np.any(mask_slice) and np.any(~mask_slice):
                    axis.contour(
                        mask_slice,
                        levels=[0.5],
                        colors="lime",
                        linewidths=0.45,
                    )
            annotate_coronal_orientation(axis, display_affine)
            axis.set_xticks([])
            axis.set_yticks([])
        axes[row, 0].set_ylabel(f"native k={index}", fontsize=8)
    for axis, title in zip(
        axes[0],
        (
            "BEFORE fusion",
            "AFTER fusion",
            "BEFORE edges",
            "AFTER edges",
            "BEFORE checkerboard",
            "AFTER checkerboard",
        ),
        strict=True,
    ):
        axis.set_title(title, fontsize=8)
    correlation_summary = ""
    if before_xcorr is not None and after_xcorr is not None:
        correlation_summary = (
            f" · brain correlation {before_xcorr:.3f} → {after_xcorr:.3f}"
        )
    figure.suptitle(
        "Post-Gd→pre-Gd rigid registration alignment QC"
        f"{correlation_summary}\n"
        "Fusion/edges: pre cyan, post magenta, agreement white · "
        "checkerboard boundaries should be continuous",
        fontsize=10,
    )
    figure.tight_layout(rect=(0, 0, 1, 0.96))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(output_path, dpi=150, bbox_inches="tight")
    plt.close(figure)
    return output_path


def run_t1_registration(request: T1RegistrationRequest) -> T1RegistrationOutput:
    """Create one durable registered image, transform, QC, and provenance record."""

    pre_image, pre = load_float(request.pre_t1_path)
    _post_image, post = load_float(request.post_t1_path)
    mask_image, mask_data = load_float(request.brain_mask_path)
    if mask_data.shape != pre.shape or not np.allclose(
        mask_image.affine,
        pre_image.affine,
        atol=1e-3,
    ):
        raise ValueError("approved brain mask must match the native pre-Gd T1 grid")
    brain_mask = mask_data > 0
    if not np.any(brain_mask):
        raise ValueError("approved brain mask is empty")

    metric, optimizer_stop = _register(
        request.pre_t1_path,
        request.post_t1_path,
        request.registered_post_path,
        request.transform_path,
        request.config,
    )
    registered_image, registered_post = load_float(request.registered_post_path)
    if registered_post.shape != pre.shape or not np.allclose(
        registered_image.affine,
        pre_image.affine,
        atol=1e-3,
    ):
        raise ValueError("registered post-Gd image does not match the pre-Gd grid")

    before_xcorr = (
        normalized_xcorr(pre, post, brain_mask)
        if post.shape == pre.shape
        else float("nan")
    )
    after_xcorr = normalized_xcorr(pre, registered_post, brain_mask)
    create_registration_qc(
        pre,
        post,
        registered_post,
        brain_mask,
        request.qc_preview_path,
        slice_start=request.qc_slice_start,
        slice_stop=request.qc_slice_stop,
        slice_count=request.qc_slice_count,
        affine=pre_image.affine,
        before_xcorr=before_xcorr,
        after_xcorr=after_xcorr,
    )
    metadata: dict[str, object] = {
        "pre_t1_path": str(request.pre_t1_path),
        "post_t1_path": str(request.post_t1_path),
        "brain_mask_path": str(request.brain_mask_path),
        "registered_post_path": str(request.registered_post_path),
        "transform_path": str(request.transform_path),
        "qc_preview_path": str(request.qc_preview_path),
        "method_spec": request.config.method_spec(),
        "human_review_required": True,
        "reference_space": "native pre-Gd T1",
    }
    return T1RegistrationOutput(
        case_id=request.case_id,
        registered_post_path=request.registered_post_path,
        registered_post_sha256=sha256_file(request.registered_post_path),
        transform_path=request.transform_path,
        transform_sha256=sha256_file(request.transform_path),
        qc_preview_path=request.qc_preview_path,
        qc_preview_sha256=sha256_file(request.qc_preview_path),
        before_xcorr=before_xcorr,
        after_xcorr=after_xcorr,
        registration_metric=metric,
        optimizer_stop=optimizer_stop,
        method_version=T1_REGISTRATION_METHOD_VERSION,
        method_spec_sha256=request.config.method_spec_sha256,
        metadata=metadata,
    )
