"""Immutable AIDAmri atlas resource and major-region mapping contracts."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

import nibabel as nib
import numpy as np

from lys_bbb.hashing import sha256_file


AIDAMRI_REVISION = "3408ed46ea097f9fff5adbcdd7da6da6102f283a"
AIDAMRI_RELEASE_VERSION = "aidamri_mri_allen_bridge_v1"
AIDAMRI_TEMPLATE_SHA256 = (
    "f1bc07b507fe260c3f48c3bc48a58ec1492aa45b0e24133665fbe77bab01b65a"
)
AIDAMRI_LABELS_SHA256 = (
    "9b7951f4bc61838ed6cbd2611ab4542d3acf11e849856d9a5aaf5552ceafeec4"
)
AIDAMRI_LOOKUP_SHA256 = (
    "8d62af8b9f961fbc3bd9b276b22898d936d72f856a4e340aff2683d1012b9279"
)
MAJOR_REGION_COLUMNS = (
    "source_label_id",
    "major_region_id",
    "major_region_acronym",
    "major_region_name",
    "hemisphere",
    "mapping_version",
    "mapping_status",
)


@dataclass(frozen=True)
class NiftiGeometry:
    shape: tuple[int, int, int]
    spacing_mm: tuple[float, float, float]
    affine: tuple[tuple[float, ...], ...]
    orientation: str
    qform_code: int
    sform_code: int
    qform: tuple[tuple[float, ...], ...] | None
    sform: tuple[tuple[float, ...], ...] | None
    physical_bounds_mm: tuple[tuple[float, float], ...]
    physical_extent_mm: tuple[float, float, float]
    determinant: float

    @property
    def handedness(self) -> str:
        return "right" if self.determinant > 0 else "left"


@dataclass(frozen=True)
class AtlasReleaseSpec:
    template_path: Path
    labels_path: Path
    source_lookup_path: Path
    template_mask_path: Path
    release_version: str = AIDAMRI_RELEASE_VERSION
    revision: str = AIDAMRI_REVISION
    template_sha256: str = AIDAMRI_TEMPLATE_SHA256
    labels_sha256: str = AIDAMRI_LABELS_SHA256
    source_lookup_sha256: str = AIDAMRI_LOOKUP_SHA256
    template_mask_sha256: str | None = None


@dataclass(frozen=True)
class ValidatedAtlasRelease:
    spec: AtlasReleaseSpec
    template_geometry: NiftiGeometry
    label_ids: tuple[int, ...]
    source_lookup_rows: tuple[dict[str, str], ...]
    template_mask_sha256: str


@dataclass(frozen=True)
class MajorRegionRow:
    source_label_id: int
    major_region_id: int
    major_region_acronym: str
    major_region_name: str
    hemisphere: str
    mapping_version: str
    mapping_status: str


@dataclass(frozen=True)
class MajorRegionScheme:
    path: Path
    sha256: str
    mapping_version: str
    rows: tuple[MajorRegionRow, ...]
    approved: bool

    @property
    def allowed_major_region_ids(self) -> frozenset[int]:
        return frozenset(row.major_region_id for row in self.rows)


def create_annotation_support_template_mask(
    labels_path: Path,
    output_path: Path,
) -> tuple[Path, str]:
    """Create a separate, explicit registration mask from annotation support."""

    if output_path.exists():
        raise FileExistsError(f"Refusing to overwrite atlas-template mask: {output_path}")
    image = nib.load(str(labels_path))
    labels = np.asanyarray(image.dataobj)
    if not np.isfinite(labels).all() or not np.array_equal(labels, np.rint(labels)):
        raise ValueError("Atlas labels must be finite integers before mask creation")
    support = labels != 0
    if not support.any():
        raise ValueError("Atlas annotation has no nonzero support")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    header = image.header.copy()
    header.set_data_dtype(np.uint8)
    nib.save(
        nib.Nifti1Image(support.astype(np.uint8), image.affine, header),
        str(output_path),
    )
    return output_path, sha256_file(output_path)


def inspect_nifti_geometry(path: Path) -> NiftiGeometry:
    """Inspect a finite, nonsingular 3-D NIfTI without changing its header."""

    image = nib.load(str(path))
    if len(image.shape) != 3:
        raise ValueError(f"Expected a 3-D NIfTI: {path}")
    affine = np.asarray(image.affine, dtype=np.float64)
    if not np.isfinite(affine).all():
        raise ValueError(f"NIfTI affine contains non-finite values: {path}")
    determinant = float(np.linalg.det(affine[:3, :3]))
    if not np.isfinite(determinant) or determinant == 0:
        raise ValueError(f"NIfTI affine is singular: {path}")
    qform, qform_code = image.header.get_qform(coded=True)
    sform, sform_code = image.header.get_sform(coded=True)
    if qform_code and sform_code and not np.allclose(
        qform, sform, rtol=1e-5, atol=1e-5
    ):
        raise ValueError(f"NIfTI qform and sform disagree: {path}")
    corners = np.array(
        [
            (i, j, k)
            for i in (0, image.shape[0] - 1)
            for j in (0, image.shape[1] - 1)
            for k in (0, image.shape[2] - 1)
        ],
        dtype=np.float64,
    )
    physical_corners = nib.affines.apply_affine(affine, corners)
    minima = physical_corners.min(axis=0)
    maxima = physical_corners.max(axis=0)
    return NiftiGeometry(
        shape=tuple(int(value) for value in image.shape),
        spacing_mm=tuple(float(value) for value in image.header.get_zooms()[:3]),
        affine=tuple(tuple(float(value) for value in row) for row in affine),
        orientation="".join(nib.aff2axcodes(affine)),
        qform_code=int(qform_code),
        sform_code=int(sform_code),
        qform=(
            tuple(tuple(float(value) for value in row) for row in qform)
            if qform_code
            else None
        ),
        sform=(
            tuple(tuple(float(value) for value in row) for row in sform)
            if sform_code
            else None
        ),
        physical_bounds_mm=tuple(
            (float(low), float(high))
            for low, high in zip(minima, maxima, strict=True)
        ),
        physical_extent_mm=tuple(float(value) for value in maxima - minima),
        determinant=determinant,
    )


def require_same_physical_grid(
    first: NiftiGeometry,
    second: NiftiGeometry,
    *,
    names: tuple[str, str],
    affine_atol: float = 1e-5,
) -> None:
    if first.shape != second.shape:
        raise ValueError(f"{names[0]} and {names[1]} shapes differ")
    if not np.allclose(first.spacing_mm, second.spacing_mm, atol=1e-6, rtol=1e-5):
        raise ValueError(f"{names[0]} and {names[1]} spacing differs")
    if not np.allclose(first.affine, second.affine, atol=affine_atol, rtol=1e-6):
        raise ValueError(f"{names[0]} and {names[1]} affines differ")
    if first.handedness != second.handedness:
        raise ValueError(f"{names[0]} and {names[1]} handedness differs")


def validate_atlas_release(spec: AtlasReleaseSpec) -> ValidatedAtlasRelease:
    """Reverify every external resource and its complete source-label lookup."""

    expected = (
        (spec.template_path, spec.template_sha256, "template"),
        (spec.labels_path, spec.labels_sha256, "annotation"),
        (spec.source_lookup_path, spec.source_lookup_sha256, "lookup"),
    )
    for path, digest, label in expected:
        if not path.is_file():
            raise FileNotFoundError(f"AIDAmri {label} is unavailable: {path}")
        observed = sha256_file(path)
        if observed != digest:
            raise ValueError(
                f"AIDAmri {label} checksum changed: expected {digest}, got {observed}"
            )
    if spec.revision != AIDAMRI_REVISION:
        raise ValueError("The AIDAmri revision is not the reviewed MVP revision")

    template_geometry = inspect_nifti_geometry(spec.template_path)
    labels_geometry = inspect_nifti_geometry(spec.labels_path)
    require_same_physical_grid(
        template_geometry,
        labels_geometry,
        names=("AIDAmri template", "AIDAmri annotation"),
    )
    labels_data = np.asanyarray(nib.load(str(spec.labels_path)).dataobj)
    rounded = np.rint(labels_data)
    if not np.isfinite(labels_data).all() or not np.array_equal(labels_data, rounded):
        raise ValueError("AIDAmri annotation contains non-integer or non-finite labels")
    label_ids = tuple(sorted(int(value) for value in np.unique(rounded) if value != 0))

    with spec.source_lookup_path.open(newline="", encoding="utf-8-sig") as handle:
        lookup_rows = tuple(csv.DictReader(handle))
    required = {"label_id", "acronym", "name", "hemisphere"}
    if not lookup_rows or not required.issubset(lookup_rows[0]):
        raise ValueError("AIDAmri lookup is missing required columns")
    lookup_ids = [int(row["label_id"]) for row in lookup_rows]
    if len(lookup_ids) != len(set(lookup_ids)):
        raise ValueError("AIDAmri lookup contains duplicate source labels")
    missing = sorted(set(label_ids) - set(lookup_ids))
    extra = sorted(set(lookup_ids) - set(label_ids))
    if missing or extra:
        raise ValueError(
            "AIDAmri lookup and annotation labels are incomplete: "
            f"missing={missing}, extra={extra}"
        )

    if not spec.template_mask_path.is_file():
        raise FileNotFoundError(
            "A separate atlas-template registration mask is required: "
            f"{spec.template_mask_path}"
        )
    mask_sha256 = sha256_file(spec.template_mask_path)
    if spec.template_mask_sha256 is not None and mask_sha256 != spec.template_mask_sha256:
        raise ValueError("The atlas-template mask checksum changed")
    mask_geometry = inspect_nifti_geometry(spec.template_mask_path)
    require_same_physical_grid(
        template_geometry,
        mask_geometry,
        names=("AIDAmri template", "atlas-template mask"),
    )
    mask_data = np.asanyarray(nib.load(str(spec.template_mask_path)).dataobj)
    values = set(float(value) for value in np.unique(mask_data))
    if not values.issubset({0.0, 1.0}) or 1.0 not in values:
        raise ValueError("The atlas-template mask must be non-empty and binary")
    return ValidatedAtlasRelease(
        spec=spec,
        template_geometry=template_geometry,
        label_ids=label_ids,
        source_lookup_rows=lookup_rows,
        template_mask_sha256=mask_sha256,
    )


def load_major_region_scheme(
    path: Path,
    *,
    source_label_ids: tuple[int, ...],
    approved: bool,
) -> MajorRegionScheme:
    """Load a complete collapse table; scientific approval is supplied separately."""

    if not path.is_file():
        raise FileNotFoundError(f"Major-region mapping is unavailable: {path}")
    with path.open(newline="", encoding="utf-8-sig") as handle:
        raw_rows = tuple(csv.DictReader(handle))
    if not raw_rows or not set(MAJOR_REGION_COLUMNS).issubset(raw_rows[0]):
        raise ValueError("Major-region mapping is missing required columns")
    rows: list[MajorRegionRow] = []
    for raw in raw_rows:
        hemisphere = raw["hemisphere"].strip().lower()
        if hemisphere not in {"left", "right"}:
            raise ValueError("Major-region hemisphere must be left or right")
        row = MajorRegionRow(
            source_label_id=int(raw["source_label_id"]),
            major_region_id=int(raw["major_region_id"]),
            major_region_acronym=raw["major_region_acronym"].strip(),
            major_region_name=raw["major_region_name"].strip(),
            hemisphere=hemisphere,
            mapping_version=raw["mapping_version"].strip(),
            mapping_status=raw["mapping_status"].strip(),
        )
        if row.major_region_id <= 0:
            raise ValueError("Major-region IDs must be positive")
        if not row.major_region_acronym or not row.major_region_name:
            raise ValueError("Major-region names and acronyms cannot be blank")
        rows.append(row)
    source_ids = [row.source_label_id for row in rows]
    if len(source_ids) != len(set(source_ids)):
        raise ValueError("Major-region mapping contains duplicate source labels")
    missing = sorted(set(source_label_ids) - set(source_ids))
    extra = sorted(set(source_ids) - set(source_label_ids))
    if missing or extra:
        raise ValueError(
            "Major-region source-label mapping is incomplete: "
            f"missing={missing}, extra={extra}"
        )
    versions = {row.mapping_version for row in rows}
    if len(versions) != 1:
        raise ValueError("Major-region mapping must contain one version")
    if approved and any(row.mapping_status != "PROPOSED" for row in rows):
        raise ValueError("Only the exact reviewed proposed mapping can be approved")
    return MajorRegionScheme(
        path=path,
        sha256=sha256_file(path),
        mapping_version=next(iter(versions)),
        rows=tuple(rows),
        approved=approved,
    )
