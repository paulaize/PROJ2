"""Focused offscreen tests for the connected desktop MVP design preview."""

from __future__ import annotations

import os
from pathlib import Path

import pytest


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication, QDialog  # noqa: E402

from lys_bbb.project_service import ProjectService  # noqa: E402
from lys_bbb_app.demo_data import demo_study  # noqa: E402
from lys_bbb_app.main import parse_args  # noqa: E402
from lys_bbb_app.ui.dialogs import (  # noqa: E402
    GroupAssignmentDialog,
    UnblindingDialog,
)
from lys_bbb_app.ui.main_window import MainWindow  # noqa: E402
from lys_bbb_app.ui.pages import ReviewsPage  # noqa: E402


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
    assert window.subjects_page.model.columnCount() == 9
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
