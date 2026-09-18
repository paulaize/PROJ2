"""MRI discovery review dialog for subject and scan assignment."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from lys_bbb_app.domain.scan_import import (
    ImportConfidence,
    OrientationPolicy,
    ScanDiscoveryReport,
    ScanImportAssignment,
    ScanRole,
)
from lys_bbb_app.domain.study import AnalysisScope
from lys_bbb_app.ui.widgets import secondary_button, show_inline_error


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
        analysis_scope: AnalysisScope = AnalysisScope.T1_T2,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.report = report
        self.analysis_scope = analysis_scope
        self.allowed_roles = (
            (ScanRole.IGNORE, ScanRole.T1_PRE, ScanRole.T1_POST, ScanRole.T2)
            if analysis_scope is AnalysisScope.T1_T2
            else (ScanRole.IGNORE, ScanRole.T1_PRE, ScanRole.T1_POST)
            if analysis_scope is AnalysisScope.T1_ONLY
            else (ScanRole.IGNORE, ScanRole.T2)
        )
        self.setWindowTitle("Review discovered MRI inputs")
        self.setModal(True)
        self.resize(1240, 720)
        self._subject_edits: dict[int, QLineEdit] = {}
        self._role_selectors: dict[int, QComboBox] = {}
        self._orientation_selectors: dict[int, QComboBox] = {}
        self._flip_boxes: dict[int, tuple[QCheckBox, QCheckBox, QCheckBox]] = {}
        self._excluded_rows: set[int] = set()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 22)
        layout.setSpacing(12)
        title = QLabel("Confirm subjects and MRI assignments")
        title.setObjectName("sectionTitle")
        layout.addWidget(title)
        summary = QLabel(
            f"{report.session_count} acquisition folder(s) · "
            f"{len(report.proposed_subject_codes)} subject(s) · "
            f"{len(report.scans) - report.ignored_scan_count} MRI input(s) proposed"
        )
        summary.setObjectName("infoBanner")
        summary.setWordWrap(True)
        layout.addWidget(summary)

        help_text = QLabel(
            "Check the subject IDs and MRI types, then confirm to import.\n"
            "Review and validate the converted images before analysis."
        )
        help_text.setObjectName("muted")
        help_text.setWordWrap(True)
        layout.addWidget(help_text)

        review_controls = QHBoxLayout()
        self.show_other_scans = QCheckBox(
            "Show excluded subjects, localizers, and alternative acquisitions"
        )
        self.show_other_scans.toggled.connect(self._apply_row_visibility)
        review_controls.addWidget(self.show_other_scans)
        review_controls.addStretch()
        self.exclusion_status = QLabel("No subjects excluded")
        self.exclusion_status.setObjectName("muted")
        review_controls.addWidget(self.exclusion_status)
        self.restore_excluded = secondary_button("Restore excluded")
        self.restore_excluded.setEnabled(False)
        self.restore_excluded.clicked.connect(self._restore_excluded_subjects)
        review_controls.addWidget(self.restore_excluded)
        exclude_subject = secondary_button("Exclude selected subject")
        exclude_subject.clicked.connect(self._exclude_selected_subjects)
        review_controls.addWidget(exclude_subject)
        layout.addLayout(review_controls)

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
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        for row, scan in enumerate(report.scans):
            subject = QLineEdit(scan.suggested_subject_code)
            subject.setToolTip(f"Inferred from {scan.session_id}")
            self._subject_edits[row] = subject
            self.table.setCellWidget(row, 0, subject)

            role = QComboBox()
            for value in self.allowed_roles:
                role.addItem(self.ROLE_LABELS[value], value.value)
            suggested_role = (
                scan.suggested_role
                if scan.suggested_role in self.allowed_roles
                else ScanRole.IGNORE
            )
            role.setCurrentIndex(role.findData(suggested_role.value))
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
            for axis, box in enumerate(boxes):
                box.setToolTip(
                    "Reorders stored voxels without changing anatomical orientation. "
                    "To correct a misoriented image, use Correct orientation after import."
                )
                box.setChecked(axis in scan.suggested_flip_axes)
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
            if row in self._excluded_rows:
                continue
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
                    animal_identifier=scan.suggested_animal_identifier,
                    time_identifier=scan.suggested_time_identifier,
                    flip_axes=flip_axes,
                )
            )
        return tuple(assignments)

    def accept(self) -> None:
        assignments = self.assignments()
        if not assignments:
            self._show_error("Assign at least one scan to an available import role.")
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
        suggested_flips = (
            self.report.scans[row].suggested_flip_axes
            if role is ScanRole.T2
            else ()
        )
        for axis, box in enumerate(self._flip_boxes[row]):
            box.setChecked(axis in suggested_flips)
        self._apply_row_visibility()

    def _exclude_selected_subjects(self) -> None:
        selected_rows = {
            index.row() for index in self.table.selectionModel().selectedRows()
        }
        if not selected_rows:
            self._show_error(
                "Select at least one scan row belonging to the subject you want to exclude."
            )
            return
        selected_codes = {
            self._subject_edits[row].text().strip().casefold()
            for row in selected_rows
        }
        self._excluded_rows.update(
            row
            for row, edit in self._subject_edits.items()
            if edit.text().strip().casefold() in selected_codes
        )
        self.table.clearSelection()
        self.error.hide()
        self._refresh_exclusion_controls()
        self._apply_row_visibility()

    def _restore_excluded_subjects(self) -> None:
        self._excluded_rows.clear()
        self._refresh_exclusion_controls()
        self._apply_row_visibility()

    def _refresh_exclusion_controls(self) -> None:
        excluded_codes = {
            self._subject_edits[row].text().strip()
            for row in self._excluded_rows
        }
        count = len(excluded_codes)
        self.exclusion_status.setText(
            f"{count} subject{'s' if count != 1 else ''} excluded"
            if count
            else "No subjects excluded"
        )
        self.restore_excluded.setEnabled(bool(self._excluded_rows))

    def _apply_row_visibility(self) -> None:
        show_ignored = self.show_other_scans.isChecked()
        for row in range(self.table.rowCount()):
            role = ScanRole(self._role_selectors[row].currentData())
            hidden_by_default = row in self._excluded_rows or role is ScanRole.IGNORE
            self.table.setRowHidden(row, hidden_by_default and not show_ignored)

    def _show_error(self, message: str) -> None:
        show_inline_error(self.error, message)
