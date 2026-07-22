"""Qt-free records for reviewed T1 registration and provisional enhancement."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from lys_bbb_app.domain.t2_lesion import ProcessingJobState


class T1RegistrationState(str, Enum):
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    APPROVED = "APPROVED"
    OUTDATED = "OUTDATED"


class T1EnhancementResultState(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    OUTDATED = "OUTDATED"


@dataclass(frozen=True)
class T1RegistrationMethodRecord:
    id: str
    active: bool
    method_version: str
    method_spec_sha256: str
    config: dict[str, Any]
    registered_at: str
    registered_by: str


@dataclass(frozen=True)
class T1RegistrationJobRecord:
    id: str
    state: ProcessingJobState
    stage: str | None
    progress_current: int | None
    progress_total: int | None
    method_id: str
    subject_ids: tuple[str, ...]
    submitted_at: str
    started_at: str | None
    finished_at: str | None
    error_message: str | None
    output_path: Path | None
    metadata: dict[str, Any]


@dataclass(frozen=True)
class T1RegistrationArtifactRecord:
    id: str
    subject_id: str
    state: T1RegistrationState
    version: int
    active: bool
    registered_post_path: Path
    registered_post_sha256: str
    transform_path: Path
    transform_sha256: str
    qc_preview_path: Path
    qc_preview_sha256: str
    source_pre_scan_input_id: str
    source_post_scan_input_id: str
    source_brain_mask_artifact_id: str
    method_id: str
    job_id: str
    before_xcorr: float
    after_xcorr: float
    registration_metric: float
    optimizer_stop: str
    created_at: str
    created_by: str
    superseded_by: str | None
    metadata: dict[str, Any]


@dataclass(frozen=True)
class T1RegistrationApprovalRecord:
    id: str
    subject_id: str
    artifact_id: str
    reviewer: str
    study_blinding_state: str
    created_at: str


@dataclass(frozen=True)
class T1RegistrationArtifactDraft:
    subject_id: str
    registered_post_path: Path
    registered_post_sha256: str
    transform_path: Path
    transform_sha256: str
    qc_preview_path: Path
    qc_preview_sha256: str
    source_pre_scan_input_id: str
    source_post_scan_input_id: str
    source_brain_mask_artifact_id: str
    before_xcorr: float
    after_xcorr: float
    registration_metric: float
    optimizer_stop: str
    metadata: dict[str, Any]


@dataclass(frozen=True)
class T1RegistrationReadiness:
    eligible_subject_ids: tuple[str, ...]
    blocked_reasons: tuple[tuple[str, str], ...]

    @property
    def eligible_count(self) -> int:
        return len(self.eligible_subject_ids)


@dataclass(frozen=True)
class T1EnhancementMethodRecord:
    id: str
    active: bool
    method_version: str
    method_spec_sha256: str
    scientific_status: str
    config: dict[str, Any]
    registered_at: str
    registered_by: str


@dataclass(frozen=True)
class T1EnhancementJobRecord:
    id: str
    state: ProcessingJobState
    stage: str | None
    progress_current: int | None
    progress_total: int | None
    method_id: str
    subject_ids: tuple[str, ...]
    submitted_at: str
    started_at: str | None
    finished_at: str | None
    error_message: str | None
    output_path: Path | None
    metadata: dict[str, Any]


@dataclass(frozen=True)
class T1EnhancementResultRecord:
    id: str
    subject_id: str
    version: int
    state: T1EnhancementResultState
    active: bool
    percent_enhancement_map: Path
    percent_enhancement_sha256: str
    summary_csv: Path
    summary_sha256: str
    qc_preview_path: Path
    qc_preview_sha256: str
    metadata_path: Path
    metadata_sha256: str
    source_registration_artifact_id: str
    source_brain_mask_artifact_id: str
    source_pre_scan_input_id: str
    method_id: str
    job_id: str
    metrics: tuple[dict[str, str], ...]
    metadata: dict[str, Any]
    created_at: str
    created_by: str
    outdated_at: str | None
    outdated_reason: str | None
    superseded_by: str | None


@dataclass(frozen=True)
class T1EnhancementResultDraft:
    subject_id: str
    percent_enhancement_map: Path
    percent_enhancement_sha256: str
    summary_csv: Path
    summary_sha256: str
    qc_preview_path: Path
    qc_preview_sha256: str
    metadata_path: Path
    metadata_sha256: str
    source_registration_artifact_id: str
    source_brain_mask_artifact_id: str
    source_pre_scan_input_id: str
    metrics: tuple[dict[str, str], ...]
    metadata: dict[str, Any]


@dataclass(frozen=True)
class T1EnhancementReadiness:
    eligible_subject_ids: tuple[str, ...]
    blocked_reasons: tuple[tuple[str, str], ...]

    @property
    def eligible_count(self) -> int:
        return len(self.eligible_subject_ids)
