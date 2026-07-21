"""Focused offscreen tests for the connected desktop MVP design preview."""

from __future__ import annotations

from dataclasses import replace
import os
from pathlib import Path

import nibabel as nib
import numpy as np
import pytest


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtCore import QItemSelectionModel, QPoint, Qt  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QApplication,
    QDialog,
    QFileDialog,
    QMessageBox,
)

from lys_bbb.project_service import ProjectService  # noqa: E402
from lys_bbb.scan_discovery import discover_mri_source  # noqa: E402
from lys_bbb_app.demo_data import demo_study  # noqa: E402
from lys_bbb_app.domain.study import (  # noqa: E402
    CreateStudyRequest,
    CreateSubjectRequest,
)
from lys_bbb_app.main import parse_args  # noqa: E402
from lys_bbb_app.services.recent_studies_service import (  # noqa: E402
    RecentStudiesService,
)
from lys_bbb_app.ui.dialogs import (  # noqa: E402
    AddSubjectDialog,
    GroupAssignmentDialog,
    RestoreSubjectDialog,
    UnblindingDialog,
)
from lys_bbb_app.ui.main_window import MainWindow  # noqa: E402
from lys_bbb_app.ui.pages import (  # noqa: E402
    ReviewsPage,
    SubjectsPage,
)
from lys_bbb_app.ui.scan_import_dialog import ScanImportReviewDialog  # noqa: E402
from lys_bbb_app.ui.subject_workspace import SubjectWorkspacePage  # noqa: E402
from lys_bbb_app.ui.widgets import ElidedLabel  # noqa: E402
from lys_bbb_app.services.study_service import StudyService  # noqa: E402


@pytest.fixture(scope="module")
def qt_app():
    app = QApplication.instance() or QApplication([])
    yield app
    app.closeAllWindows()


def test_demo_flag_is_explicit() -> None:
    assert parse_args(["--demo"]).demo is True
    assert parse_args([]).demo is False


def test_preview_connects_shell_subject_workspace_and_review_queue(
    qt_app: QApplication,
) -> None:
    window = MainWindow()

    assert window.root_stack.currentIndex() == 0
    window.open_design_preview()
    qt_app.processEvents()

    assert window.root_stack.currentIndex() == 1
    assert window.current_study is not None
    assert window.current_study.is_demo is True
    assert [workflow.key for workflow in window.current_study.workflows] == [
        "t1",
        "t2",
        "combined",
    ]
    assert window.subjects_page.proxy.rowCount() == 8
    assert window.subjects_page.model.columnCount() == 10
    assert window.subjects_page.model.headerData(6, Qt.Horizontal) == "T2 data"
    assert window.subjects_page.model.headerData(7, Qt.Horizontal) == "T2 lesion"
    assert window.reviews_page.queue_list.count() == 4
    assert window.results_page.proxy.rowCount() == 4
    assert window.results_page.model.columnCount() == 5
    assert "synthetic" in window.preview_banner.text().lower()

    window.open_subject("Mouse-001")
    assert window.content_stack.currentIndex() == window.page_indices["workspace"]
    assert window.workspace_page.subject_title.text() == "Mouse-001"
    assert window.nav_buttons["subjects"].isChecked()

    window.open_reviews_for_subject("Mouse-001")
    assert window.content_stack.currentIndex() == window.page_indices["reviews"]
    assert window.reviews_page.current_item is not None
    assert window.reviews_page.current_item.subject_id == "Mouse-001"
    window.close()


def test_subject_worklist_supports_multi_selection_and_contextual_actions(
    qt_app: QApplication,
) -> None:
    study = demo_study()
    study = replace(
        study,
        subjects=tuple(
            replace(subject, mri_input_count=1)
            for subject in study.subjects[:2]
        ),
    )
    page = SubjectsPage()
    page.set_study(study)
    selected_batches: list[tuple[str, ...]] = []
    page.subjects_flip_requested.connect(selected_batches.append)
    selection = page.table.selectionModel()
    flags = QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows
    selection.select(page.proxy.index(0, 0), flags)
    selection.select(page.proxy.index(1, 0), flags)
    qt_app.processEvents()

    assert page.flip_subjects.isEnabled()
    assert not page.open_mri.isEnabled()
    assert not page.remove_subject.isEnabled()
    assert "2 selected" in page.count_label.text()
    page.flip_subjects.click()
    assert set(selected_batches[0]) == {
        subject.subject_id for subject in study.subjects
    }

    selection.clearSelection()
    selection.select(page.proxy.index(0, 0), flags)
    qt_app.processEvents()
    assert page.open_mri.isEnabled()
    assert page.remove_subject.isEnabled()
    page.close()


def test_subject_workspace_exposes_open_mri_and_rename_actions(
    qt_app: QApplication,
) -> None:
    subject = replace(
        demo_study().subjects[0],
        mri_input_count=1,
        can_validate_inputs=True,
    )
    page = SubjectWorkspacePage()
    opened: list[str] = []
    renamed: list[str] = []
    validated: list[str] = []
    page.open_mri_requested.connect(opened.append)
    page.rename_requested.connect(renamed.append)
    page.input_validation_requested.connect(validated.append)
    page.set_subject(subject)

    assert page.open_mri.isEnabled()
    page.open_mri.click()
    page.rename_subject.click()
    page.tabs.setCurrentWidget(page.inputs_panel)
    page.inputs_panel.validate_inputs.click()
    qt_app.processEvents()

    assert opened == [subject.subject_id]
    assert renamed == [subject.subject_id]
    assert validated == [subject.subject_id]
    assert len(page.inputs_panel.scan_cards) == 3
    assert page.metadata_card.isHidden()
    assert page.workflow_container.isHidden()
    assert page.horizontalScrollBar().maximum() == 0
    page.close()


def test_subject_workspace_exposes_t2_inference_and_draft_result_preview(
    qt_app: QApplication,
) -> None:
    study = demo_study()
    draft_subject = study.subjects[0]
    ready_subject = study.subjects[4]
    page = SubjectWorkspacePage()
    study_runs: list[bool] = []
    subject_runs: list[str] = []
    opened: list[tuple[str, str]] = []
    corrections: list[tuple[str, str]] = []
    approvals: list[tuple[str, str]] = []
    rejections: list[tuple[str, str]] = []
    page.t2_run_study_requested.connect(lambda: study_runs.append(True))
    page.t2_run_subject_requested.connect(subject_runs.append)
    page.t2_open_artifact_requested.connect(
        lambda subject_id, artifact_id: opened.append((subject_id, artifact_id))
    )
    page.t2_import_correction_requested.connect(
        lambda subject_id, artifact_id: corrections.append((subject_id, artifact_id))
    )
    page.t2_approve_requested.connect(
        lambda subject_id, artifact_id: approvals.append((subject_id, artifact_id))
    )
    page.t2_reject_requested.connect(
        lambda subject_id, artifact_id: rejections.append((subject_id, artifact_id))
    )

    page.set_subject(draft_subject)
    page.tabs.setCurrentWidget(page.t2_panel)
    qt_app.processEvents()

    assert page.tabs.tabText(page.tabs.indexOf(page.t2_panel)) == "T2 Lesion"
    assert page.t2_panel.artifact_card.isVisibleTo(page.t2_panel)
    assert "4.513 mm³" in {
        widget.text()
        for widget in page.t2_panel.artifact_card.findChildren(type(page.subject_title))
    }
    assert not page.t2_panel.run_subject.isEnabled()
    page.t2_panel.open_artifact.click()
    page.t2_panel.import_correction.click()
    page.t2_panel.approve.click()
    page.t2_panel.reject.click()
    assert opened == [
        (draft_subject.subject_id, draft_subject.t2_artifact.artifact_id)
    ]
    assert corrections == opened
    assert approvals == opened
    assert rejections == opened

    page.set_subject(ready_subject)
    assert page.t2_panel.run_subject.isEnabled()
    page.t2_panel.run_subject.click()
    page.t2_panel.run_study.click()
    assert subject_runs == [ready_subject.subject_id]
    assert study_runs == [True]
    page.close()


def test_subject_worklist_offers_cohort_t2_inference(
    qt_app: QApplication,
) -> None:
    page = SubjectsPage()
    requested: list[bool] = []
    page.t2_inference_requested.connect(lambda: requested.append(True))
    page.set_study(demo_study())

    assert page.run_t2.isEnabled()
    assert "(1)" in page.run_t2.text()
    page.run_t2.click()
    qt_app.processEvents()

    assert requested == [True]
    page.close()


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


def test_subject_workspace_stacks_metadata_and_avoids_horizontal_overflow(
    qt_app: QApplication,
) -> None:
    source = demo_study().subjects[0]
    subject = replace(
        source,
        metadata=(
            ("Expected workflows", "T1 · T2"),
            ("Persistent subject ID", source.subject_id),
            (
                "T2 v1",
                "/Volumes/mri-study/" + "/nested-session" * 20 + "/scan.nii.gz",
            ),
        ),
    )
    page = SubjectWorkspacePage()
    page.resize(760, 650)
    page.set_subject(subject)
    page.show()
    qt_app.processEvents()

    assert len(page.metadata_value_labels) == len(subject.metadata)
    row_positions = [label.mapTo(page.metadata_card, QPoint(0, 0)).y() for label in page.metadata_value_labels]
    assert row_positions == sorted(row_positions)
    assert len(set(row_positions)) == len(row_positions)
    assert page.horizontalScrollBar().maximum() == 0
    assert page.metadata_value_labels[-1].text() != subject.metadata[-1][1]
    assert page.metadata_value_labels[-1].toolTip() == subject.metadata[-1][1]
    page.close()


def test_subject_filters_and_approved_result_filter(qt_app: QApplication) -> None:
    window = MainWindow()
    window.open_design_preview()

    window.subjects_page.search.setText("Mouse-007")
    qt_app.processEvents()
    assert window.subjects_page.proxy.rowCount() == 1
    assert (
        window.subjects_page.proxy.data(
            window.subjects_page.proxy.index(0, 0),
            Qt.DisplayRole,
        )
        == "Mouse-007"
    )

    window.results_page.approved_only.setChecked(True)
    qt_app.processEvents()
    assert window.results_page.proxy.rowCount() == 3
    window.close()


def test_results_page_scrolls_instead_of_overlapping_at_minimum_size(
    qt_app: QApplication,
) -> None:
    window = MainWindow()
    window.open_design_preview()
    window.resize(1180, 760)
    window.show_page("results")
    window.show()
    qt_app.processEvents()

    page = window.results_page
    content = page.widget()
    results_bottom = page.results_card.mapTo(
        content,
        QPoint(0, page.results_card.height()),
    ).y()
    plot_top = page.plot_card.mapTo(content, QPoint(0, 0)).y()
    export_top = page.export_card.mapTo(content, QPoint(0, 0)).y()

    assert plot_top > results_bottom
    assert export_top == plot_top
    assert page.verticalScrollBar().maximum() > 0
    window.close()


def test_blinded_review_hides_groups_until_explicit_unblinding(
    qt_app: QApplication,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    window = MainWindow()
    window.open_design_preview()
    qt_app.processEvents()

    assert window.settings_page.blinded_review.isChecked()
    assert window.blinded_review is True
    assert window.subjects_page.table.isColumnHidden(1)
    assert window.subjects_page.group_filter.isHidden()
    assert window.results_page.table.isColumnHidden(1)
    assert not window.results_page.blinding_note.isHidden()

    window.open_subject("Mouse-001")
    assert "Hidden during blinded review" in window.workspace_page.subject_subtitle.text()

    monkeypatch.setattr(UnblindingDialog, "exec", lambda _dialog: QDialog.Accepted)
    monkeypatch.setattr(
        GroupAssignmentDialog,
        "exec",
        lambda _dialog: QDialog.Rejected,
    )
    window.subjects_page.assign_groups.click()
    qt_app.processEvents()
    assert window.blinded_review is False
    assert not window.subjects_page.table.isColumnHidden(1)
    assert not window.subjects_page.group_filter.isHidden()
    assert not window.results_page.table.isColumnHidden(1)
    assert window.results_page.blinding_note.isHidden()

    unassigned = window.subjects_page.model.index(6, 1)
    assert window.subjects_page.model.data(unassigned, Qt.DisplayRole) == "Unassigned"
    window.close()


def test_group_assignment_preview_preserves_unassigned_subjects(
    qt_app: QApplication,
) -> None:
    dialog = GroupAssignmentDialog(demo_study().subjects)

    assignments = dialog.assignments()
    assert assignments["Mouse-001"] == "Treatment A"
    assert assignments["Mouse-007"] is None
    assert dialog.table.horizontalHeaderItem(0).text() == "Subject ID"
    assert dialog.table.horizontalHeaderItem(1).text() == "Group assignment"
    dialog.close()


def test_review_decisions_are_local_and_rejection_requires_reason(
    qt_app: QApplication,
) -> None:
    page = ReviewsPage()
    page.set_study(demo_study())
    messages: list[str] = []
    page.decision_recorded.connect(messages.append)

    review_id = page.current_item.review_id
    page._reject()
    assert review_id not in page.decisions
    assert "before rejecting" in messages[-1]

    page.issue.setCurrentText("False positive")
    page.notes.setPlainText("Synthetic boundary issue for interaction testing.")
    page._reject()
    assert page.decisions[review_id].label == "Rejected · preview"
    assert "Nothing was saved" in messages[-1]

    page._approve()
    assert page.decisions[review_id].label == "Human approved · preview"
    page.close()


def test_opening_real_schema_v1_project_does_not_inject_demo_records(
    qt_app: QApplication,
    tmp_path: Path,
) -> None:
    project_path = tmp_path / "real-study.lysbbb"
    ProjectService().create_project(project_path, name="Real study")

    window = MainWindow()
    assert window.open_project_path(project_path) is True
    qt_app.processEvents()

    assert window.current_study is not None
    assert window.current_study.is_demo is False
    assert window.current_study.name == "Real study"
    assert window.subjects_page.proxy.rowCount() == 0
    assert window.reviews_page.queue_list.count() == 0
    assert window.results_page.proxy.rowCount() == 0
    assert "legacy project" in window.preview_banner.text().lower()
    window.close()


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
    assert window.current_study.is_demo is False
    assert window.subjects_page.proxy.rowCount() == 0
    assert "persistent study" in window.preview_banner.text().lower()
    window.show_page("results")
    assert window.results_page.results_stack.currentWidget() is window.results_page.results_empty
    assert window.results_page.plot_stack.currentWidget() is window.results_page.plot_empty
    assert all(not button.isEnabled() for button in window.results_page.export_buttons)

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
    assert window.subjects_page.table.isColumnHidden(1)

    t1_source = tmp_path / "external-drive" / "t1"
    t1_source.mkdir(parents=True)
    monkeypatch.setattr(
        QFileDialog,
        "getExistingDirectory",
        lambda *_args, **_kwargs: str(t1_source),
    )
    window.select_input_folder("t1")
    assert window.current_study is not None
    assert window.current_study.t1_input_folder == t1_source.resolve()
    assert window.settings_page.t1_input_folder.text() == str(t1_source.resolve())

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
    assert not window.subjects_page.table.isColumnHidden(1)

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
    monkeypatch.setattr(
        ScanImportReviewDialog,
        "exec",
        lambda _dialog: QDialog.Accepted,
    )

    window.select_mri_source_folder()
    thread = window._scan_import_thread
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
    assert (
        window.subjects_page.model.data(
            window.subjects_page.model.index(0, 6),
            Qt.DisplayRole,
        )
        == "Input review required"
    )
    assert (
        window.subjects_page.model.data(
            window.subjects_page.model.index(0, 7),
            Qt.DisplayRole,
        )
        == "Not started"
    )

    window.open_subject(subject_id)
    input_panel = window.workspace_page.inputs_panel
    window.workspace_page.tabs.setCurrentWidget(input_panel)
    assert len(input_panel.scan_cards) == 1
    assert input_panel.validate_inputs.isEnabled()
    assert "require validation" in input_panel.readiness_label.text()
    input_panel.validate_inputs.click()
    validation_thread = window._input_validation_thread
    assert validation_thread is not None
    assert validation_thread.wait(5000)
    for _ in range(10):
        qt_app.processEvents()

    assert window.current_study is not None
    assert window.current_study.subjects[0].t2_data.label == "T2 validated"
    assert window.current_study.subjects[0].overall.label == "Ready for analysis"
    assert "passed validation" in input_panel.readiness_label.text()
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
    monkeypatch.setattr(
        RestoreSubjectDialog,
        "subject_id",
        lambda _dialog: archived_id,
    )
    window.subjects_page.restore_subjects.click()
    qt_app.processEvents()

    assert window.current_study.archived_subjects == ()
    assert window.current_study.subjects[0].label == "Mouse-01"
    window.close()
