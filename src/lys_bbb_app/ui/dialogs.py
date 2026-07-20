"""Focused dialogs for study-level desktop interactions."""

from __future__ import annotations

import re
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from lys_bbb_app.domain.study import (
    AuditEventRecord,
    CreateStudyRequest,
    CreateSubjectRequest,
)
from lys_bbb_app.domain.view_models import SubjectViewModel
from lys_bbb_app.ui.widgets import secondary_button


class CreateStudyDialog(QDialog):
    """Collect the fields required to create a canonical study root."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Create LYS BBB study")
        self.setModal(True)
        self.resize(680, 480)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 22)
        layout.setSpacing(14)
        title = QLabel("Create a persistent study")
        title.setObjectName("sectionTitle")
        layout.addWidget(title)
        detail = QLabel(
            "The application creates project.sqlite, project.json, and managed output "
            "folders. Source MRI data can remain on an external hard drive."
        )
        detail.setObjectName("infoBanner")
        detail.setWordWrap(True)
        layout.addWidget(detail)

        form = QFormLayout()
        self.name = QLineEdit("Mouse MRI Study")
        self.identifier = QLineEdit("mouse-mri-study")
        self.root_path = QLineEdit(
            str(Path.home() / "Documents" / "mouse-mri-study")
        )
        browse = secondary_button("Browse…")
        browse.clicked.connect(self._browse_parent)
        root_row = QHBoxLayout()
        root_row.addWidget(self.root_path, 1)
        root_row.addWidget(browse)
        self.description = QTextEdit()
        self.description.setPlaceholderText("Optional study description")
        self.description.setMaximumHeight(80)
        self.blinded = QCheckBox("Start with experimental groups hidden")
        self.blinded.setChecked(True)
        form.addRow("Study name", self.name)
        form.addRow("Study identifier", self.identifier)
        form.addRow("New study directory", root_row)
        form.addRow("Description", self.description)
        form.addRow("Review mode", self.blinded)
        layout.addLayout(form)

        self.error = QLabel()
        self.error.setObjectName("errorBanner")
        self.error.setWordWrap(True)
        self.error.hide()
        layout.addWidget(self.error)

        buttons = QDialogButtonBox(QDialogButtonBox.Cancel | QDialogButtonBox.Save)
        buttons.button(QDialogButtonBox.Save).setText("Create study")
        buttons.button(QDialogButtonBox.Cancel).setProperty("kind", "secondary")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def request(self, *, actor: str) -> CreateStudyRequest:
        return CreateStudyRequest(
            root_path=Path(self.root_path.text().strip()).expanduser(),
            name=self.name.text().strip(),
            identifier=self.identifier.text().strip(),
            description=self.description.toPlainText().strip() or None,
            blinded=self.blinded.isChecked(),
            actor=actor,
        )

    def accept(self) -> None:
        name = self.name.text().strip()
        identifier = self.identifier.text().strip()
        root_text = self.root_path.text().strip()
        if not name or not identifier or not root_text:
            self._show_error("Study name, identifier, and directory are required.")
            return
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", identifier):
            self._show_error(
                "The identifier may use letters, numbers, periods, underscores, and hyphens."
            )
            return
        root = Path(root_text).expanduser()
        if root.exists():
            self._show_error(
                "Choose a new study directory. Existing files are never overwritten."
            )
            return
        if not root.parent.is_dir():
            self._show_error("The parent directory does not exist.")
            return
        super().accept()

    def _browse_parent(self) -> None:
        selected = QFileDialog.getExistingDirectory(
            self,
            "Choose the parent directory for the new study",
            str(Path(self.root_path.text()).expanduser().parent),
        )
        if selected:
            identifier = self.identifier.text().strip() or "mouse-mri-study"
            self.root_path.setText(str(Path(selected) / identifier))

    def _show_error(self, message: str) -> None:
        self.error.setText(message)
        self.error.show()


class AddSubjectDialog(QDialog):
    """Collect a persistent subject identity and expected workflows."""

    def __init__(
        self,
        *,
        blinded: bool,
        group_definitions: tuple[str, ...] = (),
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Add subject")
        self.setModal(True)
        self.setMinimumWidth(520)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 22)
        layout.setSpacing(14)
        title = QLabel("Add a subject")
        title.setObjectName("sectionTitle")
        layout.addWidget(title)

        form = QFormLayout()
        self.subject_code = QLineEdit()
        self.subject_code.setPlaceholderText("Example: Mouse-001")
        self.group = QComboBox()
        self.group.setEditable(True)
        self.group.addItem("Unassigned")
        self.group.addItems(group_definitions)
        self.group.setEnabled(not blinded)
        self.expected_t1 = QCheckBox("T1 enhancement")
        self.expected_t1.setChecked(True)
        self.expected_t2 = QCheckBox("T2 lesion")
        self.expected_t2.setChecked(True)
        workflows = QHBoxLayout()
        workflows.addWidget(self.expected_t1)
        workflows.addWidget(self.expected_t2)
        workflows.addStretch()
        form.addRow("Subject ID", self.subject_code)
        form.addRow("Experimental group", self.group)
        form.addRow("Expected workflows", workflows)
        layout.addLayout(form)

        note = QLabel(
            "Groups are unavailable while the study is blinded. Subject files are "
            "assigned in the later MRI input workflow."
            if blinded
            else "The subject may remain Unassigned and receive a group later."
        )
        note.setObjectName("muted")
        note.setWordWrap(True)
        layout.addWidget(note)

        self.error = QLabel()
        self.error.setObjectName("errorBanner")
        self.error.hide()
        layout.addWidget(self.error)

        buttons = QDialogButtonBox(QDialogButtonBox.Cancel | QDialogButtonBox.Save)
        buttons.button(QDialogButtonBox.Save).setText("Add subject")
        buttons.button(QDialogButtonBox.Cancel).setProperty("kind", "secondary")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def request(self, *, actor: str) -> CreateSubjectRequest:
        group_name = None
        if self.group.isEnabled() and self.group.currentText().strip() != "Unassigned":
            group_name = self.group.currentText().strip() or None
        return CreateSubjectRequest(
            subject_code=self.subject_code.text().strip(),
            expected_t1=self.expected_t1.isChecked(),
            expected_t2=self.expected_t2.isChecked(),
            group_name=group_name,
            actor=actor,
        )

    def accept(self) -> None:
        if not self.subject_code.text().strip():
            self._show_error("Enter a stable subject ID.")
            return
        if not self.expected_t1.isChecked() and not self.expected_t2.isChecked():
            self._show_error("Select at least one expected workflow.")
            return
        super().accept()

    def _show_error(self, message: str) -> None:
        self.error.setText(message)
        self.error.show()


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
    """Edit deferred subject-to-group assignments after unblinding."""

    def __init__(
        self,
        subjects: tuple[SubjectViewModel, ...],
        group_definitions: tuple[str, ...] = (),
        *,
        persistent: bool = False,
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
            (
                "Subjects may remain Unassigned. Saving validates and records this mapping "
                "before grouped CSV/Excel-compatible exports are enabled."
                if persistent
                else "Subjects may remain Unassigned. The persistent application validates "
                "and audits this mapping before grouped exports are enabled."
            )
        )
        detail.setObjectName("infoBanner")
        detail.setWordWrap(True)
        layout.addWidget(detail)

        groups = tuple(
            dict.fromkeys(
                [*group_definitions, *sorted({subject.group for subject in subjects if subject.group})]
            )
        )
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
            subject_item = QTableWidgetItem(subject.label)
            subject_item.setFlags(subject_item.flags() & ~Qt.ItemIsEditable)
            self.table.setItem(row, 0, subject_item)

            selector = QComboBox()
            selector.setEditable(True)
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
        buttons.button(QDialogButtonBox.Save).setText(
            "Save assignments" if persistent else "Apply assignments (preview)"
        )
        buttons.button(QDialogButtonBox.Cancel).setProperty("kind", "secondary")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def assignments(self) -> dict[str, str | None]:
        """Return the currently selected preview mapping."""

        return {
            subject_id: (
                None
                if selector.currentText().strip() in {"", "Unassigned"}
                else selector.currentText().strip()
            )
            for subject_id, selector in self.group_selectors.items()
        }


class AuditHistoryDialog(QDialog):
    """Read-only presentation of append-only study audit events."""

    def __init__(
        self,
        events: tuple[AuditEventRecord, ...],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Study audit history")
        self.resize(900, 600)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 22)
        layout.setSpacing(14)
        title = QLabel("Study audit history")
        title.setObjectName("sectionTitle")
        layout.addWidget(title)
        detail = QLabel(
            "Important study, subject, blinding, and group actions are append-only."
        )
        detail.setObjectName("muted")
        layout.addWidget(detail)

        self.table = QTableWidget(len(events), 4)
        self.table.setHorizontalHeaderLabels(("Time", "Event", "Actor", "Details"))
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.Stretch)
        for row, event in enumerate(events):
            details = ", ".join(
                f"{key}={value}" for key, value in sorted(event.details.items())
            )
            for column, value in enumerate(
                (event.created_at, event.event_type, event.actor, details or "—")
            ):
                self.table.setItem(row, column, QTableWidgetItem(str(value)))
        layout.addWidget(self.table, 1)

        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        close_row = QHBoxLayout()
        close_row.addStretch()
        close_row.addWidget(close)
        layout.addLayout(close_row)
