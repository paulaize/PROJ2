"""Native ANTs atlas-to-pre-T1 registration with immutable command provenance."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable, Protocol

import nibabel as nib
import numpy as np

from lys_bbb.atlas_release import (
    AtlasReleaseSpec,
    inspect_nifti_geometry,
    require_same_physical_grid,
    validate_atlas_release,
)
from lys_bbb.hashing import sha256_file


ANTS_VERSION = "2.6.5"
ATLAS_TO_T1_METHOD_VERSION = "aidamri_to_native_pre_t1_ants_2_6_5_v1"


@dataclass(frozen=True)
class AntsExecutables:
    registration: Path
    apply_transforms: Path
    n4_bias_field_correction: Path
    create_jacobian: Path
    version: str = ANTS_VERSION

    @classmethod
    def discover(cls) -> AntsExecutables:
        names = {
            "registration": "antsRegistration",
            "apply_transforms": "antsApplyTransforms",
            "n4_bias_field_correction": "N4BiasFieldCorrection",
            "create_jacobian": "CreateJacobianDeterminantImage",
        }
        resolved: dict[str, Path] = {}
        for field, name in names.items():
            path = shutil.which(name)
            if path is None:
                raise FileNotFoundError(
                    f"{name} is unavailable. Install conda-forge::ants={ANTS_VERSION} "
                    "in the lys-bbb environment."
                )
            resolved[field] = Path(path).resolve()
        version = subprocess.run(
            [str(resolved["registration"]), "--version"],
            check=True,
            capture_output=True,
            text=True,
            shell=False,
        ).stdout
        if f"ANTs Version: {ANTS_VERSION}" not in version:
            raise ValueError(
                f"Expected native ANTs {ANTS_VERSION}; observed: {version.strip()}"
            )
        return cls(**resolved)


@dataclass(frozen=True)
class AtlasToT1Config:
    histogram_bins: int = 32
    sampling_strategy: str = "Regular"
    sampling_percentage: float = 0.25
    random_seed: int = 42
    shrink_factors: tuple[int, ...] = (4, 2, 1)
    smoothing_sigmas_mm: tuple[float, ...] = (0.4, 0.2, 0.0)
    rigid_iterations: tuple[int, ...] = (100, 50, 20)
    affine_iterations: tuple[int, ...] = (100, 50, 20)
    convergence_threshold: float = 1e-6
    convergence_window: int = 10
    gradient_step: float = 0.1
    crop_margin_mm: float = 1.0
    n4_shrink_factor: int = 4
    n4_iterations: tuple[int, ...] = (50, 50, 30)
    float_computation: bool = True
    enable_syn: bool = False

    def __post_init__(self) -> None:
        levels = len(self.shrink_factors)
        if levels != 3 or len(self.smoothing_sigmas_mm) != levels:
            raise ValueError("Atlas registration requires the provisional 4x2x1 pyramid")
        if len(self.rigid_iterations) != levels or len(self.affine_iterations) != levels:
            raise ValueError("Registration iterations must match pyramid levels")
        if self.shrink_factors != (4, 2, 1):
            raise ValueError("The MVP atlas method is fixed to a 4x2x1 pyramid")
        if self.enable_syn:
            raise ValueError("SyN is disabled until rigid and affine have been reviewed")

    def method_spec(self) -> dict[str, object]:
        return {
            "method_version": ATLAS_TO_T1_METHOD_VERSION,
            "engine": "ANTs",
            "engine_version": ANTS_VERSION,
            "fixed": "native pre-Gd T1 N4 registration copy",
            "moving": "AIDAmri MRI template",
            "metric": "Mattes mutual information",
            "candidates": ["rigid", "rigid_then_affine"],
            "interpolation": "Linear for intensity QC only",
            "scientific_status": "PROVISIONAL_METHOD_REQUIRES_LANDMARK_VALIDATION",
            "config": asdict(self),
        }

    @property
    def method_spec_sha256(self) -> str:
        payload = json.dumps(
            self.method_spec(), sort_keys=True, separators=(",", ":")
        ).encode()
        return hashlib.sha256(payload).hexdigest()


@dataclass(frozen=True)
class CommandExecution:
    args: tuple[str, ...]
    return_code: int
    stdout: str
    stderr: str
    runtime_seconds: float


class CommandRunner(Protocol):
    def __call__(self, args: tuple[str, ...], cwd: Path) -> CommandExecution: ...


def subprocess_command_runner(args: tuple[str, ...], cwd: Path) -> CommandExecution:
    started = time.monotonic()
    result = subprocess.run(
        list(args),
        cwd=cwd,
        check=False,
        capture_output=True,
        text=True,
        shell=False,
    )
    return CommandExecution(
        args=args,
        return_code=int(result.returncode),
        stdout=result.stdout,
        stderr=result.stderr,
        runtime_seconds=time.monotonic() - started,
    )


@dataclass(frozen=True)
class AtlasToT1Request:
    case_id: str
    pre_t1_path: Path
    approved_brain_mask_path: Path
    atlas_release: AtlasReleaseSpec
    output_directory: Path
    config: AtlasToT1Config = AtlasToT1Config()


@dataclass(frozen=True)
class AtlasToT1Candidate:
    candidate: str
    transform_path: Path
    transform_sha256: str
    warped_intensity_path: Path
    warped_intensity_sha256: str
    warped_support_path: Path
    warped_support_sha256: str
    command_record_path: Path
    command_record_sha256: str
    apply_command_record_path: Path
    apply_command_record_sha256: str
    runtime_seconds: float
    affine_metrics: dict[str, object]
    support_metrics: dict[str, object]


@dataclass(frozen=True)
class AtlasToT1Output:
    case_id: str
    preprocessed_t1_path: Path
    preprocessed_t1_sha256: str
    cropped_brain_mask_path: Path
    cropped_brain_mask_sha256: str
    candidates: tuple[AtlasToT1Candidate, ...]
    method_version: str
    method_spec_sha256: str
    input_sha256: dict[str, str]
    metadata_path: Path
    metadata_sha256: str


ProgressCallback = Callable[[int, int, str], None]


def run_atlas_to_t1_candidates(
    request: AtlasToT1Request,
    *,
    runner: CommandRunner = subprocess_command_runner,
    executables: AntsExecutables | None = None,
    progress: ProgressCallback | None = None,
) -> AtlasToT1Output:
    """Estimate separately reviewable rigid and affine candidates."""

    output = request.output_directory.resolve()
    if output.exists():
        raise FileExistsError(f"Refusing to overwrite atlas registration job: {output}")
    output.mkdir(parents=True)
    tools = executables or AntsExecutables.discover()
    if tools.version != ANTS_VERSION:
        raise ValueError(f"Atlas registration requires ANTs {ANTS_VERSION}")
    release = validate_atlas_release(request.atlas_release)

    pre_geometry = inspect_nifti_geometry(request.pre_t1_path)
    mask_geometry = inspect_nifti_geometry(request.approved_brain_mask_path)
    require_same_physical_grid(
        pre_geometry,
        mask_geometry,
        names=("native pre-Gd T1", "approved pre-T1 brain mask"),
        affine_atol=1e-4,
    )
    pre_image = nib.load(str(request.pre_t1_path))
    mask_image = nib.load(str(request.approved_brain_mask_path))
    pre_data = pre_image.get_fdata(dtype=np.float32)
    mask_data = np.asanyarray(mask_image.dataobj)
    if not set(float(value) for value in np.unique(mask_data)).issubset({0.0, 1.0}):
        raise ValueError("The approved pre-T1 brain mask must be binary")
    mask = mask_data != 0
    if not mask.any():
        raise ValueError("The approved pre-T1 brain mask is empty")

    input_sha256 = {
        "pre_t1": sha256_file(request.pre_t1_path),
        "approved_brain_mask": sha256_file(request.approved_brain_mask_path),
        "atlas_template": sha256_file(release.spec.template_path),
        "atlas_labels": sha256_file(release.spec.labels_path),
        "atlas_lookup": sha256_file(release.spec.source_lookup_path),
        "atlas_template_mask": release.template_mask_sha256,
    }
    registration_copy, cropped_mask = _write_cropped_registration_copies(
        pre_image,
        pre_data,
        mask,
        output,
        margin_mm=request.config.crop_margin_mm,
    )
    n4_path = output / "pre_t1_cropped_n4.nii.gz"
    _report(progress, 0, 3, "N4 bias correction on the cropped pre-T1 copy")
    n4_args = (
        str(tools.n4_bias_field_correction),
        "-d",
        "3",
        "-i",
        str(registration_copy),
        "-x",
        str(cropped_mask),
        "-s",
        str(request.config.n4_shrink_factor),
        "-c",
        f"[{_x(request.config.n4_iterations)},1e-7]",
        "-o",
        str(n4_path),
        "-v",
        "1",
    )
    _run_and_record(
        runner,
        n4_args,
        output,
        output / "n4_command.json",
        engine_version=tools.version,
        expected_outputs=(n4_path,),
    )

    candidates: list[AtlasToT1Candidate] = []
    for index, candidate in enumerate(("rigid", "affine"), start=1):
        _report(progress, index, 3, f"Running atlas-to-pre-T1 {candidate} candidate")
        candidate_dir = output / candidate
        candidate_dir.mkdir()
        prefix = candidate_dir / f"{candidate}_"
        registration_warped = candidate_dir / (
            f"atlas_intensity_{candidate}_in_pre_t1_cropped.nii.gz"
        )
        warped = candidate_dir / f"atlas_intensity_{candidate}_in_native_pre_t1.nii.gz"
        warped_support = (
            candidate_dir / f"atlas_support_{candidate}_in_native_pre_t1.nii.gz"
        )
        transform = candidate_dir / f"{candidate}_0GenericAffine.mat"
        args = _registration_args(
            tools.registration,
            fixed=n4_path,
            moving=release.spec.template_path,
            fixed_mask=cropped_mask,
            moving_mask=release.spec.template_mask_path,
            prefix=prefix,
            warped=registration_warped,
            config=request.config,
            affine=candidate == "affine",
        )
        command_record = candidate_dir / "command.json"
        execution = _run_and_record(
            runner,
            args,
            candidate_dir,
            command_record,
            engine_version=tools.version,
            expected_outputs=(registration_warped, transform),
        )
        apply_record = candidate_dir / "apply_intensity_to_full_pre_t1.json"
        apply_args = (
            str(tools.apply_transforms),
            "--dimensionality",
            "3",
            "--input",
            str(release.spec.template_path),
            "--reference-image",
            str(request.pre_t1_path),
            "--output",
            str(warped),
            "--interpolation",
            "Linear",
            "--transform",
            str(transform),
            "--float",
            "1",
            "--verbose",
            "1",
        )
        _run_and_record(
            runner,
            apply_args,
            candidate_dir,
            apply_record,
            engine_version=tools.version,
            expected_outputs=(warped,),
        )
        support_record = candidate_dir / "apply_support_to_full_pre_t1.json"
        support_args = (
            str(tools.apply_transforms),
            "--dimensionality",
            "3",
            "--input",
            str(release.spec.template_mask_path),
            "--reference-image",
            str(request.pre_t1_path),
            "--output",
            str(warped_support),
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
            support_args,
            candidate_dir,
            support_record,
            engine_version=tools.version,
            expected_outputs=(warped_support,),
        )
        warped_geometry = inspect_nifti_geometry(warped)
        require_same_physical_grid(
            pre_geometry,
            warped_geometry,
            names=("native pre-T1", f"{candidate} warped atlas"),
            affine_atol=1e-4,
        )
        require_same_physical_grid(
            pre_geometry,
            inspect_nifti_geometry(warped_support),
            names=("native pre-T1", f"{candidate} warped atlas support"),
            affine_atol=1e-4,
        )
        metrics = linear_transform_metrics(transform)
        warped_support_data = np.asanyarray(nib.load(str(warped_support)).dataobj)
        if not set(float(value) for value in np.unique(warped_support_data)).issubset(
            {0.0, 1.0}
        ):
            raise ValueError("Propagated atlas support is not binary")
        atlas_support = warped_support_data != 0
        intersection = int(np.count_nonzero(mask & atlas_support))
        subject_voxels = int(np.count_nonzero(mask))
        atlas_voxels = int(np.count_nonzero(atlas_support))
        support_metrics = {
            "subject_mask_voxels": subject_voxels,
            "warped_atlas_support_voxels": atlas_voxels,
            "intersection_voxels": intersection,
            "dice": (
                2.0 * intersection / (subject_voxels + atlas_voxels)
                if subject_voxels + atlas_voxels
                else 1.0
            ),
            "subject_covered_fraction": intersection / subject_voxels,
            "atlas_inside_subject_fraction": (
                intersection / atlas_voxels if atlas_voxels else 0.0
            ),
            "automatic_scientific_acceptance": "not_claimed",
        }
        candidates.append(
            AtlasToT1Candidate(
                candidate=candidate,
                transform_path=transform,
                transform_sha256=sha256_file(transform),
                warped_intensity_path=warped,
                warped_intensity_sha256=sha256_file(warped),
                warped_support_path=warped_support,
                warped_support_sha256=sha256_file(warped_support),
                command_record_path=command_record,
                command_record_sha256=sha256_file(command_record),
                apply_command_record_path=apply_record,
                apply_command_record_sha256=sha256_file(apply_record),
                runtime_seconds=execution.runtime_seconds,
                affine_metrics=metrics,
                support_metrics=support_metrics,
            )
        )

    for name, path in (
        ("pre_t1", request.pre_t1_path),
        ("approved_brain_mask", request.approved_brain_mask_path),
    ):
        if sha256_file(path) != input_sha256[name]:
            raise ValueError(f"{name} changed while atlas registration was running")
    metadata = {
        "case_id": request.case_id,
        "method_spec": request.config.method_spec(),
        "method_spec_sha256": request.config.method_spec_sha256,
        "engine": "ANTs",
        "engine_version": tools.version,
        "executables": {field: str(value) for field, value in asdict(tools).items()},
        "inputs": input_sha256,
        "native_pre_t1_geometry": asdict(pre_geometry),
        "approved_brain_mask_geometry": asdict(mask_geometry),
        "atlas_template_geometry": asdict(release.template_geometry),
        "reference_space": "native pre-Gd T1",
        "post_gd_dependency": False,
        "fixed_space": "native pre-Gd T1",
        "moving_space": "AIDAmri MRI template",
        "conceptual_image_warp_direction": "AIDAmri atlas to native pre-Gd T1",
        "actual_point_mapping_convention": (
            "fixed native pre-T1 points to moving AIDAmri atlas points"
        ),
        "invertible": True,
        "candidate_approval_required": True,
        "candidates": [
            {
                "candidate": item.candidate,
                "transform_sha256": item.transform_sha256,
                "warped_intensity_sha256": item.warped_intensity_sha256,
                "warped_support_sha256": item.warped_support_sha256,
                "command_record_sha256": item.command_record_sha256,
                "apply_command_record_sha256": item.apply_command_record_sha256,
                "affine_metrics": item.affine_metrics,
                "support_metrics": item.support_metrics,
            }
            for item in candidates
        ],
    }
    metadata_path = output / "atlas_to_t1_metadata.json"
    metadata_path.write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n")
    _report(progress, 3, 3, "Atlas-to-pre-T1 candidates ready for review")
    return AtlasToT1Output(
        case_id=request.case_id,
        preprocessed_t1_path=n4_path,
        preprocessed_t1_sha256=sha256_file(n4_path),
        cropped_brain_mask_path=cropped_mask,
        cropped_brain_mask_sha256=sha256_file(cropped_mask),
        candidates=tuple(candidates),
        method_version=ATLAS_TO_T1_METHOD_VERSION,
        method_spec_sha256=request.config.method_spec_sha256,
        input_sha256=input_sha256,
        metadata_path=metadata_path,
        metadata_sha256=sha256_file(metadata_path),
    )


def linear_transform_metrics(path: Path) -> dict[str, object]:
    """Report scale/shear/determinant and reject non-finite reflection transforms."""

    import SimpleITK as sitk

    transform = sitk.ReadTransform(str(path))
    if not hasattr(transform, "GetMatrix"):
        raise ValueError(f"Expected a linear ANTs transform: {path}")
    matrix = np.asarray(transform.GetMatrix(), dtype=np.float64).reshape(3, 3)
    if not np.isfinite(matrix).all():
        raise ValueError("Registration transform contains non-finite values")
    determinant = float(np.linalg.det(matrix))
    if determinant <= 0:
        raise ValueError("Registration transform contains a left-right reflection")
    stretches = np.linalg.svd(matrix, compute_uv=False)
    gram = matrix.T @ matrix
    diagonal = np.diag(np.diag(gram))
    shear_norm = float(np.linalg.norm(gram - diagonal, ord="fro"))
    return {
        "determinant": determinant,
        "principal_stretches": [float(value) for value in stretches],
        "scale": [float(np.linalg.norm(matrix[:, axis])) for axis in range(3)],
        "shear_frobenius": shear_norm,
        "automatic_scientific_acceptance": "not_claimed",
    }


def _registration_args(
    executable: Path,
    *,
    fixed: Path,
    moving: Path,
    fixed_mask: Path,
    moving_mask: Path,
    prefix: Path,
    warped: Path,
    config: AtlasToT1Config,
    affine: bool,
) -> tuple[str, ...]:
    metric = (
        f"MI[{fixed},{moving},1,{config.histogram_bins},"
        f"{config.sampling_strategy},{config.sampling_percentage}]"
    )
    args: list[str] = [
        str(executable),
        "--dimensionality",
        "3",
        "--float",
        "1" if config.float_computation else "0",
        "--output",
        f"[{prefix},{warped}]",
        "--interpolation",
        "Linear",
        "--winsorize-image-intensities",
        "[0.005,0.995]",
        "--initial-moving-transform",
        f"[{fixed},{moving},0]",
        "--transform",
        f"Rigid[{config.gradient_step}]",
        "--metric",
        metric,
        "--convergence",
        f"[{_x(config.rigid_iterations)},{config.convergence_threshold},"
        f"{config.convergence_window}]",
        "--shrink-factors",
        _x(config.shrink_factors),
        "--smoothing-sigmas",
        f"{_x(config.smoothing_sigmas_mm)}mm",
    ]
    if affine:
        args.extend(
            (
                "--transform",
                f"Affine[{config.gradient_step}]",
                "--metric",
                metric,
                "--convergence",
                f"[{_x(config.affine_iterations)},{config.convergence_threshold},"
                f"{config.convergence_window}]",
                "--shrink-factors",
                _x(config.shrink_factors),
                "--smoothing-sigmas",
                f"{_x(config.smoothing_sigmas_mm)}mm",
            )
        )
    args.extend(
        (
            "--masks",
            f"[{fixed_mask},{moving_mask}]",
            "--random-seed",
            str(config.random_seed),
            "--verbose",
            "1",
        )
    )
    return tuple(args)


def _write_cropped_registration_copies(
    image: nib.Nifti1Image,
    data: np.ndarray,
    mask: np.ndarray,
    output: Path,
    *,
    margin_mm: float,
) -> tuple[Path, Path]:
    coordinates = np.argwhere(mask)
    spacing = np.asarray(image.header.get_zooms()[:3])
    margin = np.ceil(margin_mm / spacing).astype(int)
    start = np.maximum(coordinates.min(axis=0) - margin, 0)
    stop = np.minimum(coordinates.max(axis=0) + margin + 1, mask.shape)
    slices = tuple(slice(int(a), int(b)) for a, b in zip(start, stop, strict=True))
    affine = np.asarray(image.affine) @ nib.affines.from_matvec(
        np.eye(3), start.astype(float)
    )
    image_path = output / "pre_t1_cropped_registration_copy.nii.gz"
    mask_path = output / "pre_t1_brain_mask_cropped.nii.gz"
    nib.save(nib.Nifti1Image(data[slices].astype(np.float32), affine), str(image_path))
    nib.save(nib.Nifti1Image(mask[slices].astype(np.uint8), affine), str(mask_path))
    return image_path, mask_path


def _run_and_record(
    runner: CommandRunner,
    args: tuple[str, ...],
    cwd: Path,
    record_path: Path,
    *,
    engine_version: str,
    expected_outputs: tuple[Path, ...],
) -> CommandExecution:
    execution = runner(args, cwd)
    stdout_path = record_path.with_name(f"{record_path.stem}.stdout.log")
    stderr_path = record_path.with_name(f"{record_path.stem}.stderr.log")
    stdout_path.write_text(execution.stdout)
    stderr_path.write_text(execution.stderr)
    outputs = {}
    for path in expected_outputs:
        _require_output_in_job(path, cwd)
        outputs[str(path)] = sha256_file(path) if path.is_file() else None
    record = {
        "args": list(execution.args),
        "executable_path": execution.args[0],
        "engine": "ANTs",
        "engine_version": engine_version,
        "return_code": execution.return_code,
        "runtime_seconds": execution.runtime_seconds,
        "stdout_path": str(stdout_path),
        "stderr_path": str(stderr_path),
        "outputs": outputs,
    }
    record_path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")
    if execution.return_code != 0:
        raise RuntimeError(
            f"ANTs command failed with code {execution.return_code}: "
            f"{execution.stderr.strip()}"
        )
    missing = [str(path) for path in expected_outputs if not path.is_file()]
    if missing:
        raise RuntimeError("ANTs did not create required outputs: " + ", ".join(missing))
    return execution


def _require_output_in_job(path: Path, job_directory: Path) -> None:
    resolved = path.resolve()
    root = job_directory.resolve()
    if resolved != root and root not in resolved.parents:
        raise ValueError(f"ANTs output is outside its job directory: {resolved}")


def _x(values: tuple[int | float, ...]) -> str:
    return "x".join(str(value) for value in values)


def _report(
    progress: ProgressCallback | None,
    current: int,
    total: int,
    message: str,
) -> None:
    if progress is not None:
        progress(current, total, message)
