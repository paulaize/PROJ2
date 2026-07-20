"""Production-connected MRI input review panel for one subject."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from lys_bbb_app.domain.view_models import InputScanViewModel, SubjectViewModel
from lys_bbb_app.ui.layout_helpers import clear_layout
from lys_bbb_app.ui.widgets import ElidedLabel, StatusBadge, secondary_button


class SubjectInputsPanel(QScrollArea):
    validation_requested = Signal(str)
    open_input_requested = Signal(str, str)
    flip_requested = Signal(str)
    import_requested = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.content = QWidget()
        self.layout = QVBoxLayout(self.content)
        self.layout.setContentsMargins(18, 16, 18, 18)
        self.layout.setSpacing(12)
        self.setWidget(self.content)
        self.current_subject: SubjectViewModel | None = None
        self.scan_cards: list[QFrame] = []

        header = QHBoxLayout()
        titles = QVBoxLayout()
        title = QLabel("MRI input readiness")
        title.setObjectName("cardTitle")
        description = QLabel(
            "Inspect the active converted versions, then validate their managed files "
            "before starting T1 or T2 analysis."
        )
        description.setObjectName("muted")
        description.setWordWrap(True)
        titles.addWidget(title)
        titles.addWidget(description)
        header.addLayout(titles, 1)
        self.import_inputs = secondary_button("Replace or add MRI…")
        self.import_inputs.clicked.connect(self.import_requested)
        header.addWidget(self.import_inputs)
        self.validate_inputs = QPushButton("Validate subject inputs")
        self.validate_inputs.clicked.connect(self._request_validation)
        header.addWidget(self.validate_inputs)
        self.layout.addLayout(header)

        self.readiness_card = QFrame()
        self.readiness_card.setObjectName("card")
        readiness_layout = QHBoxLayout(self.readiness_card)
        readiness_layout.setContentsMargins(14, 10, 14, 10)
        self.readiness_label = QLabel("No input selected")
        self.readiness_label.setWordWrap(True)
        readiness_layout.addWidget(self.readiness_label, 1)
        self.layout.addWidget(self.readiness_card)

        self.cards_layout = QVBoxLayout()
        self.cards_layout.setSpacing(10)
        self.layout.addLayout(self.cards_layout)

        self.next_step_card = QFrame()
        self.next_step_card.setObjectName("card")
        next_layout = QGridLayout(self.next_step_card)
        next_layout.setContentsMargins(16, 12, 16, 12)
        next_layout.setColumnStretch(0, 1)
        next_title = QLabel("What becomes available next")
        next_title.setObjectName("cardTitle")
        next_layout.addWidget(next_title, 0, 0, 1, 2)
        self.t1_next = QLabel()
        self.t1_next.setWordWrap(True)
        self.t2_next = QLabel()
        self.t2_next.setWordWrap(True)
        self.t1_continue = secondary_button("T1 brain-mask step")
        self.t1_continue.setEnabled(False)
        self.t2_continue = secondary_button("T2 lesion-mask step")
        self.t2_continue.setEnabled(False)
        next_layout.addWidget(self.t1_next, 1, 0)
        next_layout.addWidget(self.t1_continue, 1, 1)
        next_layout.addWidget(self.t2_next, 2, 0)
        next_layout.addWidget(self.t2_continue, 2, 1)
        self.layout.insertWidget(2, self.next_step_card)
        self.layout.addStretch()

    def set_subject(self, subject: SubjectViewModel) -> None:
        self.current_subject = subject
        self.validate_inputs.setEnabled(subject.can_validate_inputs)
        self.validate_inputs.setToolTip(
            ""
            if subject.can_validate_inputs
            else "Import and convert at least one MRI input first."
        )
        self._set_readiness(subject)
        clear_layout(self.cards_layout)
        self.scan_cards.clear()
        if subject.inputs:
            for scan in subject.inputs:
                card = self._scan_card(subject.subject_id, scan)
                self.scan_cards.append(card)
                self.cards_layout.addWidget(card)
        else:
            empty = QLabel(
                "No active MRI inputs are assigned to this subject. Use Replace or add "
                "MRI to review the source folder again."
            )
            empty.setObjectName("muted")
            empty.setWordWrap(True)
            empty.setContentsMargins(8, 12, 8, 12)
            self.cards_layout.addWidget(empty)
        self._set_next_steps(subject)

    def _set_readiness(self, subject: SubjectViewModel) -> None:
        if not subject.inputs:
            message = "No MRI inputs have been converted for this subject."
        else:
            conversion_failed = sum(
                scan.conversion.kind == "failed" for scan in subject.inputs
            )
            converting = sum(
                scan.conversion.kind == "processing" for scan in subject.inputs
            )
            invalid = sum(scan.validation.kind == "failed" for scan in subject.inputs)
            pending = sum(scan.validation.kind == "review" for scan in subject.inputs)
            if conversion_failed:
                message = (
                    f"{conversion_failed} input conversion(s) failed. Review the scan "
                    "card and import a corrected replacement."
                )
            elif converting:
                message = f"{converting} input conversion(s) are still running."
            elif invalid:
                message = (
                    f"{invalid} input(s) failed validation. Review the issue below and "
                    "replace or recreate the affected version."
                )
            elif pending:
                message = (
                    f"{pending} converted input(s) require validation before their "
                    "workflow can advance."
                )
            else:
                message = (
                    "All active converted inputs passed validation and are ready for "
                    "their next workflow step."
                )
        self.readiness_label.setText(message)

    def _set_next_steps(self, subject: SubjectViewModel) -> None:
        t1_ready = subject.t1_data.kind == "ready"
        t2_ready = subject.t2_data.kind == "ready"
        self.t1_next.setText(
            "T1: ready to create or import a versioned draft brain mask."
            if t1_ready
            else "T1: not expected for this subject."
            if subject.t1_data.label == "Not applicable"
            else f"T1: {subject.t1_data.label}. Validate a complete pre/post pair first."
        )
        self.t2_next.setText(
            "T2: ready to import a released lesion mask. Frozen-model execution will "
            "remain unavailable until a compatible LYS_PROJ1 release is installed."
            if t2_ready
            else "T2: not expected for this subject."
            if subject.t2_data.label == "Not applicable"
            else f"T2: {subject.t2_data.label}. Validate the converted T2 first."
        )
        t1_reason = (
            "The artifact/review service is the next implementation milestone."
            if t1_ready
            else "A validated T1 pair is required."
        )
        t2_reason = (
            "The released-mask artifact service is the next implementation milestone."
            if t2_ready
            else "A validated T2 input is required."
        )
        self.t1_continue.setToolTip(t1_reason)
        self.t2_continue.setToolTip(t2_reason)

    def _scan_card(self, subject_id: str, scan: InputScanViewModel) -> QFrame:
        card = QFrame()
        card.setObjectName("card")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(8)

        header = QHBoxLayout()
        title = QLabel(f"{scan.role_label} · version {scan.version}")
        title.setObjectName("cardTitle")
        header.addWidget(title)
        header.addStretch()
        header.addWidget(StatusBadge(scan.conversion))
        header.addWidget(StatusBadge(scan.validation))
        layout.addLayout(header)

        paths = QGridLayout()
        paths.setColumnStretch(1, 1)
        managed_key = QLabel("Managed NIfTI")
        managed_key.setObjectName("metadata")
        managed = ElidedLabel(str(scan.managed_path) if scan.managed_path else "—")
        source_key = QLabel("Source")
        source_key.setObjectName("metadata")
        source = ElidedLabel(str(scan.source_path))
        paths.addWidget(managed_key, 0, 0)
        paths.addWidget(managed, 0, 1)
        paths.addWidget(source_key, 1, 0)
        paths.addWidget(source, 1, 1)
        layout.addLayout(paths)

        facts = QGridLayout()
        fact_values = (
            ("Dimensions", scan.shape_text),
            ("Voxel spacing", scan.spacing_text),
            ("Axis codes", scan.orientation_text),
            ("Import transform", scan.transformation_text),
            ("SHA-256", scan.checksum_text),
        )
        for index, (label_text, value_text) in enumerate(fact_values):
            column = index % 3
            row = (index // 3) * 2
            label = QLabel(label_text)
            label.setObjectName("metadata")
            value = QLabel(value_text)
            value.setWordWrap(True)
            facts.addWidget(label, row, column)
            facts.addWidget(value, row + 1, column)
            facts.setColumnStretch(column, 1)
        layout.addLayout(facts)

        for issue in scan.issues:
            prefix = "Warning" if issue.severity == "warning" else "Problem"
            issue_label = QLabel(f"{prefix}: {issue.message}")
            issue_label.setWordWrap(True)
            issue_label.setProperty("issueSeverity", issue.severity)
            issue_label.setToolTip(issue.technical_detail or issue.code)
            layout.addWidget(issue_label)

        actions = QHBoxLayout()
        actions.addStretch()
        open_button = secondary_button("Open in ITK-SNAP")
        open_button.setEnabled(scan.can_open)
        open_button.clicked.connect(
            lambda _checked=False, sid=subject_id, input_id=scan.scan_input_id: (
                self.open_input_requested.emit(sid, input_id)
            )
        )
        flip_button = secondary_button("Create flipped version…")
        flip_button.setEnabled(scan.can_open)
        flip_button.clicked.connect(
            lambda _checked=False, sid=subject_id: self.flip_requested.emit(sid)
        )
        actions.addWidget(open_button)
        actions.addWidget(flip_button)
        layout.addLayout(actions)
        return card

    def _request_validation(self) -> None:
        if self.current_subject is not None:
            self.validation_requested.emit(self.current_subject.subject_id)
