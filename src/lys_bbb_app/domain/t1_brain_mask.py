"""Qt-free records for persistent T1 brain-mask generation and review."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from lys_bbb_app.domain.t2_lesion import ArtifactState, ProcessingJobState


T1_BRAIN_MASK_METHOD_VERSION = "rs2net_m_seam_continuity_v1"
T1_BRAIN_MASK_APP_GENERATION_METHOD_VERSION = (
    "rs2net_m_seam_continuity_no_tta_local_draft_v1"
)


@dataclass(frozen=True)
class T1BrainMaskReleaseRecord:
    id: str
    root_path: Path
    active: bool
    source_commit: str
    weights_sha256: str
    manifest_sha256: str
    test_time_augmentation: bool
    method_version: str
    method_spec_sha256: str
    metadata: dict[str, Any]
    validated_at: str
    validated_by: str


@dataclass(frozen=True)
class T1BrainMaskJobRecord:
    id: str
    state: ProcessingJobState
    stage: str | None
    progress_current: int | None
    progress_total: int | None
    release_id: str
    subject_ids: tuple[str, ...]
    submitted_at: str
    started_at: str | None
    finished_at: str | None
    error_message: str | None
    output_path: Path | None
    metadata: dict[str, Any]


@dataclass(frozen=True)
class T1BrainMaskArtifactRecord:
    id: str
    subject_id: str
    origin: str
    state: ArtifactState
    version: int
    active: bool
    mask_path: Path
    mask_sha256: str
    raw_mask_path: Path | None
    raw_mask_sha256: str | None
    qc_preview_path: Path | None
    source_scan_input_id: str
    release_id: str
    job_id: str
    foreground_voxels: int
    volume_mm3: float
    device: str
    regularity_warnings: tuple[str, ...]
    created_at: str
    created_by: str
    superseded_by: str | None
    metadata: dict[str, Any]


@dataclass(frozen=True)
class T1BrainMaskApprovalRecord:
    id: str
    subject_id: str
    artifact_id: str
    reviewer: str
    study_blinding_state: str
    created_at: str


@dataclass(frozen=True)
class T1BrainMaskArtifactDraft:
    subject_id: str
    source_scan_input_id: str
    mask_path: Path
    mask_sha256: str
    raw_mask_path: Path
    raw_mask_sha256: str
    qc_preview_path: Path | None
    foreground_voxels: int
    volume_mm3: float
    device: str
    regularity_warnings: tuple[str, ...]
    metadata: dict[str, Any]


@dataclass(frozen=True)
class T1CorrectedBrainMaskDraft:
    subject_id: str
    source_artifact_id: str
    mask_path: Path
    mask_sha256: str
    qc_preview_path: Path | None
    foreground_voxels: int
    volume_mm3: float
    imported_from: Path
    metadata: dict[str, Any]


@dataclass(frozen=True)
class T1BrainMaskReadiness:
    eligible_subject_ids: tuple[str, ...]
    blocked_reasons: tuple[tuple[str, str], ...]

    @property
    def eligible_count(self) -> int:
        return len(self.eligible_subject_ids)
