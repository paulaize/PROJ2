"""Build immutable UI view models from persistent study records."""

from __future__ import annotations

from datetime import datetime

from lys_bbb_app.domain.scan_import import (
    InputValidationState,
    ScanImportState,
    ScanInputRecord,
    ScanRole,
)
from lys_bbb_app.domain.study import LegacyProjectRecord, StudySnapshot, SubjectRecord
from lys_bbb_app.domain.t2_lesion import (
    ArtifactState,
    ProcessingJobState,
    ResultState,
)
from lys_bbb_app.domain.view_models import (
    InputIssueViewModel,
    InputScanViewModel,
    MetricViewModel,
    PriorityActionViewModel,
    ResultViewModel,
    StatusValue,
    StudyViewModel,
    SubjectViewModel,
    T2LesionArtifactViewModel,
    WorkflowSummaryViewModel,
)


NOT_STARTED = StatusValue("Not started", "neutral")
NOT_APPLICABLE = StatusValue("Not applicable", "neutral")
WAITING_FOR_INPUT = StatusValue("Waiting for input", "unavailable")


def present_legacy_project(project: LegacyProjectRecord) -> StudyViewModel:
    """Represent a real legacy project without inventing subject records."""

    return StudyViewModel(
        study_id=project.project_id,
        name=project.name,
        root_path=project.database_path,
        description="Legacy schema-v1 project. Migrate it before adding subjects.",
        schema_version=project.schema_version,
        last_opened="Just now",
        is_demo=False,
        metrics=(
            MetricViewModel("Subjects", "0", "No subjects imported", "neutral"),
            MetricViewModel("Ready", "0", "No available actions", "ready"),
            MetricViewModel("Need review", "0", "No review items", "review"),
            MetricViewModel("Blocked", "0", "No subjects", "failed"),
            MetricViewModel("Complete", "0", "No subjects", "approved"),
        ),
        workflows=(),
        priority_actions=(),
        subjects=(),
        reviews=(),
        results=(),
    )


def present_study(study: StudySnapshot) -> StudyViewModel:
    """Represent canonical durable state without inventing scientific outputs."""

    subjects = tuple(
        _present_subject(
            subject,
            study.inputs_for_subject(subject.id),
            study.t2_artifacts_for_subject(subject.id),
            study,
        )
        for subject in study.subjects
    )
    results = tuple(
        _present_result(subject, study)
        for subject in study.subjects
        if study.t2_results_for_subject(subject.id)
    )
    archived_subjects = tuple(
        _present_subject(subject, (), (), study) for subject in study.archived_subjects
    )
    t1_expected = sum(subject.expected_t1 for subject in study.subjects)
    t2_expected = sum(subject.expected_t2 for subject in study.subjects)
    active_inputs = tuple(record for record in study.scan_inputs if record.active)
    converted_t1 = sum(
        record.state is ScanImportState.CONVERTED
        and record.role in {ScanRole.T1_PRE, ScanRole.T1_POST}
        for record in active_inputs
    )
    converted_t2 = sum(
        record.state is ScanImportState.CONVERTED and record.role is ScanRole.T2
        for record in active_inputs
    )
    failed_inputs = sum(
        record.state is ScanImportState.FAILED for record in active_inputs
    )
    unassigned = sum(subject.group_name is None for subject in study.subjects)
    input_reviews = sum(subject.overall.label == "Input review required" for subject in subjects)
    t1_input_reviews = sum(subject.t1_data.kind == "review" for subject in subjects)
    t1_validated = sum(subject.t1_data.kind == "ready" for subject in subjects)
    t2_input_reviews = sum(subject.t2_data.kind == "review" for subject in subjects)
    t2_validated = sum(subject.t2_data.kind == "ready" for subject in subjects)
    t2_drafts = sum(subject.t2_lesion.kind == "review" for subject in subjects)
    t2_approved = sum(subject.t2_lesion.kind == "approved" for subject in subjects)
    t2_outdated_results = sum(
        any(
            result.state is ResultState.OUTDATED
            for result in study.t2_results_for_subject(subject.id)
        )
        and study.active_t2_result_for_subject(subject.id) is None
        for subject in study.subjects
    )
    complete_subjects = sum(subject.overall.label == "Complete" for subject in subjects)
    t2_eligible = sum(
        subject.can_run_t2_inference
        and (
            subject.t2_artifact is None
            or subject.t2_artifact.state.kind == "outdated"
        )
        for subject in subjects
    )
    t2_running_jobs = sum(
        job.job_type == "T2_LESION_INFERENCE"
        and job.state is ProcessingJobState.RUNNING
        for job in study.processing_jobs
    )
    active_release = study.active_t2_model_release
    review_count = input_reviews + t2_drafts

    workflows: tuple[WorkflowSummaryViewModel, ...] = ()
    priority_actions: tuple[PriorityActionViewModel, ...] = ()
    if subjects:
        workflows = (
            WorkflowSummaryViewModel(
                "t1",
                "T1 Enhancement",
                "Pre/post T1 import and review-gated enhancement workflow.",
                (
                    StatusValue(f"{t1_input_reviews} need input review", "review")
                    if t1_input_reviews
                    else StatusValue(f"{t1_validated} ready for mask", "ready")
                    if t1_validated
                    else WAITING_FOR_INPUT
                ),
                (
                    ("Expected subjects", str(t1_expected)),
                    ("Inputs converted", str(converted_t1)),
                    ("Input reviews", str(t1_input_reviews)),
                    ("Approved results", "0"),
                ),
                "View subjects",
                "subjects",
            ),
            WorkflowSummaryViewModel(
                "t2",
                "T2 Lesion",
                "Native T2 and released lesion-mask review workflow.",
                (
                    StatusValue(f"{t2_drafts} draft masks need review", "review")
                    if t2_drafts
                    else StatusValue(f"{t2_running_jobs} inference job running", "processing")
                    if t2_running_jobs
                    else StatusValue(f"{t2_input_reviews} need input review", "review")
                    if t2_input_reviews
                    else StatusValue(f"{t2_eligible} ready for inference", "ready")
                    if t2_eligible
                    else WAITING_FOR_INPUT
                ),
                (
                    ("Expected subjects", str(t2_expected)),
                    ("T2 scans converted", str(converted_t2)),
                    ("Input reviews", str(t2_input_reviews)),
                    ("Approved results", str(t2_approved)),
                ),
                "View subjects",
                "subjects",
            ),
            WorkflowSummaryViewModel(
                "combined",
                "Combined MRI Results",
                "Approved subject-level T1 and T2 measurements.",
                (
                    StatusValue(f"{t2_approved} approved T2 results", "approved")
                    if t2_approved
                    else StatusValue("No approved results yet", "unavailable")
                ),
                (
                    ("Subjects", str(len(subjects))),
                    ("Complete", str(complete_subjects)),
                    ("Outdated results", str(t2_outdated_results)),
                    ("Export eligible", str(t2_approved)),
                ),
                "View results",
                "results",
            ),
        )
        priority_actions = (
            PriorityActionViewModel(
                (
                    f"{input_reviews} subjects require MRI input validation"
                    if input_reviews
                    else f"{t1_validated + t2_validated} workflows are ready for masks"
                    if active_inputs
                    else f"{len(subjects)} subjects are waiting for MRI discovery"
                ),
                (
                    "Open a subject and review the Inputs tab"
                    if input_reviews
                    else "Validated inputs can advance to versioned mask artifacts"
                    if active_inputs
                    else "Choose or review the MRI source folder"
                ),
                "review" if input_reviews else "ready" if active_inputs else "unavailable",
                "subjects",
            ),
        )
        if t2_eligible:
            priority_actions = (
                PriorityActionViewModel(
                    f"{t2_eligible} subjects are ready for T2 lesion inference",
                    (
                        f"Frozen release: {active_release.version}"
                        if active_release is not None
                        else "Select the frozen LYS v1 release before starting"
                    ),
                    "ready" if active_release is not None else "review",
                    "subjects",
                ),
            ) + priority_actions
        if t2_drafts:
            priority_actions = (
                PriorityActionViewModel(
                    f"{t2_drafts} draft T2 lesion masks require human review",
                    "Approve, reject, or import an ITK-SNAP correction",
                    "review",
                    "subjects",
                ),
            ) + priority_actions
        if not study.is_blinded and unassigned:
            priority_actions += (
                PriorityActionViewModel(
                    f"{unassigned} subjects have no experimental group",
                    "Group assignment remains optional for subject-level work",
                    "review",
                    "subjects",
                ),
            )

    return StudyViewModel(
        study_id=study.id,
        name=study.name,
        root_path=study.root_path,
        description=study.description or "",
        schema_version=study.schema_version,
        last_opened="Just now",
        is_demo=False,
        blinded_review=study.is_blinded,
        group_definitions=study.group_definitions,
        archived_subjects=archived_subjects,
        metrics=(
            MetricViewModel("Subjects", str(len(subjects)), "Persisted in this study", "neutral"),
            MetricViewModel(
                "Ready",
                str(
                    sum(
                        subject.overall.label == "Ready for analysis"
                        for subject in subjects
                    )
                ),
                "At least one workflow has validated input",
                "ready",
            ),
            MetricViewModel(
                "Need review",
                str(review_count),
                "MRI inputs or draft T2 masks",
                "review",
            ),
            MetricViewModel("Blocked", str(failed_inputs), "Input conversion failures", "failed"),
            MetricViewModel(
                "Complete",
                str(complete_subjects),
                "All expected workflows are complete",
                "approved",
            ),
        ),
        workflows=workflows,
        priority_actions=priority_actions,
        subjects=subjects,
        reviews=(),
        results=results,
        mri_input_folder=study.mri_input_folder,
        t1_input_folder=study.t1_input_folder,
        t2_input_folder=study.t2_input_folder,
        active_t2_release_label=(
            f"{active_release.name} · {active_release.version}"
            if active_release is not None
            else None
        ),
        t2_eligible_subject_count=t2_eligible,
        t2_running_job_count=t2_running_jobs,
    )


def _present_subject(
    subject: SubjectRecord,
    scan_inputs: tuple[ScanInputRecord, ...],
    artifacts,
    study: StudySnapshot,
) -> SubjectViewModel:
    expected = " · ".join(
        workflow
        for workflow, enabled in (("T1", subject.expected_t1), ("T2", subject.expected_t2))
        if enabled
    )
    active = tuple(record for record in scan_inputs if record.active)
    t1_data = _t1_input_status(active) if subject.expected_t1 else NOT_APPLICABLE
    t2_data = _t2_input_status(active) if subject.expected_t2 else NOT_APPLICABLE
    active_t2_input = next(
        (record for record in active if record.role is ScanRole.T2),
        None,
    )
    active_t2_artifact = next(
        (artifact for artifact in artifacts if artifact.active),
        None,
    )
    latest_t2_artifact = active_t2_artifact or next(iter(artifacts), None)
    active_t2_result = study.active_t2_result_for_subject(subject.id)
    t2_job_running = any(
        job.job_type == "T2_LESION_INFERENCE"
        and job.state is ProcessingJobState.RUNNING
        and subject.id in job.subject_ids
        for job in study.processing_jobs
    )
    t2_lesion = (
        StatusValue("Generating draft mask", "processing")
        if t2_job_running
        else StatusValue("Approved lesion volume", "approved")
        if active_t2_result is not None
        else StatusValue("Mask · human review required", "review")
        if active_t2_artifact is not None
        and active_t2_artifact.state in {
            ArtifactState.DRAFT_REVIEW_REQUIRED,
            ArtifactState.CORRECTED_REVIEW_REQUIRED,
        }
        else StatusValue("Mask rejected", "failed")
        if latest_t2_artifact is not None
        and latest_t2_artifact.state is ArtifactState.REJECTED
        else StatusValue("Result outdated", "outdated")
        if latest_t2_artifact is not None
        and latest_t2_artifact.state is ArtifactState.OUTDATED
        else StatusValue("Ready for segmentation", "ready")
        if t2_data.kind == "ready"
        else NOT_STARTED
        if subject.expected_t2
        else NOT_APPLICABLE
    )
    active_release = study.active_t2_model_release
    input_available = (
        active_t2_input is not None
        and active_t2_input.output_path is not None
        and active_t2_input.output_path.is_file()
    )
    spacing_compatible = (
        active_t2_input is not None
        and len(active_t2_input.output_spacing_mm) == 3
        and all(
            abs(observed - expected) <= 1e-5
            for observed, expected in zip(
                active_t2_input.output_spacing_mm,
                (0.07, 0.07, 0.5),
                strict=True,
            )
        )
    )
    can_run_t2 = (
        t2_data.kind == "ready"
        and input_available
        and spacing_compatible
        and not t2_job_running
    )
    blocked_reason = _t2_blocked_reason(
        subject.expected_t2,
        t2_data,
        input_available,
        spacing_compatible,
        active_release is not None,
        t2_job_running,
    )
    ready = t1_data.label == "Inputs validated" or t2_data.label == "T2 validated"
    failed = t1_data.kind == "failed" or t2_data.kind == "failed"
    needs_artifact_review = t2_lesion.kind == "review"
    metadata = [
        ("Expected workflows", expected),
        ("Persistent subject ID", subject.id),
    ]
    history = ["Subject created in persistent study state"]
    history.extend(
        f"{record.role.value} v{record.version}: {record.state.value.replace('_', ' ').title()}"
        for record in scan_inputs
    )
    history.extend(
        f"T2 lesion mask v{artifact.version}: "
        f"{artifact.state.value.replace('_', ' ').title()}"
        for artifact in artifacts
    )
    history.extend(
        f"T2 lesion result v{result.version}: "
        f"{result.state.value.replace('_', ' ').title()} · "
        f"{result.lesion_volume_mm3:.3f} mm³"
        for result in study.t2_results_for_subject(subject.id)
    )
    history.extend(
        f"{record.role.value} v{record.version}: "
        f"{record.validation_state.value.replace('_', ' ').title()}"
        for record in scan_inputs
        if record.validation_state is not InputValidationState.NOT_RUN
    )
    return SubjectViewModel(
        subject_id=subject.id,
        display_id=subject.subject_code,
        group=subject.group_name,
        t1_data=t1_data,
        brain_mask=NOT_STARTED if subject.expected_t1 else NOT_APPLICABLE,
        registration=NOT_STARTED if subject.expected_t1 else NOT_APPLICABLE,
        t1_result=NOT_STARTED if subject.expected_t1 else NOT_APPLICABLE,
        t2_data=t2_data,
        t2_lesion=t2_lesion,
        overall=(
            StatusValue("Blocked", "failed")
            if failed
            else StatusValue("Complete", "approved")
            if active_t2_result is not None and not subject.expected_t1
            else StatusValue("T2 complete · T1 pending", "ready")
            if active_t2_result is not None
            else StatusValue("Review required", "review")
            if needs_artifact_review
            else StatusValue("Ready for analysis", "ready")
            if ready
            else StatusValue("Input review required", "review")
            if any(record.state is ScanImportState.CONVERTED for record in active)
            else NOT_STARTED
        ),
        updated=_format_timestamp(subject.updated_at),
        metadata=tuple(metadata),
        history=tuple(history),
        mri_input_count=sum(
            record.state is ScanImportState.CONVERTED for record in active
        ),
        inputs=tuple(_present_scan_input(record) for record in active),
        can_validate_inputs=any(
            record.state is ScanImportState.CONVERTED for record in active
        ),
        t2_artifact=(
            _present_t2_artifact(latest_t2_artifact, study)
            if latest_t2_artifact is not None
            else None
        ),
        can_run_t2_inference=can_run_t2,
        t2_inference_blocked_reason=blocked_reason,
        t2_release_label=(
            f"{active_release.name} · {active_release.version}"
            if active_release is not None
            else None
        ),
    )


def _present_t2_artifact(artifact, study: StudySnapshot) -> T2LesionArtifactViewModel:
    release = next(
        (item for item in study.model_releases if item.id == artifact.model_release_id),
        None,
    )
    review = study.review_for_artifact(artifact.id)
    result = next(
        (
            item
            for item in study.t2_results_for_subject(artifact.subject_id)
            if item.source_artifact_id == artifact.id
        ),
        None,
    )
    state = {
        ArtifactState.DRAFT_REVIEW_REQUIRED: StatusValue(
            "Draft · human review required",
            "review",
        ),
        ArtifactState.CORRECTED_REVIEW_REQUIRED: StatusValue(
            "Corrected mask · review required",
            "review",
        ),
        ArtifactState.APPROVED: StatusValue("Human approved", "approved"),
        ArtifactState.REJECTED: StatusValue("Rejected", "failed"),
        ArtifactState.OUTDATED: StatusValue("Outdated", "outdated"),
    }[artifact.state]
    return T2LesionArtifactViewModel(
        artifact_id=artifact.id,
        version=artifact.version,
        state=state,
        mask_path=artifact.mask_path,
        probability_path=artifact.probability_path,
        qc_preview_path=artifact.qc_preview_path,
        lesion_voxel_count=artifact.lesion_voxel_count,
        provisional_volume_text=f"{artifact.provisional_volume_mm3:.3f} mm³",
        threshold_text=f"{artifact.threshold:.2f}",
        release_label=(release.version if release is not None else artifact.model_release_id),
        device=artifact.device,
        created_at=_format_timestamp(artifact.created_at),
        source_scan_input_id=artifact.source_scan_input_id,
        origin_label=(
            "ITK-SNAP correction"
            if artifact.origin == "CORRECTED"
            else "RatLesNetV2 automatic draft"
        ),
        can_correct=artifact.active
        and artifact.state
        in {
            ArtifactState.DRAFT_REVIEW_REQUIRED,
            ArtifactState.CORRECTED_REVIEW_REQUIRED,
            ArtifactState.APPROVED,
        },
        can_review=artifact.active
        and artifact.state
        in {
            ArtifactState.DRAFT_REVIEW_REQUIRED,
            ArtifactState.CORRECTED_REVIEW_REQUIRED,
        },
        official_volume_text=(
            f"{result.lesion_volume_mm3:.3f} mm³"
            if result is not None and result.state is ResultState.APPROVED
            else None
        ),
        reviewer=review.reviewer if review is not None else None,
        reviewed_at=(
            _format_timestamp(review.created_at) if review is not None else None
        ),
    )


def _present_result(subject: SubjectRecord, study: StudySnapshot) -> ResultViewModel:
    result = next(iter(study.t2_results_for_subject(subject.id)), None)
    if result is None:
        raise RuntimeError("A result view was requested for a subject without results.")
    state = (
        StatusValue("Human approved", "approved")
        if result.state is ResultState.APPROVED and result.active
        else StatusValue("Outdated", "outdated")
    )
    return ResultViewModel(
        subject_id=subject.subject_code,
        group=subject.group_name,
        t1_value="Not available",
        t1_state=StatusValue("Not available", "unavailable"),
        t2_value=f"{result.lesion_volume_mm3:.3f} mm³",
        t2_state=state,
        method_version=result.method_version,
    )


def _t2_blocked_reason(
    expected: bool,
    input_status: StatusValue,
    input_available: bool,
    spacing_compatible: bool,
    release_available: bool,
    running: bool,
) -> str | None:
    if not expected:
        return "T2 is marked not applicable for this subject."
    if running:
        return "T2 lesion inference is already running for this subject."
    if input_status.kind != "ready":
        return "Import, convert, visually review, and validate the active T2 input first."
    if not input_available:
        return "The managed T2 NIfTI is unavailable. Reconnect its study storage."
    if not spacing_compatible:
        return "This release expects 0.07 × 0.07 × 0.5 mm T2 voxel spacing."
    if not release_available:
        return "Select and validate the frozen LYS v1 RatLesNetV2 release."
    return None


def _t1_input_status(records: tuple[ScanInputRecord, ...]) -> StatusValue:
    relevant = tuple(
        record for record in records if record.role in {ScanRole.T1_PRE, ScanRole.T1_POST}
    )
    if any(record.state is ScanImportState.FAILED for record in relevant):
        return StatusValue("Conversion failed", "failed")
    if any(
        record.state in {ScanImportState.QUEUED, ScanImportState.CONVERTING}
        for record in relevant
    ):
        return StatusValue("Converting inputs", "processing")
    converted = {
        record.role for record in relevant if record.state is ScanImportState.CONVERTED
    }
    if converted == {ScanRole.T1_PRE, ScanRole.T1_POST}:
        converted_records = tuple(
            record for record in relevant if record.role in converted
        )
        if any(
            record.validation_state is InputValidationState.INVALID
            for record in converted_records
        ):
            return StatusValue("Validation failed", "failed")
        if all(
            record.validation_state is InputValidationState.VALID
            for record in converted_records
        ):
            return StatusValue("Inputs validated", "ready")
        return StatusValue("Input review required", "review")
    if converted:
        return StatusValue("Incomplete T1 pair", "review")
    return WAITING_FOR_INPUT


def _t2_input_status(records: tuple[ScanInputRecord, ...]) -> StatusValue:
    relevant = tuple(record for record in records if record.role is ScanRole.T2)
    if any(record.state is ScanImportState.FAILED for record in relevant):
        return StatusValue("Conversion failed", "failed")
    if any(
        record.state in {ScanImportState.QUEUED, ScanImportState.CONVERTING}
        for record in relevant
    ):
        return StatusValue("Converting T2", "processing")
    if any(record.state is ScanImportState.CONVERTED for record in relevant):
        record = next(
            item for item in relevant if item.state is ScanImportState.CONVERTED
        )
        if record.validation_state is InputValidationState.INVALID:
            return StatusValue("Validation failed", "failed")
        if record.validation_state is InputValidationState.VALID:
            return StatusValue("T2 validated", "ready")
        return StatusValue("Input review required", "review")
    return WAITING_FOR_INPUT


def _present_scan_input(record: ScanInputRecord) -> InputScanViewModel:
    role_labels = {
        ScanRole.T1_PRE: "Pre-Gd T1",
        ScanRole.T1_POST: "Post-Gd T1",
        ScanRole.T2: "T2-weighted",
    }
    conversion = {
        ScanImportState.QUEUED: StatusValue("Queued", "processing"),
        ScanImportState.CONVERTING: StatusValue("Converting", "processing"),
        ScanImportState.CONVERTED: StatusValue("Converted", "ready"),
        ScanImportState.FAILED: StatusValue("Conversion failed", "failed"),
        ScanImportState.SUPERSEDED: StatusValue("Superseded", "neutral"),
    }[record.state]
    validation = (
        {
            InputValidationState.NOT_RUN: StatusValue("Review required", "review"),
            InputValidationState.VALID: StatusValue("Validated", "ready"),
            InputValidationState.INVALID: StatusValue(
                "Validation failed",
                "failed",
            ),
        }[record.validation_state]
        if record.state is ScanImportState.CONVERTED
        else StatusValue("Not available", "unavailable")
    )
    flips = ", ".join("XYZ"[axis] for axis in record.flip_axes)
    transformation = (
        f"{record.orientation_policy.value.replace('_', ' ').title()} · "
        f"flipped {flips}"
        if flips
        else record.orientation_policy.value.replace("_", " ").title()
    )
    return InputScanViewModel(
        scan_input_id=record.id,
        role=record.role.value,
        role_label=role_labels[record.role],
        version=record.version,
        conversion=conversion,
        validation=validation,
        managed_path=record.output_path,
        source_path=record.source_path,
        shape_text=" × ".join(str(value) for value in record.output_shape) or "—",
        spacing_text=(
            " × ".join(f"{value:.4g}" for value in record.output_spacing_mm) + " mm"
            if record.output_spacing_mm
            else "—"
        ),
        orientation_text=" ".join(record.output_axis_codes) or "—",
        transformation_text=transformation,
        checksum_text=(
            f"{record.output_sha256[:12]}…" if record.output_sha256 else "—"
        ),
        issues=tuple(
            InputIssueViewModel(
                issue.code,
                issue.severity,
                issue.user_message,
                issue.technical_detail,
            )
            for issue in record.validation_issues
        ),
        can_open=(
            record.state is ScanImportState.CONVERTED
            and record.output_path is not None
        ),
    )


def _format_timestamp(value: str) -> str:
    try:
        timestamp = datetime.fromisoformat(value)
    except ValueError:
        return value
    return timestamp.astimezone().strftime("%Y-%m-%d %H:%M")
