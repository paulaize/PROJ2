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
from lys_bbb_app.domain.scan_import import (
    ImportConfidence,
    OrientationPolicy,
    ScanDiscoveryReport,
    ScanImportAssignment,
    ScanRole,
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
        self.mri_source = QLineEdit()
        self.mri_source.setPlaceholderText("Optional Bruker/NIfTI folder; can be chosen later")
        source_browse = secondary_button("Browse…")
        source_browse.clicked.connect(self._browse_mri_source)
        source_row = QHBoxLayout()
        source_row.addWidget(self.mri_source, 1)
        source_row.addWidget(source_browse)
        self.description = QTextEdit()
        self.description.setPlaceholderText("Optional study description")
        self.description.setMaximumHeight(80)
        self.blinded = QCheckBox("Start with experimental groups hidden")
        self.blinded.setChecked(True)
        form.addRow("Study name", self.name)
        form.addRow("Study identifier", self.identifier)
        form.addRow("New study directory", root_row)
        form.addRow("MRI source folder", source_row)
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

    def mri_source_path(self) -> Path | None:
        value = self.mri_source.text().strip()
        return Path(value).expanduser() if value else None

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
        source = self.mri_source_path()
        if source is not None and not source.is_dir():
            self._show_error("The optional MRI source folder is not available.")
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

    def _browse_mri_source(self) -> None:
        selected = QFileDialog.getExistingDirectory(
            self,
            "Choose the folder containing Bruker sessions or NIfTI MRI files",
            str(Path(self.mri_source.text()).expanduser() if self.mri_source.text() else Path.home()),
        )
        if selected:
            self.mri_source.setText(selected)

    def _show_error(self, message: str) -> None:
        self.error.setText(message)
        self.error.show()


class ScanImportReviewDialog(QDialog):
    """Let the researcher correct discovered subjects, roles, and storage axes."""

    ROLE_LABELS = {
        ScanRole.IGNORE: "Do not import",
        ScanRole.T1_PRE: "T1 pre-Gd",
        ScanRole.T1_POST: "T1 post-Gd",
        ScanRole.T2: "T2-weighted",
    }
    ORIENTATION_LABELS = {
        OrientationPolicy.NATIVE: "Keep native storage",
        OrientationPolicy.T1_CORONAL: "Coronal quantitative (RSA)",
    }

    def __init__(
        self,
        report: ScanDiscoveryReport,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.report = report
        self.setWindowTitle("Review discovered MRI inputs")
        self.setModal(True)
        self.resize(1240, 720)
        self._subject_edits: dict[int, QLineEdit] = {}
        self._role_selectors: dict[int, QComboBox] = {}
        self._orientation_selectors: dict[int, QComboBox] = {}
        self._flip_boxes: dict[int, tuple[QCheckBox, QCheckBox, QCheckBox]] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 22)
        layout.setSpacing(12)
        title = QLabel("Confirm subjects and MRI assignments")
        title.setObjectName("sectionTitle")
        layout.addWidget(title)
        summary = QLabel(
            f"Found {report.session_count} acquisition folder(s), "
            f"{len(report.proposed_subject_codes)} proposed subject(s), and "
            f"{len(report.scans) - report.ignored_scan_count} proposed T1/T2 input(s). "
            "Nothing is imported until you confirm this table."
        )
        summary.setObjectName("infoBanner")
        summary.setWordWrap(True)
        layout.addWidget(summary)

        help_text = QLabel(
            "Edit subject IDs and scan roles where needed. T1 coronal conversion uses the "
            "NIfTI affine without interpolation. X/Y/Z flips reverse the stored voxel axis "
            "and update the affine; every choice is recorded in provenance. Automatic "
            "outputs remain inputs awaiting later scientific QC."
        )
        help_text.setObjectName("muted")
        help_text.setWordWrap(True)
        layout.addWidget(help_text)

        self.show_other_scans = QCheckBox("Show localizers and alternative acquisitions")
        self.show_other_scans.toggled.connect(self._apply_row_visibility)
        layout.addWidget(self.show_other_scans)

        self.table = QTableWidget(len(report.scans), 8)
        self.table.setHorizontalHeaderLabels(
            [
                "Subject ID",
                "Import role",
                "Session / scan",
                "Protocol",
                "Acquired",
                "NIfTI orientation",
                "Flip storage axes",
                "Confidence / issues",
            ]
        )
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(50)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        for row, scan in enumerate(report.scans):
            subject = QLineEdit(scan.suggested_subject_code)
            subject.setToolTip(f"Inferred from {scan.session_id}")
            self._subject_edits[row] = subject
            self.table.setCellWidget(row, 0, subject)

            role = QComboBox()
            for value in (ScanRole.IGNORE, ScanRole.T1_PRE, ScanRole.T1_POST, ScanRole.T2):
                role.addItem(self.ROLE_LABELS[value], value.value)
            role.setCurrentIndex(role.findData(scan.suggested_role.value))
            role.currentIndexChanged.connect(
                lambda _index, table_row=row: self._role_changed(table_row)
            )
            self._role_selectors[row] = role
            self.table.setCellWidget(row, 1, role)

            scan_label = scan.session_id
            if scan.scan_id is not None:
                scan_label += f"  ·  scan {scan.scan_id}"
            self.table.setItem(row, 2, QTableWidgetItem(scan_label))
            protocol = QTableWidgetItem(scan.protocol or scan.source_path.name)
            protocol.setToolTip(
                f"Method: {scan.method or 'unknown'}\nSeries: {scan.series_comment or 'not recorded'}"
            )
            self.table.setItem(row, 3, protocol)
            self.table.setItem(
                row,
                4,
                QTableWidgetItem(scan.acquisition_orientation or "Unknown"),
            )

            orientation = QComboBox()
            for value in (OrientationPolicy.NATIVE, OrientationPolicy.T1_CORONAL):
                orientation.addItem(self.ORIENTATION_LABELS[value], value.value)
            orientation.setCurrentIndex(
                orientation.findData(scan.orientation_policy.value)
            )
            self._orientation_selectors[row] = orientation
            self.table.setCellWidget(row, 5, orientation)

            flip_widget = QWidget()
            flip_layout = QHBoxLayout(flip_widget)
            flip_layout.setContentsMargins(2, 0, 2, 0)
            boxes = tuple(QCheckBox(axis) for axis in ("X", "Y", "Z"))
            for box in boxes:
                flip_layout.addWidget(box)
            flip_layout.addStretch()
            self._flip_boxes[row] = boxes  # type: ignore[assignment]
            self.table.setCellWidget(row, 6, flip_widget)

            issue_text = "; ".join(issue.message for issue in scan.issues)
            confidence = QTableWidgetItem(
                f"Role {scan.role_confidence.value.title()} · "
                f"ID {scan.subject_confidence.value.title()}"
                + (" · Review" if issue_text else "")
            )
            confidence.setToolTip(
                f"Role proposal: {scan.role_reason}"
                + (f"\n{issue_text}" if issue_text else "")
            )
            self.table.setItem(row, 7, confidence)

        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Interactive)
        for column, width in enumerate((120, 125, 255, 155, 90, 185, 125)):
            self.table.setColumnWidth(column, width)
        header.setSectionResizeMode(7, QHeaderView.Stretch)
        layout.addWidget(self.table, 1)
        self._apply_row_visibility()

        self.error = QLabel()
        self.error.setObjectName("errorBanner")
        self.error.setWordWrap(True)
        self.error.hide()
        layout.addWidget(self.error)
        buttons = QDialogButtonBox(QDialogButtonBox.Cancel | QDialogButtonBox.Save)
        buttons.button(QDialogButtonBox.Save).setText("Confirm and convert to NIfTI")
        buttons.button(QDialogButtonBox.Cancel).setProperty("kind", "secondary")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def assignments(self) -> tuple[ScanImportAssignment, ...]:
        assignments: list[ScanImportAssignment] = []
        for row, scan in enumerate(self.report.scans):
            role = ScanRole(self._role_selectors[row].currentData())
            if role is ScanRole.IGNORE:
                continue
            orientation = OrientationPolicy(
                self._orientation_selectors[row].currentData()
            )
            flip_axes = tuple(
                axis
                for axis, box in enumerate(self._flip_boxes[row])
                if box.isChecked()
            )
            assignments.append(
                ScanImportAssignment(
                    proposal_id=scan.proposal_id,
                    subject_code=self._subject_edits[row].text().strip(),
                    role=role,
                    source_path=scan.source_path,
                    source_format=scan.source_format,
                    session_id=scan.session_id,
                    scan_id=scan.scan_id,
                    protocol=scan.protocol,
                    method=scan.method,
                    acquisition_orientation=scan.acquisition_orientation,
                    confidence=(
                        scan.role_confidence
                        if role is scan.suggested_role
                        else ImportConfidence.LOW
                    ),
                    orientation_policy=orientation,
                    flip_axes=flip_axes,
                )
            )
        return tuple(assignments)

    def accept(self) -> None:
        assignments = self.assignments()
        if not assignments:
            self._show_error("Assign at least one scan to T1 pre, T1 post, or T2.")
            return
        if any(not assignment.subject_code for assignment in assignments):
            self._show_error("Every imported scan requires a subject ID.")
            return
        keys = [(item.subject_code.casefold(), item.role) for item in assignments]
        if len(keys) != len(set(keys)):
            self._show_error(
                "A subject can have only one active scan for each role. Edit duplicate "
                "subject IDs or scan roles before continuing."
            )
            return
        proposal_ids = [item.proposal_id for item in assignments]
        if len(proposal_ids) != len(set(proposal_ids)):
            self._show_error("The same discovered scan cannot be imported twice.")
            return
        super().accept()

    def _role_changed(self, row: int) -> None:
        role = ScanRole(self._role_selectors[row].currentData())
        desired = (
            OrientationPolicy.T1_CORONAL
            if role in {ScanRole.T1_PRE, ScanRole.T1_POST}
            else OrientationPolicy.NATIVE
        )
        selector = self._orientation_selectors[row]
        selector.setCurrentIndex(selector.findData(desired.value))
        self.table.setRowHidden(
            row,
            role is ScanRole.IGNORE and not self.show_other_scans.isChecked(),
        )

    def _apply_row_visibility(self) -> None:
        show_ignored = self.show_other_scans.isChecked()
        for row in range(self.table.rowCount()):
            role = ScanRole(self._role_selectors[row].currentData())
            self.table.setRowHidden(row, role is ScanRole.IGNORE and not show_ignored)

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
