"""Qt-free records for T2 inference, artifact review, and approved results."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any


T2_LESION_MASK_ARTIFACT_TYPE = "T2_LESION_MASK"
T2_LESION_VOLUME_RESULT_TYPE = "T2_LESION_VOLUME"
T2_NATIVE_VOLUME_METHOD_VERSION = "native_binary_mask_volume_v1"
class ProcessingJobState(str, Enum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    INTERRUPTED = "INTERRUPTED"


class ArtifactState(str, Enum):
    DRAFT_REVIEW_REQUIRED = "DRAFT_REVIEW_REQUIRED"
    CORRECTED_REVIEW_REQUIRED = "CORRECTED_REVIEW_REQUIRED"
    APPROVED = "APPROVED"
    OUTDATED = "OUTDATED"


class ResultState(str, Enum):
    APPROVED = "APPROVED"
    OUTDATED = "OUTDATED"


@dataclass(frozen=True)
class T2ModelReleaseRecord:
    id: str
    name: str
    version: str
    root_path: Path
    active: bool
    architecture: str
    threshold: float
    expected_spacing_mm: tuple[float, float, float]
    model_sha256: tuple[str, ...]
    manifest_sha256: str
    frozen_spec_sha256: str
    threshold_sha256: str
    project_git_commit: str
    ratlesnetv2_git_commit: str
    metadata: dict[str, Any]
    validated_at: str
    validated_by: str


@dataclass(frozen=True)
class ProcessingJobRecord:
    id: str
    job_type: str
    state: ProcessingJobState
    stage: str | None
    progress_current: int | None
    progress_total: int | None
    model_release_id: str | None
    subject_ids: tuple[str, ...]
    submitted_at: str
    started_at: str | None
    finished_at: str | None
    error_message: str | None
    output_path: Path | None
    metadata: dict[str, Any]


@dataclass(frozen=True)
class T2LesionArtifactRecord:
    id: str
    subject_id: str
    artifact_type: str
    origin: str
    state: ArtifactState
    version: int
    active: bool
    mask_path: Path
    mask_sha256: str
    probability_path: Path
    probability_sha256: str
    qc_preview_path: Path | None
    source_scan_input_id: str
    model_release_id: str
    job_id: str
    lesion_voxel_count: int
    provisional_volume_mm3: float
    threshold: float
    device: str
    created_at: str
    created_by: str
    superseded_by: str | None
    metadata: dict[str, Any]


@dataclass(frozen=True)
class T2ApprovalRecord:
    id: str
    subject_id: str
    artifact_id: str
    reviewer: str
    study_blinding_state: str
    created_at: str


@dataclass(frozen=True)
class T2LesionResultRecord:
    id: str
    subject_id: str
    version: int
    state: ResultState
    active: bool
    lesion_voxel_count: int
    lesion_volume_mm3: float
    unit: str
    method_version: str
    source_artifact_id: str
    source_scan_input_id: str
    model_release_id: str
    mask_sha256: str
    reviewer: str
    created_at: str
    approved_at: str
    outdated_at: str | None
    outdated_reason: str | None
    superseded_by: str | None
    metadata: dict[str, Any]


@dataclass(frozen=True)
class T2ArtifactDraft:
    subject_id: str
    source_scan_input_id: str
    mask_path: Path
    mask_sha256: str
    probability_path: Path
    probability_sha256: str
    qc_preview_path: Path | None
    lesion_voxel_count: int
    provisional_volume_mm3: float
    threshold: float
    device: str
    metadata: dict[str, Any]


@dataclass(frozen=True)
class T2CorrectedArtifactDraft:
    subject_id: str
    source_artifact_id: str
    mask_path: Path
    mask_sha256: str
    qc_preview_path: Path | None
    lesion_voxel_count: int
    provisional_volume_mm3: float
    imported_from: Path
    metadata: dict[str, Any]


@dataclass(frozen=True)
class T2InferenceReadiness:
    eligible_subject_ids: tuple[str, ...]
    blocked_reasons: tuple[tuple[str, str], ...]

    @property
    def eligible_count(self) -> int:
        return len(self.eligible_subject_ids)
