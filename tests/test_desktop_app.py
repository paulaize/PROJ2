"""Focused offscreen tests for the connected desktop application."""

from __future__ import annotations

from dataclasses import replace
import os
from pathlib import Path

import nibabel as nib
import numpy as np
import pytest


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QIcon, QPixmap  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QApplication,
    QDialog,
    QFileDialog,
    QLabel,
    QMessageBox,
    QPushButton,
)

from lys_bbb.scan_discovery import discover_mri_source  # noqa: E402
from lys_bbb_app.application.study_presenter import present_study  # noqa: E402
from lys_bbb_app.domain.scan_import import ScanRole  # noqa: E402
from lys_bbb_app.domain.study import (  # noqa: E402
    AnalysisScope,
    CreateStudyRequest,
    CreateSubjectRequest,
)
from lys_bbb_app.domain.view_models import (  # noqa: E402
    ReviewItemViewModel,
    StatusValue,
    StudyViewModel,
)
from lys_bbb_app.features import (  # noqa: E402
    FULL_FEATURES,
    active_features,
    features_for_profile,
)
from lys_bbb_app.main import application_icon_path, parse_args  # noqa: E402
from lys_bbb_app.services.recent_studies_service import (  # noqa: E402
    RecentStudiesService,
)
from lys_bbb_app.services.study_service import StudyService  # noqa: E402
from lys_bbb_app.ui.dialogs import (  # noqa: E402
    AddSubjectDialog,
    CreateStudyDialog,
    GroupAssignmentDialog,
    RestoreSubjectDialog,
    UnblindingDialog,
)
from lys_bbb_app.ui.main_window import MainWindow  # noqa: E402
from lys_bbb_app.ui.reviews import ReviewsPage  # noqa: E402
from lys_bbb_app.ui.scan_import_dialog import ScanImportReviewDialog  # noqa: E402
from lys_bbb_app.ui.widgets import CollapsibleSection, ElidedLabel  # noqa: E402


@pytest.fixture(scope="module")
def qt_app():
    app = QApplication.instance() or QApplication([])
    yield app
    app.closeAllWindows()


def _empty_study_view(tmp_path: Path) -> StudyViewModel:
    return StudyViewModel(
        study_id="study",
        name="Study",
        root_path=tmp_path,
        metrics=(),
        workflows=(),
        priority_actions=(),
        subjects=(),
        reviews=(),
        results=(),
    )


def test_launcher_accepts_only_an_optional_project_path() -> None:
    assert parse_args([]).project is None
    assert parse_args(["/tmp/study"]).project == Path("/tmp/study")


def test_launcher_uses_the_lys_logo_without_a_platform_override(
    qt_app: QApplication,
    tmp_path: Path,
) -> None:
    default_icon = application_icon_path({})
    assert default_icon == (
        Path(__file__).resolve().parents[1]
        / "packaging"
        / "assets"
        / "lys-irm-icon.png"
    )
    assert not QIcon(str(default_icon)).isNull()

    override = tmp_path / "custom-icon.png"
    override.write_bytes(default_icon.read_bytes())
    assert application_icon_path({"LYS_IRM_ICON": str(override)}) == override


def test_full_profile_uses_antspyx_and_exposes_atlas_entry_points(
    qt_app: QApplication,
    tmp_path: Path,
) -> None:
    assert active_features({}) is FULL_FEATURES
    assert features_for_profile("full") is FULL_FEATURES
    assert FULL_FEATURES.ants_backend == "antspyx"
    with pytest.raises(ValueError, match="Unknown LYS IRM feature profile"):
        features_for_profile("unexpected")

    atlas_review = ReviewItemViewModel(
        subject_id="stable-subject-id",
        subject_label="Mouse-001",
        category="Atlas mappings",
        artifact_name="Atlas to pre-T1 candidate",
        reason="Human review required",
        automatic_qc="Stored registration candidate.",
        status=StatusValue("Awaiting review", "review"),
        artifact_id="atlas-v1",
        workflow_key="atlas_to_t1",
    )
    t1_review = replace(
        atlas_review,
        artifact_id="registration-v1",
        workflow_key="t1_registration",
        category="T1 registrations",
        artifact_name="Post-Gd to pre-Gd registration",
    )
    study = replace(
        _empty_study_view(tmp_path),
        reviews=(atlas_review, t1_review),
    )

    window = MainWindow(features=FULL_FEATURES)
    window._set_study(study)
    qt_app.processEvents()

    assert window.windowTitle() == "LYS IRM"
    assert window.workspace_page.atlas_mapping_panel is not None
    assert set(window.reviews_page.modality_buttons) == {"T1", "T2", "Atlas"}
    assert window.reviews_page.reviews == (atlas_review, t1_review)
    window.close()


def test_elided_label_preserves_and_reveals_the_complete_value(
    qt_app: QApplication,
) -> None:
    full_value = "/external-drive/" + "/nested-folder" * 20 + "/scan.nii.gz"
    label = ElidedLabel(full_value)
    label.resize(180, 28)
    label.show()
    qt_app.processEvents()

    assert label.full_text == full_value
    assert label.text() != full_value
    assert "…" in label.text()
    assert label.toolTip() == full_value

    label.resize(2400, 28)
    qt_app.processEvents()
    assert label.text() == full_value
    assert label.toolTip() == ""
    label.close()


def test_technical_details_are_collapsed_but_accessible(
    qt_app: QApplication,
) -> None:
    section = CollapsibleSection()
    section.show()
    qt_app.processEvents()

    assert not section.is_expanded
    assert section.content.isHidden()
    section.set_expanded(True)
    qt_app.processEvents()
    assert section.is_expanded
    assert not section.content.isHidden()
    section.close()


def test_shell_has_specific_scientific_identity_and_plain_navigation(
    qt_app: QApplication,
    tmp_path: Path,
) -> None:
    window = MainWindow(
        recent_studies=RecentStudiesService(tmp_path / "preferences" / "recent.json")
    )

    assert window.windowTitle() == "LYS IRM"
    assert [
        button.text().replace("&&", "&") for button in window.nav_buttons.values()
    ] == [
        "Overview",
        "Subjects",
        "Reviews",
        "Results & exports",
        "Settings",
    ]
    assert window.workspace_page.next_action_card.objectName() == "nextActionCard"
    assert (
        window.workspace_page.tabs.tabText(2)
        == "T1 Registration + Result"
    )
    subject_actions = {
        button.text(): button.property("kind")
        for button in window.subjects_page.findChildren(QPushButton)
    }
    assert subject_actions["Import MRI folder…"] is None
    assert subject_actions["Add subject"] == "secondary"
    assert subject_actions["Run T2 segmentation…"] == "secondary"
    window.close()


def test_create_study_dialog_derives_hidden_identifier_from_name(
    qt_app: QApplication,
    tmp_path: Path,
) -> None:
    dialog = CreateStudyDialog()
    dialog.name.setText("  EAE Pilot / 2026  ")
    assert Path(dialog.root_path.text()).name == "eae-pilot-2026"
    dialog.root_path.setText(str(tmp_path / "eae-pilot"))

    request = dialog.request(actor="QA Researcher")

    assert request.name == "EAE Pilot / 2026"
    assert request.identifier == "eae-pilot-2026"
    assert request.analysis_scope is AnalysisScope.T1_T2
    assert not any(
        label.text() == "Study identifier"
        for label in dialog.findChildren(QLabel)
    )
    dialog.accept()
    assert dialog.result() == QDialog.DialogCode.Accepted
    dialog.close()


@pytest.mark.parametrize(
    ("scope", "expected_tabs", "t1_hidden", "t2_hidden"),
    (
        (
            AnalysisScope.T1_ONLY,
            ("Inputs", "T1 Brain Mask", "T1 Registration + Result", "History"),
            False,
            True,
        ),
        (
            AnalysisScope.T2_ONLY,
            ("Inputs", "T2 Lesion", "History"),
            True,
            False,
        ),
    ),
)
def test_single_modality_study_removes_irrelevant_ui(
    qt_app: QApplication,
    tmp_path: Path,
    scope: AnalysisScope,
    expected_tabs: tuple[str, ...],
    t1_hidden: bool,
    t2_hidden: bool,
) -> None:
    service = StudyService()
    service.create_study(
        CreateStudyRequest(
            tmp_path / scope.value.lower(),
            "Scoped study",
            scope.value.lower(),
            analysis_scope=scope,
            actor="Reviewer A",
        )
    )
    snapshot = service.add_subject(
        CreateSubjectRequest(
            "Mouse-001",
            scope.includes_t1,
            scope.includes_t2,
            actor="Reviewer A",
        )
    )
    window = MainWindow(
        study_service=service,
        recent_studies=RecentStudiesService(
            tmp_path / f"{scope.value.lower()}-preferences" / "recent.json"
        ),
    )
    window._set_study(present_study(snapshot))
    window.open_subject(snapshot.subjects[0].id)
    qt_app.processEvents()

    assert window.current_study.analysis_scope is scope
    assert [workflow.key for workflow in window.current_study.workflows] == [
        "t1" if scope.includes_t1 else "t2"
    ]
    assert window.subjects_page.table.isColumnHidden(2) is t1_hidden
    assert window.subjects_page.table.isColumnHidden(3) is t2_hidden
    assert window.results_page.table.isColumnHidden(2) is t1_hidden
    assert window.results_page.table.isColumnHidden(3) is t2_hidden
    assert window.subjects_page.run_t2.isHidden() is (not scope.includes_t2)
    assert window.reviews_page.modality_buttons["T1"].isHidden() is t1_hidden
    assert window.reviews_page.modality_buttons["T2"].isHidden() is t2_hidden
    assert tuple(
        window.workspace_page.tabs.tabText(index)
        for index in range(window.workspace_page.tabs.count())
        if window.workspace_page.tabs.isTabVisible(index)
    ) == expected_tabs
    assert window.workspace_page.t1_summary.isHidden() is t1_hidden
    assert window.workspace_page.t2_summary.isHidden() is t2_hidden
    window.close()


def test_creation_dialog_records_selected_analysis_scope(
    qt_app: QApplication,
) -> None:
    dialog = CreateStudyDialog()
    dialog.analysis_scope.setCurrentIndex(
        dialog.analysis_scope.findData(AnalysisScope.T2_ONLY)
    )

    assert dialog.request(actor="QA Researcher").analysis_scope is AnalysisScope.T2_ONLY
    dialog.close()


def test_add_subject_inherits_scope_without_extra_workflow_fields(
    qt_app: QApplication,
) -> None:
    dialog = AddSubjectDialog(
        blinded=True,
        analysis_scope=AnalysisScope.T2_ONLY,
    )
    dialog.subject_code.setText("Mouse-001")

    request = dialog.request(actor="QA Researcher")

    assert request.expected_t1 is False
    assert request.expected_t2 is True
    assert not any(
        label.text() == "Expected workflows"
        for label in dialog.findChildren(QLabel)
    )
    dialog.close()


def test_overview_workflow_grid_reflows_at_supported_window_sizes(
    qt_app: QApplication,
    tmp_path: Path,
) -> None:
    service = StudyService()
    service.create_study(
        CreateStudyRequest(
            tmp_path / "responsive-study",
            "Responsive study",
            "responsive-study",
            actor="QA Researcher",
        )
    )
    service.add_subject(
        CreateSubjectRequest("Mouse-001", True, True, actor="QA Researcher")
    )
    window = MainWindow(
        study_service=service,
        recent_studies=RecentStudiesService(tmp_path / "preferences" / "recent.json"),
    )
    window.resize(1180, 760)
    window._set_study(present_study(service.current_study))
    window.show()
    qt_app.processEvents()
    assert window.overview_page._workflow_column_count == 2

    window.resize(1440, 900)
    qt_app.processEvents()
    assert window.overview_page._workflow_column_count == 3
    window.close()


def test_persistent_review_queue_emits_connected_t2_actions(
    qt_app: QApplication,
    tmp_path: Path,
) -> None:
    qc_slices = []
    for index in range(3):
        path = tmp_path / "qc_slices" / f"slice_{index + 1:04d}.png"
        path.parent.mkdir(exist_ok=True)
        pixmap = QPixmap(12, 12)
        pixmap.fill(Qt.GlobalColor.black)
        assert pixmap.save(str(path))
        qc_slices.append(path)
    review = ReviewItemViewModel(
        subject_id="stable-subject-id",
        subject_label="Mouse-001",
        category="T2 lesion masks",
        artifact_name="T2 lesion mask v1",
        reason="Human review required",
        automatic_qc="Native-space draft produced by the frozen release.",
        status=StatusValue("Awaiting review", "review"),
        artifact_id="artifact-t2-v1",
        qc_preview_path=qc_slices[1],
        qc_slice_paths=tuple(qc_slices),
    )
    base = _empty_study_view(tmp_path)
    page = ReviewsPage()
    page.set_study(replace(base, reviews=(review,)))
    approvals: list[tuple[str, str]] = []
    edits: list[tuple[str, str]] = []
    subjects: list[str] = []
    page.approve_requested.connect(
        lambda subject_id, artifact_id: approvals.append((subject_id, artifact_id))
    )
    page.manual_edit_requested.connect(
        lambda subject_id, artifact_id: edits.append((subject_id, artifact_id))
    )
    page.subject_requested.connect(subjects.append)

    assert set(page.modality_buttons) == {"T1", "T2"}
    assert len(page.queue_buttons) == 1
    assert page.queue_buttons[0].text() == "Mouse-001 — T2 lesion"
    assert page.approve.isEnabled()
    assert not page.previous_slice.isHidden()
    assert page.slice_label.text() == "Slice 2 / 3"
    assert not page.technical_details.is_expanded
    page.next_slice.click()
    assert page.slice_label.text() == "Slice 3 / 3"

    page.approve.click()
    page.manual_edit.click()
    page.open_subject.click()
    qt_app.processEvents()

    assert approvals == [("stable-subject-id", "artifact-t2-v1")]
    assert edits == [("stable-subject-id", "artifact-t2-v1")]
    assert subjects == ["stable-subject-id"]
    page.close()


def test_registration_review_uses_qc_approval_without_mask_editing(
    qt_app: QApplication,
    tmp_path: Path,
) -> None:
    qc_path = tmp_path / "registration_qc.png"
    pixmap = QPixmap(24, 24)
    pixmap.fill(Qt.GlobalColor.black)
    assert pixmap.save(str(qc_path))
    review = ReviewItemViewModel(
        subject_id="stable-subject-id",
        subject_label="Mouse-001",
        category="T1 registrations",
        artifact_name="Post-Gd to pre-Gd registration · v1",
        reason="Inspect registration QC before approval.",
        automatic_qc="Cross-correlation 0.500 → 0.800",
        status=StatusValue("Registration · human review required", "review"),
        artifact_id="registration-v1",
        qc_preview_path=qc_path,
        workflow_key="t1_registration",
        approve_label="Approve registration",
        can_manual_edit=False,
        supports_slice_qc=False,
    )
    base = _empty_study_view(tmp_path)
    page = ReviewsPage()
    page.set_study(replace(base, reviews=(review,)))
    approvals: list[tuple[str, str]] = []
    qc_requests: list[tuple[str, str]] = []
    page.approve_requested.connect(
        lambda subject_id, artifact_id: approvals.append((subject_id, artifact_id))
    )
    page.qc_slices_requested.connect(
        lambda subject_id, artifact_id: qc_requests.append((subject_id, artifact_id))
    )
    qt_app.processEvents()

    assert page.queue_buttons[0].text() == "Mouse-001 — T1 registration"
    assert page.approve.text() == "Approve registration"
    assert page.manual_edit.isHidden()
    assert page.previous_slice.isHidden()
    assert qc_requests == []
    page.approve.click()
    assert approvals == [("stable-subject-id", "registration-v1")]
    page.close()


def test_persistent_study_adds_reopens_unblinds_and_groups_subjects(
    qt_app: QApplication,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = StudyService()
    study = service.create_study(
        CreateStudyRequest(
            root_path=tmp_path / "persistent-study",
            name="Persistent study",
            identifier="persistent-study",
            actor="Reviewer A",
        )
    )
    service.close_study()
    recent_studies = RecentStudiesService(tmp_path / "preferences" / "recent.json")
    window = MainWindow(study_service=service, recent_studies=recent_studies)

    assert window.open_project_path(study.root_path) is True
    assert window.current_study is not None
    assert window.subjects_page.proxy.rowCount() == 0
    assert window.study_banner.isHidden()
    assert window.study_banner.text() == ""
    assert window.jobs_label.isHidden()
    window.show_page("results")
    assert (
        window.results_page.results_stack.currentWidget()
        is window.results_page.results_empty
    )
    assert window.results_page.approved_only.text() == "Show approved results only"
    assert window.results_page.show_method_details.text() == "Show technical details"
    assert not window.results_page.approved_csv.isEnabled()
    assert window.results_page.approved_only.isHidden()
    assert window.results_page.export_card.isHidden()

    monkeypatch.setattr(AddSubjectDialog, "exec", lambda _dialog: QDialog.Accepted)
    monkeypatch.setattr(
        AddSubjectDialog,
        "request",
        lambda _dialog, actor: CreateSubjectRequest(
            "Mouse-P01",
            True,
            True,
            actor=actor,
        ),
    )
    window.add_subject()
    qt_app.processEvents()
    assert window.subjects_page.proxy.rowCount() == 1
    assert (
        window.subjects_page.model.data(
            window.subjects_page.model.index(0, 0),
            Qt.DisplayRole,
        )
        == "Mouse-P01"
    )
    subject_id = window.current_study.subjects[0].subject_id
    window.open_subject(subject_id)
    assert window.workspace_page.next_action_title.text() == "Add MRI inputs"
    assert window.workspace_page.next_action_button.text() == "Add MRI inputs"
    assert not window.workspace_page.technical_details.is_expanded
    assert window.workspace_page.tabs.count() == 6
    assert window.workspace_page.tabs.tabText(4) == "Atlas Mapping"
    atlas_panel = window.workspace_page.atlas_mapping_panel
    assert atlas_panel.configure_resource.isEnabled()
    assert not atlas_panel.run_atlas.isEnabled()
    assert not atlas_panel.run_t1_t2.isEnabled()
    assert not atlas_panel.create_composite.isEnabled()
    assert not atlas_panel.calculate_result.isEnabled()
    assert window.subjects_page.model.columnCount() == 5
    assert window.subjects_page.group_filter.isHidden()

    monkeypatch.setattr(UnblindingDialog, "exec", lambda _dialog: QDialog.Accepted)
    monkeypatch.setattr(GroupAssignmentDialog, "exec", lambda _dialog: QDialog.Accepted)
    monkeypatch.setattr(
        GroupAssignmentDialog,
        "assignments",
        lambda dialog: {next(iter(dialog.group_selectors)): "Treatment A"},
    )
    window.manage_groups()
    qt_app.processEvents()
    assert window.current_study is not None
    assert window.current_study.blinded_review is False
    assert window.current_study.subjects[0].group == "Treatment A"
    assert not window.subjects_page.group_filter.isHidden()

    window.close_study()
    assert window.open_project_path(study.root_path) is True
    assert window.current_study is not None
    assert len(window.current_study.subjects) == 1
    assert window.current_study.subjects[0].label == "Mouse-P01"
    assert window.current_study.subjects[0].group == "Treatment A"
    assert [event.event_type for event in service.list_audit_events()[:2]] == [
        "STUDY_OPENED",
        "SUBJECT_GROUPS_ASSIGNED",
    ]
    window.close()


def test_mri_folder_flow_reviews_and_converts_discovered_nifti_off_gui_thread(
    qt_app: QApplication,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = StudyService()
    study = service.create_study(
        CreateStudyRequest(
            root_path=tmp_path / "import-study",
            name="Import study",
            identifier="import-study",
            actor="Reviewer A",
        )
    )
    source_root = tmp_path / "external-drive" / "mri"
    source_root.mkdir(parents=True)
    source = source_root / "C1S1_D1_t2w.nii.gz"
    nib.save(
        nib.Nifti1Image(np.ones((3, 4, 5), dtype=np.float32), np.eye(4)),
        source,
    )
    window = MainWindow(
        study_service=service,
        recent_studies=RecentStudiesService(
            tmp_path / "preferences" / "recent.json"
        ),
    )
    assert window.open_project_path(study.root_path)
    monkeypatch.setattr(
        QFileDialog,
        "getExistingDirectory",
        lambda *_args, **_kwargs: str(source_root),
    )
    monkeypatch.setattr(ScanImportReviewDialog, "exec", lambda _dialog: QDialog.Accepted)

    window.select_mri_source_folder()
    thread = window._background_jobs.get("scan_import")
    assert thread is not None
    assert thread.wait(5000)
    for _ in range(10):
        qt_app.processEvents()

    snapshot = service.current_study
    assert snapshot is not None
    assert snapshot.mri_input_folder == source_root.resolve()
    assert len(snapshot.subjects) == 1
    assert snapshot.subjects[0].subject_code == "C1S1_D1"
    assert snapshot.scan_inputs[0].state.value == "CONVERTED"
    assert snapshot.scan_inputs[0].output_path is not None
    assert snapshot.scan_inputs[0].output_path.is_file()
    assert window.subjects_page.proxy.rowCount() == 1
    assert window.current_study is not None
    subject_id = window.current_study.subjects[0].subject_id
    assert window.current_study.subjects[0].t2_data.label == "Input review required"
    assert window.current_study.subjects[0].t2_lesion.label == "Not started"
    assert window.subjects_page.model.data(
        window.subjects_page.model.index(0, 1),
        Qt.DisplayRole,
    ) == "Validate selected conversion"
    assert window.subjects_page.model.data(
        window.subjects_page.model.index(0, 3),
        Qt.DisplayRole,
    ) == "Input review required"

    window.subjects_page.table.selectRow(0)
    qt_app.processEvents()
    assert window.subjects_page.validate_selected.isEnabled()
    window.subjects_page.validate_selected.click()
    validation_thread = window._background_jobs.get("input_validation")
    assert validation_thread is not None
    assert validation_thread.wait(5000)
    for _ in range(10):
        qt_app.processEvents()

    assert window.current_study is not None
    assert window.current_study.subjects[0].t2_data.label == "T2 validated"
    assert window.current_study.subjects[0].overall.label == "Ready for analysis"
    assert (
        window.content_stack.currentIndex()
        == window.page_indices["subjects"]
    )
    window.open_subject(subject_id)
    input_panel = window.workspace_page.inputs_panel
    assert len(input_panel.scan_cards) == 1
    technical_sections = input_panel.findChildren(CollapsibleSection)
    assert technical_sections
    assert all(not section.is_expanded for section in technical_sections)
    reopened = service.open_study(study.root_path)
    assert reopened.scan_inputs[0].validation_state.value == "VALID"
    assert any(
        event.event_type == "MRI_INPUTS_VALIDATED"
        for event in service.list_audit_events()
    )
    window.close()


def test_scan_review_can_exclude_and_restore_an_entire_discovered_subject(
    qt_app: QApplication,
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "mri"
    source_root.mkdir()
    for subject in ("C1S1_D1", "C2S2_D1"):
        nib.save(
            nib.Nifti1Image(np.ones((3, 4, 5), dtype=np.float32), np.eye(4)),
            source_root / f"{subject}_t2w.nii.gz",
        )
    dialog = ScanImportReviewDialog(discover_mri_source(source_root))
    excluded_row = next(
        row
        for row, edit in dialog._subject_edits.items()
        if edit.text() == "C1S1_D1"
    )

    dialog.table.selectRow(excluded_row)
    dialog._exclude_selected_subjects()
    qt_app.processEvents()

    assert {item.subject_code for item in dialog.assignments()} == {"C2S2_D1"}
    assert dialog.table.isRowHidden(excluded_row)
    assert dialog.exclusion_status.text() == "1 subject excluded"

    dialog._restore_excluded_subjects()
    assert {item.subject_code for item in dialog.assignments()} == {
        "C1S1_D1",
        "C2S2_D1",
    }
    dialog.close()


def test_scan_review_only_offers_roles_from_the_study_scope(
    qt_app: QApplication,
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "mri"
    source_root.mkdir()
    nib.save(
        nib.Nifti1Image(np.ones((3, 4, 5), dtype=np.float32), np.eye(4)),
        source_root / "C1S1_D1_t2w.nii.gz",
    )
    dialog = ScanImportReviewDialog(
        discover_mri_source(source_root),
        analysis_scope=AnalysisScope.T1_ONLY,
    )
    selector = dialog._role_selectors[0]

    assert {
        ScanRole(selector.itemData(index))
        for index in range(selector.count())
    } == {ScanRole.IGNORE, ScanRole.T1_PRE, ScanRole.T1_POST}
    assert ScanRole(selector.currentData()) is ScanRole.IGNORE
    dialog.close()


def test_subjects_page_removes_and_restores_subject_without_deleting_data(
    qt_app: QApplication,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = StudyService()
    study = service.create_study(
        CreateStudyRequest(
            tmp_path / "removal-study",
            "Removal study",
            "removal-study",
            actor="Reviewer A",
        )
    )
    service.add_subject(CreateSubjectRequest("Mouse-01", True, True, actor="Reviewer A"))
    window = MainWindow(
        study_service=service,
        recent_studies=RecentStudiesService(
            tmp_path / "preferences" / "recent.json"
        ),
    )
    assert window.open_project_path(study.root_path)
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *_args, **_kwargs: QMessageBox.StandardButton.Yes,
    )

    window.subjects_page.table.selectRow(0)
    qt_app.processEvents()
    assert window.subjects_page.remove_subject.isEnabled()
    window.subjects_page.remove_subject.click()
    qt_app.processEvents()

    assert window.current_study is not None
    assert window.current_study.subjects == ()
    assert len(window.current_study.archived_subjects) == 1
    assert window.subjects_page.restore_subjects.isEnabled()

    archived_id = window.current_study.archived_subjects[0].subject_id
    monkeypatch.setattr(RestoreSubjectDialog, "exec", lambda _dialog: QDialog.Accepted)
    monkeypatch.setattr(RestoreSubjectDialog, "subject_id", lambda _dialog: archived_id)
    window.subjects_page.restore_subjects.click()
    qt_app.processEvents()

    assert window.current_study.archived_subjects == ()
    assert window.current_study.subjects[0].label == "Mouse-01"
    window.close()
