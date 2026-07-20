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
from lys_bbb_app.ui.subject_inputs import SubjectInputsPanel
from lys_bbb_app.ui.widgets import ElidedLabel, StatusBadge, secondary_button


class SubjectWorkspacePage(QScrollArea):
    back_requested = Signal()
    open_mri_requested = Signal(str)
    input_mri_open_requested = Signal(str, str)
    input_validation_requested = Signal(str)
    input_flip_requested = Signal(str)
    input_import_requested = Signal()
    rename_requested = Signal(str)

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

        self.workflow_title = QLabel("Workflow progress")
        self.workflow_title.setObjectName("sectionTitle")
        self.layout.addWidget(self.workflow_title)
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
        self.inputs_panel = SubjectInputsPanel()
        self.inputs_panel.open_input_requested.connect(
            self.input_mri_open_requested.emit
        )
        self.inputs_panel.validation_requested.connect(
            self.input_validation_requested.emit
        )
        self.inputs_panel.flip_requested.connect(self.input_flip_requested.emit)
        self.inputs_panel.import_requested.connect(self.input_import_requested.emit)
        self.history_list = QListWidget()
        self.tabs.addTab(self.summary_tab, "Summary")
        self.tabs.addTab(self.inputs_panel, "Inputs")
        self.tabs.addTab(self.history_list, "History")
        self.tabs.setMinimumHeight(130)
        self.tabs.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.tabs.currentChanged.connect(self._tab_changed)
        self.layout.addWidget(self.tabs, 1)

    def set_subject(self, subject: SubjectViewModel) -> None:
        self.current_subject = subject
        self.subject_title.setText(subject.label)
        self.open_mri.setEnabled(subject.mri_input_count > 0)
        self._refresh_subject_subtitle()
        self.inputs_panel.set_subject(subject)

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
        t1_inputs_ready = subject.t1_data.kind == "ready"
        t2_inputs_ready = subject.t2_data.kind == "ready"
        cards = (
            (
                "T1 Enhancement",
                "Imported → Mask review → Registration review → Quantification → Complete",
                subject.brain_mask if t1_inputs_ready else subject.t1_data,
                "Brain-mask step" if t1_inputs_ready else "Review inputs",
                not t1_inputs_ready and subject.t1_data.label != "Not applicable",
            ),
            (
                "T2 Lesion",
                "Imported → Mask generated/imported → Review → Quantification → Complete",
                subject.t2_lesion if t2_inputs_ready else subject.t2_data,
                "Lesion-mask step" if t2_inputs_ready else "Review inputs",
                not t2_inputs_ready and subject.t2_data.label != "Not applicable",
            ),
        )
        for title, progression, status, action, action_enabled in cards:
            self.workflow_layout.addWidget(
                self._workflow_row(
                    title,
                    progression,
                    status,
                    action,
                    action_enabled=action_enabled,
                )
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
        *,
        action_enabled: bool,
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
        button.setEnabled(action_enabled)
        button.setToolTip(
            ""
            if action_enabled
            else "This input is ready. The versioned artifact/review step is the next milestone."
        )
        button.clicked.connect(self._show_inputs)
        layout.addWidget(button, 1, 1, Qt.AlignRight)
        return card

    def _show_inputs(self) -> None:
        self.tabs.setCurrentWidget(self.inputs_panel)

    def _tab_changed(self, _index: int) -> None:
        inputs_focused = self.tabs.currentWidget() is self.inputs_panel
        self.metadata_card.setVisible(not inputs_focused)
        self.workflow_title.setVisible(not inputs_focused)
        self.workflow_container.setVisible(not inputs_focused)
