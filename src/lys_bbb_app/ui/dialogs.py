"""Focused dialogs for study-level desktop interactions."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from lys_bbb_app.domain.view_models import SubjectViewModel
from lys_bbb_app.ui.widgets import secondary_button


class UnblindingDialog(QDialog):
    """Require an explicit acknowledgement before revealing study groups."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Unblind study groups")
        self.setModal(True)
        self.setMinimumWidth(560)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 22)
        layout.setSpacing(14)

        title = QLabel("Reveal experimental groups?")
        title.setObjectName("sectionTitle")
        layout.addWidget(title)

        warning = QLabel(
            "This reveals the group allocation for every subject. It cannot make "
            "earlier decisions blinded again, and the final application will record "
            "this action in the study audit history."
        )
        warning.setObjectName("previewBanner")
        warning.setWordWrap(True)
        layout.addWidget(warning)

        detail = QLabel(
            "Reviewer identity remains recorded whether the study is blinded or "
            "unblinded. After confirmation, subjects may stay Unassigned or receive "
            "a group before grouped summaries and exports are created."
        )
        detail.setObjectName("muted")
        detail.setWordWrap(True)
        layout.addWidget(detail)

        buttons = QDialogButtonBox(QDialogButtonBox.Cancel | QDialogButtonBox.Ok)
        confirm = buttons.button(QDialogButtonBox.Ok)
        confirm.setText("Confirm unblinding")
        confirm.setProperty("kind", "danger")
        buttons.button(QDialogButtonBox.Cancel).setProperty("kind", "secondary")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)


class GroupAssignmentDialog(QDialog):
    """Preview deferred subject-to-group assignment after unblinding."""

    def __init__(
        self,
        subjects: tuple[SubjectViewModel, ...],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Assign experimental groups")
        self.setModal(True)
        self.resize(660, 680)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 22)
        layout.setSpacing(14)

        title = QLabel("Assign groups after review")
        title.setObjectName("sectionTitle")
        layout.addWidget(title)

        detail = QLabel(
            "Subjects may remain Unassigned. The persisted MVP will validate and "
            "audit this mapping before grouped CSV/Excel-compatible exports are enabled."
        )
        detail.setObjectName("infoBanner")
        detail.setWordWrap(True)
        layout.addWidget(detail)

        groups = sorted({subject.group for subject in subjects if subject.group})
        self.table = QTableWidget(len(subjects), 2)
        self.table.setHorizontalHeaderLabels(("Subject ID", "Group assignment"))
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(44)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionMode(QTableWidget.NoSelection)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.Stretch)

        self.group_selectors: dict[str, QComboBox] = {}
        for row, subject in enumerate(subjects):
            subject_item = QTableWidgetItem(subject.subject_id)
            subject_item.setFlags(subject_item.flags() & ~Qt.ItemIsEditable)
            self.table.setItem(row, 0, subject_item)

            selector = QComboBox()
            selector.addItem("Unassigned", None)
            selector.addItems(groups)
            if subject.group is not None:
                selector.setCurrentText(subject.group)
            self.table.setCellWidget(row, 1, selector)
            self.group_selectors[subject.subject_id] = selector
        layout.addWidget(self.table, 1)

        import_row = QHBoxLayout()
        import_mapping = secondary_button("Import subject/group CSV…")
        import_mapping.setEnabled(False)
        import_mapping.setToolTip(
            "CSV import will be connected with the persisted subject service."
        )
        import_row.addWidget(import_mapping)
        import_hint = QLabel("Expected columns: subject_id, group")
        import_hint.setObjectName("metadata")
        import_row.addWidget(import_hint)
        import_row.addStretch()
        layout.addLayout(import_row)

        buttons = QDialogButtonBox(QDialogButtonBox.Cancel | QDialogButtonBox.Save)
        buttons.button(QDialogButtonBox.Save).setText("Apply assignments (preview)")
        buttons.button(QDialogButtonBox.Cancel).setProperty("kind", "secondary")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def assignments(self) -> dict[str, str | None]:
        """Return the currently selected preview mapping."""

        return {
            subject_id: selector.currentData()
            if selector.currentIndex() == 0
            else selector.currentText()
            for subject_id, selector in self.group_selectors.items()
        }
