"""Major-region collapse, direct ANTs propagation, and native-T2 overlap."""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path

import nibabel as nib
import numpy as np
from scipy import ndimage

from lys_bbb.atlas_registration import (
    ANTS_VERSION,
    AntsExecutables,
    CommandRunner,
    _run_and_record,
    subprocess_command_runner,
)
from lys_bbb.atlas_release import (
    MajorRegionScheme,
    inspect_nifti_geometry,
    require_same_physical_grid,
)
from lys_bbb.hashing import sha256_file


@dataclass(frozen=True)
class MappingApprovalGate:
    atlas_release_valid: bool
    major_region_scheme_approved: bool
    atlas_to_t1_approved: bool
    t1_to_t2_approved: bool
    composite_labels_approved: bool

    def require_overlap_eligible(self) -> None:
        missing = [
            label
            for label, ready in (
                ("valid atlas release", self.atlas_release_valid),
                ("approved major-region mapping", self.major_region_scheme_approved),
                ("approved atlas-to-pre-T1 registration", self.atlas_to_t1_approved),
                ("approved pre-T1-to-T2 registration", self.t1_to_t2_approved),
                ("approved composite labels on native T2", self.composite_labels_approved),
            )
            if not ready
        ]
        if missing:
            raise ValueError("Regional overlap is blocked until: " + ", ".join(missing))


@dataclass(frozen=True)
class AtlasCompositeRequest:
    source_atlas_labels_path: Path
    major_region_scheme: MajorRegionScheme
    native_pre_t1_path: Path
    native_t2_path: Path
    atlas_to_t1_transform_path: Path
    t1_to_t2_transform_path: Path
    output_directory: Path


@dataclass(frozen=True)
class AtlasCompositeOutput:
    source_major_labels_path: Path
    source_major_labels_sha256: str
    labels_in_pre_t1_path: Path
    labels_in_pre_t1_sha256: str
    labels_in_native_t2_path: Path
    labels_in_native_t2_sha256: str
    atlas_support_in_native_t2_path: Path
    atlas_support_in_native_t2_sha256: str
    command_record_paths: tuple[Path, ...]
    metadata_path: Path
    metadata_sha256: str


@dataclass(frozen=True)
class MajorRegionLesionResult:
    lesion_voxel_count: int
    lesion_volume_mm3: float
    mapped_lesion_voxels: int
    unmapped_lesion_voxels: int
    outside_atlas_support_lesion_voxels: int
    boundary_lesion_voxels: int
    nominal_dominant_region_id: int | None
    sensitivity_status: str
    result_csv_path: Path
    result_csv_sha256: str
    metadata_path: Path
    metadata_sha256: str
    lesion_sha256: str


def collapse_source_labels(
    source_labels_path: Path,
    scheme: MajorRegionScheme,
    output_path: Path,
) -> Path:
    """Collapse source labels on the atlas grid without spatial resampling."""

    image = nib.load(str(source_labels_path))
    source = np.asanyarray(image.dataobj)
    if not np.isfinite(source).all() or not np.array_equal(source, np.rint(source)):
        raise ValueError("Source atlas labels must be finite integers")
    lookup = {row.source_label_id: row.major_region_id for row in scheme.rows}
    observed = set(int(value) for value in np.unique(source) if value != 0)
    missing = sorted(observed - set(lookup))
    if missing:
        raise ValueError(f"Major-region mapping lacks source labels: {missing}")
    collapsed = np.zeros(source.shape, dtype=np.int16)
    for source_id, major_id in lookup.items():
        collapsed[source == source_id] = major_id
    validate_major_label_array(collapsed, scheme.allowed_major_region_ids)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    header = image.header.copy()
    header.set_data_dtype(np.int16)
    nib.save(nib.Nifti1Image(collapsed, image.affine, header), str(output_path))
    return output_path


def create_native_composite_labels(
    request: AtlasCompositeRequest,
    *,
    runner: CommandRunner = subprocess_command_runner,
    executables: AntsExecutables | None = None,
) -> AtlasCompositeOutput:
    """Resample original-grid major labels directly once into pre-T1 and T2."""

    output = request.output_directory.resolve()
    if output.exists():
        raise FileExistsError(f"Refusing to overwrite atlas composite: {output}")
    output.mkdir(parents=True)
    tools = executables or AntsExecutables.discover()
    if tools.version != ANTS_VERSION:
        raise ValueError(f"Atlas composition requires ANTs {ANTS_VERSION}")
    source_major = collapse_source_labels(
        request.source_atlas_labels_path,
        request.major_region_scheme,
        output / "major_labels_on_source_atlas_grid.nii.gz",
    )
    source_image = nib.load(str(source_major))
    source_data = np.asanyarray(source_image.dataobj)
    source_support = output / "atlas_major_region_support_on_source_grid.nii.gz"
    nib.save(
        nib.Nifti1Image((source_data != 0).astype(np.uint8), source_image.affine),
        str(source_support),
    )

    pre_labels = output / "major_labels_in_native_pre_t1.nii.gz"
    pre_record = output / "apply_major_labels_to_pre_t1.json"
    _apply_labels(
        tools,
        runner,
        input_path=source_major,
        reference_path=request.native_pre_t1_path,
        output_path=pre_labels,
        transforms=(request.atlas_to_t1_transform_path,),
        record_path=pre_record,
    )
    validate_major_label_volume(
        pre_labels,
        request.native_pre_t1_path,
        request.major_region_scheme.allowed_major_region_ids,
    )

    t2_labels = output / "major_labels_in_original_native_t2.nii.gz"
    t2_record = output / "apply_major_labels_directly_to_native_t2.json"
    # Empirical ANTs 2.6.5 label-cube proof: for image resampling, the first listed
    # transform acts first on each output-grid point. We need T2->pre followed by
    # pre->atlas, so the pre-to-T2 registration transform is listed first.
    _apply_labels(
        tools,
        runner,
        input_path=source_major,
        reference_path=request.native_t2_path,
        output_path=t2_labels,
        transforms=(
            request.t1_to_t2_transform_path,
            request.atlas_to_t1_transform_path,
        ),
        record_path=t2_record,
    )
    validate_major_label_volume(
        t2_labels,
        request.native_t2_path,
        request.major_region_scheme.allowed_major_region_ids,
    )
    support_t2 = output / "atlas_support_in_original_native_t2.nii.gz"
    support_record = output / "apply_atlas_support_directly_to_native_t2.json"
    _apply_labels(
        tools,
        runner,
        input_path=source_support,
        reference_path=request.native_t2_path,
        output_path=support_t2,
        transforms=(
            request.t1_to_t2_transform_path,
            request.atlas_to_t1_transform_path,
        ),
        record_path=support_record,
    )
    _require_binary_grid(support_t2, request.native_t2_path, "atlas support")
    metadata = {
        "scientific_status": "DRAFT_REVIEW_REQUIRED",
        "source_atlas_labels_sha256": sha256_file(request.source_atlas_labels_path),
        "major_region_scheme_sha256": request.major_region_scheme.sha256,
        "major_region_scheme_approved": request.major_region_scheme.approved,
        "atlas_to_t1_transform_sha256": sha256_file(
            request.atlas_to_t1_transform_path
        ),
        "t1_to_t2_transform_sha256": sha256_file(request.t1_to_t2_transform_path),
        "native_pre_t1_sha256": sha256_file(request.native_pre_t1_path),
        "native_t2_sha256": sha256_file(request.native_t2_path),
        "native_t2_resampling_count": 1,
        "native_t2_labels_derived_from_pre_resample": False,
        "transform_order_proof_contract": (
            "ANTs 2.6.5 labeled-cube proof: command -t t1_to_t2 -t atlas_to_t1 "
            "maps output points T2->pre->atlas"
        ),
        "fine_source_labels_exposed": False,
        "interpolation": "GenericLabel",
        "engine": "ANTs",
        "engine_version": tools.version,
    }
    metadata_path = output / "composite_metadata.json"
    metadata_path.write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n")
    return AtlasCompositeOutput(
        source_major_labels_path=source_major,
        source_major_labels_sha256=sha256_file(source_major),
        labels_in_pre_t1_path=pre_labels,
        labels_in_pre_t1_sha256=sha256_file(pre_labels),
        labels_in_native_t2_path=t2_labels,
        labels_in_native_t2_sha256=sha256_file(t2_labels),
        atlas_support_in_native_t2_path=support_t2,
        atlas_support_in_native_t2_sha256=sha256_file(support_t2),
        command_record_paths=(pre_record, t2_record, support_record),
        metadata_path=metadata_path,
        metadata_sha256=sha256_file(metadata_path),
    )


def compute_native_t2_lesion_overlap(
    *,
    native_t2_path: Path,
    native_lesion_mask_path: Path,
    major_labels_in_t2_path: Path,
    atlas_support_in_t2_path: Path,
    scheme: MajorRegionScheme,
    approval_gate: MappingApprovalGate,
    reviewed_orientation: str,
    output_directory: Path,
    boundary_distance_mm: float = 0.5,
    ap_perturbation_mm: float = 0.5,
) -> MajorRegionLesionResult:
    """Measure overlap on the untouched lesion grid with physical AP stress tests."""

    approval_gate.require_overlap_eligible()
    if not scheme.approved:
        raise ValueError("Approved regional exports require an approved major-region scheme")
    output = output_directory.resolve()
    if output.exists():
        raise FileExistsError(f"Refusing to overwrite regional result: {output}")
    output.mkdir(parents=True)

    t2_geometry = inspect_nifti_geometry(native_t2_path)
    labels_geometry = inspect_nifti_geometry(major_labels_in_t2_path)
    lesion_geometry = inspect_nifti_geometry(native_lesion_mask_path)
    support_geometry = inspect_nifti_geometry(atlas_support_in_t2_path)
    for geometry, name in (
        (labels_geometry, "major labels"),
        (lesion_geometry, "native lesion mask"),
        (support_geometry, "atlas support"),
    ):
        require_same_physical_grid(
            t2_geometry,
            geometry,
            names=("native T2", name),
            affine_atol=1e-4,
        )
    lesion_sha256 = sha256_file(native_lesion_mask_path)
    lesion_image = nib.load(str(native_lesion_mask_path))
    lesion_raw = np.asanyarray(lesion_image.dataobj)
    if not set(float(value) for value in np.unique(lesion_raw)).issubset({0.0, 1.0}):
        raise ValueError("The native lesion artifact must be binary")
    lesion = lesion_raw != 0
    labels = np.asanyarray(nib.load(str(major_labels_in_t2_path)).dataobj)
    labels = validate_major_label_array(labels, scheme.allowed_major_region_ids)
    support = _require_binary_grid(
        atlas_support_in_t2_path, native_t2_path, "atlas support"
    )
    observed_orientation = "".join(nib.aff2axcodes(lesion_image.affine))
    if reviewed_orientation != observed_orientation:
        raise ValueError(
            "The reviewed orientation does not match the native T2 affine: "
            f"reviewed={reviewed_orientation}, observed={observed_orientation}"
        )
    if not any(code in {"A", "P"} for code in reviewed_orientation):
        raise ValueError("The reviewed orientation has no physical AP direction")

    spacing = tuple(float(value) for value in lesion_image.header.get_zooms()[:3])
    voxel_volume = float(abs(np.linalg.det(lesion_image.affine[:3, :3])))
    boundary = major_region_boundary(labels)
    distance = ndimage.distance_transform_edt(~boundary, sampling=spacing)
    boundary_lesion = lesion & (distance <= boundary_distance_mm)

    anterior = shift_labels_in_physical_ap(
        labels, lesion_image.affine, ap_perturbation_mm
    )
    posterior = shift_labels_in_physical_ap(
        labels, lesion_image.affine, -ap_perturbation_mm
    )
    nominal_counts = _lesion_counts(labels, lesion)
    anterior_counts = _lesion_counts(anterior, lesion)
    posterior_counts = _lesion_counts(posterior, lesion)
    nominal_dominant = _dominant_region(nominal_counts)
    perturbed_dominants = {
        _dominant_region(anterior_counts),
        _dominant_region(posterior_counts),
    }
    sensitivity_status = (
        "UNSTABLE_UNCERTAIN"
        if any(value != nominal_dominant for value in perturbed_dominants)
        else "STABLE_UNDER_AP_STRESS_TEST"
    )

    descriptors = _major_region_descriptors(scheme)
    rows: list[dict[str, object]] = []
    lesion_voxels = int(np.count_nonzero(lesion))
    for region_id in sorted(descriptors):
        descriptor = descriptors[region_id]
        region_voxels = int(np.count_nonzero(labels == region_id))
        overlap = nominal_counts.get(region_id, 0)
        rows.append(
            {
                "major_region_id": region_id,
                "major_region_acronym": descriptor[0],
                "major_region_name": descriptor[1],
                "hemisphere": descriptor[2],
                "acquired_region_voxels": region_voxels,
                "outside_acquired_fov": region_voxels == 0,
                "zero_overlap_in_acquired_fov": region_voxels > 0 and overlap == 0,
                "lesion_voxels": overlap,
                "lesion_volume_mm3": overlap * voxel_volume,
                "fraction_of_lesion": overlap / lesion_voxels if lesion_voxels else 0.0,
                "anterior_0_5mm_lesion_voxels": anterior_counts.get(region_id, 0),
                "posterior_0_5mm_lesion_voxels": posterior_counts.get(region_id, 0),
                "sensitivity_status": sensitivity_status,
                "mapping_version": scheme.mapping_version,
            }
        )
    result_csv = output / "major_region_lesion_overlap.csv"
    with result_csv.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    mapped = lesion & (labels != 0)
    outside_support = lesion & ~support
    metadata = {
        "scientific_status": "APPROVED_INPUTS_MAJOR_REGION_RESULT",
        "native_t2_sha256": sha256_file(native_t2_path),
        "native_lesion_sha256": lesion_sha256,
        "major_labels_sha256": sha256_file(major_labels_in_t2_path),
        "atlas_support_sha256": sha256_file(atlas_support_in_t2_path),
        "major_region_scheme_sha256": scheme.sha256,
        "major_region_mapping_version": scheme.mapping_version,
        "fine_labels_exposed": False,
        "native_lesion_resampled": False,
        "native_t2_orientation": reviewed_orientation,
        "voxel_volume_mm3": voxel_volume,
        "lesion_voxel_count": lesion_voxels,
        "lesion_volume_mm3": lesion_voxels * voxel_volume,
        "mapped_lesion_voxels": int(np.count_nonzero(mapped)),
        "unmapped_lesion_voxels": int(np.count_nonzero(lesion & ~mapped)),
        "outside_atlas_support_lesion_voxels": int(np.count_nonzero(outside_support)),
        "near_major_region_boundary_distance_mm": boundary_distance_mm,
        "near_major_region_boundary_lesion_voxels": int(
            np.count_nonzero(boundary_lesion)
        ),
        "ap_sensitivity_perturbation_mm": ap_perturbation_mm,
        "ap_sensitivity_is_confidence_interval": False,
        "nominal_dominant_region_id": nominal_dominant,
        "anterior_dominant_region_id": _dominant_region(anterior_counts),
        "posterior_dominant_region_id": _dominant_region(posterior_counts),
        "sensitivity_status": sensitivity_status,
    }
    metadata_path = output / "major_region_lesion_result.json"
    metadata_path.write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n")
    if sha256_file(native_lesion_mask_path) != lesion_sha256:
        raise ValueError("The native lesion mask changed during overlap calculation")
    return MajorRegionLesionResult(
        lesion_voxel_count=lesion_voxels,
        lesion_volume_mm3=lesion_voxels * voxel_volume,
        mapped_lesion_voxels=int(np.count_nonzero(mapped)),
        unmapped_lesion_voxels=int(np.count_nonzero(lesion & ~mapped)),
        outside_atlas_support_lesion_voxels=int(np.count_nonzero(outside_support)),
        boundary_lesion_voxels=int(np.count_nonzero(boundary_lesion)),
        nominal_dominant_region_id=nominal_dominant,
        sensitivity_status=sensitivity_status,
        result_csv_path=result_csv,
        result_csv_sha256=sha256_file(result_csv),
        metadata_path=metadata_path,
        metadata_sha256=sha256_file(metadata_path),
        lesion_sha256=lesion_sha256,
    )


def validate_major_label_volume(
    labels_path: Path,
    reference_path: Path,
    allowed_ids: frozenset[int],
) -> np.ndarray:
    require_same_physical_grid(
        inspect_nifti_geometry(reference_path),
        inspect_nifti_geometry(labels_path),
        names=("reference image", "propagated major labels"),
        affine_atol=1e-4,
    )
    return validate_major_label_array(
        np.asanyarray(nib.load(str(labels_path)).dataobj), allowed_ids
    )


def validate_major_label_array(
    labels: np.ndarray,
    allowed_ids: frozenset[int],
) -> np.ndarray:
    if not np.isfinite(labels).all() or not np.array_equal(labels, np.rint(labels)):
        raise ValueError("Propagated labels are not finite integers")
    integer = np.rint(labels).astype(np.int32)
    unexpected = sorted(set(int(value) for value in np.unique(integer)) - {0} - allowed_ids)
    if unexpected:
        raise ValueError(f"Fine or unknown labels leaked into major output: {unexpected}")
    return integer


def major_region_boundary(labels: np.ndarray) -> np.ndarray:
    boundary = np.zeros(labels.shape, dtype=bool)
    for axis in range(3):
        first = [slice(None)] * 3
        second = [slice(None)] * 3
        first[axis] = slice(0, -1)
        second[axis] = slice(1, None)
        left = labels[tuple(first)]
        right = labels[tuple(second)]
        different = (left != right) & (left != 0) & (right != 0)
        boundary[tuple(first)] |= different
        boundary[tuple(second)] |= different
    return boundary


def shift_labels_in_physical_ap(
    labels: np.ndarray,
    affine: np.ndarray,
    distance_mm: float,
) -> np.ndarray:
    """Shift label content along physical RAS anterior, independent of array axis."""

    axcodes = nib.aff2axcodes(affine)
    if not any(code in {"A", "P"} for code in axcodes):
        raise ValueError("Cannot derive the physical AP direction from the NIfTI affine")
    world_displacement = np.array([0.0, distance_mm, 0.0], dtype=np.float64)
    voxel_displacement = np.linalg.solve(affine[:3, :3], world_displacement)
    shifted = ndimage.shift(
        labels,
        shift=voxel_displacement,
        order=0,
        mode="constant",
        cval=0,
        prefilter=False,
    )
    return shifted.astype(labels.dtype, copy=False)


def compose_point_mapping_affines(
    atlas_to_pre_point_mapping: np.ndarray,
    pre_to_t2_point_mapping: np.ndarray,
) -> np.ndarray:
    """Compose ANTs output-point mappings as T2->pre->atlas."""

    first = np.asarray(atlas_to_pre_point_mapping, dtype=np.float64)
    second = np.asarray(pre_to_t2_point_mapping, dtype=np.float64)
    if first.shape != (4, 4) or second.shape != (4, 4):
        raise ValueError("Point-mapping affines must be 4x4")
    return first @ second


def _apply_labels(
    tools: AntsExecutables,
    runner: CommandRunner,
    *,
    input_path: Path,
    reference_path: Path,
    output_path: Path,
    transforms: tuple[Path, ...],
    record_path: Path,
) -> None:
    args: list[str] = [
        str(tools.apply_transforms),
        "--dimensionality",
        "3",
        "--input",
        str(input_path),
        "--reference-image",
        str(reference_path),
        "--output",
        str(output_path),
        "--interpolation",
        "GenericLabel",
        "--output-data-type",
        "int",
        "--default-value",
        "0",
    ]
    for transform in transforms:
        args.extend(("--transform", str(transform)))
    args.extend(("--float", "1", "--verbose", "1"))
    _run_and_record(
        runner,
        tuple(args),
        output_path.parent,
        record_path,
        engine_version=tools.version,
        expected_outputs=(output_path,),
    )


def _require_binary_grid(path: Path, reference: Path, label: str) -> np.ndarray:
    require_same_physical_grid(
        inspect_nifti_geometry(reference),
        inspect_nifti_geometry(path),
        names=("reference image", label),
        affine_atol=1e-4,
    )
    data = np.asanyarray(nib.load(str(path)).dataobj)
    if not set(float(value) for value in np.unique(data)).issubset({0.0, 1.0}):
        raise ValueError(f"The {label} must be binary")
    return data != 0


def _lesion_counts(labels: np.ndarray, lesion: np.ndarray) -> dict[int, int]:
    values, counts = np.unique(labels[lesion & (labels != 0)], return_counts=True)
    return {int(value): int(count) for value, count in zip(values, counts, strict=True)}


def _dominant_region(counts: dict[int, int]) -> int | None:
    if not counts:
        return None
    return min(counts, key=lambda key: (-counts[key], key))


def _major_region_descriptors(
    scheme: MajorRegionScheme,
) -> dict[int, tuple[str, str, str]]:
    descriptors: dict[int, tuple[str, str, str]] = {}
    for row in scheme.rows:
        value = (row.major_region_acronym, row.major_region_name, row.hemisphere)
        previous = descriptors.setdefault(row.major_region_id, value)
        if previous != value:
            raise ValueError("A major-region ID has inconsistent name or hemisphere")
    return descriptors
