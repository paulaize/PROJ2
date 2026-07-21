"""Immutable view models used by the desktop design preview."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class StatusValue:
    """User-facing state with a semantic colour role."""

    label: str
    kind: str = "neutral"


@dataclass(frozen=True)
class MetricViewModel:
    label: str
    value: str
    detail: str
    kind: str = "neutral"


@dataclass(frozen=True)
class WorkflowSummaryViewModel:
    key: str
    title: str
    description: str
    status: StatusValue
    facts: tuple[tuple[str, str], ...]
    action_label: str
    target_page: str


@dataclass(frozen=True)
class PriorityActionViewModel:
    label: str
    detail: str
    kind: str
    target_page: str


@dataclass(frozen=True)
class InputIssueViewModel:
    code: str
    severity: str
    message: str
    technical_detail: str | None = None


@dataclass(frozen=True)
class InputScanViewModel:
    scan_input_id: str
    role: str
    role_label: str
    version: int
    conversion: StatusValue
    validation: StatusValue
    managed_path: Path | None
    source_path: Path
    shape_text: str
    spacing_text: str
    orientation_text: str
    transformation_text: str
    checksum_text: str
    issues: tuple[InputIssueViewModel, ...]
    can_open: bool


@dataclass(frozen=True)
class T2LesionArtifactViewModel:
    artifact_id: str
    version: int
    state: StatusValue
    mask_path: Path
    probability_path: Path
    qc_preview_path: Path | None
    lesion_voxel_count: int
    provisional_volume_text: str
    threshold_text: str
    release_label: str
    device: str
    created_at: str
    source_scan_input_id: str
    origin_label: str
    can_correct: bool
    can_review: bool
    official_volume_text: str | None = None
    reviewer: str | None = None
    reviewed_at: str | None = None


@dataclass(frozen=True)
class SubjectViewModel:
    subject_id: str
    group: str | None
    t1_data: StatusValue
    brain_mask: StatusValue
    registration: StatusValue
    t1_result: StatusValue
    t2_data: StatusValue
    t2_lesion: StatusValue
    overall: StatusValue
    updated: str
    metadata: tuple[tuple[str, str], ...] = ()
    history: tuple[str, ...] = ()
    display_id: str | None = None
    mri_input_count: int = 0
    inputs: tuple[InputScanViewModel, ...] = ()
    can_validate_inputs: bool = False
    t2_artifact: T2LesionArtifactViewModel | None = None
    can_run_t2_inference: bool = False
    t2_inference_blocked_reason: str | None = None
    t2_release_label: str | None = None

    @property
    def label(self) -> str:
        return self.display_id or self.subject_id


@dataclass(frozen=True)
class ReviewItemViewModel:
    review_id: str
    subject_id: str
    category: str
    artifact_name: str
    reason: str
    automatic_qc: str
    status: StatusValue
    slice_count: int = 30


@dataclass(frozen=True)
class ResultViewModel:
    subject_id: str
    group: str | None
    t1_value: str
    t1_state: StatusValue
    t2_value: str
    t2_state: StatusValue
    method_version: str


@dataclass(frozen=True)
class StudyViewModel:
    study_id: str
    name: str
    root_path: Path | None
    description: str
    schema_version: int
    last_opened: str
    is_demo: bool
    metrics: tuple[MetricViewModel, ...]
    workflows: tuple[WorkflowSummaryViewModel, ...]
    priority_actions: tuple[PriorityActionViewModel, ...]
    subjects: tuple[SubjectViewModel, ...]
    reviews: tuple[ReviewItemViewModel, ...]
    results: tuple[ResultViewModel, ...]
    blinded_review: bool = True
    group_definitions: tuple[str, ...] = ()
    archived_subjects: tuple[SubjectViewModel, ...] = ()
    mri_input_folder: Path | None = None
    t1_input_folder: Path | None = None
    t2_input_folder: Path | None = None
    active_t2_release_label: str | None = None
    t2_eligible_subject_count: int = 0
    t2_running_job_count: int = 0

    def subject(self, subject_id: str) -> SubjectViewModel | None:
        return next(
            (subject for subject in self.subjects if subject.subject_id == subject_id),
            None,
        )
