"""General review queue for persistent scientific artifacts."""

from __future__ import annotations

import math

import numpy as np
from PySide6.QtCore import QTimer, Qt, Signal
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (
    QButtonGroup,
    QDoubleSpinBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSlider,
    QSplitter,
    QStackedWidget,
    QTabBar,
    QVBoxLayout,
    QWidget,
)

from lys_bbb_app.domain.view_models import (
    ReviewItemViewModel,
    StudyViewModel,
)
from lys_bbb_app.features import AppFeatures, FULL_FEATURES
from lys_bbb_app.services.t2_threshold_preview_service import (
    load_t2_threshold_preview,
    orient_t2_threshold_preview_slice,
)
from lys_bbb_app.ui.layout_helpers import clear_layout, page_heading
from lys_bbb_app.ui.widgets import CollapsibleSection, StatusBadge, secondary_button


class ReviewsPage(QWidget):
    """Display actionable study-level review work without owning scientific state."""

    approve_requested = Signal(str, str)
    manual_edit_requested = Signal(str, str)
    subject_requested = Signal(str)
    qc_slices_requested = Signal(str, str)
    threshold_apply_requested = Signal(str, str, float)

    def __init__(self, *, features: AppFeatures = FULL_FEATURES) -> None:
        super().__init__()
        self.features = features
        self.reviews: tuple[ReviewItemViewModel, ...] = ()
        self.filtered: list[ReviewItemViewModel] = []
        self.current_item: ReviewItemViewModel | None = None
        self.current_row = -1
        self.current_slice = 1
        self.requested_qc_artifacts: set[str] = set()
        self._threshold_scan: np.ndarray | None = None
        self._threshold_probability: np.ndarray | None = None
        self._threshold_intensity_range = (0.0, 1.0)
        self._threshold_spacing = (1.0, 1.0, 1.0)
        self._threshold_floor = 1e-6
        self._threshold_refresh_timer = QTimer(self)
        self._threshold_refresh_timer.setSingleShot(True)
        self._threshold_refresh_timer.setInterval(25)
        self._threshold_refresh_timer.timeout.connect(self._refresh_threshold_preview)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 28)
        layout.setSpacing(14)
        heading, _heading_layout = page_heading(
            "Review and QC",
            "Inspect exact artifacts and record explicit human approval.",
        )
        layout.addWidget(heading)
        layout.addWidget(self._build_modality_tabs())

        splitter = self.review_splitter = QSplitter(Qt.Horizontal)
        splitter.setChildrenCollapsible(False)
        splitter.addWidget(self._build_queue())
        splitter.addWidget(self._build_viewer())
        splitter.addWidget(self._build_review_panel())
        splitter.setSizes([270, 650, 330])
        layout.addWidget(splitter, 1)

    def _build_modality_tabs(self) -> QTabBar:
        self.modality_tabs = QTabBar()
        self.modality_tabs.setDocumentMode(True)
        self.modality_tabs.setExpanding(False)
        self.modality_tabs.setDrawBase(False)
        self.modality_tab_indices: dict[str, int] = {}
        self._modality_by_tab: dict[int, str] = {}
        for modality in ("T1", "T2"):
            self._add_modality_tab(modality)
        self.modality_tabs.currentChanged.connect(self._modality_tab_changed)
        return self.modality_tabs

    def _add_modality_tab(self, modality: str) -> None:
        if modality in self.modality_tab_indices:
            return
        index = self.modality_tabs.addTab(modality)
        self.modality_tab_indices[modality] = index
        self._modality_by_tab[index] = modality

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
        self.slice_slider = QSlider(Qt.Horizontal)
        self.slice_slider.setRange(1, 1)
        self.slice_slider.setMinimumWidth(180)
        self.slice_slider.valueChanged.connect(self._slice_changed)
        self.slice_label = QLabel("Slice 1 / 1")
        controls.addWidget(previous)
        controls.addWidget(next_item)
        controls.addStretch()
        controls.addWidget(self.slice_slider, 1)
        controls.addWidget(self.slice_label)
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
        self.technical_details = CollapsibleSection()
        self.review_qc = QLabel()
        self.review_qc.setWordWrap(True)
        self.review_qc.setObjectName("muted")
        self.technical_details.content_layout.addWidget(self.review_qc)
        self.review_status_holder = QHBoxLayout()

        self.threshold_card = QFrame()
        self.threshold_card.setObjectName("subtleCard")
        threshold_layout = QVBoxLayout(self.threshold_card)
        threshold_layout.setContentsMargins(12, 11, 12, 11)
        threshold_title = QLabel("Case-specific probability threshold")
        threshold_title.setObjectName("cardTitle")
        threshold_help = QLabel(
            "Preview a cutoff for this animal only. The model default is unchanged."
        )
        threshold_help.setObjectName("muted")
        threshold_help.setWordWrap(True)
        threshold_layout.addWidget(threshold_title)
        threshold_layout.addWidget(threshold_help)
        threshold_value_row = QHBoxLayout()
        self.threshold_slider = QSlider(Qt.Horizontal)
        self.threshold_slider.setRange(0, 1200)
        self.threshold_slider.valueChanged.connect(self._threshold_slider_changed)
        self.threshold_spin = QDoubleSpinBox()
        self.threshold_spin.setDecimals(8)
        self.threshold_spin.setRange(1e-9, 0.99999999)
        self.threshold_spin.setSingleStep(0.001)
        self.threshold_spin.valueChanged.connect(self._threshold_spin_changed)
        threshold_value_row.addWidget(self.threshold_slider, 1)
        threshold_value_row.addWidget(self.threshold_spin)
        threshold_layout.addLayout(threshold_value_row)
        self.threshold_summary = QLabel()
        self.threshold_summary.setObjectName("muted")
        self.threshold_summary.setWordWrap(True)
        self.threshold_warning = QLabel()
        self.threshold_warning.setObjectName("warningBanner")
        self.threshold_warning.setWordWrap(True)
        threshold_layout.addWidget(self.threshold_summary)
        threshold_layout.addWidget(self.threshold_warning)
        threshold_actions = QHBoxLayout()
        self.threshold_reset = secondary_button("Reset to model default")
        self.threshold_reset.clicked.connect(self._reset_threshold)
        self.threshold_apply = QPushButton("Apply to this case")
        self.threshold_apply.clicked.connect(self._apply_threshold)
        threshold_actions.addWidget(self.threshold_reset)
        threshold_actions.addStretch()
        threshold_actions.addWidget(self.threshold_apply)
        threshold_layout.addLayout(threshold_actions)

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
        layout.addWidget(self.technical_details)
        layout.addLayout(self.review_status_holder)
        layout.addWidget(self.threshold_card)
        layout.addStretch()
        layout.addWidget(self.approve)
        layout.addWidget(self.manual_edit)
        layout.addWidget(self.open_subject)
        self._set_actions_enabled(False)
        self.threshold_card.hide()
        return panel

    def set_study(self, study: StudyViewModel) -> None:
        self.reviews = tuple(
            review
            for review in study.reviews
            if self.features.atlas_mapping
            or not review.workflow_key.startswith("atlas_")
        )
        if any(_review_modality(item) == "Atlas" for item in self.reviews):
            self._add_modality_tab("Atlas")
        allowed_modalities = tuple(
            modality
            for modality, enabled in (
                ("T1", study.analysis_scope.includes_t1),
                ("T2", study.analysis_scope.includes_t2),
                (
                    "Atlas",
                    study.analysis_scope.includes_t1
                    and study.analysis_scope.includes_t2
                    and self.features.atlas_mapping,
                ),
            )
            if enabled
        )
        for modality, index in self.modality_tab_indices.items():
            self.modality_tabs.setTabVisible(index, modality in allowed_modalities)
        default_modality = next(
            (
                modality
                for modality in ("Atlas", "T2", "T1")
                if modality in allowed_modalities
                if any(_review_modality(item) == modality for item in self.reviews)
            ),
            allowed_modalities[0],
        )
        self.modality_tabs.blockSignals(True)
        self.modality_tabs.setCurrentIndex(
            self.modality_tab_indices[default_modality]
        )
        self.modality_tabs.blockSignals(False)
        self._populate_queue(default_modality)

    def focus_subject(self, subject_id: str) -> None:
        review = next(
            (item for item in self.reviews if item.subject_id == subject_id),
            None,
        )
        if review is None:
            return
        modality = _review_modality(review)
        self.modality_tabs.blockSignals(True)
        self.modality_tabs.setCurrentIndex(self.modality_tab_indices[modality])
        self.modality_tabs.blockSignals(False)
        self._populate_queue(modality)
        for index, item in enumerate(self.filtered):
            if item.subject_id == subject_id:
                self._select_review(index)
                break

    def _modality_tab_changed(self, index: int) -> None:
        modality = self._modality_by_tab.get(index)
        if modality is not None:
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
        self.technical_details.set_expanded(False)
        self.approve.setText(review.approve_label)
        self.manual_edit.setText(review.manual_edit_label)
        self.manual_edit.setVisible(review.can_manual_edit)
        self.empty_viewer.setText(
            "Registration QC preview is unavailable. Open the subject to inspect "
            "the stored registration details."
            if review.workflow_key == "t1_registration"
            else "No QC preview is available. Open the current mask in ITK-SNAP "
            "for full review."
        )
        clear_layout(self.review_status_holder)
        self.review_status_holder.addWidget(StatusBadge(review.status))
        self.review_status_holder.addStretch()
        self._prepare_threshold_control(review)
        self._show_review_image(review)
        self._set_actions_enabled(True)

    def _show_review_image(self, review: ReviewItemViewModel) -> None:
        if self._has_threshold_preview(review):
            assert self._threshold_scan is not None
            self._configure_slice_slider(int(self._threshold_scan.shape[2]))
            self._refresh_threshold_preview()
            return
        has_real_slices = bool(review.qc_slice_paths)
        can_browse_slices = has_real_slices
        self.slice_slider.setVisible(can_browse_slices)
        self.slice_label.setVisible(can_browse_slices)
        if has_real_slices:
            self._configure_slice_slider(len(review.qc_slice_paths))
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
                    review.supports_slice_qc
                    and review.artifact_id is not None
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
        self._clear_threshold_control()
        self.technical_details.set_expanded(False)
        self.approve.setText("Approve current mask")
        self.manual_edit.setText("Manually edit in ITK-SNAP…")
        self.manual_edit.show()
        clear_layout(self.review_status_holder)
        self.viewer_stack.setCurrentWidget(self.empty_viewer)
        self.slice_slider.hide()
        self.slice_label.hide()
        self._set_actions_enabled(False)

    def _set_actions_enabled(self, selected: bool) -> None:
        actionable = (
            selected
            and self.current_item is not None
            and self.current_item.artifact_id is not None
        )
        threshold_preview_pending = self._threshold_preview_is_pending()
        self.approve.setEnabled(actionable and not threshold_preview_pending)
        self.manual_edit.setEnabled(
            actionable
            and self.current_item is not None
            and self.current_item.can_manual_edit
            and not threshold_preview_pending
        )
        pending_tooltip = (
            "Apply the previewed case threshold, or reset it, before approving or "
            "opening the mask for manual editing."
            if threshold_preview_pending
            else ""
        )
        self.approve.setToolTip(pending_tooltip)
        self.manual_edit.setToolTip(pending_tooltip)
        self.open_subject.setEnabled(selected)

    def _threshold_preview_is_pending(self) -> bool:
        review = self.current_item
        return (
            review is not None
            and self._has_threshold_preview(review)
            and review.current_threshold is not None
            and not math.isclose(
                float(self.threshold_spin.value()),
                review.current_threshold,
                rel_tol=0,
                abs_tol=max(1e-12, self._threshold_floor / 2),
            )
        )

    def _configure_slice_slider(self, slice_count: int) -> None:
        self.slice_slider.blockSignals(True)
        self.slice_slider.setRange(1, max(1, slice_count))
        self.slice_slider.setValue(
            max(1, min(self.current_slice, max(1, slice_count)))
        )
        self.slice_slider.blockSignals(False)
        self.slice_slider.show()
        self.slice_label.show()

    def _slice_changed(self, slice_number: int) -> None:
        if self.current_item is None:
            return
        self.current_slice = int(slice_number)
        if self._has_threshold_preview(self.current_item):
            self._refresh_threshold_preview()
        else:
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

    def _prepare_threshold_control(self, review: ReviewItemViewModel) -> None:
        self._clear_threshold_control()
        if (
            not review.can_adjust_threshold
            or review.reference_path is None
            or review.probability_path is None
            or review.current_threshold is None
            or review.model_default_threshold is None
        ):
            return
        try:
            preview = load_t2_threshold_preview(
                review.reference_path,
                review.probability_path,
                expected_probability_sha256=review.probability_sha256,
            )
        except (FileNotFoundError, OSError, ValueError) as exc:
            self.threshold_card.show()
            self.threshold_summary.setText(f"Threshold preview unavailable: {exc}")
            self.threshold_warning.setText(
                "Re-run inference before attempting a case-specific threshold."
            )
            self.threshold_slider.setEnabled(False)
            self.threshold_spin.setEnabled(False)
            self.threshold_reset.setEnabled(False)
            self.threshold_apply.setEnabled(False)
            return

        self._threshold_scan = preview.scan
        self._threshold_probability = preview.probability
        self._threshold_intensity_range = preview.intensity_range
        self._threshold_spacing = preview.spacing_mm
        maximum = preview.maximum_probability
        self._threshold_floor = max(
            1e-9,
            min(1e-6, maximum / 1000.0 if maximum > 0.0 else 1e-6),
        )
        self.threshold_spin.setRange(self._threshold_floor, 0.99999999)
        self.threshold_slider.setEnabled(True)
        self.threshold_spin.setEnabled(True)
        self.threshold_reset.setEnabled(True)
        self.threshold_card.show()
        self._set_threshold_value(review.current_threshold)

    def _clear_threshold_control(self) -> None:
        self._threshold_refresh_timer.stop()
        self._threshold_scan = None
        self._threshold_probability = None
        self.threshold_card.hide()

    def _has_threshold_preview(self, review: ReviewItemViewModel) -> bool:
        return (
            review.can_adjust_threshold
            and self._threshold_scan is not None
            and self._threshold_probability is not None
        )

    def _set_threshold_value(self, threshold: float) -> None:
        value = min(max(float(threshold), self._threshold_floor), 0.99999999)
        self.threshold_spin.blockSignals(True)
        self.threshold_slider.blockSignals(True)
        self.threshold_spin.setValue(value)
        self.threshold_slider.setValue(
            _threshold_to_slider(value, self._threshold_floor)
        )
        self.threshold_spin.blockSignals(False)
        self.threshold_slider.blockSignals(False)
        self._refresh_threshold_preview()

    def _threshold_slider_changed(self, position: int) -> None:
        value = _slider_to_threshold(position, self._threshold_floor)
        self.threshold_spin.blockSignals(True)
        self.threshold_spin.setValue(value)
        self.threshold_spin.blockSignals(False)
        self._threshold_refresh_timer.start()

    def _threshold_spin_changed(self, value: float) -> None:
        self.threshold_slider.blockSignals(True)
        self.threshold_slider.setValue(
            _threshold_to_slider(value, self._threshold_floor)
        )
        self.threshold_slider.blockSignals(False)
        self._threshold_refresh_timer.start()

    def _reset_threshold(self) -> None:
        review = self.current_item
        if review is not None and review.model_default_threshold is not None:
            self._set_threshold_value(review.model_default_threshold)

    def _refresh_threshold_preview(self) -> None:
        review = self.current_item
        scan = self._threshold_scan
        probability = self._threshold_probability
        if (
            review is None
            or scan is None
            or probability is None
            or not self._has_threshold_preview(review)
        ):
            return
        threshold = float(self.threshold_spin.value())
        mask = probability >= threshold
        lesion_voxels = int(np.count_nonzero(mask))
        volume = float(lesion_voxels * np.prod(self._threshold_spacing))
        maximum = float(probability.max()) if probability.size else 0.0
        self.threshold_summary.setText(
            f"Preview: {lesion_voxels:,} lesion voxels · {volume:.4f} mm³ · "
            f"case maximum {maximum:.6g} · model default "
            f"{review.model_default_threshold:.2f}"
        )
        outside_validated = not math.isclose(
            threshold,
            review.model_default_threshold,
            rel_tol=0,
            abs_tol=1e-12,
        )
        self.threshold_warning.setVisible(outside_validated)
        self.threshold_warning.setText(
            "Case-specific override: this cutoff was not selected during model "
            "validation and requires careful human review."
        )
        self.threshold_apply.setEnabled(
            review.artifact_id is not None
            and review.current_threshold is not None
            and not math.isclose(
                threshold,
                review.current_threshold,
                rel_tol=0,
                abs_tol=max(1e-12, self._threshold_floor / 2),
            )
        )
        self._set_actions_enabled(True)

        z = max(0, min(self.current_slice - 1, scan.shape[2] - 1))
        image_slice = orient_t2_threshold_preview_slice(scan[:, :, z])
        mask_slice = orient_t2_threshold_preview_slice(mask[:, :, z])
        low, high = self._threshold_intensity_range
        gray = np.clip((image_slice - low) / (high - low), 0.0, 1.0)
        gray_u8 = np.asarray(np.rint(gray * 255.0), dtype=np.uint8)
        rgb = np.repeat(gray_u8[:, :, None], 3, axis=2)
        if np.any(mask_slice):
            rgb[mask_slice] = np.asarray(
                0.62 * rgb[mask_slice] + 0.38 * np.array([32, 211, 176]),
                dtype=np.uint8,
            )
            boundary = _mask_boundary(mask_slice)
            rgb[boundary] = np.array([32, 211, 176], dtype=np.uint8)
        rgb = np.ascontiguousarray(rgb)
        height, width = rgb.shape[:2]
        image = QImage(
            rgb.data,
            width,
            height,
            int(rgb.strides[0]),
            QImage.Format_RGB888,
        ).copy()
        pixmap = QPixmap.fromImage(image)
        self.qc_image.setPixmap(
            pixmap.scaled(820, 500, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        )
        self.slice_label.setText(f"Slice {z + 1} / {scan.shape[2]}")
        self.viewer_stack.setCurrentWidget(self.qc_image)

    def _apply_threshold(self) -> None:
        review = self.current_item
        if review is not None and review.artifact_id is not None:
            self.threshold_apply_requested.emit(
                review.subject_id,
                review.artifact_id,
                float(self.threshold_spin.value()),
            )

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


def _slider_to_threshold(position: int, floor: float) -> float:
    fraction = min(max(position, 0), 1200) / 1200.0
    return float(math.exp(math.log(floor) + fraction * -math.log(floor)))


def _threshold_to_slider(threshold: float, floor: float) -> int:
    value = min(max(float(threshold), floor), 1.0)
    fraction = (math.log(value) - math.log(floor)) / -math.log(floor)
    return int(round(min(max(fraction, 0.0), 1.0) * 1200))


def _mask_boundary(mask: np.ndarray) -> np.ndarray:
    """Return a one-pixel internal boundary without requiring scipy."""

    inside = np.asarray(mask, dtype=bool)
    neighbours = np.zeros_like(inside)
    if inside.shape[0] > 2 and inside.shape[1] > 2:
        neighbours[1:-1, 1:-1] = (
            inside[:-2, 1:-1]
            & inside[2:, 1:-1]
            & inside[1:-1, :-2]
            & inside[1:-1, 2:]
        )
    return inside & ~neighbours


def _review_modality(review: ReviewItemViewModel) -> str:
    if review.workflow_key:
        if review.workflow_key.startswith("atlas_"):
            return "Atlas"
        return "T2" if review.workflow_key == "t2_lesion" else "T1"
    text = f"{review.category} {review.artifact_name}".casefold()
    return "T2" if "t2" in text or "lesion" in text else "T1"


def _review_workflow_label(review: ReviewItemViewModel) -> str:
    if review.workflow_key == "atlas_scheme":
        return "Major-region scheme"
    if review.workflow_key == "atlas_t2_support":
        return "T2 support mask"
    if review.workflow_key == "atlas_to_t1":
        return "Atlas → pre-T1"
    if review.workflow_key == "t1_to_t2_registration":
        return "Pre-T1 → T2"
    if review.workflow_key == "atlas_composite":
        return "Major labels on T2"
    if review.workflow_key == "t2_lesion":
        return "T2 lesion"
    if review.workflow_key == "t1_brain_mask":
        return "T1 brain mask"
    if review.workflow_key == "t1_registration":
        return "T1 registration"
    text = f"{review.category} {review.artifact_name}".casefold()
    if "t2" in text or "lesion" in text:
        return "T2 lesion"
    if "registration" in text:
        return "T1 registration"
    if "brain mask" in text or "brain masks" in text:
        return "T1 brain mask"
    return "T1 result"
