"""Action-first subject-centred workspace page."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from lys_bbb_app.domain.view_models import SubjectViewModel
from lys_bbb_app.ui.layout_helpers import clear_layout
from lys_bbb_app.ui.subject_inputs import SubjectInputsPanel
from lys_bbb_app.ui.t1_brain_mask import T1BrainMaskPanel
from lys_bbb_app.ui.t2_lesion import T2LesionPanel
from lys_bbb_app.ui.widgets import (
    CollapsibleSection,
    ElidedLabel,
    StatusBadge,
    secondary_button,
)


class SubjectWorkspacePage(QScrollArea):
    back_requested = Signal()
    open_mri_requested = Signal(str)
    input_mri_open_requested = Signal(str, str)
    input_validation_requested = Signal(str)
    input_flip_requested = Signal(str)
    input_import_requested = Signal()
    rename_requested = Signal(str)
    t2_release_requested = Signal()
    t2_run_subject_requested = Signal(str)
    t2_run_study_requested = Signal()
    t2_manual_edit_requested = Signal(str, str)
    t2_approve_requested = Signal(str, str)
    t1_brain_mask_release_requested = Signal()
    t1_brain_mask_run_requested = Signal(str)
    t1_brain_mask_manual_edit_requested = Signal(str, str)
    t1_brain_mask_approve_requested = Signal(str, str)

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
        self._next_action_code = "inputs"

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

        self.next_action_card = QFrame()
        self.next_action_card.setObjectName("card")
        next_action_layout = QHBoxLayout(self.next_action_card)
        next_action_layout.setContentsMargins(18, 14, 18, 14)
        next_action_layout.setSpacing(18)
        next_action_copy = QVBoxLayout()
        next_action_copy.setSpacing(3)
        next_action_label = QLabel("NEXT ACTION")
        next_action_label.setObjectName("metadata")
        self.next_action_title = QLabel()
        self.next_action_title.setObjectName("cardTitle")
        self.next_action_detail = QLabel()
        self.next_action_detail.setObjectName("muted")
        self.next_action_detail.setWordWrap(True)
        next_action_copy.addWidget(next_action_label)
        next_action_copy.addWidget(self.next_action_title)
        next_action_copy.addWidget(self.next_action_detail)
        next_action_layout.addLayout(next_action_copy, 1)
        self.next_action_button = QPushButton()
        self.next_action_button.clicked.connect(self._perform_next_action)
        next_action_layout.addWidget(self.next_action_button)
        self.layout.addWidget(self.next_action_card)

        self.workflow_summary = QFrame()
        self.workflow_summary.setObjectName("subtleCard")
        workflow_layout = QHBoxLayout(self.workflow_summary)
        workflow_layout.setContentsMargins(14, 10, 14, 10)
        workflow_layout.setSpacing(12)
        t1_label = QLabel("T1")
        t1_label.setObjectName("metadata")
        workflow_layout.addWidget(t1_label)
        self.t1_status_layout = QHBoxLayout()
        workflow_layout.addLayout(self.t1_status_layout)
        workflow_layout.addStretch()
        t2_label = QLabel("T2")
        t2_label.setObjectName("metadata")
        workflow_layout.addWidget(t2_label)
        self.t2_status_layout = QHBoxLayout()
        workflow_layout.addLayout(self.t2_status_layout)
        self.layout.addWidget(self.workflow_summary)

        self.technical_details = CollapsibleSection("Technical subject details")
        self.metadata_layout = self.technical_details.content_layout
        self.metadata_value_labels: list[ElidedLabel] = []
        self.layout.addWidget(self.technical_details)

        self.tabs = QTabWidget()
        self.inputs_panel = SubjectInputsPanel()
        self.inputs_panel.open_input_requested.connect(
            self.input_mri_open_requested.emit
        )
        self.inputs_panel.validation_requested.connect(
            self.input_validation_requested.emit
        )
        self.inputs_panel.flip_requested.connect(self.input_flip_requested.emit)
        self.inputs_panel.import_requested.connect(self.input_import_requested.emit)
        self.t1_brain_mask_panel = T1BrainMaskPanel()
        self.t1_brain_mask_panel.select_release_requested.connect(
            self.t1_brain_mask_release_requested.emit
        )
        self.t1_brain_mask_panel.run_subject_requested.connect(
            self.t1_brain_mask_run_requested.emit
        )
        self.t1_brain_mask_panel.manual_edit_requested.connect(
            self.t1_brain_mask_manual_edit_requested.emit
        )
        self.t1_brain_mask_panel.approve_requested.connect(
            self.t1_brain_mask_approve_requested.emit
        )
        self.t2_panel = T2LesionPanel()
        self.t2_panel.select_release_requested.connect(self.t2_release_requested.emit)
        self.t2_panel.run_subject_requested.connect(self.t2_run_subject_requested.emit)
        self.t2_panel.run_study_requested.connect(self.t2_run_study_requested.emit)
        self.t2_panel.manual_edit_requested.connect(
            self.t2_manual_edit_requested.emit
        )
        self.t2_panel.approve_requested.connect(self.t2_approve_requested.emit)
        self.history_list = QListWidget()
        self.tabs.addTab(self.inputs_panel, "Inputs")
        self.tabs.addTab(self.t1_brain_mask_panel, "T1 Brain Mask")
        self.tabs.addTab(self.t2_panel, "T2 Lesion")
        self.tabs.addTab(self.history_list, "History")
        self.tabs.setMinimumHeight(390)
        self.tabs.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.layout.addWidget(self.tabs, 1)

    def set_subject(self, subject: SubjectViewModel) -> None:
        self.current_subject = subject
        self.subject_title.setText(subject.label)
        self.open_mri.setEnabled(subject.mri_input_count > 0)
        self._refresh_subject_subtitle()
        self.inputs_panel.set_subject(subject)
        self.t1_brain_mask_panel.set_subject(subject)
        self.t2_panel.set_subject(subject)
        self.technical_details.set_expanded(False)

        clear_layout(self.t1_status_layout)
        self.t1_status_layout.addWidget(StatusBadge(subject.t1_workflow_status))
        clear_layout(self.t2_status_layout)
        self.t2_status_layout.addWidget(StatusBadge(subject.t2_workflow_status))
        self._set_next_action(subject)

        clear_layout(self.metadata_layout)
        self.metadata_value_labels.clear()
        metadata_header = QHBoxLayout()
        metadata_title = QLabel("Stored subject information")
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

        self.history_list.clear()
        self.history_list.addItems(subject.history or ("No history recorded.",))

    def _set_next_action(self, subject: SubjectViewModel) -> None:
        action = subject.next_action
        self.next_action_title.setText(action.label)
        self.next_action_button.setText(action.label)
        self.next_action_button.setVisible(True)
        self.next_action_button.setEnabled(action.kind != "processing")

        if not subject.inputs:
            self._next_action_code = "import"
            detail = "Add the subject's pre/post T1 or native T2 scans."
        elif subject.needs_input_validation:
            self._next_action_code = "validate"
            detail = "Run geometry and provenance checks on the converted MRI."
        elif subject.t1_data.kind == "failed" or subject.t2_data.kind == "failed":
            self._next_action_code = "inputs"
            self.next_action_button.setText("Open inputs")
            detail = "Review the affected scan and replace it if needed."
        elif subject.brain_mask.kind == "review":
            self._next_action_code = "t1"
            detail = "Inspect the current mask, correct it if needed, then approve it."
        elif subject.registration.kind == "review":
            self._next_action_code = "t1"
            self.next_action_button.setText("Open T1 workflow")
            detail = "The registered post-Gd image is awaiting explicit review."
        elif subject.t2_lesion.kind == "review":
            self._next_action_code = "t2"
            detail = "Inspect the lesion mask, correct it if needed, then approve it."
        elif action.label == "Select T1 mask method":
            self._next_action_code = "select_t1"
            detail = "Choose and validate the frozen local T1 mask release."
        elif action.label == "Generate T1 brain mask":
            self._next_action_code = "run_t1"
            detail = "Generate an automatic draft; human review will still be required."
        elif action.label == "Select T2 model release":
            self._next_action_code = "select_t2"
            detail = "Choose and validate the frozen T2 ensemble release."
        elif action.label == "Run T2 segmentation":
            self._next_action_code = "run_t2"
            detail = "Generate a lesion-mask draft for explicit human review."
        elif action.label in {"Run T1 registration", "Calculate T1 enhancement"}:
            self._next_action_code = "t1"
            self.next_action_button.setText("Open T1 workflow")
            detail = "The subject is ready for the next T1 analysis step."
        elif action.kind == "processing":
            self._next_action_code = "none"
            detail = "The current background operation must finish before continuing."
        elif action.kind == "approved":
            self._next_action_code = "none"
            self.next_action_button.hide()
            detail = "All currently enabled workflow steps are complete."
        else:
            self._next_action_code = "inputs"
            self.next_action_button.setText("Review workflow")
            detail = "Open the relevant workflow to inspect its current state."
        self.next_action_detail.setText(detail)

    def _perform_next_action(self) -> None:
        subject = self.current_subject
        if subject is None:
            return
        if self._next_action_code == "import":
            self.input_import_requested.emit()
        elif self._next_action_code == "validate":
            self.input_validation_requested.emit(subject.subject_id)
        elif self._next_action_code == "inputs":
            self._show_inputs()
        elif self._next_action_code == "t1":
            self._show_t1()
        elif self._next_action_code == "t2":
            self._show_t2()
        elif self._next_action_code == "select_t1":
            self.t1_brain_mask_release_requested.emit()
        elif self._next_action_code == "run_t1":
            self.t1_brain_mask_run_requested.emit(subject.subject_id)
        elif self._next_action_code == "select_t2":
            self.t2_release_requested.emit()
        elif self._next_action_code == "run_t2":
            self.t2_run_subject_requested.emit(subject.subject_id)

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
        self.subject_subtitle.setText(f"Group: {group}   ·   Updated {subject.updated}")

    def _show_inputs(self) -> None:
        self.tabs.setCurrentWidget(self.inputs_panel)

    def _show_t2(self) -> None:
        self.tabs.setCurrentWidget(self.t2_panel)

    def _show_t1(self) -> None:
        self.tabs.setCurrentWidget(self.t1_brain_mask_panel)
