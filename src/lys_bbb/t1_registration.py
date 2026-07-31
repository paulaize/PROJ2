"""Typed pre/post T1 registration contract for CLI and desktop callers.

The registered post-Gd image is a durable scientific artifact.  Callers provide all
output paths explicitly so the application can commit them atomically and later
quantification can consume the exact reviewed image instead of recomputing a transform.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import time
from dataclasses import asdict, dataclass
from pathlib import Path

import nibabel as nib
import numpy as np
from scipy import ndimage

from lys_bbb.atlas_registration import (
    _run_and_record,
    _require_runtime_match,
    _require_supported_runtime,
    _x,
)
from lys_bbb.atlas_release import (
    inspect_nifti_geometry,
    require_same_physical_grid,
)
from lys_bbb.hashing import sha256_file
from lys_bbb.qc_orientation import (
    annotate_coronal_orientation,
    orient_native_coronal_qc_slice,
)
from lys_bbb.registration_runtime import (
    ANTSPYX_ENGINE,
    ANTSPYX_VERSION,
    AntsExecutables,
    CommandRunner,
)


T1_REGISTRATION_METHOD_VERSION = (
    "antspyx_0_6_3_unmasked_regular_25pct_mattes_rigid_v1"
)


@dataclass(frozen=True)
class T1RegistrationConfig:
    histogram_bins: int = 50
    sampling_strategy: str = "Regular"
    sampling_percentage: float = 0.25
    random_seed: int = 42
    gradient_step: float = 0.1
    iterations: tuple[int, ...] = (1000, 500, 250, 100)
    shrink_factors: tuple[int, ...] = (8, 4, 2, 1)
    smoothing_sigmas_mm: tuple[float, ...] = (0.45, 0.3, 0.15, 0.0)
    convergence_threshold: float = 1e-6
    convergence_window: int = 10
    winsorize_quantiles: tuple[float, float] = (0.005, 0.995)
    itk_threads: int = 1
    single_precision: bool = True
    interpolation: str = "linear"
    runtime_engine: str = ANTSPYX_ENGINE
    runtime_version: str = ANTSPYX_VERSION

    def __post_init__(self) -> None:
        expected = {
            "histogram_bins": 50,
            "sampling_strategy": "Regular",
            "sampling_percentage": 0.25,
            "random_seed": 42,
            "gradient_step": 0.1,
            "iterations": (1000, 500, 250, 100),
            "shrink_factors": (8, 4, 2, 1),
            "smoothing_sigmas_mm": (0.45, 0.3, 0.15, 0.0),
            "convergence_threshold": 1e-6,
            "convergence_window": 10,
            "winsorize_quantiles": (0.005, 0.995),
            "itk_threads": 1,
            "single_precision": True,
            "interpolation": "linear",
        }
        observed = asdict(self)
        for name, value in expected.items():
            if observed[name] != value:
                raise ValueError(
                    f"{T1_REGISTRATION_METHOD_VERSION} requires {name}={value!r}"
                )
        if self.interpolation != "linear":
            raise ValueError("the frozen registration method requires linear interpolation")
        _require_supported_runtime(self.runtime_engine, self.runtime_version)

    def method_spec(self) -> dict[str, object]:
        config = asdict(self)
        del config["runtime_engine"]
        del config["runtime_version"]
        return {
            "method_version": T1_REGISTRATION_METHOD_VERSION,
            "engine": self.runtime_engine,
            "engine_version": self.runtime_version,
            "transform": "rigid, six degrees of freedom",
            "initializer": "geometry centres (fixed pre-T1, moving post-T1)",
            "metric": "Mattes mutual information",
            "metric_masks": "none; corrected pre-T1 brain mask is QC only",
            "fixed": "unchanged native pre-Gd T1",
            "moving": "native post-Gd T1",
            "interpolation": "Linear, once into the unchanged native pre-T1 grid",
            "scientific_status": "DRAFT_REVIEW_REQUIRED",
            "config": config,
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
    pre_t1_identity: str | None = None
    post_t1_identity: str | None = None
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
    *,
    runner: CommandRunner | None = None,
    executables: AntsExecutables | None = None,
) -> tuple[float, str, Path, float]:
    if runner is None or executables is None:
        from lys_bbb.antspyx_backend import (
            antspyx_executables,
            antspyx_subprocess_command_runner,
        )

        runner = runner or antspyx_subprocess_command_runner
        executables = executables or antspyx_executables()
    _require_runtime_match(
        config.runtime_engine,
        config.runtime_version,
        executables,
    )
    registered_post_path.parent.mkdir(parents=True, exist_ok=True)
    expected_transform = (
        transform_path.parent / "post_to_pre_ants_0GenericAffine.mat"
    )
    if transform_path != expected_transform:
        raise ValueError(
            "The selected ANTs method requires transform filename "
            "post_to_pre_ants_0GenericAffine.mat"
        )
    prefix = transform_path.parent / "post_to_pre_ants_"
    low, high = config.winsorize_quantiles
    args = (
        str(executables.registration),
        "--dimensionality",
        "3",
        "--float",
        "1",
        "--collapse-output-transforms",
        "1",
        "--write-composite-transform",
        "0",
        "--output",
        f"[{prefix},{registered_post_path}]",
        "--interpolation",
        "Linear",
        "--winsorize-image-intensities",
        f"[{low},{high}]",
        "--use-histogram-matching",
        "0",
        "--initial-moving-transform",
        f"[{pre_path},{post_path},0]",
        "--transform",
        f"Rigid[{config.gradient_step}]",
        "--metric",
        (
            f"MI[{pre_path},{post_path},1,{config.histogram_bins},"
            f"{config.sampling_strategy},{config.sampling_percentage}]"
        ),
        "--convergence",
        (
            f"[{_x(config.iterations)},{config.convergence_threshold},"
            f"{config.convergence_window}]"
        ),
        "--shrink-factors",
        _x(config.shrink_factors),
        "--smoothing-sigmas",
        f"{_x(config.smoothing_sigmas_mm)}mm",
        "--random-seed",
        str(config.random_seed),
        "--verbose",
        "1",
    )
    command_record = transform_path.parent / "registration_command.json"
    previous_threads = os.environ.get("ITK_GLOBAL_DEFAULT_NUMBER_OF_THREADS")
    started = time.monotonic()
    os.environ["ITK_GLOBAL_DEFAULT_NUMBER_OF_THREADS"] = str(config.itk_threads)
    try:
        _run_and_record(
            runner,
            args,
            transform_path.parent,
            command_record,
            engine=executables.engine,
            engine_version=executables.version,
            expected_outputs=(registered_post_path, transform_path),
        )
        command_payload = json.loads(command_record.read_text(encoding="utf-8"))
        command_payload["itk_global_default_number_of_threads"] = config.itk_threads
        command_payload["single_precision"] = config.single_precision
        command_record.write_text(
            json.dumps(command_payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    finally:
        if previous_threads is None:
            os.environ.pop("ITK_GLOBAL_DEFAULT_NUMBER_OF_THREADS", None)
        else:
            os.environ["ITK_GLOBAL_DEFAULT_NUMBER_OF_THREADS"] = previous_threads
    runtime = time.monotonic() - started
    metric = _last_ants_metric(command_record)
    return (
        metric,
        "antsRegistration completed; native iteration log retained",
        command_record,
        runtime,
    )


def _last_ants_metric(command_record: Path) -> float:
    """Read the final Mattes MI diagnostic while retaining the complete native log."""

    payload = json.loads(command_record.read_text(encoding="utf-8"))
    stdout_path = payload.get("stdout_path")
    if not stdout_path:
        return float("nan")
    text = Path(str(stdout_path)).read_text(encoding="utf-8", errors="replace")
    values = re.findall(
        r"DIAGNOSTIC,\s*\d+,\s*([-+]?\d+(?:\.\d+)?(?:e[-+]?\d+)?)",
        text,
        flags=re.IGNORECASE,
    )
    return float(values[-1]) if values else float("nan")


def register_post_to_pre(
    pre_path: Path,
    post_path: Path,
    out_path: Path,
    transform_path: Path,
    config: T1RegistrationConfig | None = None,
) -> dict[str, object]:
    """Compatibility wrapper used by the existing pair and cohort CLIs."""

    selected = config or T1RegistrationConfig()
    if transform_path.exists():
        raise FileExistsError(f"Refusing to overwrite registration transform: {transform_path}")
    ants_transform = transform_path.parent / "post_to_pre_ants_0GenericAffine.mat"
    metric, optimizer_stop, _command_record, _runtime = _register(
        pre_path,
        post_path,
        out_path,
        ants_transform,
        selected,
    )
    if ants_transform != transform_path:
        ants_transform.replace(transform_path)
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


def run_t1_registration(
    request: T1RegistrationRequest,
    *,
    runner: CommandRunner | None = None,
    executables: AntsExecutables | None = None,
) -> T1RegistrationOutput:
    """Create one durable registered image, transform, QC, and provenance record."""

    if not request.pre_t1_identity or not request.post_t1_identity:
        raise ValueError(
            "Explicit database/manifest identities are required for both pre/post T1 inputs"
        )
    if request.pre_t1_identity != request.post_t1_identity:
        raise ValueError(
            "Explicit pre/post T1 identities differ; refusing cross-animal registration"
        )
    requested_outputs = (
        request.registered_post_path,
        request.transform_path,
        request.qc_preview_path,
    )
    existing = [path for path in requested_outputs if path.exists()]
    if existing:
        raise FileExistsError(f"Refusing to overwrite T1 registration outputs: {existing}")
    pre_geometry = inspect_nifti_geometry(request.pre_t1_path)
    post_geometry = inspect_nifti_geometry(request.post_t1_path)
    mask_geometry = inspect_nifti_geometry(request.brain_mask_path)
    require_same_physical_grid(
        pre_geometry,
        mask_geometry,
        names=("native pre-Gd T1", "corrected pre-T1 brain mask"),
        affine_atol=1e-4,
    )
    input_sha256 = {
        "pre_t1": sha256_file(request.pre_t1_path),
        "post_t1": sha256_file(request.post_t1_path),
        "corrected_pre_t1_brain_mask": sha256_file(request.brain_mask_path),
    }
    pre_image, pre = load_float(request.pre_t1_path)
    _post_image, post = load_float(request.post_t1_path)
    mask_image, mask_data = load_float(request.brain_mask_path)
    if mask_data.shape != pre.shape or not np.allclose(
        mask_image.affine,
        pre_image.affine,
        atol=1e-3,
    ):
        raise ValueError("approved brain mask must match the native pre-Gd T1 grid")
    values = set(float(value) for value in np.unique(mask_data))
    if not values.issubset({0.0, 1.0}):
        raise ValueError("corrected pre-T1 brain mask must be binary")
    brain_mask = mask_data != 0
    if not np.any(brain_mask):
        raise ValueError("approved brain mask is empty")

    metric, optimizer_stop, command_record, runtime_seconds = _register(
        request.pre_t1_path,
        request.post_t1_path,
        request.registered_post_path,
        request.transform_path,
        request.config,
        runner=runner,
        executables=executables,
    )
    registered_image, registered_post = load_float(request.registered_post_path)
    if registered_post.shape != pre.shape or not np.allclose(
        registered_image.affine,
        pre_image.affine,
        atol=1e-4,
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
    output_sha256 = {
        "registered_post_t1": sha256_file(request.registered_post_path),
        "transform": sha256_file(request.transform_path),
        "qc_preview": sha256_file(request.qc_preview_path),
        "registration_command": sha256_file(command_record),
    }
    for name, path in (
        ("pre_t1", request.pre_t1_path),
        ("post_t1", request.post_t1_path),
        ("corrected_pre_t1_brain_mask", request.brain_mask_path),
    ):
        if sha256_file(path) != input_sha256[name]:
            raise ValueError(f"{name} changed during pre/post T1 registration")
    metadata: dict[str, object] = {
        "scientific_status": "DRAFT_REVIEW_REQUIRED",
        "explicit_input_identity": {
            "pre_t1": request.pre_t1_identity,
            "post_t1": request.post_t1_identity,
            "matched": True,
        },
        "pre_t1_path": str(request.pre_t1_path),
        "post_t1_path": str(request.post_t1_path),
        "brain_mask_path": str(request.brain_mask_path),
        "registered_post_path": str(request.registered_post_path),
        "transform_path": str(request.transform_path),
        "qc_preview_path": str(request.qc_preview_path),
        "method_spec": request.config.method_spec(),
        "method_spec_sha256": request.config.method_spec_sha256,
        "inputs_sha256": input_sha256,
        "outputs_sha256": output_sha256,
        "native_pre_t1_geometry": asdict(pre_geometry),
        "native_post_t1_geometry": asdict(post_geometry),
        "corrected_pre_t1_brain_mask_geometry": asdict(mask_geometry),
        "registered_post_t1_geometry": asdict(
            inspect_nifti_geometry(request.registered_post_path)
        ),
        "registration_command_path": str(command_record),
        "registration_command_sha256": output_sha256["registration_command"],
        "registration_runtime_seconds": runtime_seconds,
        "engine": request.config.runtime_engine,
        "engine_version": request.config.runtime_version,
        "random_seed": request.config.random_seed,
        "itk_threads": request.config.itk_threads,
        "human_review_required": True,
        "reference_space": "native pre-Gd T1",
        "native_pre_t1_resampled": False,
    }
    return T1RegistrationOutput(
        case_id=request.case_id,
        registered_post_path=request.registered_post_path,
        registered_post_sha256=output_sha256["registered_post_t1"],
        transform_path=request.transform_path,
        transform_sha256=output_sha256["transform"],
        qc_preview_path=request.qc_preview_path,
        qc_preview_sha256=output_sha256["qc_preview"],
        before_xcorr=before_xcorr,
        after_xcorr=after_xcorr,
        registration_metric=metric,
        optimizer_stop=optimizer_stop,
        method_version=T1_REGISTRATION_METHOD_VERSION,
        method_spec_sha256=request.config.method_spec_sha256,
        metadata=metadata,
    )
