"""Qt-free immutable records for the atlas-mapping vertical slice."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from lys_bbb_app.domain.t2_lesion import ProcessingJobState


class AtlasReviewState(str, Enum):
    DRAFT_REVIEW_REQUIRED = "DRAFT_REVIEW_REQUIRED"
    APPROVED = "APPROVED"
    OUTDATED = "OUTDATED"


@dataclass(frozen=True)
class AtlasReleaseRecord:
    id: str
    active: bool
    release_version: str
    aidamri_revision: str
    template_path: Path
    template_sha256: str
    labels_path: Path
    labels_sha256: str
    source_lookup_path: Path
    source_lookup_sha256: str
    template_mask_path: Path
    template_mask_sha256: str
    geometry: dict[str, Any]
    registered_at: str
    registered_by: str


@dataclass(frozen=True)
class MajorRegionSchemeRecord:
    id: str
    active: bool
    state: AtlasReviewState
    mapping_version: str
    mapping_path: Path
    mapping_sha256: str
    source_label_count: int
    major_region_count: int
    registered_at: str
    registered_by: str
    reviewer: str | None
    reviewed_at: str | None


@dataclass(frozen=True)
class T2RegistrationSupportMaskRecord:
    id: str
    subject_id: str
    active: bool
    state: AtlasReviewState
    version: int
    mask_path: Path
    mask_sha256: str
    source_t2_scan_input_id: str
    created_at: str
    created_by: str
    reviewer: str | None
    reviewed_at: str | None


@dataclass(frozen=True)
class AtlasMappingMethodRecord:
    id: str
    active: bool
    method_version: str
    method_spec_sha256: str
    config: dict[str, Any]
    registered_at: str
    registered_by: str


@dataclass(frozen=True)
class AtlasMappingJobRecord:
    id: str
    subject_id: str
    state: ProcessingJobState
    stage: str
    progress_current: int | None
    progress_total: int | None
    method_id: str
    submitted_at: str
    started_at: str | None
    finished_at: str | None
    error_message: str | None
    output_path: Path | None
    metadata: dict[str, Any]


@dataclass(frozen=True)
class AtlasToT1ArtifactRecord:
    id: str
    subject_id: str
    active: bool
    state: AtlasReviewState
    candidate: str
    transform_path: Path
    transform_sha256: str
    warped_intensity_path: Path
    warped_intensity_sha256: str
    warped_support_path: Path
    warped_support_sha256: str
    qc_path: Path
    qc_sha256: str
    metadata_path: Path
    metadata_sha256: str
    source_pre_scan_input_id: str
    source_t1_mask_artifact_id: str
    atlas_release_id: str
    method_id: str
    job_id: str
    created_at: str
    selected_by_review: bool
    reviewer: str | None
    reviewed_at: str | None


@dataclass(frozen=True)
class T1ToT2ArtifactRecord:
    id: str
    subject_id: str
    active: bool
    state: AtlasReviewState
    transform_path: Path
    transform_sha256: str
    transformed_t1_path: Path
    transformed_t1_sha256: str
    transformed_t1_mask_path: Path
    transformed_t1_mask_sha256: str
    qc_montage_path: Path
    qc_montage_sha256: str
    qc_manifest_path: Path
    qc_manifest_sha256: str
    qc_slice_paths: tuple[Path, ...]
    metadata_path: Path
    metadata_sha256: str
    source_pre_scan_input_id: str
    source_t2_scan_input_id: str
    source_t1_mask_artifact_id: str
    source_t2_support_mask_id: str
    lesion_exclusion_artifact_id: str | None
    lesion_exclusion_sha256: str | None
    method_id: str
    job_id: str
    created_at: str
    reviewer: str | None
    reviewed_at: str | None


@dataclass(frozen=True)
class AtlasInT2CompositeRecord:
    id: str
    subject_id: str
    active: bool
    state: AtlasReviewState
    labels_path: Path
    labels_sha256: str
    support_path: Path
    support_sha256: str
    qc_montage_path: Path
    qc_montage_sha256: str
    qc_manifest_path: Path
    qc_manifest_sha256: str
    qc_slice_paths: tuple[Path, ...]
    metadata_path: Path
    metadata_sha256: str
    source_atlas_to_t1_artifact_id: str
    source_t1_to_t2_artifact_id: str
    atlas_release_id: str
    major_region_scheme_id: str
    source_t2_scan_input_id: str
    created_at: str
    reviewer: str | None
    reviewed_at: str | None


@dataclass(frozen=True)
class MajorRegionLesionResultRecord:
    id: str
    subject_id: str
    active: bool
    state: AtlasReviewState
    result_csv_path: Path
    result_csv_sha256: str
    metadata_path: Path
    metadata_sha256: str
    lesion_voxel_count: int
    lesion_volume_mm3: float
    mapped_lesion_voxels: int
    unmapped_lesion_voxels: int
    outside_atlas_support_lesion_voxels: int
    boundary_lesion_voxels: int
    sensitivity_status: str
    source_composite_artifact_id: str
    source_lesion_artifact_id: str
    source_lesion_sha256: str
    major_region_scheme_id: str
    created_at: str


@dataclass(frozen=True)
class AtlasMappingState:
    release: AtlasReleaseRecord | None
    scheme: MajorRegionSchemeRecord | None
    t2_support_mask: T2RegistrationSupportMaskRecord | None
    atlas_to_t1_candidates: tuple[AtlasToT1ArtifactRecord, ...]
    selected_atlas_to_t1: AtlasToT1ArtifactRecord | None
    t1_to_t2: T1ToT2ArtifactRecord | None
    composite: AtlasInT2CompositeRecord | None
    result: MajorRegionLesionResultRecord | None
    jobs: tuple[AtlasMappingJobRecord, ...]
