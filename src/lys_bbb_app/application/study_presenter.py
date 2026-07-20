"""Build immutable UI view models from persistent study records."""

from __future__ import annotations

from datetime import datetime

from lys_bbb_app.domain.study import StudySnapshot, SubjectRecord
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


def present_study(study: StudySnapshot) -> StudyViewModel:
    """Represent durable Phase 1 state without inventing scientific outputs."""

    subjects = tuple(_present_subject(subject) for subject in study.subjects)
    t1_expected = sum(subject.expected_t1 for subject in study.subjects)
    t2_expected = sum(subject.expected_t2 for subject in study.subjects)
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
                    ("Inputs imported", "0"),
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
                    ("T2 scans imported", "0"),
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
                f"{len(subjects)} subjects are waiting for MRI input assignment",
                "Scientific import arrives in desktop Phase 3",
                "unavailable",
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
        metrics=(
            MetricViewModel("Subjects", str(len(subjects)), "Persisted in this study", "neutral"),
            MetricViewModel("Ready", "0", "No scientific inputs yet", "ready"),
            MetricViewModel("Need review", "0", "No draft artifacts", "review"),
            MetricViewModel("Blocked", "0", "No workflow failures", "failed"),
            MetricViewModel("Complete", "0", "No approved results", "approved"),
        ),
        workflows=workflows,
        priority_actions=priority_actions,
        subjects=subjects,
        reviews=(),
        results=(),
        t1_input_folder=study.t1_input_folder,
        t2_input_folder=study.t2_input_folder,
    )


def _present_subject(subject: SubjectRecord) -> SubjectViewModel:
    expected = " · ".join(
        workflow
        for workflow, enabled in (("T1", subject.expected_t1), ("T2", subject.expected_t2))
        if enabled
    )
    return SubjectViewModel(
        subject_id=subject.id,
        display_id=subject.subject_code,
        group=subject.group_name,
        t1_data=WAITING_FOR_INPUT if subject.expected_t1 else NOT_APPLICABLE,
        brain_mask=NOT_STARTED if subject.expected_t1 else NOT_APPLICABLE,
        registration=NOT_STARTED if subject.expected_t1 else NOT_APPLICABLE,
        t1_result=NOT_STARTED if subject.expected_t1 else NOT_APPLICABLE,
        t2_lesion=WAITING_FOR_INPUT if subject.expected_t2 else NOT_APPLICABLE,
        overall=NOT_STARTED,
        updated=_format_timestamp(subject.updated_at),
        metadata=(
            ("Expected workflows", expected),
            ("Persistent subject ID", subject.id),
        ),
        history=("Subject created in persistent study state",),
    )


def _format_timestamp(value: str) -> str:
    try:
        timestamp = datetime.fromisoformat(value)
    except ValueError:
        return value
    return timestamp.astimezone().strftime("%Y-%m-%d %H:%M")
