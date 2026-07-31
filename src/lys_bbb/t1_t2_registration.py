"""Rigid native pre-T1 to original partial-T2 registration contract."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path

import nibabel as nib
import numpy as np

from lys_bbb.atlas_registration import (
    AntsExecutables,
    CommandRunner,
    ProgressCallback,
    _run_and_record,
    _require_runtime_match,
    _require_supported_runtime,
    _x,
    linear_transform_metrics,
)
from lys_bbb.atlas_release import (
    inspect_nifti_geometry,
    require_same_physical_grid,
)
from lys_bbb.hashing import sha256_file
from lys_bbb.registration_runtime import ANTSPYX_ENGINE, ANTSPYX_VERSION


T1_TO_T2_ANTSPYX_METHOD_VERSION = (
    "native_pre_t1_to_partial_t2_antspyx_0_6_3_"
    "rigid_unmasked_sensitivity_v1"
)


@dataclass(frozen=True)
class T1ToT2Config:
    histogram_bins: int = 32
    sampling_strategy: str = "Regular"
    sampling_percentage: float = 0.5
    random_seed: int = 42
    shrink_factors: tuple[int, ...] = (2, 1)
    smoothing_sigmas_mm: tuple[float, ...] = (0.2, 0.0)
    iterations: tuple[int, ...] = (100, 40)
    convergence_threshold: float = 1e-6
    convergence_window: int = 10
    gradient_step: float = 0.1
    initialization: str = "geometry"
    runtime_engine: str = ANTSPYX_ENGINE
    runtime_version: str = ANTSPYX_VERSION

    def __post_init__(self) -> None:
        expected = {
            "histogram_bins": 32,
            "sampling_strategy": "Regular",
            "sampling_percentage": 0.5,
            "random_seed": 42,
            "shrink_factors": (2, 1),
            "smoothing_sigmas_mm": (0.2, 0.0),
            "iterations": (100, 40),
            "convergence_threshold": 1e-6,
            "convergence_window": 10,
            "gradient_step": 0.1,
            "initialization": "geometry",
        }
        observed = asdict(self)
        for name, value in expected.items():
            if observed[name] != value:
                raise ValueError(
                    f"{T1_TO_T2_ANTSPYX_METHOD_VERSION} requires {name}={value!r}"
                )
        _require_supported_runtime(self.runtime_engine, self.runtime_version)

    def method_spec(self) -> dict[str, object]:
        config = asdict(self)
        del config["runtime_engine"]
        del config["runtime_version"]
        return {
            "method_version": self.method_version,
            "engine": self.runtime_engine,
            "engine_version": self.runtime_version,
            "fixed": "original native T2",
            "moving": "original native pre-Gd T1",
            "transform": "rigid, six degrees of freedom",
            "initializer": "geometry centres",
            "metric": "Mattes mutual information",
            "metric_masks": "none; corrected T1 mask is propagated for QC only",
            "interpolation": (
                "Linear once for scalar T1; GenericLabel once for the QC mask; "
                "unchanged native T2 reference grid"
            ),
            "winsorize_quantiles": [0.005, 0.995],
            "scientific_status": "DRAFT_REVIEW_REQUIRED",
            "config": config,
        }

    @property
    def method_version(self) -> str:
        return T1_TO_T2_ANTSPYX_METHOD_VERSION

    @property
    def method_spec_sha256(self) -> str:
        payload = json.dumps(
            self.method_spec(), sort_keys=True, separators=(",", ":")
        ).encode()
        return hashlib.sha256(payload).hexdigest()


@dataclass(frozen=True)
class T1ToT2Request:
    case_id: str
    pre_t1_path: Path
    approved_t1_brain_mask_path: Path
    native_t2_path: Path
    t2_registration_support_mask_path: Path | None
    output_directory: Path
    pre_t1_identity: str | None = None
    t2_identity: str | None = None
    lesion_display_mask_path: Path | None = None
    config: T1ToT2Config = T1ToT2Config()


@dataclass(frozen=True)
class T1ToT2Output:
    case_id: str
    transform_path: Path
    transform_sha256: str
    transformed_t1_path: Path
    transformed_t1_sha256: str
    transformed_t1_brain_mask_path: Path
    transformed_t1_brain_mask_sha256: str
    command_record_path: Path
    command_record_sha256: str
    cost_mask_path: Path | None
    cost_mask_sha256: str | None
    affine_metrics: dict[str, object]
    method_version: str
    method_spec_sha256: str
    input_sha256: dict[str, str]
    metadata_path: Path
    metadata_sha256: str


def run_t1_to_t2_registration(
    request: T1ToT2Request,
    *,
    runner: CommandRunner | None = None,
    executables: AntsExecutables | None = None,
    progress: ProgressCallback | None = None,
) -> T1ToT2Output:
    """Estimate one review-required rigid transform without resampling the T2."""

    output = request.output_directory.resolve()
    if output.exists():
        raise FileExistsError(f"Refusing to overwrite T1-to-T2 job: {output}")
    if runner is None or executables is None:
        from lys_bbb.antspyx_backend import (
            antspyx_executables,
            antspyx_subprocess_command_runner,
        )

        runner = runner or antspyx_subprocess_command_runner
        executables = executables or antspyx_executables()
    tools = executables
    _require_runtime_match(
        request.config.runtime_engine,
        request.config.runtime_version,
        tools,
    )
    if not request.pre_t1_identity or not request.t2_identity:
        raise ValueError(
            "Explicit pre-T1 and T2 subject/session identities are required; "
            "the pairing cannot be inferred from filenames or image content."
        )
    if request.pre_t1_identity != request.t2_identity:
        raise ValueError(
            "Explicit pre-T1 and T2 identities differ; refusing cross-animal registration"
        )

    t1_geometry = inspect_nifti_geometry(request.pre_t1_path)
    t1_mask_geometry = inspect_nifti_geometry(request.approved_t1_brain_mask_path)
    t2_geometry = inspect_nifti_geometry(request.native_t2_path)
    require_same_physical_grid(
        t1_geometry,
        t1_mask_geometry,
        names=("native pre-Gd T1", "approved T1 brain mask"),
        affine_atol=1e-4,
    )
    _require_binary_nonempty(request.approved_t1_brain_mask_path, "T1 brain mask")

    display_support_mask = request.t2_registration_support_mask_path
    if display_support_mask is not None:
        require_same_physical_grid(
            t2_geometry,
            inspect_nifti_geometry(display_support_mask),
            names=("native T2", "display-only T2 support mask"),
            affine_atol=1e-4,
        )
        _require_binary_nonempty(display_support_mask, "display-only T2 support mask")
    lesion_path = request.lesion_display_mask_path
    if lesion_path is not None:
        require_same_physical_grid(
            t2_geometry,
            inspect_nifti_geometry(lesion_path),
            names=("native T2", "display-only lesion mask"),
            affine_atol=1e-4,
        )
        _require_binary(lesion_path, "display-only lesion mask")

    input_sha256 = {
        "pre_t1": sha256_file(request.pre_t1_path),
        "approved_t1_brain_mask": sha256_file(request.approved_t1_brain_mask_path),
        "native_t2": sha256_file(request.native_t2_path),
    }
    if display_support_mask is not None:
        input_sha256["display_only_t2_support_mask"] = sha256_file(
            display_support_mask
        )
    if lesion_path is not None:
        input_sha256["display_only_lesion_mask"] = sha256_file(lesion_path)

    output.mkdir(parents=True)
    cost_mask_path: Path | None = None

    prefix = output / "rigid_"
    transformed_t1 = output / "pre_t1_rigid_in_native_t2.nii.gz"
    transform = output / "rigid_0GenericAffine.mat"
    initialization_feature = "0" if request.config.initialization == "geometry" else "1"
    metric = (
        f"MI[{request.native_t2_path},{request.pre_t1_path},1,"
        f"{request.config.histogram_bins},{request.config.sampling_strategy},"
        f"{request.config.sampling_percentage}]"
    )
    args: list[str] = [
        str(tools.registration),
        "--dimensionality",
        "3",
        "--float",
        "1",
        "--output",
        f"[{prefix},{transformed_t1}]",
        "--interpolation",
        "Linear",
        "--winsorize-image-intensities",
        "[0.005,0.995]",
        "--initial-moving-transform",
        f"[{request.native_t2_path},{request.pre_t1_path},{initialization_feature}]",
        "--transform",
        f"Rigid[{request.config.gradient_step}]",
        "--metric",
        metric,
        "--convergence",
        f"[{_x(request.config.iterations)},{request.config.convergence_threshold},"
        f"{request.config.convergence_window}]",
        "--shrink-factors",
        _x(request.config.shrink_factors),
        "--smoothing-sigmas",
        f"{_x(request.config.smoothing_sigmas_mm)}mm",
    ]
    args.extend(
        (
            "--random-seed",
            str(request.config.random_seed),
            "--verbose",
            "1",
        )
    )
    if progress is not None:
        progress(0, 1, "Running native pre-T1 to partial-T2 rigid registration")
    command_record = output / "command.json"
    _run_and_record(
        runner,
        tuple(args),
        output,
        command_record,
        engine=tools.engine,
        engine_version=tools.version,
        expected_outputs=(transformed_t1, transform),
    )
    transformed_t1_mask = output / "approved_t1_brain_mask_in_native_t2.nii.gz"
    mask_record = output / "apply_t1_brain_mask_to_native_t2.json"
    mask_args = (
        str(tools.apply_transforms),
        "--dimensionality",
        "3",
        "--input",
        str(request.approved_t1_brain_mask_path),
        "--reference-image",
        str(request.native_t2_path),
        "--output",
        str(transformed_t1_mask),
        "--interpolation",
        "GenericLabel",
        "--output-data-type",
        "uchar",
        "--transform",
        str(transform),
        "--float",
        "1",
        "--verbose",
        "1",
    )
    _run_and_record(
        runner,
        mask_args,
        output,
        mask_record,
        engine=tools.engine,
        engine_version=tools.version,
        expected_outputs=(transformed_t1_mask,),
    )
    require_same_physical_grid(
        t2_geometry,
        inspect_nifti_geometry(transformed_t1),
        names=("native T2", "transformed pre-T1"),
        affine_atol=1e-4,
    )
    metrics = linear_transform_metrics(transform)
    transformed_mask = _require_binary(
        transformed_t1_mask, "transformed T1 brain mask"
    )
    require_same_physical_grid(
        t2_geometry,
        inspect_nifti_geometry(transformed_t1_mask),
        names=("native T2", "transformed T1 brain mask"),
        affine_atol=1e-4,
    )
    if not transformed_mask.any():
        raise ValueError("The transformed T1 brain mask has no support in native T2")
    for name, path in (
        ("pre_t1", request.pre_t1_path),
        ("approved_t1_brain_mask", request.approved_t1_brain_mask_path),
        ("native_t2", request.native_t2_path),
    ):
        if sha256_file(path) != input_sha256[name]:
            raise ValueError(f"{name} changed during T1-to-T2 registration")
    if (
        display_support_mask is not None
        and sha256_file(display_support_mask)
        != input_sha256["display_only_t2_support_mask"]
    ):
        raise ValueError("display_only_t2_support_mask changed during registration")
    if (
        lesion_path is not None
        and sha256_file(lesion_path) != input_sha256["display_only_lesion_mask"]
    ):
        raise ValueError("display_only_lesion_mask changed during registration")
    metadata = {
        "case_id": request.case_id,
        "method_spec": request.config.method_spec(),
        "method_spec_sha256": request.config.method_spec_sha256,
        "engine": tools.engine,
        "engine_version": tools.version,
        "executables": {field: str(value) for field, value in asdict(tools).items()},
        "inputs": input_sha256,
        "explicit_input_identity": {
            "pre_t1": request.pre_t1_identity,
            "t2": request.t2_identity,
            "pairing_identity_explicit": True,
            "matched": True,
        },
        "native_pre_t1_geometry": asdict(t1_geometry),
        "approved_t1_brain_mask_geometry": asdict(t1_mask_geometry),
        "native_t2_geometry": asdict(t2_geometry),
        "transformed_t1_geometry": asdict(
            inspect_nifti_geometry(transformed_t1)
        ),
        "transformed_t1_brain_mask_geometry": asdict(
            inspect_nifti_geometry(transformed_t1_mask)
        ),
        "t2_registration_support_mask_geometry": (
            asdict(inspect_nifti_geometry(display_support_mask))
            if display_support_mask is not None
            else None
        ),
        "conceptual_image_warp_direction": "native pre-T1 to native T2",
        "actual_point_mapping_convention": "fixed T2 points to moving pre-T1 points",
        "invertible": True,
        "registration_metric_masks_used": False,
        "corrected_t1_mask_role": "propagated_for_qc_only",
        "lesion_role": "display_only" if lesion_path is not None else None,
        "native_t2_resampled": False,
        "transformed_t1_brain_mask_sha256": sha256_file(transformed_t1_mask),
        "transform_sha256": sha256_file(transform),
        "transformed_t1_sha256": sha256_file(transformed_t1),
        "registration_command_sha256": sha256_file(command_record),
        "mask_apply_command_sha256": sha256_file(mask_record),
        "human_review_required": True,
        "affine_metrics": metrics,
    }
    metadata_path = output / "t1_to_t2_metadata.json"
    metadata_path.write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n")
    if progress is not None:
        progress(1, 1, "T1-to-T2 rigid candidate ready for all-slice review")
    return T1ToT2Output(
        case_id=request.case_id,
        transform_path=transform,
        transform_sha256=sha256_file(transform),
        transformed_t1_path=transformed_t1,
        transformed_t1_sha256=sha256_file(transformed_t1),
        transformed_t1_brain_mask_path=transformed_t1_mask,
        transformed_t1_brain_mask_sha256=sha256_file(transformed_t1_mask),
        command_record_path=command_record,
        command_record_sha256=sha256_file(command_record),
        cost_mask_path=cost_mask_path,
        cost_mask_sha256=None,
        affine_metrics=metrics,
        method_version=request.config.method_version,
        method_spec_sha256=request.config.method_spec_sha256,
        input_sha256=input_sha256,
        metadata_path=metadata_path,
        metadata_sha256=sha256_file(metadata_path),
    )


def _require_binary(path: Path, label: str) -> np.ndarray:
    data = np.asanyarray(nib.load(str(path)).dataobj)
    values = set(float(value) for value in np.unique(data))
    if not values.issubset({0.0, 1.0}):
        raise ValueError(f"The {label} must be binary")
    return data != 0


def _require_binary_nonempty(path: Path, label: str) -> np.ndarray:
    data = _require_binary(path, label)
    if not data.any():
        raise ValueError(f"The {label} is empty")
    return data
