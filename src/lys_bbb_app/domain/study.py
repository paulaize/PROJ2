"""Qt-free domain records and requests for persistent desktop studies."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from lys_bbb_app.domain.scan_import import ScanInputRecord
from lys_bbb_app.domain.t1_brain_mask import (
    T1BrainMaskApprovalRecord,
    T1BrainMaskArtifactRecord,
    T1BrainMaskJobRecord,
    T1BrainMaskReleaseRecord,
)
from lys_bbb_app.domain.t1_analysis import (
    T1EnhancementJobRecord,
    T1EnhancementMethodRecord,
    T1EnhancementResultRecord,
    T1RegistrationApprovalRecord,
    T1RegistrationArtifactRecord,
    T1RegistrationJobRecord,
    T1RegistrationMethodRecord,
)
from lys_bbb_app.domain.t2_lesion import (
    ProcessingJobRecord,
    T2LesionArtifactRecord,
    T2LesionResultRecord,
    T2ModelReleaseRecord,
    T2ApprovalRecord,
)
from lys_bbb_app.domain.atlas_mapping import AtlasMappingState


LEGACY_PROJECT_FILE_SUFFIX = ".lysbbb"


class BlindingState(str, Enum):
    """One-way review blinding state for a study."""

    BLINDED = "BLINDED"
    UNBLINDED = "UNBLINDED"


@dataclass(frozen=True)
class SubjectRecord:
    id: str
    subject_code: str
    group_name: str | None
    metadata: dict[str, Any]
    expected_t1: bool
    expected_t2: bool
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class AuditEventRecord:
    id: str
    event_type: str
    actor: str
    created_at: str
    subject_id: str | None
    details: dict[str, Any]


@dataclass(frozen=True)
class LegacyProjectRecord:
    """Read-only summary of a schema-v1 project awaiting migration."""

    project_id: str
    name: str
    database_path: Path
    schema_version: int


@dataclass(frozen=True)
class RecentStudy:
    """Small launcher-facing record stored outside the scientific study database."""

    name: str
    path: str
    last_opened: str


@dataclass(frozen=True)
class StudySnapshot:
    id: str
    identifier: str
    name: str
    description: str | None
    root_path: Path
    database_path: Path
    schema_version: int
    blinding_state: BlindingState
    created_at: str
    updated_at: str
    unblinded_at: str | None
    unblinded_by: str | None
    subjects: tuple[SubjectRecord, ...]
    scan_inputs: tuple[ScanInputRecord, ...]
    group_definitions: tuple[str, ...]
    model_releases: tuple[T2ModelReleaseRecord, ...] = ()
    processing_jobs: tuple[ProcessingJobRecord, ...] = ()
    artifacts: tuple[T2LesionArtifactRecord, ...] = ()
    reviews: tuple[T2ApprovalRecord, ...] = ()
    results: tuple[T2LesionResultRecord, ...] = ()
    t1_brain_mask_releases: tuple[T1BrainMaskReleaseRecord, ...] = ()
    t1_brain_mask_jobs: tuple[T1BrainMaskJobRecord, ...] = ()
    t1_brain_mask_artifacts: tuple[T1BrainMaskArtifactRecord, ...] = ()
    t1_brain_mask_approvals: tuple[T1BrainMaskApprovalRecord, ...] = ()
    t1_registration_methods: tuple[T1RegistrationMethodRecord, ...] = ()
    t1_registration_jobs: tuple[T1RegistrationJobRecord, ...] = ()
    t1_registration_artifacts: tuple[T1RegistrationArtifactRecord, ...] = ()
    t1_registration_approvals: tuple[T1RegistrationApprovalRecord, ...] = ()
    t1_enhancement_methods: tuple[T1EnhancementMethodRecord, ...] = ()
    t1_enhancement_jobs: tuple[T1EnhancementJobRecord, ...] = ()
    t1_enhancement_results: tuple[T1EnhancementResultRecord, ...] = ()
    atlas_mapping_states: tuple[tuple[str, AtlasMappingState], ...] = ()
    archived_subjects: tuple[SubjectRecord, ...] = ()
    mri_input_folder: Path | None = None
    t1_input_folder: Path | None = None
    t2_input_folder: Path | None = None

    @property
    def is_blinded(self) -> bool:
        return self.blinding_state is BlindingState.BLINDED

    def subject(self, subject_id: str) -> SubjectRecord | None:
        return next(
            (subject for subject in self.subjects if subject.id == subject_id),
            None,
        )

    def inputs_for_subject(self, subject_id: str) -> tuple[ScanInputRecord, ...]:
        return tuple(
            record for record in self.scan_inputs if record.subject_id == subject_id
        )

    def t2_artifacts_for_subject(
        self,
        subject_id: str,
    ) -> tuple[T2LesionArtifactRecord, ...]:
        return tuple(
            artifact for artifact in self.artifacts if artifact.subject_id == subject_id
        )

    def t1_brain_masks_for_subject(
        self,
        subject_id: str,
    ) -> tuple[T1BrainMaskArtifactRecord, ...]:
        return tuple(
            artifact
            for artifact in self.t1_brain_mask_artifacts
            if artifact.subject_id == subject_id
        )

    def t1_brain_mask_approval_for_artifact(
        self,
        artifact_id: str,
    ) -> T1BrainMaskApprovalRecord | None:
        return next(
            (
                approval
                for approval in self.t1_brain_mask_approvals
                if approval.artifact_id == artifact_id
            ),
            None,
        )

    def t1_registrations_for_subject(
        self,
        subject_id: str,
    ) -> tuple[T1RegistrationArtifactRecord, ...]:
        return tuple(
            artifact
            for artifact in self.t1_registration_artifacts
            if artifact.subject_id == subject_id
        )

    def t1_registration_approval_for_artifact(
        self,
        artifact_id: str,
    ) -> T1RegistrationApprovalRecord | None:
        return next(
            (
                approval
                for approval in self.t1_registration_approvals
                if approval.artifact_id == artifact_id
            ),
            None,
        )

    def t1_enhancement_results_for_subject(
        self,
        subject_id: str,
    ) -> tuple[T1EnhancementResultRecord, ...]:
        return tuple(
            result
            for result in self.t1_enhancement_results
            if result.subject_id == subject_id
        )

    def active_t1_enhancement_result_for_subject(
        self,
        subject_id: str,
    ) -> T1EnhancementResultRecord | None:
        return next(
            (
                result
                for result in self.t1_enhancement_results
                if result.subject_id == subject_id and result.active
            ),
            None,
        )

    def atlas_mapping_for_subject(self, subject_id: str) -> AtlasMappingState | None:
        return next(
            (state for identifier, state in self.atlas_mapping_states if identifier == subject_id),
            None,
        )

    def t2_results_for_subject(
        self,
        subject_id: str,
    ) -> tuple[T2LesionResultRecord, ...]:
        return tuple(
            result for result in self.results if result.subject_id == subject_id
        )

    def review_for_artifact(self, artifact_id: str) -> T2ApprovalRecord | None:
        return next(
            (review for review in self.reviews if review.artifact_id == artifact_id),
            None,
        )

    def active_t2_result_for_subject(
        self,
        subject_id: str,
    ) -> T2LesionResultRecord | None:
        return next(
            (
                result
                for result in self.results
                if result.subject_id == subject_id and result.active
            ),
            None,
        )

    @property
    def active_t2_model_release(self) -> T2ModelReleaseRecord | None:
        return next((release for release in self.model_releases if release.active), None)

    @property
    def active_t1_brain_mask_release(self) -> T1BrainMaskReleaseRecord | None:
        return next(
            (release for release in self.t1_brain_mask_releases if release.active),
            None,
        )

    @property
    def active_t1_registration_method(self) -> T1RegistrationMethodRecord | None:
        return next(
            (method for method in self.t1_registration_methods if method.active),
            None,
        )

    @property
    def active_t1_enhancement_method(self) -> T1EnhancementMethodRecord | None:
        return next(
            (method for method in self.t1_enhancement_methods if method.active),
            None,
        )


@dataclass(frozen=True)
class CreateStudyRequest:
    root_path: Path
    name: str
    identifier: str
    description: str | None = None
    blinded: bool = True
    group_definitions: tuple[str, ...] = ()
    actor: str = "Application"


@dataclass(frozen=True)
class CreateSubjectRequest:
    subject_code: str
    expected_t1: bool
    expected_t2: bool
    group_name: str | None = None
    metadata: dict[str, Any] | None = None
    actor: str = "Application"
