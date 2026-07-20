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
from lys_bbb_app.domain.view_models import (
    InputIssueViewModel,
    InputScanViewModel,
    MetricViewModel,
    PriorityActionViewModel,
    StatusValue,
    StudyViewModel,
    SubjectViewModel,
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
    """Represent durable Phase 1 state without inventing scientific outputs."""

    subjects = tuple(
        _present_subject(subject, study.inputs_for_subject(subject.id))
        for subject in study.subjects
    )
    archived_subjects = tuple(
        _present_subject(subject, ()) for subject in study.archived_subjects
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
                    StatusValue(f"{t2_input_reviews} need input review", "review")
                    if t2_input_reviews
                    else StatusValue(f"{t2_validated} ready for mask", "ready")
                    if t2_validated
                    else WAITING_FOR_INPUT
                ),
                (
                    ("Expected subjects", str(t2_expected)),
                    ("T2 scans converted", str(converted_t2)),
                    ("Input reviews", str(t2_input_reviews)),
                    ("Approved volumes", "0"),
                ),
                "View subjects",
                "subjects",
            ),
            WorkflowSummaryViewModel(
                "combined",
                "Combined MRI Results",
                "Approved subject-level T1 and T2 measurements.",
                StatusValue("No results yet", "unavailable"),
                (
                    ("Subjects", str(len(subjects))),
                    ("Complete", "0"),
                    ("Outdated results", "0"),
                    ("Export eligible", "0"),
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
                str(input_reviews),
                "Converted inputs awaiting validation",
                "review",
            ),
            MetricViewModel("Blocked", str(failed_inputs), "Input conversion failures", "failed"),
            MetricViewModel("Complete", "0", "No approved results", "approved"),
        ),
        workflows=workflows,
        priority_actions=priority_actions,
        subjects=subjects,
        reviews=(),
        results=(),
        mri_input_folder=study.mri_input_folder,
        t1_input_folder=study.t1_input_folder,
        t2_input_folder=study.t2_input_folder,
    )


def _present_subject(
    subject: SubjectRecord,
    scan_inputs: tuple[ScanInputRecord, ...],
) -> SubjectViewModel:
    expected = " · ".join(
        workflow
        for workflow, enabled in (("T1", subject.expected_t1), ("T2", subject.expected_t2))
        if enabled
    )
    active = tuple(record for record in scan_inputs if record.active)
    t1_data = _t1_input_status(active) if subject.expected_t1 else NOT_APPLICABLE
    t2_data = _t2_input_status(active) if subject.expected_t2 else NOT_APPLICABLE
    ready = t1_data.label == "Inputs validated" or t2_data.label == "T2 validated"
    failed = t1_data.kind == "failed" or t2_data.kind == "failed"
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
        t2_lesion=NOT_STARTED if subject.expected_t2 else NOT_APPLICABLE,
        overall=(
            StatusValue("Blocked", "failed")
            if failed
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
    )


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
