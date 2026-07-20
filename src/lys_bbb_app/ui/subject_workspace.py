"""Responsive subject-centred workspace page."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QScrollArea,
    QSizePolicy,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from lys_bbb_app.domain.view_models import StatusValue, SubjectViewModel
from lys_bbb_app.ui.layout_helpers import clear_layout
from lys_bbb_app.ui.widgets import ElidedLabel, StatusBadge, secondary_button


class SubjectWorkspacePage(QScrollArea):
    back_requested = Signal()
    open_mri_requested = Signal(str)
    rename_requested = Signal(str)
    review_requested = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.content = QWidget()
        self.layout = QVBoxLayout(self.content)
        self.layout.setContentsMargins(28, 18, 28, 20)
        self.layout.setSpacing(12)
        self.setWidget(self.content)
        self.current_subject: SubjectViewModel | None = None
        self.blinded_review = False

        top = QHBoxLayout()
        back = secondary_button("← Subjects")
        back.clicked.connect(self.back_requested)
        top.addWidget(back)
        top.addStretch()
        self.open_mri = secondary_button("Open MRI in ITK-SNAP")
        self.open_mri.clicked.connect(self._open_mri)
        top.addWidget(self.open_mri)
        self.rename_subject = secondary_button("Rename subject…")
        self.rename_subject.clicked.connect(self._rename_subject)
        top.addWidget(self.rename_subject)
        self.layout.addLayout(top)

        self.subject_title = QLabel("Subject")
        self.subject_title.setObjectName("pageTitle")
        self.subject_subtitle = QLabel()
        self.subject_subtitle.setObjectName("muted")
        self.subject_subtitle.setWordWrap(True)
        self.subject_subtitle.setMinimumWidth(0)
        self.subject_subtitle.setSizePolicy(
            QSizePolicy.Ignored,
            QSizePolicy.Preferred,
        )
        self.layout.addWidget(self.subject_title)
        self.layout.addWidget(self.subject_subtitle)

        self.metadata_card = QFrame()
        self.metadata_card.setObjectName("card")
        self.metadata_layout = QVBoxLayout(self.metadata_card)
        self.metadata_layout.setContentsMargins(18, 14, 18, 14)
        self.metadata_layout.setSpacing(7)
        self.metadata_value_labels: list[ElidedLabel] = []
        self.layout.addWidget(self.metadata_card)

        title = QLabel("Workflow progress")
        title.setObjectName("sectionTitle")
        self.layout.addWidget(title)
        self.workflow_container = QWidget()
        self.workflow_layout = QVBoxLayout(self.workflow_container)
        self.workflow_layout.setContentsMargins(0, 0, 0, 0)
        self.workflow_layout.setSpacing(12)
        self.layout.addWidget(self.workflow_container)

        self.tabs = QTabWidget()
        self.summary_tab = QLabel()
        self.summary_tab.setWordWrap(True)
        self.summary_tab.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.summary_tab.setMargin(18)
        self.inputs_tab = QLabel(
            "Input assignments, geometry, hashes, and validation issues will appear here."
        )
        self.inputs_tab.setWordWrap(True)
        self.inputs_tab.setMargin(18)
        self.history_list = QListWidget()
        self.tabs.addTab(self.summary_tab, "Summary")
        self.tabs.addTab(self.inputs_tab, "Inputs")
        self.tabs.addTab(self.history_list, "History")
        self.tabs.setMinimumHeight(130)
        self.tabs.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.layout.addWidget(self.tabs, 1)

    def set_subject(self, subject: SubjectViewModel) -> None:
        self.current_subject = subject
        self.subject_title.setText(subject.label)
        self.open_mri.setEnabled(subject.mri_input_count > 0)
        self._refresh_subject_subtitle()

        clear_layout(self.metadata_layout)
        self.metadata_value_labels.clear()
        metadata_header = QHBoxLayout()
        metadata_title = QLabel("Subject details")
        metadata_title.setObjectName("cardTitle")
        metadata_header.addWidget(metadata_title)
        metadata_header.addStretch()
        metadata_header.addWidget(StatusBadge(subject.overall))
        self.metadata_layout.addLayout(metadata_header)
        for label, value in subject.metadata:
            row = QHBoxLayout()
            row.setSpacing(16)
            key = QLabel(label)
            key.setObjectName("metadata")
            key.setMinimumWidth(145)
            key.setMaximumWidth(180)
            value_label = ElidedLabel(value)
            value_label.setStyleSheet("font-weight: 650;")
            self.metadata_value_labels.append(value_label)
            row.addWidget(key)
            row.addWidget(value_label, 1)
            self.metadata_layout.addLayout(row)

        clear_layout(self.workflow_layout)
        cards = (
            (
                "T1 Enhancement",
                "Imported → Mask review → Registration review → Quantification → Complete",
                subject.t1_result
                if subject.t1_result.kind not in {"failed", "unavailable"}
                else subject.brain_mask,
                "Review T1 artifacts",
            ),
            (
                "T2 Lesion",
                "Imported → Mask generated/imported → Review → Quantification → Complete",
                subject.t2_lesion,
                "Review T2 artifacts",
            ),
        )
        for title, progression, status, action in cards:
            self.workflow_layout.addWidget(
                self._workflow_row(title, progression, status, action)
            )

        self.summary_tab.setText(
            "This workspace keeps every workflow under one subject identity. Use the "
            "workflow cards above to move to the relevant review queue. Scientific "
            "actions remain disabled until their service and state contracts are "
            "implemented."
        )
        self.history_list.clear()
        self.history_list.addItems(subject.history or ("No history recorded.",))

    def _open_mri(self) -> None:
        if self.current_subject is not None:
            self.open_mri_requested.emit(self.current_subject.subject_id)

    def _rename_subject(self) -> None:
        if self.current_subject is not None:
            self.rename_requested.emit(self.current_subject.subject_id)

    def set_blinded_review(self, blinded: bool) -> None:
        self.blinded_review = blinded
        self._refresh_subject_subtitle()

    def _refresh_subject_subtitle(self) -> None:
        subject = self.current_subject
        if subject is None:
            return
        group = (
            "Hidden during blinded review"
            if self.blinded_review
            else subject.group or "Unassigned"
        )
        self.subject_subtitle.setText(
            f"Group: {group}   ·   Overall state: {subject.overall.label}   ·   "
            f"Updated {subject.updated}"
        )

    def _workflow_row(
        self,
        title_text: str,
        progression: str,
        status: StatusValue,
        action_text: str,
    ) -> QFrame:
        card = QFrame()
        card.setObjectName("card")
        card.setMinimumHeight(88)
        layout = QGridLayout(card)
        layout.setContentsMargins(18, 12, 18, 12)
        layout.setHorizontalSpacing(16)
        layout.setVerticalSpacing(5)
        layout.setColumnStretch(0, 1)
        title = QLabel(title_text)
        title.setObjectName("cardTitle")
        progress = QLabel(progression)
        progress.setObjectName("muted")
        progress.setWordWrap(True)
        progress.setMinimumWidth(0)
        progress.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        layout.addWidget(title, 0, 0)
        layout.addWidget(StatusBadge(status), 0, 1, Qt.AlignRight)
        layout.addWidget(progress, 1, 0)
        button = secondary_button(action_text)
        subject_id = self.current_subject.subject_id if self.current_subject else ""
        button.clicked.connect(
            lambda _checked=False, selected_subject_id=subject_id: (
                self.review_requested.emit(selected_subject_id)
            )
        )
        layout.addWidget(button, 1, 1, Qt.AlignRight)
        return card
