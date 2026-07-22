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

from lys_bbb.hashing import sha256_file


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


def _window(values: np.ndarray) -> tuple[float, float]:
    finite = values[np.isfinite(values)]
    if not finite.size:
        return 0.0, 1.0
    lower, upper = np.percentile(finite, [1, 99.5])
    return float(lower), float(max(upper, lower + 1.0))


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
) -> Path:
    cache_root = Path(tempfile.gettempdir()) / "lys_bbb_mri_cache"
    os.environ.setdefault("MPLCONFIGDIR", str(cache_root / "matplotlib"))
    os.environ.setdefault("XDG_CACHE_HOME", str(cache_root / "xdg"))
    Path(os.environ["MPLCONFIGDIR"]).mkdir(parents=True, exist_ok=True)
    Path(os.environ["XDG_CACHE_HOME"]).mkdir(parents=True, exist_ok=True)
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    slices = _montage_slices(
        pre.shape,
        slice_count,
        slice_start,
        slice_stop,
    )
    image_min, image_max = _window(np.concatenate((pre.ravel(), registered_post.ravel())))
    raw_difference = np.abs(post - pre) if post.shape == pre.shape else None
    registered_difference = np.abs(registered_post - pre)
    difference_values = registered_difference[np.isfinite(registered_difference)]
    difference_max = (
        float(np.percentile(difference_values, 98))
        if difference_values.size
        else 1.0
    )
    difference_max = max(difference_max, 1.0)

    figure, axes = plt.subplots(
        len(slices),
        5,
        figsize=(12, max(7, len(slices) * 2.0)),
        squeeze=False,
    )
    for row, index in enumerate(slices):
        panels = (
            pre[:, :, index],
            post[:, :, index] if post.shape == pre.shape else np.zeros(pre.shape[:2]),
            registered_post[:, :, index],
            (
                raw_difference[:, :, index]
                if raw_difference is not None
                else np.zeros(pre.shape[:2])
            ),
            registered_difference[:, :, index],
        )
        for column, panel in enumerate(panels):
            axis = axes[row, column]
            difference_panel = column >= 3
            axis.imshow(
                np.rot90(panel),
                cmap="magma" if difference_panel else "gray",
                vmin=0.0 if difference_panel else image_min,
                vmax=difference_max if difference_panel else image_max,
            )
            axis.contour(
                np.rot90(brain_mask[:, :, index]),
                levels=[0.5],
                colors="lime",
                linewidths=0.45,
            )
            axis.set_xticks([])
            axis.set_yticks([])
        axes[row, 0].set_ylabel(f"k={index}", fontsize=8)
    for axis, title in zip(
        axes[0],
        ("pre", "post raw", "post registered", "|raw-pre|", "|registered-pre|"),
        strict=True,
    ):
        axis.set_title(title, fontsize=8)
    figure.suptitle(
        "Post-Gd to native pre-Gd rigid registration · approved mask outline",
        fontsize=10,
    )
    figure.tight_layout()
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
