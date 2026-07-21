"""Clearly labelled synthetic T1/T2 data for desktop interaction design."""

from __future__ import annotations

from pathlib import Path

from lys_bbb_app.domain.view_models import (
    InputIssueViewModel,
    InputScanViewModel,
    MetricViewModel,
    PriorityActionViewModel,
    ResultViewModel,
    ReviewItemViewModel,
    StatusValue,
    StudyViewModel,
    SubjectViewModel,
    T2LesionArtifactViewModel,
    WorkflowSummaryViewModel,
)


APPROVED = StatusValue("Human approved", "approved")
REVIEW = StatusValue("Awaiting review", "review")
READY = StatusValue("Ready", "ready")
BLOCKED = StatusValue("Blocked", "failed")
PROCESSING = StatusValue("Processing", "processing")
MISSING = StatusValue("Not available", "unavailable")
PROVISIONAL = StatusValue("Provisional", "outdated")
OUTDATED = StatusValue("Result outdated", "outdated")
NOT_APPLICABLE = StatusValue("Not applicable", "neutral")
NOT_STARTED = StatusValue("Not started", "neutral")
WAITING_FOR_MASK = StatusValue("Waiting for mask", "unavailable")
INPUT_REVIEW = StatusValue("Input review required", "review")
INPUTS_VALIDATED = StatusValue("Inputs validated", "ready")
T2_VALIDATED = StatusValue("T2 validated", "ready")


def _demo_t2_artifact(subject_code: str) -> T2LesionArtifactViewModel:
    root = Path(f"/synthetic-preview/{subject_code}/t2-lesion/v001")
    return T2LesionArtifactViewModel(
        artifact_id=f"synthetic-{subject_code}-t2-draft",
        version=1,
        state=StatusValue("Draft · human review required", "review"),
        mask_path=root / "ensemble_mask.nii.gz",
        probability_path=root / "ensemble_probability.nii.gz",
        qc_preview_path=None,
        lesion_voxel_count=1842,
        provisional_volume_text="4.513 mm³",
        threshold_text="0.40",
        release_label="LYS_v1-6069dabd",
        device="mps",
        created_at="Today, 14:42",
        source_scan_input_id=f"synthetic-{subject_code}-T2",
        origin_label="RatLesNetV2 automatic draft",
        can_correct=True,
        can_review=True,
    )


def _demo_inputs(
    subject_code: str,
    *,
    include_t1: bool = True,
    include_t2: bool = True,
    t1_validation: StatusValue = StatusValue("Validated", "ready"),
    t2_validation: StatusValue = StatusValue("Validated", "ready"),
) -> tuple[InputScanViewModel, ...]:
    roles: list[tuple[str, str, StatusValue]] = []
    if include_t1:
        roles.extend(
            (
                ("T1_PRE", "Pre-Gd T1", t1_validation),
                ("T1_POST", "Post-Gd T1", t1_validation),
            )
        )
    if include_t2:
        roles.append(("T2", "T2-weighted", t2_validation))
    return tuple(
        InputScanViewModel(
            scan_input_id=f"synthetic-{subject_code}-{role}",
            role=role,
            role_label=role_label,
            version=1,
            conversion=StatusValue("Converted", "ready"),
            validation=validation,
            managed_path=Path(
                f"/synthetic-preview/{subject_code}/inputs/{role.lower()}/v001/image.nii.gz"
            ),
            source_path=Path(f"/synthetic-source/{subject_code}/{role.lower()}"),
            shape_text="256 × 256 × 18" if role == "T2" else "128 × 128 × 176",
            spacing_text=(
                "0.07 × 0.07 × 0.5 mm"
                if role == "T2"
                else "0.156 × 0.156 × 0.156 mm"
            ),
            orientation_text="L I P" if role == "T2" else "R A S",
            transformation_text=(
                "T1 Coronal · flipped X" if role.startswith("T1") else "Native"
            ),
            checksum_text="71c83d0eaa42…",
            issues=(
                (
                    InputIssueViewModel(
                        "SYNTHETIC_VALIDATION_EXAMPLE",
                        "error",
                        "Example geometry problem for design review.",
                    ),
                )
                if validation.kind == "failed"
                else ()
            ),
            can_open=False,
        )
        for role, role_label, validation in roles
    )


def demo_study() -> StudyViewModel:
    """Return a representative T1/T2 study for UI design review."""

    subjects = (
        SubjectViewModel(
            subject_id="Mouse-001",
            group="Treatment A",
            t1_data=INPUT_REVIEW,
            brain_mask=REVIEW,
            registration=WAITING_FOR_MASK,
            t1_result=BLOCKED,
            t2_data=INPUT_REVIEW,
            t2_lesion=REVIEW,
            overall=REVIEW,
            updated="Today, 14:42",
            metadata=(
                ("Timepoint", "D1"),
                ("Expected workflows", "T1 · T2"),
                ("Lesion side", "Left"),
            ),
            history=(
                "Draft T2 lesion mask imported · 14:42",
                "T1 pair validated · 13:08",
            ),
            inputs=_demo_inputs(
                "Mouse-001",
                t1_validation=StatusValue("Review required", "review"),
                t2_validation=StatusValue("Review required", "review"),
            ),
            can_validate_inputs=True,
            t2_artifact=_demo_t2_artifact("Mouse-001"),
            t2_inference_blocked_reason="Validate the current T2 input first.",
            t2_release_label="RatLesNetV2 five-fold ensemble · LYS_v1-6069dabd",
        ),
        SubjectViewModel(
            subject_id="Mouse-002",
            group="Treatment A",
            t1_data=INPUTS_VALIDATED,
            brain_mask=APPROVED,
            registration=REVIEW,
            t1_result=BLOCKED,
            t2_data=T2_VALIDATED,
            t2_lesion=APPROVED,
            overall=REVIEW,
            updated="Today, 13:17",
            metadata=(("Timepoint", "D1"), ("Expected workflows", "T1 · T2")),
            history=(
                "Registration completed · 13:17",
                "Brain mask approved · Yesterday",
            ),
            inputs=_demo_inputs("Mouse-002"),
        ),
        SubjectViewModel(
            subject_id="Mouse-003",
            group="Treatment B",
            t1_data=INPUTS_VALIDATED,
            brain_mask=APPROVED,
            registration=APPROVED,
            t1_result=PROVISIONAL,
            t2_data=T2_VALIDATED,
            t2_lesion=APPROVED,
            overall=PROVISIONAL,
            updated="Yesterday",
            metadata=(("Timepoint", "D7"), ("Expected workflows", "T1 · T2")),
            history=("T1 measurement generated with development method v0.3",),
            inputs=_demo_inputs("Mouse-003"),
        ),
        SubjectViewModel(
            subject_id="Mouse-004",
            group="Treatment B",
            t1_data=INPUTS_VALIDATED,
            brain_mask=PROCESSING,
            registration=NOT_STARTED,
            t1_result=BLOCKED,
            t2_data=NOT_APPLICABLE,
            t2_lesion=NOT_APPLICABLE,
            overall=PROCESSING,
            updated="Today, 14:54",
            metadata=(("Timepoint", "D1"), ("Expected workflows", "T1 only")),
            history=("Draft brain mask job started · 14:54",),
            inputs=_demo_inputs("Mouse-004", include_t2=False),
        ),
        SubjectViewModel(
            subject_id="Mouse-005",
            group="Vehicle",
            t1_data=INPUTS_VALIDATED,
            brain_mask=StatusValue("Rejected", "failed"),
            registration=WAITING_FOR_MASK,
            t1_result=BLOCKED,
            t2_data=T2_VALIDATED,
            t2_lesion=READY,
            overall=BLOCKED,
            updated="Monday",
            metadata=(("Timepoint", "D1"), ("Expected workflows", "T1 · T2")),
            history=("Brain mask rejected: superior false positive · Monday",),
            inputs=_demo_inputs("Mouse-005"),
            can_run_t2_inference=True,
            t2_release_label="RatLesNetV2 five-fold ensemble · LYS_v1-6069dabd",
        ),
        SubjectViewModel(
            subject_id="Mouse-006",
            group="Vehicle",
            t1_data=INPUTS_VALIDATED,
            brain_mask=APPROVED,
            registration=APPROVED,
            t1_result=OUTDATED,
            t2_data=T2_VALIDATED,
            t2_lesion=APPROVED,
            overall=OUTDATED,
            updated="Friday",
            metadata=(("Timepoint", "D7"), ("Expected workflows", "T1 · T2")),
            history=(
                "Approved brain mask replaced; T1 result marked outdated · Friday",
            ),
            inputs=_demo_inputs("Mouse-006"),
        ),
        SubjectViewModel(
            subject_id="Mouse-007",
            group=None,
            t1_data=StatusValue("Validation failed", "failed"),
            brain_mask=NOT_STARTED,
            registration=NOT_STARTED,
            t1_result=BLOCKED,
            t2_data=NOT_APPLICABLE,
            t2_lesion=NOT_APPLICABLE,
            overall=BLOCKED,
            updated="Thursday",
            metadata=(("Timepoint", "D1"), ("Expected workflows", "T1 only")),
            history=(
                "Post-Gd image dimensions do not match expected acquisition · Thursday",
            ),
            inputs=_demo_inputs(
                "Mouse-007",
                include_t2=False,
                t1_validation=StatusValue("Validation failed", "failed"),
            ),
        ),
        SubjectViewModel(
            subject_id="Mouse-008",
            group="Treatment B",
            t1_data=MISSING,
            brain_mask=NOT_APPLICABLE,
            registration=NOT_APPLICABLE,
            t1_result=NOT_APPLICABLE,
            t2_data=T2_VALIDATED,
            t2_lesion=APPROVED,
            overall=APPROVED,
            updated="Wednesday",
            metadata=(("Timepoint", "24H"), ("Expected workflows", "T2 only")),
            history=("Native T2 lesion volume approved · Wednesday",),
            inputs=_demo_inputs("Mouse-008", include_t1=False),
        ),
    )

    reviews = (
        ReviewItemViewModel(
            "review-001",
            "Mouse-001",
            "Brain masks",
            "RS2-Net draft brain mask · v1",
            "Automatic QC: possible superior skull inclusion",
            "Brain coverage 98.1% · edge contact warning",
            REVIEW,
            176,
        ),
        ReviewItemViewModel(
            "review-002",
            "Mouse-002",
            "Registrations",
            "Rigid post-Gd → pre-Gd registration · v1",
            "Visual decision required",
            "Cross-correlation improved 0.61 → 0.84",
            REVIEW,
            176,
        ),
        ReviewItemViewModel(
            "review-003",
            "Mouse-001",
            "T2 lesion masks",
            "RatLesNetV2 draft lesion mask · v1",
            "Human review required by release policy",
            "Native-grid mask · postprocessing none",
            REVIEW,
            24,
        ),
        ReviewItemViewModel(
            "review-004",
            "Mouse-003",
            "Results",
            "T1 enhancement result · method v0.3",
            "Method remains provisional",
            "All upstream artifacts approved",
            REVIEW,
            176,
        ),
    )

    results = (
        ResultViewModel(
            "Mouse-003",
            "Treatment B",
            "12.4 a.u.",
            PROVISIONAL,
            "8.72 mm³",
            APPROVED,
            "T1 v0.3 · T2 v1.0",
        ),
        ResultViewModel(
            "Mouse-006",
            "Vehicle",
            "Outdated",
            OUTDATED,
            "2.14 mm³",
            APPROVED,
            "T1 v0.3 · T2 v1.0",
        ),
        ResultViewModel(
            "Mouse-008",
            "Treatment B",
            "Not applicable",
            NOT_APPLICABLE,
            "11.31 mm³",
            APPROVED,
            "T2 v1.0",
        ),
        ResultViewModel(
            "Mouse-001",
            "Treatment A",
            "Awaiting review",
            REVIEW,
            "Awaiting review",
            REVIEW,
            "—",
        ),
    )

    return StudyViewModel(
        study_id="demo-lys-2026",
        name="LYS Design Preview 2026",
        root_path=None,
        description="Synthetic subjects for reviewing the desktop workflow and visual design.",
        schema_version=6,
        last_opened="Design preview",
        is_demo=True,
        metrics=(
            MetricViewModel("Subjects", "24", "8 shown in preview", "neutral"),
            MetricViewModel("Ready", "16", "At least one available action", "ready"),
            MetricViewModel("Need review", "8", "Across T1 and T2", "review"),
            MetricViewModel("Blocked", "2", "Input or approval issue", "failed"),
            MetricViewModel("Complete", "10", "All expected workflows", "approved"),
        ),
        workflows=(
            WorkflowSummaryViewModel(
                "t1",
                "T1 Enhancement",
                "Semi-quantitative post-Gd enhancement in native pre-Gd space.",
                StatusValue("Review required", "review"),
                (
                    ("Valid T1 pairs", "21"),
                    ("Masks awaiting review", "8"),
                    ("Registrations awaiting review", "3"),
                    ("Approved results", "0"),
                ),
                "View T1 tasks",
                "reviews",
            ),
            WorkflowSummaryViewModel(
                "t2",
                "T2 Lesion",
                "Reviewed native-space lesion masks and volume in mm³.",
                StatusValue("1 ready for inference", "ready"),
                (
                    ("T2 scans", "18"),
                    ("Draft masks", "12"),
                    ("Awaiting review", "5"),
                    ("Approved volumes", "7"),
                ),
                "View T2 tasks",
                "reviews",
            ),
            WorkflowSummaryViewModel(
                "combined",
                "Combined MRI Results",
                "Subject-level T1 and T2 table preserving approvals and missing data.",
                StatusValue("6 subjects ready", "ready"),
                (
                    ("Both workflows", "9"),
                    ("Missing workflow", "6"),
                    ("Outdated results", "1"),
                    ("Export eligible", "7"),
                ),
                "View combined results",
                "results",
            ),
        ),
        priority_actions=(
            PriorityActionViewModel(
                "8 brain masks require review",
                "Highest priority · T1 workflow",
                "review",
                "reviews",
            ),
            PriorityActionViewModel(
                "3 registrations require review",
                "T1 alignment decisions",
                "review",
                "reviews",
            ),
            PriorityActionViewModel(
                "2 T2 masks have incomplete provenance",
                "Release metadata required",
                "failed",
                "subjects",
            ),
            PriorityActionViewModel(
                "6 subjects are ready for quantification",
                "Run-ready T1 or T2 jobs",
                "ready",
                "subjects",
            ),
        ),
        subjects=subjects,
        reviews=reviews,
        results=results,
        active_t2_release_label="RatLesNetV2 five-fold ensemble · LYS_v1-6069dabd",
        t2_eligible_subject_count=1,
    )
