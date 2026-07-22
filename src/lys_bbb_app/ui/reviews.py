"""General review queue for persistent scientific artifacts."""

from __future__ import annotations

from PySide6.QtCore import QTimer, Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSplitter,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from lys_bbb_app.domain.view_models import (
    ReviewItemViewModel,
    StudyViewModel,
)
from lys_bbb_app.ui.layout_helpers import clear_layout, page_heading
from lys_bbb_app.ui.widgets import StatusBadge, secondary_button


class ReviewsPage(QWidget):
    """Display actionable study-level review work without owning scientific state."""

    approve_requested = Signal(str, str)
    manual_edit_requested = Signal(str, str)
    subject_requested = Signal(str)
    qc_slices_requested = Signal(str, str)

    def __init__(self) -> None:
        super().__init__()
        self.reviews: tuple[ReviewItemViewModel, ...] = ()
        self.filtered: list[ReviewItemViewModel] = []
        self.current_item: ReviewItemViewModel | None = None
        self.current_row = -1
        self.current_slice = 1
        self.requested_qc_artifacts: set[str] = set()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 28)
        layout.setSpacing(14)
        heading, _heading_layout = page_heading("Review and QC")
        layout.addWidget(heading)

        splitter = QSplitter(Qt.Horizontal)
        splitter.setChildrenCollapsible(False)
        splitter.addWidget(self._build_categories())
        splitter.addWidget(self._build_queue())
        splitter.addWidget(self._build_viewer())
        splitter.addWidget(self._build_review_panel())
        splitter.setSizes([180, 270, 560, 300])
        layout.addWidget(splitter, 1)

    def _build_categories(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("panel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(12, 14, 12, 14)
        title = QLabel("Queues")
        title.setObjectName("cardTitle")
        layout.addWidget(title)
        self.modality_group = QButtonGroup(self)
        self.modality_group.setExclusive(True)
        self.modality_buttons: dict[str, QPushButton] = {}
        for modality in ("T1", "T2"):
            button = QPushButton(modality)
            button.setCheckable(True)
            button.setProperty("kind", "reviewFilter")
            button.clicked.connect(
                lambda checked, selected=modality: self._modality_changed(selected)
                if checked
                else None
            )
            self.modality_group.addButton(button)
            self.modality_buttons[modality] = button
            layout.addWidget(button)
        layout.addStretch()
        return panel

    def _build_queue(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("panel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(12, 14, 12, 14)
        title = QLabel("Awaiting review")
        title.setObjectName("cardTitle")
        layout.addWidget(title)
        self.queue_scroll = QScrollArea()
        self.queue_scroll.setWidgetResizable(True)
        self.queue_scroll.setFrameShape(QFrame.NoFrame)
        self.queue_container = QWidget()
        self.queue_layout = QVBoxLayout(self.queue_container)
        self.queue_layout.setContentsMargins(0, 2, 0, 2)
        self.queue_layout.setSpacing(8)
        self.queue_scroll.setWidget(self.queue_container)
        self.queue_group = QButtonGroup(self)
        self.queue_group.setExclusive(True)
        self.queue_buttons: list[QPushButton] = []
        layout.addWidget(self.queue_scroll)
        return panel

    def _build_viewer(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("panel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(10, 10, 10, 10)

        self.viewer_stack = QStackedWidget()
        self.qc_image = QLabel()
        self.qc_image.setAlignment(Qt.AlignCenter)
        self.qc_image.setStyleSheet("background: #101b2b; border-radius: 8px;")
        self.empty_viewer = QLabel(
            "No QC preview is available. Open the current mask in ITK-SNAP for full review."
        )
        self.empty_viewer.setAlignment(Qt.AlignCenter)
        self.empty_viewer.setWordWrap(True)
        self.empty_viewer.setObjectName("muted")
        self.viewer_stack.addWidget(self.qc_image)
        self.viewer_stack.addWidget(self.empty_viewer)
        layout.addWidget(self.viewer_stack, 1)

        controls = QHBoxLayout()
        previous = secondary_button("← Item")
        previous.clicked.connect(self._previous_item)
        next_item = secondary_button("Item →")
        next_item.clicked.connect(self._next_item)
        self.previous_slice = secondary_button("‹ Slice")
        self.previous_slice.clicked.connect(lambda: self._move_slice(-1))
        self.next_slice = secondary_button("Slice ›")
        self.next_slice.clicked.connect(lambda: self._move_slice(1))
        self.slice_label = QLabel("Slice 1 / 1")
        controls.addWidget(previous)
        controls.addWidget(next_item)
        controls.addStretch()
        controls.addWidget(self.previous_slice)
        controls.addWidget(self.slice_label)
        controls.addWidget(self.next_slice)
        layout.addLayout(controls)

        return panel

    def _build_review_panel(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("panel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(16, 15, 16, 15)
        self.review_subject = QLabel("Select a review item")
        self.review_subject.setObjectName("cardTitle")
        self.review_artifact = QLabel()
        self.review_artifact.setWordWrap(True)
        self.review_reason = QLabel()
        self.review_reason.setObjectName("muted")
        self.review_reason.setWordWrap(True)
        self.review_qc = QLabel()
        self.review_qc.setObjectName("infoBanner")
        self.review_qc.setWordWrap(True)
        self.review_qc.setMaximumHeight(90)
        self.review_status_holder = QHBoxLayout()

        self.approve = QPushButton("Approve current mask")
        self.approve.setObjectName("approveReviewButton")
        self.approve.clicked.connect(self._approve)
        self.manual_edit = secondary_button("Manually edit in ITK-SNAP…")
        self.manual_edit.clicked.connect(self._manual_edit)
        self.open_subject = secondary_button("Open subject details")
        self.open_subject.clicked.connect(self._open_subject)

        layout.addWidget(self.review_subject)
        layout.addWidget(self.review_artifact)
        layout.addWidget(self.review_reason)
        layout.addWidget(self.review_qc)
        layout.addLayout(self.review_status_holder)
        layout.addStretch()
        layout.addWidget(self.approve)
        layout.addWidget(self.manual_edit)
        layout.addWidget(self.open_subject)
        self._set_actions_enabled(False)
        return panel

    def set_study(self, study: StudyViewModel) -> None:
        self.reviews = study.reviews
        default_modality = "T2" if any(
            _review_modality(item) == "T2" for item in self.reviews
        ) else "T1"
        self.modality_buttons[default_modality].setChecked(True)
        self._populate_queue(default_modality)

    def focus_subject(self, subject_id: str) -> None:
        review = next(
            (item for item in self.reviews if item.subject_id == subject_id),
            None,
        )
        if review is None:
            return
        modality = _review_modality(review)
        self.modality_buttons[modality].setChecked(True)
        self._populate_queue(modality)
        for index, item in enumerate(self.filtered):
            if item.subject_id == subject_id:
                self._select_review(index)
                break

    def _modality_changed(self, modality: str) -> None:
        self._populate_queue(modality)

    def _populate_queue(self, modality: str) -> None:
        self.filtered = [
            review
            for review in self.reviews
            if _review_modality(review) == modality
        ]
        for button in self.queue_buttons:
            self.queue_group.removeButton(button)
        self.queue_buttons.clear()
        clear_layout(self.queue_layout)
        for index, review in enumerate(self.filtered):
            subject = review.subject_label or review.subject_id
            button = QPushButton(f"{subject} — {_review_workflow_label(review)}")
            button.setCheckable(True)
            button.setProperty("kind", "reviewItem")
            button.clicked.connect(
                lambda checked, row=index: self._select_review(row)
                if checked
                else None
            )
            self.queue_group.addButton(button)
            self.queue_buttons.append(button)
            self.queue_layout.addWidget(button)
        self.queue_layout.addStretch()
        if self.filtered:
            self._select_review(0)
        else:
            self._clear_selection()

    def _select_review(self, row: int) -> None:
        if not 0 <= row < len(self.filtered):
            self._clear_selection()
            return
        self.current_item = self.filtered[row]
        self.current_row = row
        self.queue_buttons[row].setChecked(True)
        review = self.current_item
        subject = review.subject_label or review.subject_id
        available_slices = len(review.qc_slice_paths) or review.slice_count
        self.current_slice = max(1, (available_slices + 1) // 2)
        self.review_subject.setText(f"{subject} · {review.category}")
        self.review_artifact.setText(review.artifact_name)
        self.review_reason.setText(review.reason)
        self.review_qc.setText(review.automatic_qc)
        clear_layout(self.review_status_holder)
        self.review_status_holder.addWidget(StatusBadge(review.status))
        self.review_status_holder.addStretch()
        self._show_review_image(review)
        self._set_actions_enabled(True)

    def _show_review_image(self, review: ReviewItemViewModel) -> None:
        has_real_slices = bool(review.qc_slice_paths)
        can_browse_slices = has_real_slices
        self.previous_slice.setVisible(can_browse_slices)
        self.next_slice.setVisible(can_browse_slices)
        self.slice_label.setVisible(can_browse_slices)
        if has_real_slices:
            self._show_real_qc_slice(review)
            return
        preview = review.qc_preview_path
        if preview is not None and preview.is_file():
            pixmap = QPixmap(str(preview))
            if not pixmap.isNull():
                self.qc_image.setPixmap(
                    pixmap.scaled(820, 500, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                )
                self.viewer_stack.setCurrentWidget(self.qc_image)
                if (
                    review.artifact_id is not None
                    and review.artifact_id not in self.requested_qc_artifacts
                ):
                    self.requested_qc_artifacts.add(review.artifact_id)
                    QTimer.singleShot(
                        0,
                        lambda subject_id=review.subject_id,
                        artifact_id=review.artifact_id: self.qc_slices_requested.emit(
                            subject_id,
                            artifact_id,
                        ),
                    )
                return
        self.viewer_stack.setCurrentWidget(self.empty_viewer)

    def _clear_selection(self) -> None:
        self.current_item = None
        self.current_row = -1
        self.review_subject.setText("No artifacts are awaiting review")
        self.review_artifact.clear()
        self.review_reason.setText(
            "Run an eligible workflow to create a review item for this modality."
        )
        self.review_qc.clear()
        clear_layout(self.review_status_holder)
        self.viewer_stack.setCurrentWidget(self.empty_viewer)
        self.previous_slice.hide()
        self.next_slice.hide()
        self.slice_label.hide()
        self._set_actions_enabled(False)

    def _set_actions_enabled(self, selected: bool) -> None:
        actionable = (
            selected
            and self.current_item is not None
            and self.current_item.artifact_id is not None
        )
        self.approve.setEnabled(actionable)
        self.manual_edit.setEnabled(actionable)
        self.open_subject.setEnabled(selected)

    def _move_slice(self, delta: int) -> None:
        if self.current_item is None:
            return
        slice_count = len(self.current_item.qc_slice_paths)
        if slice_count < 1:
            return
        self.current_slice = max(
            1,
            min(self.current_slice + delta, slice_count),
        )
        self._show_real_qc_slice(self.current_item)

    def _show_real_qc_slice(self, review: ReviewItemViewModel) -> None:
        slice_count = len(review.qc_slice_paths)
        if not 1 <= self.current_slice <= slice_count:
            self.viewer_stack.setCurrentWidget(self.empty_viewer)
            return
        pixmap = QPixmap(str(review.qc_slice_paths[self.current_slice - 1]))
        if pixmap.isNull():
            self.viewer_stack.setCurrentWidget(self.empty_viewer)
            return
        self.qc_image.setPixmap(
            pixmap.scaled(820, 500, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        )
        self.slice_label.setText(f"Slice {self.current_slice} / {slice_count}")
        self.viewer_stack.setCurrentWidget(self.qc_image)

    def _previous_item(self) -> None:
        if self.filtered:
            self._select_review(max(0, self.current_row - 1))

    def _next_item(self) -> None:
        if self.filtered:
            self._select_review(min(len(self.filtered) - 1, self.current_row + 1))

    def _approve(self) -> None:
        review = self.current_item
        if review is None:
            return
        if review.artifact_id is not None:
            self.approve_requested.emit(
                review.subject_id,
                review.artifact_id,
            )

    def _manual_edit(self) -> None:
        review = self.current_item
        if review is None:
            return
        if review.artifact_id is not None:
            self.manual_edit_requested.emit(review.subject_id, review.artifact_id)

    def _open_subject(self) -> None:
        if self.current_item is not None:
            self.subject_requested.emit(self.current_item.subject_id)

def _review_modality(review: ReviewItemViewModel) -> str:
    if review.workflow_key:
        return "T2" if review.workflow_key == "t2_lesion" else "T1"
    text = f"{review.category} {review.artifact_name}".casefold()
    return "T2" if "t2" in text or "lesion" in text else "T1"


def _review_workflow_label(review: ReviewItemViewModel) -> str:
    if review.workflow_key == "t2_lesion":
        return "T2 lesion"
    if review.workflow_key == "t1_brain_mask":
        return "T1 brain mask"
    text = f"{review.category} {review.artifact_name}".casefold()
    if "t2" in text or "lesion" in text:
        return "T2 lesion"
    if "registration" in text:
        return "T1 registration"
    if "brain mask" in text or "brain masks" in text:
        return "T1 brain mask"
    return "T1 result"
