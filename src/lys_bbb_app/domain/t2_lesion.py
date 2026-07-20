"""Qt-free records for frozen T2 inference jobs and draft lesion artifacts."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any


class ProcessingJobState(str, Enum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    INTERRUPTED = "INTERRUPTED"


class ArtifactState(str, Enum):
    DRAFT_REVIEW_REQUIRED = "DRAFT_REVIEW_REQUIRED"
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
class T2InferenceReadiness:
    eligible_subject_ids: tuple[str, ...]
    blocked_reasons: tuple[tuple[str, str], ...]

    @property
    def eligible_count(self) -> int:
        return len(self.eligible_subject_ids)
