"""Application service for persistent study and subject actions."""

from __future__ import annotations

import re
import shutil
from dataclasses import replace
from pathlib import Path
from typing import Callable
from uuid import uuid4

from lys_bbb.input_validation import NiftiInputValidation, validate_managed_nifti
from lys_bbb.t2_inference import (
    T2InferenceOutput,
    create_t2_qc_preview,
    run_frozen_t2_ensemble,
)
from lys_bbb.t2_model_release import (
    FrozenT2ModelRelease,
    validate_frozen_t2_model_release,
)
from lys_bbb.scan_conversion import convert_scan_assignment
from lys_bbb.scan_discovery import discover_mri_source
from lys_bbb.project_state import ProjectDatabase, ProjectStateError
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
from lys_bbb_app.domain.study import (
    AuditEventRecord,
    CreateStudyRequest,
    CreateSubjectRequest,
    LegacyProjectRecord,
    StudySnapshot,
)
from lys_bbb_app.domain.t2_lesion import (
    ReviewDecision,
    T2ArtifactDraft,
    T2InferenceReadiness,
)
from lys_bbb_app.infrastructure.study_database import StudyRepository
from lys_bbb_app.infrastructure.external_viewer import (
    ExternalViewerError,
    ViewerLaunch,
    launch_itksnap,
)
from lys_bbb_app.services.t2_export_service import (
    ApprovedT2Export,
    export_approved_t2_results,
)
from lys_bbb_app.services.t2_review_service import T2ReviewService


ScanConverter = Callable[..., ScanConversionResult]
InputValidator = Callable[..., NiftiInputValidation]
ViewerLauncher = Callable[..., ViewerLaunch]
ProgressCallback = Callable[[int, int, str], None]
T2ReleaseValidator = Callable[[Path | str], FrozenT2ModelRelease]
T2InferenceRunner = Callable[..., T2InferenceOutput]
T2QCBuilder = Callable[[Path, Path, Path], Path]


class StudyService:
    """Own the currently opened canonical study repository."""

    def __init__(
        self,
        *,
        scan_converter: ScanConverter = convert_scan_assignment,
        input_validator: InputValidator = validate_managed_nifti,
        viewer_launcher: ViewerLauncher = launch_itksnap,
        t2_release_validator: T2ReleaseValidator = validate_frozen_t2_model_release,
        t2_inference_runner: T2InferenceRunner = run_frozen_t2_ensemble,
        t2_qc_builder: T2QCBuilder = create_t2_qc_preview,
    ) -> None:
        self._repository: StudyRepository | None = None
        self._scan_converter = scan_converter
        self._input_validator = input_validator
        self._viewer_launcher = viewer_launcher
        self._t2_release_validator = t2_release_validator
        self._t2_inference_runner = t2_inference_runner
        self._t2_qc_builder = t2_qc_builder

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
        try:
            legacy = ProjectDatabase.open(legacy_path).snapshot()
        except ProjectStateError as exc:
            raise StudyStateError(str(exc)) from exc
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

    def inspect_legacy_project(self, path: Path | str) -> LegacyProjectRecord:
        """Read a legacy project without retaining it as mutable application state."""

        try:
            project = ProjectDatabase.open(path).snapshot()
        except ProjectStateError as exc:
            raise StudyStateError(str(exc)) from exc
        self.close_study()
        return LegacyProjectRecord(
            project_id=project.project_id,
            name=project.name,
            database_path=project.database_path,
            schema_version=project.schema_version,
        )

    def add_subject(self, request: CreateSubjectRequest) -> StudySnapshot:
        return self._require_repository().add_subject(request)

    def remove_subject(self, subject_id: str, *, actor: str) -> StudySnapshot:
        return self._require_repository().archive_subject(subject_id, actor=actor)

    def restore_subject(self, subject_id: str, *, actor: str) -> StudySnapshot:
        return self._require_repository().restore_subject(subject_id, actor=actor)

    def rename_subject(
        self,
        subject_id: str,
        subject_code: str,
        *,
        actor: str,
    ) -> StudySnapshot:
        return self._require_repository().rename_subject(
            subject_id,
            subject_code,
            actor=actor,
        )

    def converted_mri_inputs(self, subject_id: str) -> tuple[ScanInputRecord, ...]:
        snapshot = self._require_repository().snapshot()
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

        repository = self._require_repository()
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
            if record.output_path is None:
                issues = (
                    InputValidationIssue(
                        "INPUT_FILE_MISSING",
                        "error",
                        "The converted NIfTI path is missing from study state.",
                    ),
                )
            else:
                try:
                    validation = self._input_validator(
                        record.output_path,
                        expected_sha256=record.output_sha256,
                        expected_shape=record.output_shape,
                        expected_spacing_mm=record.output_spacing_mm,
                        expected_axis_codes=record.output_axis_codes,
                    )
                    issues = tuple(
                        InputValidationIssue(
                            issue.code,
                            issue.severity,
                            issue.message,
                            issue.technical_detail,
                        )
                        for issue in validation.issues
                    )
                except Exception as exc:
                    issues = (
                        InputValidationIssue(
                            "INPUT_VALIDATION_FAILED",
                            "error",
                            "The managed NIfTI validation could not be completed.",
                            str(exc),
                        ),
                    )
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

    def register_t2_model_release(
        self,
        release_root: Path | str,
        *,
        actor: str,
    ) -> StudySnapshot:
        """Validate and activate one immutable LYS_PROJ1 inference release."""

        repository = self._require_repository()
        try:
            release = self._t2_release_validator(release_root)
        except (FileNotFoundError, OSError, ValueError) as exc:
            raise StudyStateError(f"The T2 model release is not valid: {exc}") from exc
        repository.register_t2_model_release(release, actor=actor)
        return repository.snapshot()

    def t2_inference_readiness(
        self,
        subject_ids: tuple[str, ...] | None = None,
    ) -> T2InferenceReadiness:
        """Return active subjects whose current native T2 is release-compatible."""

        snapshot = self._require_repository().snapshot()
        requested = set(subject_ids) if subject_ids is not None else None
        active_ids = {subject.id for subject in snapshot.subjects}
        subjects_with_current_drafts = {
            artifact.subject_id for artifact in snapshot.artifacts if artifact.active
        }
        if requested is not None and requested - active_ids:
            raise StudyStateError("One or more selected subjects are no longer active.")
        eligible: list[str] = []
        blocked: list[tuple[str, str]] = []
        for subject in snapshot.subjects:
            if requested is not None and subject.id not in requested:
                continue
            if requested is None and subject.id in subjects_with_current_drafts:
                blocked.append(
                    (subject.id, "A current draft lesion mask already awaits review.")
                )
                continue
            if not subject.expected_t2:
                blocked.append((subject.id, "T2 is marked not applicable."))
                continue
            t2 = next(
                (
                    record
                    for record in snapshot.inputs_for_subject(subject.id)
                    if record.active and record.role is ScanRole.T2
                ),
                None,
            )
            if t2 is None or t2.state is not ScanImportState.CONVERTED:
                blocked.append((subject.id, "No converted T2 input is available."))
                continue
            if t2.validation_state is not InputValidationState.VALID:
                blocked.append((subject.id, "The active T2 input has not passed validation."))
                continue
            if t2.output_path is None or not t2.output_path.is_file():
                blocked.append((subject.id, "The managed T2 NIfTI is unavailable."))
                continue
            if len(t2.output_spacing_mm) != 3 or any(
                abs(observed - expected) > 1e-5
                for observed, expected in zip(
                    t2.output_spacing_mm,
                    (0.07, 0.07, 0.5),
                    strict=True,
                )
            ):
                blocked.append(
                    (
                        subject.id,
                        "Voxel spacing is incompatible with this release "
                        "(expected 0.07 × 0.07 × 0.5 mm).",
                    )
                )
                continue
            eligible.append(subject.id)
        return T2InferenceReadiness(tuple(eligible), tuple(blocked))

    def run_t2_lesion_inference(
        self,
        *,
        actor: str,
        subject_ids: tuple[str, ...] | None = None,
        device_name: str = "auto",
        progress: ProgressCallback | None = None,
    ) -> StudySnapshot:
        """Run the frozen ensemble and commit immutable draft artifacts on success."""

        repository = self._require_repository()
        snapshot = repository.snapshot()
        release_record = snapshot.active_t2_model_release
        if release_record is None:
            raise StudyStateError(
                "Select and validate the frozen LYS v1 RatLesNetV2 release first."
            )
        try:
            release = self._t2_release_validator(release_record.root_path)
        except (FileNotFoundError, OSError, ValueError) as exc:
            raise StudyStateError(
                f"The registered T2 model release is no longer valid: {exc}"
            ) from exc
        if (
            release.id != release_record.id
            or release.manifest_sha256 != release_record.manifest_sha256
            or release.frozen_spec_sha256 != release_record.frozen_spec_sha256
            or release.threshold_sha256 != release_record.threshold_sha256
            or release.model_sha256 != release_record.model_sha256
            or release.metadata.get("runtime_sha256")
            != release_record.metadata.get("runtime_sha256")
        ):
            raise StudyStateError(
                "The installed T2 release changed after validation. Select it again."
            )

        readiness = self.t2_inference_readiness(subject_ids)
        if not readiness.eligible_subject_ids:
            raise StudyStateError(
                "No active subjects have a validated, release-compatible T2 input."
            )
        inputs_by_subject = {
            subject_id: next(
                record
                for record in snapshot.inputs_for_subject(subject_id)
                if record.active
                and record.role is ScanRole.T2
                and record.state is ScanImportState.CONVERTED
                and record.output_path is not None
            )
            for subject_id in readiness.eligible_subject_ids
        }
        job_id = repository.create_t2_inference_job(
            readiness.eligible_subject_ids,
            release_id=release.id,
            actor=actor,
        )
        work_root = repository.root_path / "work" / "t2_lesion" / job_id
        output_root = repository.root_path / "outputs" / "t2_lesion" / "jobs" / job_id
        repository.start_t2_inference_job(job_id)

        def report(current: int, total: int, message: str) -> None:
            repository.update_t2_inference_job(job_id, current, total, message)
            if progress is not None:
                progress(current, total, message)

        try:
            inference = self._t2_inference_runner(
                release,
                {
                    subject_id: record.output_path
                    for subject_id, record in inputs_by_subject.items()
                },
                work_root=work_root,
                output_root=output_root,
                device_name=device_name,
                progress=report,
            )
            drafts: list[T2ArtifactDraft] = []
            for index, case in enumerate(inference.cases, start=1):
                record = inputs_by_subject.get(case.case_id)
                if record is None or record.output_path is None:
                    raise RuntimeError(
                        f"Inference returned an unexpected subject ID: {case.case_id}"
                    )
                qc_path = case.mask_path.parent / "qc_preview.png"
                self._t2_qc_builder(record.output_path, case.mask_path, qc_path)
                drafts.append(
                    T2ArtifactDraft(
                        subject_id=case.case_id,
                        source_scan_input_id=record.id,
                        mask_path=case.mask_path,
                        mask_sha256=case.mask_sha256,
                        probability_path=case.probability_path,
                        probability_sha256=case.probability_sha256,
                        qc_preview_path=qc_path,
                        lesion_voxel_count=case.lesion_voxel_count,
                        provisional_volume_mm3=case.lesion_volume_mm3,
                        threshold=release.threshold,
                        device=inference.device,
                        metadata={
                            "shape": list(case.shape),
                            "spacing_mm": list(case.spacing_mm),
                            "axis_codes": list(case.axis_codes),
                            "ensemble": "unweighted_mean_lesion_probability",
                            "postprocessing": "none",
                            "native_affine_preserved": True,
                            "predictions_are_drafts": True,
                            "human_review_required": True,
                            "inference_summary": str(inference.summary_path),
                        },
                    )
                )
                report(index, len(inference.cases), f"Creating T2 QC preview {index} of {len(inference.cases)}")
            repository.complete_t2_inference_job(
                job_id,
                tuple(drafts),
                release_id=release.id,
                output_path=output_root,
                actor=actor,
            )
        except Exception as exc:
            repository.fail_t2_inference_job(job_id, str(exc), actor=actor)
            if isinstance(exc, StudyStateError):
                raise
            raise StudyStateError(f"T2 lesion inference failed: {exc}") from exc
        return repository.snapshot()

    def open_mri_in_itksnap(
        self,
        subject_id: str,
        scan_input_id: str,
        *,
        actor: str,
        viewer_path: Path | str | None = None,
    ) -> ViewerLaunch:
        repository = self._require_repository()
        record = next(
            (
                item
                for item in self.converted_mri_inputs(subject_id)
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

    def open_t2_draft_in_itksnap(
        self,
        subject_id: str,
        artifact_id: str,
        *,
        actor: str,
        viewer_path: Path | str | None = None,
    ) -> ViewerLaunch:
        return self._t2_review_service().open_editable_copy_in_itksnap(
            subject_id,
            artifact_id,
            actor=actor,
            viewer_path=viewer_path,
        )

    def import_corrected_t2_mask(
        self,
        subject_id: str,
        source_artifact_id: str,
        corrected_path: Path | str,
        *,
        actor: str,
    ) -> StudySnapshot:
        self._t2_review_service().import_corrected_mask(
            subject_id,
            source_artifact_id,
            corrected_path,
            actor=actor,
        )
        return self._require_repository().snapshot()

    def approve_t2_mask(
        self,
        subject_id: str,
        artifact_id: str,
        *,
        reviewer: str,
        notes: str | None = None,
    ) -> StudySnapshot:
        self._t2_review_service().review_mask(
            subject_id,
            artifact_id,
            ReviewDecision.APPROVED,
            reviewer=reviewer,
            notes=notes,
        )
        return self._require_repository().snapshot()

    def reject_t2_mask(
        self,
        subject_id: str,
        artifact_id: str,
        *,
        reviewer: str,
        issue_code: str,
        notes: str,
    ) -> StudySnapshot:
        self._t2_review_service().review_mask(
            subject_id,
            artifact_id,
            ReviewDecision.REJECTED,
            reviewer=reviewer,
            issue_code=issue_code,
            notes=notes,
        )
        return self._require_repository().snapshot()

    def export_approved_t2_results_csv(
        self,
        destination: Path | str,
        *,
        actor: str,
    ) -> ApprovedT2Export:
        repository = self._require_repository()
        exported = export_approved_t2_results(repository.snapshot(), destination)
        repository.record_audit_event(
            "APPROVED_T2_RESULTS_EXPORTED",
            actor=actor,
            details={
                "path": str(exported.path),
                "row_count": exported.row_count,
                "blinded": exported.blinded,
                "approved_only": True,
            },
        )
        return exported

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

        snapshot = self._require_repository().snapshot()
        subjects = {subject.id: subject for subject in snapshot.subjects}
        unknown = [subject_id for subject_id in selected_subject_ids if subject_id not in subjects]
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
            for record in records:
                assignments.append(
                    ScanImportAssignment(
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
                        flip_axes=tuple(
                            sorted(set(record.flip_axes).symmetric_difference(axes))
                        ),
                    )
                )
        if missing_subjects:
            raise StudyStateError(
                "These subjects have no converted MRI input in the selected scope: "
                + ", ".join(missing_subjects)
                + ". Import or convert their scans before running the batch flip."
            )
        return tuple(assignments)

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

    def _t2_review_service(self) -> T2ReviewService:
        return T2ReviewService(
            self._require_repository(),
            viewer_launcher=self._viewer_launcher,
            qc_builder=self._t2_qc_builder,
        )


def _identifier_from_name(name: str) -> str:
    identifier = re.sub(r"[^A-Za-z0-9._-]+", "-", name.strip()).strip("-._")
    return identifier or "migrated-study"


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
