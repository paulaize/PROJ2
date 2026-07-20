"""Qt-free domain records and requests for persistent desktop studies."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from lys_bbb_app.domain.scan_import import ScanInputRecord
from lys_bbb_app.domain.t2_lesion import (
    ProcessingJobRecord,
    T2LesionArtifactRecord,
    T2ModelReleaseRecord,
)


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

    @property
    def active_t2_model_release(self) -> T2ModelReleaseRecord | None:
        return next((release for release in self.model_releases if release.active), None)


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
