"""General review queue for synthetic fixtures and persistent T2 artifacts."""

from __future__ import annotations

from collections import Counter

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSlider,
    QSplitter,
    QStackedWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from lys_bbb_app.domain.t2_lesion import T2_REJECTION_ISSUES
from lys_bbb_app.domain.view_models import (
    ReviewItemViewModel,
    StatusValue,
    StudyViewModel,
)
from lys_bbb_app.ui.layout_helpers import clear_layout, page_heading
from lys_bbb_app.ui.widgets import StatusBadge, SyntheticSliceViewer, secondary_button


class ReviewsPage(QWidget):
    """Display actionable study-level review work without owning scientific state."""

    decision_recorded = Signal(str)
    approve_requested = Signal(str, str, str)
    reject_requested = Signal(str, str, str, str)
    correction_requested = Signal(str, str)
    import_correction_requested = Signal(str, str)
    subject_requested = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.is_demo = False
        self.reviews: tuple[ReviewItemViewModel, ...] = ()
        self.filtered: list[ReviewItemViewModel] = []
        self.current_item: ReviewItemViewModel | None = None
        self.current_slice = 1
        self.decisions: dict[str, StatusValue] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 28)
        layout.setSpacing(14)
        heading, _heading_layout = page_heading(
            "Review and QC",
            "Study-level work queue for masks and other review-gated artifacts.",
        )
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
        self.category_list = QListWidget()
        self.category_list.setObjectName("reviewCategories")
        self.category_list.currentTextChanged.connect(self._category_changed)
        layout.addWidget(title)
        layout.addWidget(self.category_list)
        return panel

    def _build_queue(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("panel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(12, 14, 12, 14)
        title = QLabel("Awaiting review")
        title.setObjectName("cardTitle")
        self.queue_list = QListWidget()
        self.queue_list.setObjectName("reviewQueue")
        self.queue_list.currentRowChanged.connect(self._select_review)
        layout.addWidget(title)
        layout.addWidget(self.queue_list)
        return panel

    def _build_viewer(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("panel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(10, 10, 10, 10)

        self.viewer_stack = QStackedWidget()
        self.synthetic_viewer = SyntheticSliceViewer()
        self.qc_image = QLabel()
        self.qc_image.setAlignment(Qt.AlignCenter)
        self.qc_image.setStyleSheet("background: #101b2b; border-radius: 8px;")
        self.empty_viewer = QLabel(
            "No QC preview is available. Open the current mask in ITK-SNAP for full review."
        )
        self.empty_viewer.setAlignment(Qt.AlignCenter)
        self.empty_viewer.setWordWrap(True)
        self.empty_viewer.setObjectName("muted")
        self.viewer_stack.addWidget(self.synthetic_viewer)
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

        self.overlay_controls = QWidget()
        overlay = QHBoxLayout(self.overlay_controls)
        overlay.setContentsMargins(0, 0, 0, 0)
        visible = QCheckBox("Mask overlay")
        visible.setChecked(True)
        visible.toggled.connect(
            lambda enabled: self.synthetic_viewer.set_overlay_opacity(
                self.opacity.value() / 100 if enabled else 0.0
            )
        )
        self.opacity = QSlider(Qt.Horizontal)
        self.opacity.setRange(0, 100)
        self.opacity.setValue(55)
        self.opacity.valueChanged.connect(
            lambda value: self.synthetic_viewer.set_overlay_opacity(value / 100)
        )
        overlay.addWidget(visible)
        overlay.addWidget(QLabel("Opacity"))
        overlay.addWidget(self.opacity)
        layout.addWidget(self.overlay_controls)
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

        self.issue = QComboBox()
        self.issue.addItem("Select issue type…", None)
        for label, code in T2_REJECTION_ISSUES:
            self.issue.addItem(label, code)
        self.notes = QTextEdit()
        self.notes.setPlaceholderText(
            "Optional approval note; rejection requires a reason…"
        )
        self.notes.setMaximumHeight(100)

        self.approve = QPushButton("Approve")
        self.approve.setObjectName("approveReviewButton")
        self.approve.clicked.connect(self._approve)
        self.reject = QPushButton("Reject")
        self.reject.setObjectName("rejectReviewButton")
        self.reject.setProperty("kind", "danger")
        self.reject.clicked.connect(self._reject)
        self.correction = secondary_button("Correct a copy in ITK-SNAP")
        self.correction.clicked.connect(self._open_correction)
        self.import_correction = secondary_button("Import corrected mask…")
        self.import_correction.clicked.connect(self._import_correction)
        self.open_subject = secondary_button("Open subject details")
        self.open_subject.clicked.connect(self._open_subject)

        layout.addWidget(self.review_subject)
        layout.addWidget(self.review_artifact)
        layout.addWidget(self.review_reason)
        layout.addWidget(self.review_qc)
        layout.addLayout(self.review_status_holder)
        layout.addSpacing(8)
        layout.addWidget(QLabel("Issue type"))
        layout.addWidget(self.issue)
        layout.addWidget(QLabel("Reviewer notes"))
        layout.addWidget(self.notes)
        layout.addStretch()
        layout.addWidget(self.approve)
        layout.addWidget(self.reject)
        layout.addWidget(self.correction)
        layout.addWidget(self.import_correction)
        layout.addWidget(self.open_subject)
        self._set_actions_enabled(False)
        return panel

    def set_study(self, study: StudyViewModel) -> None:
        self.is_demo = study.is_demo
        self.reviews = study.reviews
        self.decisions.clear()
        counts = Counter(item.category for item in self.reviews)
        categories = ["All reviews", *sorted(counts)]
        self.category_list.blockSignals(True)
        self.category_list.clear()
        for category in categories:
            count = len(self.reviews) if category == "All reviews" else counts[category]
            item = QListWidgetItem(f"{category}  {count}")
            item.setData(Qt.UserRole, category)
            self.category_list.addItem(item)
        self.category_list.blockSignals(False)
        self.category_list.setCurrentRow(0)
        self._populate_queue("All reviews")

    def focus_subject(self, subject_id: str) -> None:
        self.category_list.setCurrentRow(0)
        for index, review in enumerate(self.filtered):
            if review.subject_id == subject_id:
                self.queue_list.setCurrentRow(index)
                break

    def _category_changed(self, _display_text: str) -> None:
        item = self.category_list.currentItem()
        category = item.data(Qt.UserRole) if item is not None else "All reviews"
        self._populate_queue(category)

    def _populate_queue(self, category: str) -> None:
        self.filtered = [
            review
            for review in self.reviews
            if category == "All reviews" or review.category == category
        ]
        self.queue_list.blockSignals(True)
        self.queue_list.clear()
        for review in self.filtered:
            decision = self.decisions.get(review.review_id, review.status)
            subject = review.subject_label or review.subject_id
            self.queue_list.addItem(
                QListWidgetItem(
                    f"{subject}\n{review.artifact_name}\n{decision.label}"
                )
            )
        self.queue_list.blockSignals(False)
        if self.filtered:
            self.queue_list.setCurrentRow(0)
            self._select_review(0)
        else:
            self._clear_selection()

    def _select_review(self, row: int) -> None:
        if not 0 <= row < len(self.filtered):
            self._clear_selection()
            return
        self.current_item = self.filtered[row]
        review = self.current_item
        subject = review.subject_label or review.subject_id
        self.current_slice = max(1, review.slice_count // 2)
        self.review_subject.setText(f"{subject} · {review.category}")
        self.review_artifact.setText(review.artifact_name)
        self.review_reason.setText(review.reason)
        self.review_qc.setText(review.automatic_qc)
        clear_layout(self.review_status_holder)
        status = self.decisions.get(review.review_id, review.status)
        self.review_status_holder.addWidget(StatusBadge(status))
        self.review_status_holder.addStretch()
        self.issue.setCurrentIndex(0)
        self.notes.clear()
        self._show_review_image(review)
        self._set_actions_enabled(True)

    def _show_review_image(self, review: ReviewItemViewModel) -> None:
        self.previous_slice.setVisible(self.is_demo)
        self.next_slice.setVisible(self.is_demo)
        self.slice_label.setVisible(self.is_demo)
        self.overlay_controls.setVisible(self.is_demo)
        if self.is_demo:
            self.synthetic_viewer.set_context(self.current_slice, review.slice_count)
            self.slice_label.setText(
                f"Slice {self.current_slice} / {review.slice_count}"
            )
            self.viewer_stack.setCurrentWidget(self.synthetic_viewer)
            return
        preview = review.qc_preview_path
        if preview is not None and preview.is_file():
            pixmap = QPixmap(str(preview))
            if not pixmap.isNull():
                self.qc_image.setPixmap(
                    pixmap.scaled(820, 500, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                )
                self.viewer_stack.setCurrentWidget(self.qc_image)
                return
        self.viewer_stack.setCurrentWidget(self.empty_viewer)

    def _clear_selection(self) -> None:
        self.current_item = None
        self.review_subject.setText("No artifacts are awaiting review")
        self.review_artifact.clear()
        self.review_reason.setText(
            "Run an eligible workflow or import a corrected mask to create a review item."
        )
        self.review_qc.clear()
        clear_layout(self.review_status_holder)
        self.viewer_stack.setCurrentWidget(self.empty_viewer)
        self.previous_slice.hide()
        self.next_slice.hide()
        self.slice_label.hide()
        self.overlay_controls.hide()
        self._set_actions_enabled(False)

    def _set_actions_enabled(self, selected: bool) -> None:
        actionable = selected and (
            self.is_demo
            or (
                self.current_item is not None
                and self.current_item.artifact_id is not None
            )
        )
        self.approve.setEnabled(actionable)
        self.reject.setEnabled(actionable)
        self.correction.setEnabled(actionable)
        self.import_correction.setEnabled(actionable)
        self.open_subject.setEnabled(selected)
        self.issue.setEnabled(actionable)
        self.notes.setEnabled(actionable)

    def _move_slice(self, delta: int) -> None:
        if self.current_item is None or not self.is_demo:
            return
        self.current_slice = max(
            1,
            min(self.current_slice + delta, self.current_item.slice_count),
        )
        self.synthetic_viewer.set_context(
            self.current_slice,
            self.current_item.slice_count,
        )
        self.slice_label.setText(
            f"Slice {self.current_slice} / {self.current_item.slice_count}"
        )

    def _previous_item(self) -> None:
        if self.queue_list.count():
            self.queue_list.setCurrentRow(max(0, self.queue_list.currentRow() - 1))

    def _next_item(self) -> None:
        if self.queue_list.count():
            self.queue_list.setCurrentRow(
                min(self.queue_list.count() - 1, self.queue_list.currentRow() + 1)
            )

    def _approve(self) -> None:
        review = self.current_item
        if review is None:
            return
        if self.is_demo:
            self.decisions[review.review_id] = StatusValue(
                "Human approved · preview",
                "approved",
            )
            self._refresh_preview_decision(
                f"Preview: approved {review.artifact_name} for "
                f"{review.subject_label or review.subject_id}."
            )
            return
        if review.artifact_id is not None:
            self.approve_requested.emit(
                review.subject_id,
                review.artifact_id,
                self.notes.toPlainText().strip(),
            )

    def _reject(self) -> None:
        review = self.current_item
        if review is None:
            return
        issue_code = self.issue.currentData()
        notes = self.notes.toPlainText().strip()
        if not issue_code or not notes:
            self.decision_recorded.emit(
                "Choose an issue type and enter reviewer notes before rejecting."
            )
            return
        if self.is_demo:
            self.decisions[review.review_id] = StatusValue(
                "Rejected · preview",
                "failed",
            )
            self._refresh_preview_decision(
                f"Preview: rejected {review.artifact_name} for "
                f"{review.subject_label or review.subject_id}."
            )
            return
        if review.artifact_id is not None:
            self.reject_requested.emit(
                review.subject_id,
                review.artifact_id,
                str(issue_code),
                notes,
            )

    def _open_correction(self) -> None:
        review = self.current_item
        if review is None:
            return
        if self.is_demo:
            self.decision_recorded.emit(
                "Correction launch is a preview interaction only."
            )
        elif review.artifact_id is not None:
            self.correction_requested.emit(review.subject_id, review.artifact_id)

    def _import_correction(self) -> None:
        review = self.current_item
        if review is None:
            return
        if self.is_demo:
            self.decision_recorded.emit(
                "Correction import is a preview interaction only."
            )
        elif review.artifact_id is not None:
            self.import_correction_requested.emit(
                review.subject_id,
                review.artifact_id,
            )

    def _open_subject(self) -> None:
        if self.current_item is not None:
            self.subject_requested.emit(self.current_item.subject_id)

    def _refresh_preview_decision(self, message: str) -> None:
        row = self.queue_list.currentRow()
        current_category = self.category_list.currentItem()
        category = (
            current_category.data(Qt.UserRole)
            if current_category is not None
            else "All reviews"
        )
        self._populate_queue(category)
        self.queue_list.setCurrentRow(min(row, self.queue_list.count() - 1))
        self.decision_recorded.emit(message + " Nothing was saved.")
