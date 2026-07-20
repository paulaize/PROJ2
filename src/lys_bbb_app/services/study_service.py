"""Application service for persistent study and subject actions."""

from __future__ import annotations

import re
import shutil
from dataclasses import replace
from pathlib import Path
from typing import Callable
from uuid import uuid4

from lys_bbb.scan_conversion import convert_scan_assignment
from lys_bbb.scan_discovery import discover_mri_source
from lys_bbb.project_state import ProjectDatabase
from lys_bbb_app.domain.scan_import import (
    ScanConversionResult,
    ScanDiscoveryReport,
    ScanImportAssignment,
)
from lys_bbb_app.domain.study import (
    AuditEventRecord,
    CreateStudyRequest,
    CreateSubjectRequest,
    StudySnapshot,
)
from lys_bbb_app.infrastructure.study_database import StudyRepository, StudyStateError


ScanConverter = Callable[..., ScanConversionResult]
ProgressCallback = Callable[[int, int, str], None]


class StudyService:
    """Own the currently opened canonical study repository."""

    def __init__(self, *, scan_converter: ScanConverter = convert_scan_assignment) -> None:
        self._repository: StudyRepository | None = None
        self._scan_converter = scan_converter

    @property
    def current_study(self) -> StudySnapshot | None:
        if self._repository is None:
            return None
        return self._repository.snapshot()

    def create_study(self, request: CreateStudyRequest) -> StudySnapshot:
        target = request.root_path.expanduser().resolve()
        if target.exists():
            raise StudyStateError(
                f"The study directory already exists and will not be overwritten: {target}"
            )
        staging = target.with_name(f".{target.name}.creating-{uuid4().hex[:8]}")
        try:
            repository = StudyRepository.create(replace(request, root_path=staging))
            repository.snapshot()
            staging.rename(target)
            self._repository = StudyRepository.open(target)
        except Exception:
            self._repository = None
            if staging.exists():
                shutil.rmtree(staging)
            raise
        return self._repository.snapshot()

    def open_study(self, path: Path | str) -> StudySnapshot:
        self._repository = StudyRepository.open(path)
        snapshot = self._repository.snapshot()
        self._repository.record_audit_event(
            "STUDY_OPENED",
            actor="Application",
            details={"root_path": str(snapshot.root_path)},
        )
        return self._repository.snapshot()

    def migrate_legacy_project(
        self,
        legacy_path: Path | str,
        target_root: Path,
        *,
        actor: str,
    ) -> StudySnapshot:
        legacy = ProjectDatabase.open(legacy_path).snapshot()
        target = target_root.expanduser().resolve()
        if target.exists():
            raise StudyStateError(
                f"The migration target already exists and will not be overwritten: {target}"
            )
        staging = target.with_name(f".{target.name}.migrating-{uuid4().hex[:8]}")
        request = CreateStudyRequest(
            root_path=staging,
            name=legacy.name,
            identifier=_identifier_from_name(legacy.name),
            description="Migrated from a schema-v1 .lysbbb project.",
            blinded=True,
            actor=actor,
        )
        try:
            repository = StudyRepository.create(request)
            if legacy.t1_input_folder is not None:
                repository.set_input_folder_reference(
                    "t1",
                    legacy.t1_input_folder,
                    actor=actor,
                )
            if legacy.t2_input_folder is not None:
                repository.set_input_folder_reference(
                    "t2",
                    legacy.t2_input_folder,
                    actor=actor,
                )
            repository.record_audit_event(
                "LEGACY_PROJECT_MIGRATED",
                actor=actor,
                details={
                    "legacy_path": str(legacy.database_path),
                    "legacy_project_id": legacy.project_id,
                    "legacy_schema_version": legacy.schema_version,
                },
            )
            repository.snapshot()
            staging.rename(target)
            self._repository = StudyRepository.open(target)
        except Exception:
            self._repository = None
            if staging.exists():
                shutil.rmtree(staging)
            raise
        return self._repository.snapshot()

    def add_subject(self, request: CreateSubjectRequest) -> StudySnapshot:
        return self._require_repository().add_subject(request)

    def remove_subject(self, subject_id: str, *, actor: str) -> StudySnapshot:
        return self._require_repository().archive_subject(subject_id, actor=actor)

    def restore_subject(self, subject_id: str, *, actor: str) -> StudySnapshot:
        return self._require_repository().restore_subject(subject_id, actor=actor)

    def unblind(self, *, reviewer: str) -> StudySnapshot:
        return self._require_repository().unblind(actor=reviewer)

    def assign_groups(
        self,
        assignments: dict[str, str | None],
        *,
        reviewer: str,
    ) -> StudySnapshot:
        return self._require_repository().assign_groups(
            assignments,
            actor=reviewer,
        )

    def list_audit_events(self) -> tuple[AuditEventRecord, ...]:
        return self._require_repository().list_audit_events()

    def set_input_folder(
        self,
        kind: str,
        path: Path | str,
        *,
        actor: str,
    ) -> StudySnapshot:
        return self._require_repository().set_input_folder_reference(
            kind,
            path,
            actor=actor,
            require_available=True,
        )

    def discover_mri_folder(self, path: Path | str, *, actor: str) -> ScanDiscoveryReport:
        """Reference and inspect one MRI root without mutating its source files."""

        root = Path(path).expanduser().resolve()
        self._require_repository().set_input_folder_reference(
            "mri",
            root,
            actor=actor,
            require_available=True,
        )
        return discover_mri_source(root)

    def import_confirmed_scans(
        self,
        assignments: tuple[ScanImportAssignment, ...],
        *,
        actor: str,
        progress: ProgressCallback | None = None,
    ) -> StudySnapshot:
        """Persist a reviewed plan and convert every selected scan to NIfTI."""

        if len({assignment.proposal_id for assignment in assignments}) != len(assignments):
            raise StudyStateError("Each discovered scan can be imported only once per plan.")
        repository = self._require_repository()
        records = repository.stage_scan_imports(assignments, actor=actor)
        assignment_by_proposal = {
            assignment.proposal_id: assignment for assignment in assignments
        }
        total = len(records)
        for index, record in enumerate(records, start=1):
            assignment = assignment_by_proposal[record.proposal_id]
            label = f"{record.subject_code} · {record.role.value}"
            if progress is not None:
                progress(index - 1, total, f"Converting {label}")
            repository.mark_scan_import_converting(record.id)
            output_directory = (
                repository.root_path
                / "outputs"
                / "subjects"
                / _safe_path_component(record.subject_code)
                / "inputs"
                / record.role.value.casefold()
                / f"v{record.version:03d}"
            )
            work_directory = repository.root_path / "work" / "mri-import" / record.id
            try:
                result = self._scan_converter(
                    assignment,
                    output_directory=output_directory,
                    work_directory=work_directory,
                )
                repository.complete_scan_import(record.id, result, actor=actor)
            except Exception as exc:
                repository.fail_scan_import(record.id, str(exc), actor=actor)
            if progress is not None:
                progress(index, total, f"Finished {label}")
        return repository.snapshot()

    def close_study(self) -> None:
        self._repository = None

    def _require_repository(self) -> StudyRepository:
        if self._repository is None:
            raise StudyStateError("Create or open a study before changing study state.")
        return self._repository


def _identifier_from_name(name: str) -> str:
    identifier = re.sub(r"[^A-Za-z0-9._-]+", "-", name.strip()).strip("-._")
    return identifier or "migrated-study"


def _safe_path_component(value: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", value.strip()).strip("._-")
    if not safe:
        raise StudyStateError("Subject ID cannot be represented as a safe output folder.")
    return safe
