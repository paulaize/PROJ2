"""Build immutable UI view models from persistent study records."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from lys_bbb_app.domain.scan_import import (
    InputValidationState,
    ScanImportState,
    ScanInputRecord,
    ScanRole,
)
from lys_bbb_app.domain.study import LegacyProjectRecord, StudySnapshot, SubjectRecord
from lys_bbb_app.domain.t1_analysis import (
    T1EnhancementResultState,
    T1RegistrationState,
)
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
    ReviewItemViewModel,
    ResultViewModel,
    StatusValue,
    StudyViewModel,
    SubjectViewModel,
    T1BrainMaskArtifactViewModel,
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
            study.t1_brain_masks_for_subject(subject.id),
            study.t2_artifacts_for_subject(subject.id),
            study,
        )
        for subject in study.subjects
    )
    results = tuple(
        _present_result(subject, study)
        for subject in study.subjects
        if study.t2_results_for_subject(subject.id)
        or study.t1_enhancement_results_for_subject(subject.id)
    )
    t1_reviews = tuple(
        _present_t1_brain_mask_review_item(subject, artifact, study)
        for subject in study.subjects
        for artifact in study.t1_brain_masks_for_subject(subject.id)
        if artifact.active
        and artifact.state
        in {
            ArtifactState.DRAFT_REVIEW_REQUIRED,
            ArtifactState.CORRECTED_REVIEW_REQUIRED,
        }
    )
    t2_reviews = tuple(
        _present_t2_review_item(subject, artifact, study)
        for subject in study.subjects
        for artifact in study.t2_artifacts_for_subject(subject.id)
        if artifact.active
        and artifact.state
        in {
            ArtifactState.DRAFT_REVIEW_REQUIRED,
            ArtifactState.CORRECTED_REVIEW_REQUIRED,
        }
    )
    reviews = t1_reviews + t2_reviews
    archived_subjects = tuple(
        _present_subject(subject, (), (), (), study)
        for subject in study.archived_subjects
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
    t1_drafts = sum(subject.brain_mask.kind == "review" for subject in subjects)
    t1_approved = sum(subject.brain_mask.kind == "approved" for subject in subjects)
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
    t1_running_jobs = sum(
        job.state is ProcessingJobState.RUNNING
        for job in study.t1_brain_mask_jobs
    )
    t1_eligible = sum(
        subject.can_run_t1_brain_mask
        and (
            subject.t1_brain_mask_artifact is None
            or subject.t1_brain_mask_artifact.state.kind == "outdated"
        )
        for subject in subjects
    )
    active_release = study.active_t2_model_release
    active_t1_release = study.active_t1_brain_mask_release
    review_count = input_reviews + t1_drafts + t2_drafts

    workflows: tuple[WorkflowSummaryViewModel, ...] = ()
    priority_actions: tuple[PriorityActionViewModel, ...] = ()
    if subjects:
        workflows = (
            WorkflowSummaryViewModel(
                "t1",
                "T1 Enhancement",
                "Pre/post T1 import and review-gated enhancement workflow.",
                (
                    StatusValue(f"{t1_drafts} brain masks need review", "review")
                    if t1_drafts
                    else StatusValue(
                        f"{t1_running_jobs} brain-mask job running",
                        "processing",
                    )
                    if t1_running_jobs
                    else StatusValue(f"{t1_input_reviews} need input review", "review")
                    if t1_input_reviews
                    else StatusValue(f"{t1_eligible} ready for mask", "ready")
                    if t1_eligible
                    else WAITING_FOR_INPUT
                ),
                (
                    ("Expected subjects", str(t1_expected)),
                    ("Inputs converted", str(converted_t1)),
                    ("Input reviews", str(t1_input_reviews)),
                    ("Approved brain masks", str(t1_approved)),
                ),
                "Review T1 brain masks" if t1_drafts else "View subjects",
                "reviews" if t1_drafts else "subjects",
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
                "Review T2 masks" if t2_drafts else "View subjects",
                "reviews" if t2_drafts else "subjects",
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
        if t1_eligible:
            priority_actions = (
                PriorityActionViewModel(
                    f"{t1_eligible} subjects are ready for T1 brain-mask generation",
                    (
                        f"Frozen method: {active_t1_release.method_version}"
                        if active_t1_release is not None
                        else "Select the frozen local RS2/M-seam release before starting"
                    ),
                    "ready" if active_t1_release is not None else "review",
                    "subjects",
                ),
            ) + priority_actions
        if t2_drafts:
            priority_actions = (
                PriorityActionViewModel(
                    f"{t2_drafts} draft T2 lesion masks require human review",
                    "Approve or manually edit the current mask in ITK-SNAP",
                    "review",
                    "reviews",
                ),
            ) + priority_actions
        if t1_drafts:
            priority_actions = (
                PriorityActionViewModel(
                    f"{t1_drafts} draft T1 brain masks require human review",
                    "Approve or manually edit the current mask in ITK-SNAP",
                    "review",
                    "reviews",
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
                "MRI inputs or draft masks",
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
        reviews=reviews,
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
        active_t1_brain_mask_release_label=(
            f"RS2-Net/M-seam · {active_t1_release.method_version}"
            if active_t1_release is not None
            else None
        ),
        t1_brain_mask_eligible_subject_count=t1_eligible,
        t1_brain_mask_running_job_count=t1_running_jobs,
    )


def _present_subject(
    subject: SubjectRecord,
    scan_inputs: tuple[ScanInputRecord, ...],
    t1_artifacts,
    t2_artifacts,
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
        (artifact for artifact in t2_artifacts if artifact.active),
        None,
    )
    latest_t2_artifact = active_t2_artifact or next(iter(t2_artifacts), None)
    active_t1_artifact = next(
        (artifact for artifact in t1_artifacts if artifact.active),
        None,
    )
    latest_t1_artifact = active_t1_artifact or next(iter(t1_artifacts), None)
    subject_registrations = study.t1_registrations_for_subject(subject.id)
    active_registration = next(
        (artifact for artifact in subject_registrations if artifact.active),
        None,
    )
    latest_registration = active_registration or next(iter(subject_registrations), None)
    subject_t1_results = study.t1_enhancement_results_for_subject(subject.id)
    active_t1_result = study.active_t1_enhancement_result_for_subject(subject.id)
    latest_t1_result = active_t1_result or next(iter(subject_t1_results), None)
    active_pre_t1 = next(
        (record for record in active if record.role is ScanRole.T1_PRE),
        None,
    )
    pre_t1_valid = (
        active_pre_t1 is not None
        and active_pre_t1.state is ScanImportState.CONVERTED
        and active_pre_t1.validation_state is InputValidationState.VALID
    )
    active_t2_result = study.active_t2_result_for_subject(subject.id)
    t2_job_running = any(
        job.job_type == "T2_LESION_INFERENCE"
        and job.state is ProcessingJobState.RUNNING
        and subject.id in job.subject_ids
        for job in study.processing_jobs
    )
    t1_job_running = any(
        job.state is ProcessingJobState.RUNNING and subject.id in job.subject_ids
        for job in study.t1_brain_mask_jobs
    )
    registration_job_running = any(
        job.state is ProcessingJobState.RUNNING and subject.id in job.subject_ids
        for job in study.t1_registration_jobs
    )
    enhancement_job_running = any(
        job.state is ProcessingJobState.RUNNING and subject.id in job.subject_ids
        for job in study.t1_enhancement_jobs
    )
    brain_mask = (
        StatusValue("Generating draft mask", "processing")
        if t1_job_running
        else StatusValue("Human-approved brain mask", "approved")
        if active_t1_artifact is not None
        and active_t1_artifact.state is ArtifactState.APPROVED
        else StatusValue("Mask · human review required", "review")
        if active_t1_artifact is not None
        and active_t1_artifact.state
        in {
            ArtifactState.DRAFT_REVIEW_REQUIRED,
            ArtifactState.CORRECTED_REVIEW_REQUIRED,
        }
        else StatusValue("Brain mask outdated", "outdated")
        if latest_t1_artifact is not None
        and latest_t1_artifact.state is ArtifactState.OUTDATED
        else StatusValue("Ready for brain mask", "ready")
        if pre_t1_valid
        else NOT_STARTED
        if subject.expected_t1
        else NOT_APPLICABLE
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
        else StatusValue("Result outdated", "outdated")
        if latest_t2_artifact is not None
        and latest_t2_artifact.state is ArtifactState.OUTDATED
        else StatusValue("Ready for segmentation", "ready")
        if t2_data.kind == "ready"
        else NOT_STARTED
        if subject.expected_t2
        else NOT_APPLICABLE
    )
    registration = (
        StatusValue("Registering post-Gd T1", "processing")
        if registration_job_running
        else StatusValue("Human-approved registration", "approved")
        if active_registration is not None
        and active_registration.state is T1RegistrationState.APPROVED
        else StatusValue("Registration · human review required", "review")
        if active_registration is not None
        and active_registration.state is T1RegistrationState.REVIEW_REQUIRED
        else StatusValue("Registration outdated", "outdated")
        if latest_registration is not None
        and latest_registration.state is T1RegistrationState.OUTDATED
        else StatusValue("Ready for registration", "ready")
        if active_t1_artifact is not None
        and active_t1_artifact.state is ArtifactState.APPROVED
        else NOT_STARTED
        if subject.expected_t1
        else NOT_APPLICABLE
    )
    t1_result = (
        StatusValue("Calculating provisional enhancement", "processing")
        if enhancement_job_running
        else StatusValue("Provisional enhancement", "review")
        if active_t1_result is not None
        and active_t1_result.state is T1EnhancementResultState.PROVISIONAL
        else StatusValue("Enhancement result outdated", "outdated")
        if latest_t1_result is not None
        and latest_t1_result.state is T1EnhancementResultState.OUTDATED
        else StatusValue("Ready for provisional calculation", "ready")
        if active_registration is not None
        and active_registration.state is T1RegistrationState.APPROVED
        else NOT_STARTED
        if subject.expected_t1
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
    pre_t1_available = (
        active_pre_t1 is not None
        and active_pre_t1.output_path is not None
        and active_pre_t1.output_path.is_file()
    )
    can_run_t1 = pre_t1_valid and pre_t1_available and not t1_job_running
    t1_blocked_reason = _t1_brain_mask_blocked_reason(
        subject.expected_t1,
        pre_t1_valid,
        pre_t1_available,
        study.active_t1_brain_mask_release is not None,
        t1_job_running,
    )
    ready = t1_data.label == "Inputs validated" or t2_data.label == "T2 validated"
    failed = t1_data.kind == "failed" or t2_data.kind == "failed"
    needs_artifact_review = (
        t2_lesion.kind == "review"
        or brain_mask.kind == "review"
        or registration.kind == "review"
    )
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
        for artifact in t2_artifacts
    )
    history.extend(
        f"T1 brain mask v{artifact.version}: "
        f"{artifact.state.value.replace('_', ' ').title()}"
        for artifact in t1_artifacts
    )
    history.extend(
        f"T1 registration v{artifact.version}: "
        f"{artifact.state.value.replace('_', ' ').title()}"
        for artifact in subject_registrations
    )
    history.extend(
        f"T1 enhancement v{result.version}: "
        f"{result.state.value.replace('_', ' ').title()}"
        for result in subject_t1_results
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
        brain_mask=brain_mask,
        registration=registration,
        t1_result=t1_result,
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
        t1_brain_mask_artifact=(
            _present_t1_brain_mask_artifact(latest_t1_artifact, study)
            if latest_t1_artifact is not None
            else None
        ),
        can_run_t1_brain_mask=can_run_t1,
        t1_brain_mask_blocked_reason=t1_blocked_reason,
        t1_brain_mask_release_label=(
            f"RS2-Net/M-seam · {study.active_t1_brain_mask_release.method_version}"
            if study.active_t1_brain_mask_release is not None
            else None
        ),
    )


def _present_t1_brain_mask_review_item(
    subject: SubjectRecord,
    artifact,
    study: StudySnapshot,
) -> ReviewItemViewModel:
    """Build one actionable queue item for the current unreviewed T1 brain mask."""

    presented = _present_t1_brain_mask_artifact(artifact, study)
    source = next(
        (
            item
            for item in study.inputs_for_subject(subject.id)
            if item.id == artifact.source_scan_input_id
        ),
        None,
    )
    slice_count = (
        int(source.output_shape[-1])
        if source is not None and source.output_shape
        else 1
    )
    corrected = artifact.state is ArtifactState.CORRECTED_REVIEW_REQUIRED
    warning_text = (
        " · ".join(artifact.regularity_warnings)
        if artifact.regularity_warnings
        else "No automatic regularity warnings"
    )
    return ReviewItemViewModel(
        review_id=artifact.id,
        subject_id=subject.id,
        category="T1 brain masks",
        artifact_name=(
            f"ITK-SNAP corrected brain mask · v{artifact.version}"
            if corrected
            else f"RS2-Net/M-seam draft brain mask · v{artifact.version}"
        ),
        reason=(
            "The human-corrected mask requires explicit approval before T1 analysis."
            if corrected
            else "The automatic pre-label requires explicit human review."
        ),
        automatic_qc=(
            f"Mask-volume QC {artifact.volume_mm3:.3f} mm³ · "
            f"{artifact.foreground_voxels:,} foreground voxels · "
            f"{warning_text} · {presented.release_label}"
        ),
        status=presented.state,
        slice_count=slice_count,
        subject_label=subject.subject_code,
        artifact_id=artifact.id,
        qc_preview_path=artifact.qc_preview_path,
        qc_slice_paths=_qc_slice_paths(artifact.qc_preview_path),
        workflow_key="t1_brain_mask",
    )


def _present_t2_review_item(
    subject: SubjectRecord,
    artifact,
    study: StudySnapshot,
) -> ReviewItemViewModel:
    """Build one actionable queue item for the current unreviewed T2 mask."""

    presented = _present_t2_artifact(artifact, study)
    source = next(
        (
            item
            for item in study.inputs_for_subject(subject.id)
            if item.id == artifact.source_scan_input_id
        ),
        None,
    )
    slice_count = (
        int(source.output_shape[-1])
        if source is not None and source.output_shape
        else 1
    )
    corrected = artifact.state is ArtifactState.CORRECTED_REVIEW_REQUIRED
    return ReviewItemViewModel(
        review_id=artifact.id,
        subject_id=subject.id,
        category="T2 lesion masks",
        artifact_name=(
            f"ITK-SNAP corrected lesion mask · v{artifact.version}"
            if corrected
            else f"RatLesNetV2 draft lesion mask · v{artifact.version}"
        ),
        reason=(
            "The human-corrected mask requires explicit approval before measurement."
            if corrected
            else "The automatic prediction requires explicit human review."
        ),
        automatic_qc=(
            f"Provisional volume {artifact.provisional_volume_mm3:.3f} mm³ · "
            f"{artifact.lesion_voxel_count:,} lesion voxels · threshold "
            f"{artifact.threshold:.2f} · {presented.release_label}"
        ),
        status=presented.state,
        slice_count=slice_count,
        subject_label=subject.subject_code,
        artifact_id=artifact.id,
        qc_preview_path=artifact.qc_preview_path,
        qc_slice_paths=_qc_slice_paths(artifact.qc_preview_path),
        workflow_key="t2_lesion",
    )


def _qc_slice_paths(qc_preview_path: Path | None) -> tuple[Path, ...]:
    """Return already-rendered QC slices without loading scientific image data."""

    if qc_preview_path is None:
        return ()
    slice_directory = qc_preview_path.parent / "qc_slices"
    if not slice_directory.is_dir():
        return ()
    return tuple(sorted(slice_directory.glob("slice_*.png")))


def _present_t1_brain_mask_artifact(
    artifact,
    study: StudySnapshot,
) -> T1BrainMaskArtifactViewModel:
    release = next(
        (
            item
            for item in study.t1_brain_mask_releases
            if item.id == artifact.release_id
        ),
        None,
    )
    approval = study.t1_brain_mask_approval_for_artifact(artifact.id)
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
        ArtifactState.OUTDATED: StatusValue("Outdated", "outdated"),
    }[artifact.state]
    return T1BrainMaskArtifactViewModel(
        artifact_id=artifact.id,
        version=artifact.version,
        state=state,
        mask_path=artifact.mask_path,
        raw_mask_path=artifact.raw_mask_path,
        qc_preview_path=artifact.qc_preview_path,
        foreground_voxels=artifact.foreground_voxels,
        volume_text=f"{artifact.volume_mm3:.3f} mm³",
        release_label=(
            release.method_version if release is not None else artifact.release_id
        ),
        device=artifact.device,
        regularity_warnings=artifact.regularity_warnings,
        created_at=_format_timestamp(artifact.created_at),
        source_scan_input_id=artifact.source_scan_input_id,
        origin_label=(
            "ITK-SNAP correction"
            if artifact.origin == "CORRECTED"
            else "RS2-Net/M-seam automatic draft"
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
        reviewer=approval.reviewer if approval is not None else None,
        reviewed_at=(
            _format_timestamp(approval.created_at) if approval is not None else None
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
    t2_result = next(iter(study.t2_results_for_subject(subject.id)), None)
    t1_result = next(iter(study.t1_enhancement_results_for_subject(subject.id)), None)
    if t2_result is None and t1_result is None:
        raise RuntimeError("A result view was requested for a subject without results.")
    t2_state = (
        StatusValue("Human approved", "approved")
        if t2_result is not None
        and t2_result.state is ResultState.APPROVED
        and t2_result.active
        else StatusValue("Outdated", "outdated")
        if t2_result is not None
        else StatusValue("Not available", "unavailable")
    )
    t1_state = (
        StatusValue("Provisional · method validation pending", "review")
        if t1_result is not None
        and t1_result.state is T1EnhancementResultState.PROVISIONAL
        and t1_result.active
        else StatusValue("Outdated", "outdated")
        if t1_result is not None
        else StatusValue("Not available", "unavailable")
    )
    t1_value = "Not available"
    if t1_result is not None:
        percent_row = next(
            (
                row
                for row in t1_result.metrics
                if row.get("metric") == "percent_enhancement"
            ),
            None,
        )
        median = percent_row.get("median") if percent_row is not None else None
        t1_value = f"Median {float(median):.3f}% · provisional" if median else "Provisional"
    versions = tuple(
        version
        for version in (
            (
                next(
                    (
                        method.method_version
                        for method in study.t1_enhancement_methods
                        if t1_result is not None and method.id == t1_result.method_id
                    ),
                    None,
                )
            ),
            t2_result.method_version if t2_result is not None else None,
        )
        if version is not None
    )
    return ResultViewModel(
        subject_id=subject.subject_code,
        group=subject.group_name,
        t1_value=t1_value,
        t1_state=t1_state,
        t2_value=(
            f"{t2_result.lesion_volume_mm3:.3f} mm³"
            if t2_result is not None
            else "Not available"
        ),
        t2_state=t2_state,
        method_version=" · ".join(versions),
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


def _t1_brain_mask_blocked_reason(
    expected: bool,
    pre_t1_valid: bool,
    input_available: bool,
    release_available: bool,
    running: bool,
) -> str | None:
    if not expected:
        return "T1 is marked not applicable for this subject."
    if running:
        return "T1 brain-mask generation is already running for this subject."
    if not pre_t1_valid:
        return "Import, visually review, and validate the native pre-Gd T1 first."
    if not input_available:
        return "The managed pre-Gd T1 NIfTI is unavailable. Reconnect its study storage."
    if not release_available:
        return "Select and validate the frozen local RS2-Net/M-seam release."
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
