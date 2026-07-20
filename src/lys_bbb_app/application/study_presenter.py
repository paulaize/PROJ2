"""Build immutable UI view models from persistent study records."""

from __future__ import annotations

from datetime import datetime

from lys_bbb_app.domain.scan_import import ScanImportState, ScanInputRecord, ScanRole
from lys_bbb_app.domain.study import LegacyProjectRecord, StudySnapshot, SubjectRecord
from lys_bbb_app.domain.view_models import (
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

    workflows: tuple[WorkflowSummaryViewModel, ...] = ()
    priority_actions: tuple[PriorityActionViewModel, ...] = ()
    if subjects:
        workflows = (
            WorkflowSummaryViewModel(
                "t1",
                "T1 Enhancement",
                "Pre/post T1 import and review-gated enhancement workflow.",
                WAITING_FOR_INPUT,
                (
                    ("Expected subjects", str(t1_expected)),
                    ("Inputs converted", str(converted_t1)),
                    ("Awaiting review", "0"),
                    ("Approved results", "0"),
                ),
                "View subjects",
                "subjects",
            ),
            WorkflowSummaryViewModel(
                "t2",
                "T2 Lesion",
                "Native T2 and released lesion-mask review workflow.",
                WAITING_FOR_INPUT,
                (
                    ("Expected subjects", str(t2_expected)),
                    ("T2 scans converted", str(converted_t2)),
                    ("Awaiting review", "0"),
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
                    f"{len(subjects)} subjects are available for MRI input review"
                    if active_inputs
                    else f"{len(subjects)} subjects are waiting for MRI discovery"
                ),
                "Choose or review the MRI source folder",
                "review" if active_inputs else "unavailable",
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
                str(sum(subject.overall.label == "Inputs ready" for subject in subjects)),
                "At least one workflow has converted input",
                "ready",
            ),
            MetricViewModel("Need review", "0", "No draft artifacts", "review"),
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
    ready = t1_data.label == "Inputs converted" or t2_data.label == "T2 converted"
    failed = t1_data.kind == "failed" or t2_data.kind == "failed"
    metadata = [
        ("Expected workflows", expected),
        ("Persistent subject ID", subject.id),
    ]
    for record in active:
        value = (
            str(record.output_path)
            if record.output_path is not None
            else f"Failed — {record.error_message}"
            if record.error_message
            else record.state.value.replace("_", " ").title()
        )
        metadata.append((f"{record.role.value} v{record.version}", value))
    history = ["Subject created in persistent study state"]
    history.extend(
        f"{record.role.value} v{record.version}: {record.state.value.replace('_', ' ').title()}"
        for record in scan_inputs
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
            else StatusValue("Inputs ready", "ready")
            if ready
            else NOT_STARTED
        ),
        updated=_format_timestamp(subject.updated_at),
        metadata=tuple(metadata),
        history=tuple(history),
        mri_input_count=sum(
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
        return StatusValue("Inputs converted", "ready")
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
        return StatusValue("T2 converted", "ready")
    return WAITING_FOR_INPUT


def _format_timestamp(value: str) -> str:
    try:
        timestamp = datetime.fromisoformat(value)
    except ValueError:
        return value
    return timestamp.astimezone().strftime("%Y-%m-%d %H:%M")
