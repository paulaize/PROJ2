"""MRI discovery, import, validation, and inspection workflows."""

from __future__ import annotations

import re
from dataclasses import replace
from pathlib import Path
from typing import Callable
from uuid import uuid4

from lys_bbb.input_validation import NiftiInputValidation
from lys_bbb_app.domain.errors import StudyStateError
from lys_bbb_app.domain.scan_import import (
    InputValidationIssue,
    InputValidationOutcome,
    InputValidationState,
    ScanConversionResult,
    ScanDiscoveryReport,
    ScanImportAssignment,
    ScanImportState,
    ScanInputRecord,
    ScanRole,
)
from lys_bbb_app.domain.study import StudySnapshot
from lys_bbb_app.infrastructure.external_viewer import (
    ExternalViewerError,
    ViewerLaunch,
)
from lys_bbb_app.infrastructure.study_database import StudyRepository


RepositoryProvider = Callable[[], StudyRepository]
ScanConverter = Callable[..., ScanConversionResult]
InputValidator = Callable[..., NiftiInputValidation]
ViewerLauncher = Callable[..., ViewerLaunch]
DiscoveryRunner = Callable[[Path], ScanDiscoveryReport]
ProgressCallback = Callable[[int, int, str], None]


class MriInputService:
    """Coordinate managed MRI inputs without owning study lifecycle state."""

    def __init__(
        self,
        repository_provider: RepositoryProvider,
        *,
        scan_converter: ScanConverter,
        input_validator: InputValidator,
        viewer_launcher: ViewerLauncher,
        discovery_runner: DiscoveryRunner,
    ) -> None:
        self._repository_provider = repository_provider
        self._scan_converter = scan_converter
        self._input_validator = input_validator
        self._viewer_launcher = viewer_launcher
        self._discovery_runner = discovery_runner

    def converted_inputs(self, subject_id: str) -> tuple[ScanInputRecord, ...]:
        snapshot = self._repository().snapshot()
        if snapshot.subject(subject_id) is None:
            raise StudyStateError("The selected subject is not active in this study.")
        return tuple(
            record
            for record in snapshot.inputs_for_subject(subject_id)
            if record.active
            and record.state is ScanImportState.CONVERTED
            and record.output_path is not None
        )

    def validate_subject_inputs(
        self,
        subject_id: str,
        *,
        actor: str,
    ) -> StudySnapshot:
        """Validate active managed NIfTI inputs and persist explicit outcomes."""

        repository = self._repository()
        snapshot = repository.snapshot()
        if snapshot.subject(subject_id) is None:
            raise StudyStateError("The selected subject is not active in this study.")
        records = tuple(
            record
            for record in snapshot.inputs_for_subject(subject_id)
            if record.active and record.state is ScanImportState.CONVERTED
        )
        if not records:
            raise StudyStateError(
                "Import and convert at least one MRI input before validation."
            )

        outcomes: dict[str, InputValidationOutcome] = {}
        for record in records:
            issues = self._validation_issues(record)
            outcomes[record.id] = InputValidationOutcome(
                scan_input_id=record.id,
                state=(
                    InputValidationState.INVALID
                    if any(issue.severity == "error" for issue in issues)
                    else InputValidationState.VALID
                ),
                issues=issues,
            )

        _add_t1_pair_warnings(records, outcomes)
        repository.record_input_validations(
            subject_id,
            tuple(outcomes.values()),
            actor=actor,
        )
        return repository.snapshot()

    def open_in_itksnap(
        self,
        subject_id: str,
        scan_input_id: str,
        *,
        actor: str,
        viewer_path: Path | str | None = None,
    ) -> ViewerLaunch:
        repository = self._repository()
        record = next(
            (
                item
                for item in self.converted_inputs(subject_id)
                if item.id == scan_input_id
            ),
            None,
        )
        if record is None or record.output_path is None:
            raise StudyStateError(
                "Select an active converted MRI input before opening ITK-SNAP."
            )
        try:
            launch = self._viewer_launcher(record.output_path, viewer_path)
        except ExternalViewerError as exc:
            raise StudyStateError(str(exc)) from exc
        repository.record_audit_event(
            "MRI_OPENED_IN_ITKSNAP",
            actor=actor,
            subject_id=subject_id,
            details={
                "subject_id": subject_id,
                "scan_input_id": record.id,
                "role": record.role.value,
                "version": record.version,
                "image_path": str(record.output_path),
            },
        )
        return launch

    def plan_bulk_flip(
        self,
        subject_ids: tuple[str, ...],
        flip_axes: tuple[int, ...],
        roles: tuple[ScanRole, ...],
    ) -> tuple[ScanImportAssignment, ...]:
        """Build immutable replacement assignments without performing conversion."""

        selected_subject_ids = tuple(dict.fromkeys(subject_ids))
        axes = set(flip_axes)
        if not selected_subject_ids:
            raise StudyStateError("Select at least one subject to flip.")
        if not axes or not axes <= {0, 1, 2}:
            raise StudyStateError("Select one or more valid storage axes to flip.")
        selected_roles = set(roles)
        if not selected_roles or not selected_roles <= {
            ScanRole.T1_PRE,
            ScanRole.T1_POST,
            ScanRole.T2,
        }:
            raise StudyStateError("Select a valid MRI input scope for the batch flip.")

        snapshot = self._repository().snapshot()
        subjects = {subject.id: subject for subject in snapshot.subjects}
        unknown = [
            subject_id
            for subject_id in selected_subject_ids
            if subject_id not in subjects
        ]
        if unknown:
            raise StudyStateError("One or more selected subjects are no longer active.")

        assignments: list[ScanImportAssignment] = []
        missing_subjects: list[str] = []
        for subject_id in selected_subject_ids:
            records = tuple(
                record
                for record in snapshot.inputs_for_subject(subject_id)
                if record.active
                and record.state is ScanImportState.CONVERTED
                and record.role in selected_roles
            )
            if not records:
                missing_subjects.append(subjects[subject_id].subject_code)
                continue
            assignments.extend(
                _replacement_assignment(record, axes) for record in records
            )
        if missing_subjects:
            raise StudyStateError(
                "These subjects have no converted MRI input in the selected scope: "
                + ", ".join(missing_subjects)
                + ". Import or convert their scans before running the batch flip."
            )
        return tuple(assignments)

    def discover_folder(
        self,
        path: Path | str,
        *,
        actor: str,
    ) -> ScanDiscoveryReport:
        """Reference and inspect one MRI root without mutating its source files."""

        root = Path(path).expanduser().resolve()
        self._repository().set_input_folder_reference(
            "mri",
            root,
            actor=actor,
            require_available=True,
        )
        return self._discovery_runner(root)

    def import_confirmed_scans(
        self,
        assignments: tuple[ScanImportAssignment, ...],
        *,
        actor: str,
        progress: ProgressCallback | None = None,
    ) -> StudySnapshot:
        """Persist a reviewed plan and convert every selected scan to NIfTI."""

        if len({assignment.proposal_id for assignment in assignments}) != len(
            assignments
        ):
            raise StudyStateError(
                "Each discovered scan can be imported only once per plan."
            )
        repository = self._repository()
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

    def _repository(self) -> StudyRepository:
        return self._repository_provider()

    def _validation_issues(
        self,
        record: ScanInputRecord,
    ) -> tuple[InputValidationIssue, ...]:
        if record.output_path is None:
            return (
                InputValidationIssue(
                    "INPUT_FILE_MISSING",
                    "error",
                    "The converted NIfTI path is missing from study state.",
                ),
            )
        try:
            validation = self._input_validator(
                record.output_path,
                expected_sha256=record.output_sha256,
                expected_shape=record.output_shape,
                expected_spacing_mm=record.output_spacing_mm,
                expected_axis_codes=record.output_axis_codes,
            )
        except Exception as exc:
            return (
                InputValidationIssue(
                    "INPUT_VALIDATION_FAILED",
                    "error",
                    "The managed NIfTI validation could not be completed.",
                    str(exc),
                ),
            )
        return tuple(
            InputValidationIssue(
                issue.code,
                issue.severity,
                issue.message,
                issue.technical_detail,
            )
            for issue in validation.issues
        )


def _replacement_assignment(
    record: ScanInputRecord,
    axes: set[int],
) -> ScanImportAssignment:
    return ScanImportAssignment(
        proposal_id=f"bulk-flip-{uuid4()}",
        subject_code=record.subject_code,
        role=record.role,
        source_path=record.source_path,
        source_format=record.source_format,
        session_id=record.session_id,
        scan_id=record.scan_id,
        protocol=record.protocol,
        method=record.method,
        acquisition_orientation=record.acquisition_orientation,
        confidence=record.confidence,
        orientation_policy=record.orientation_policy,
        flip_axes=tuple(sorted(set(record.flip_axes).symmetric_difference(axes))),
    )


def _safe_path_component(value: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", value.strip()).strip("._-")
    if not safe:
        raise StudyStateError("Subject ID cannot be represented as a safe output folder.")
    return safe


def _add_t1_pair_warnings(
    records: tuple[ScanInputRecord, ...],
    outcomes: dict[str, InputValidationOutcome],
) -> None:
    by_role = {record.role: record for record in records}
    pre = by_role.get(ScanRole.T1_PRE)
    post = by_role.get(ScanRole.T1_POST)
    if pre is None or post is None or post.id not in outcomes:
        return

    warnings: list[InputValidationIssue] = []
    if pre.output_shape != post.output_shape:
        warnings.append(
            InputValidationIssue(
                "T1_PAIR_SHAPE_DIFFERS",
                "warning",
                "Pre- and post-Gd dimensions differ; registration must resample the "
                "post-Gd image into pre-Gd space.",
                f"Pre {pre.output_shape}; post {post.output_shape}",
            )
        )
    if pre.output_spacing_mm != post.output_spacing_mm:
        warnings.append(
            InputValidationIssue(
                "T1_PAIR_SPACING_DIFFERS",
                "warning",
                "Pre- and post-Gd voxel spacing differs; inspect registration QC "
                "carefully.",
                f"Pre {pre.output_spacing_mm}; post {post.output_spacing_mm}",
            )
        )
    if pre.output_axis_codes != post.output_axis_codes:
        warnings.append(
            InputValidationIssue(
                "T1_PAIR_ORIENTATION_DIFFERS",
                "warning",
                "Pre- and post-Gd orientation labels differ; confirm the assignments "
                "before registration.",
                f"Pre {pre.output_axis_codes}; post {post.output_axis_codes}",
            )
        )
    if warnings:
        outcome = outcomes[post.id]
        outcomes[post.id] = replace(
            outcome,
            issues=(*outcome.issues, *warnings),
        )
