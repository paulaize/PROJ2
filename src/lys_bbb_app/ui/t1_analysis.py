"""Subject-level controls for reviewed T1 registration and enhancement."""

from __future__ import annotations

from PySide6.QtCore import QUrl, Qt, Signal
from PySide6.QtGui import QDesktopServices, QPixmap
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from lys_bbb_app.domain.atlas_mapping import AtlasMappingState, AtlasReviewState
from lys_bbb_app.domain.view_models import SubjectViewModel
from lys_bbb_app.domain.view_models import StatusValue
from lys_bbb_app.ui.layout_helpers import clear_layout, populate_stat_grid
from lys_bbb_app.ui.widgets import CollapsibleSection, ElidedLabel, StatusBadge


class T1AnalysisPanel(QScrollArea):
    """Expose the two downstream T1 gates without owning scientific state."""

    run_registration_requested = Signal(str)
    approve_registration_requested = Signal(str, str)
    run_enhancement_requested = Signal(str)
    run_t1_to_t2_requested = Signal(str)
    approve_t1_to_t2_requested = Signal(str, str)

    def __init__(self) -> None:
        super().__init__()
        self.current_subject: SubjectViewModel | None = None
        self.t1_to_t2_state: AtlasMappingState | None = None
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        content = QWidget()
        self.layout = QVBoxLayout(content)
        self.layout.setContentsMargins(18, 16, 18, 18)
        self.layout.setSpacing(14)
        self.setWidget(content)

        self.layout.addWidget(self._build_registration_card())
        self.layout.addWidget(self._build_t1_to_t2_card())
        self.layout.addWidget(self._build_enhancement_card())
        self.layout.addStretch()

    def _build_registration_card(self) -> QFrame:
        card = QFrame()
        card.setObjectName("card")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 14, 16, 16)
        layout.setSpacing(12)

        header = QHBoxLayout()
        copy = QVBoxLayout()
        title = QLabel("Post-to-pre T1 registration")
        title.setObjectName("sectionTitle")
        detail = QLabel("Register post-Gd T1 into native pre-Gd space, then review it.")
        detail.setObjectName("muted")
        detail.setWordWrap(True)
        copy.addWidget(title)
        copy.addWidget(detail)
        header.addLayout(copy, 1)
        self.registration_status = QHBoxLayout()
        header.addLayout(self.registration_status)
        layout.addLayout(header)

        action_row = QHBoxLayout()
        self.registration_readiness = QLabel()
        self.registration_readiness.setObjectName("muted")
        self.registration_readiness.setWordWrap(True)
        action_row.addWidget(self.registration_readiness, 1)
        self.run_registration = QPushButton("Run registration")
        self.run_registration.clicked.connect(self._run_registration)
        self.approve_registration = QPushButton("Approve registration")
        self.approve_registration.clicked.connect(self._approve_registration)
        action_row.addWidget(self.run_registration)
        action_row.addWidget(self.approve_registration)
        layout.addLayout(action_row)

        self.registration_artifact = QWidget()
        artifact_layout = QVBoxLayout(self.registration_artifact)
        artifact_layout.setContentsMargins(0, 0, 0, 0)
        artifact_layout.setSpacing(10)
        self.registration_viewer, self.registration_qc, self.registration_qc_empty = (
            _qc_viewer("Registration QC preview is unavailable.")
        )
        artifact_layout.addWidget(self.registration_viewer)
        qc_action_row = QHBoxLayout()
        qc_action_row.addStretch()
        self.open_registration_qc = QPushButton("Open QC full size")
        self.open_registration_qc.clicked.connect(
            self._open_registration_qc_full_size
        )
        qc_action_row.addWidget(self.open_registration_qc)
        artifact_layout.addLayout(qc_action_row)
        self.registration_stats = QGridLayout()
        self.registration_stats.setHorizontalSpacing(20)
        artifact_layout.addLayout(self.registration_stats)

        self.registration_details = CollapsibleSection()
        registration_paths = QGridLayout()
        self.registered_post_path = ElidedLabel()
        self.transform_path = ElidedLabel()
        registration_paths.addWidget(QLabel("Registered post-Gd"), 0, 0)
        registration_paths.addWidget(self.registered_post_path, 0, 1)
        registration_paths.addWidget(QLabel("Transform"), 1, 0)
        registration_paths.addWidget(self.transform_path, 1, 1)
        registration_paths.setColumnStretch(1, 1)
        self.registration_details.content_layout.addLayout(registration_paths)
        artifact_layout.addWidget(self.registration_details)
        layout.addWidget(self.registration_artifact)
        return card

    def _build_t1_to_t2_card(self) -> QFrame:
        self.t1_to_t2_card = QFrame()
        self.t1_to_t2_card.setObjectName("card")
        layout = QVBoxLayout(self.t1_to_t2_card)
        layout.setContentsMargins(16, 14, 16, 16)
        layout.setSpacing(12)

        header = QHBoxLayout()
        copy = QVBoxLayout()
        title = QLabel("Native pre-T1 to native partial-T2 registration")
        title.setObjectName("sectionTitle")
        detail = QLabel(
            "Selected unmasked rigid method. The original T2 grid is unchanged; "
            "inspect every original T2 slice."
        )
        detail.setObjectName("muted")
        detail.setWordWrap(True)
        copy.addWidget(title)
        copy.addWidget(detail)
        header.addLayout(copy, 1)
        self.t1_to_t2_status = QHBoxLayout()
        header.addLayout(self.t1_to_t2_status)
        layout.addLayout(header)

        warning = QLabel(
            "DRAFT_REVIEW_REQUIRED: this operational development method has not "
            "been independently landmark-validated."
        )
        warning.setObjectName("warningBanner")
        warning.setWordWrap(True)
        layout.addWidget(warning)

        actions = QHBoxLayout()
        self.t1_to_t2_readiness = QLabel()
        self.t1_to_t2_readiness.setObjectName("muted")
        self.t1_to_t2_readiness.setWordWrap(True)
        actions.addWidget(self.t1_to_t2_readiness, 1)
        self.run_t1_to_t2 = QPushButton("Run rigid registration")
        self.run_t1_to_t2.clicked.connect(self._run_t1_to_t2)
        self.t1_to_t2_slice = QComboBox()
        self.t1_to_t2_slice.currentIndexChanged.connect(
            self._show_t1_to_t2_slice
        )
        self.approve_t1_to_t2 = QPushButton("Approve after human QC")
        self.approve_t1_to_t2.clicked.connect(self._approve_t1_to_t2)
        actions.addWidget(self.run_t1_to_t2)
        actions.addWidget(self.t1_to_t2_slice)
        actions.addWidget(self.approve_t1_to_t2)
        layout.addLayout(actions)

        self.t1_to_t2_qc = QLabel("All-slice QC appears here after registration.")
        self.t1_to_t2_qc.setAlignment(Qt.AlignCenter)
        self.t1_to_t2_qc.setMinimumHeight(190)
        self.t1_to_t2_qc.setMaximumHeight(230)
        self.t1_to_t2_qc.setStyleSheet(
            "background: #101b2b; border-radius: 8px;"
        )
        layout.addWidget(self.t1_to_t2_qc)

        self.t1_to_t2_details = CollapsibleSection()
        paths = QGridLayout()
        self.t1_to_t2_transform_path = ElidedLabel()
        self.transformed_t1_path = ElidedLabel()
        paths.addWidget(QLabel("Rigid transform"), 0, 0)
        paths.addWidget(self.t1_to_t2_transform_path, 0, 1)
        paths.addWidget(QLabel("Pre-T1 in native T2"), 1, 0)
        paths.addWidget(self.transformed_t1_path, 1, 1)
        paths.setColumnStretch(1, 1)
        self.t1_to_t2_details.content_layout.addLayout(paths)
        layout.addWidget(self.t1_to_t2_details)
        return self.t1_to_t2_card

    def _build_enhancement_card(self) -> QFrame:
        card = QFrame()
        card.setObjectName("card")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 14, 16, 16)
        layout.setSpacing(12)

        header = QHBoxLayout()
        copy = QVBoxLayout()
        title = QLabel("Semi-quantitative T1-weighted gadolinium enhancement")
        title.setObjectName("sectionTitle")
        detail = QLabel(
            "Calculate from the exact approved registration and brain mask."
        )
        detail.setObjectName("muted")
        detail.setWordWrap(True)
        copy.addWidget(title)
        copy.addWidget(detail)
        header.addLayout(copy, 1)
        self.enhancement_status = QHBoxLayout()
        header.addLayout(self.enhancement_status)
        layout.addLayout(header)

        warning = QLabel(
            "Provisional: the normalization method is still undergoing "
            "signal-preservation validation."
        )
        warning.setObjectName("warningBanner")
        warning.setWordWrap(True)
        layout.addWidget(warning)

        action_row = QHBoxLayout()
        self.enhancement_readiness = QLabel()
        self.enhancement_readiness.setObjectName("muted")
        self.enhancement_readiness.setWordWrap(True)
        action_row.addWidget(self.enhancement_readiness, 1)
        self.run_enhancement = QPushButton("Calculate provisional enhancement")
        self.run_enhancement.clicked.connect(self._run_enhancement)
        action_row.addWidget(self.run_enhancement)
        layout.addLayout(action_row)

        self.enhancement_result = QWidget()
        result_layout = QVBoxLayout(self.enhancement_result)
        result_layout.setContentsMargins(0, 0, 0, 0)
        result_layout.setSpacing(10)
        self.enhancement_value = QLabel()
        self.enhancement_value.setObjectName("cardTitle")
        result_layout.addWidget(self.enhancement_value)
        self.enhancement_viewer, self.enhancement_qc, self.enhancement_qc_empty = (
            _qc_viewer("Enhancement QC preview is unavailable.")
        )
        result_layout.addWidget(self.enhancement_viewer)

        self.enhancement_details = CollapsibleSection()
        result_paths = QGridLayout()
        self.enhancement_map_path = ElidedLabel()
        self.enhancement_summary_path = ElidedLabel()
        self.enhancement_metadata_path = ElidedLabel()
        result_paths.addWidget(QLabel("Enhancement map"), 0, 0)
        result_paths.addWidget(self.enhancement_map_path, 0, 1)
        result_paths.addWidget(QLabel("Summary"), 1, 0)
        result_paths.addWidget(self.enhancement_summary_path, 1, 1)
        result_paths.addWidget(QLabel("Metadata"), 2, 0)
        result_paths.addWidget(self.enhancement_metadata_path, 2, 1)
        result_paths.setColumnStretch(1, 1)
        self.enhancement_details.content_layout.addLayout(result_paths)
        result_layout.addWidget(self.enhancement_details)
        layout.addWidget(self.enhancement_result)
        return card

    def set_subject(self, subject: SubjectViewModel) -> None:
        self.current_subject = subject
        self.registration_details.set_expanded(False)
        self.enhancement_details.set_expanded(False)
        self.t1_to_t2_details.set_expanded(False)
        self._set_registration(subject)
        self._set_t1_to_t2(subject)
        self._set_enhancement(subject)

    def set_t1_to_t2_state(self, state: AtlasMappingState | None) -> None:
        self.t1_to_t2_state = state
        if self.current_subject is not None:
            self._set_t1_to_t2(self.current_subject)

    def _set_t1_to_t2(self, subject: SubjectViewModel) -> None:
        self.t1_to_t2_card.setVisible(subject.expects_t1 and subject.expects_t2)
        clear_layout(self.t1_to_t2_status)
        artifact = self.t1_to_t2_state.t1_to_t2 if self.t1_to_t2_state else None
        if artifact is None:
            status = StatusValue("Not run", "pending")
        elif artifact.state is AtlasReviewState.APPROVED:
            status = StatusValue("Approved", "approved")
        elif artifact.state is AtlasReviewState.DRAFT_REVIEW_REQUIRED:
            status = StatusValue("Human QC required", "review")
        else:
            status = StatusValue("Outdated", "warning")
        self.t1_to_t2_status.addWidget(StatusBadge(status))

        ready = (
            subject.expects_t1
            and subject.expects_t2
            and subject.t1_data.kind == "ready"
            and subject.t2_data.kind == "ready"
            and subject.brain_mask.kind == "approved"
            and artifact is None
        )
        self.run_t1_to_t2.setEnabled(ready)
        self.t1_to_t2_readiness.setText(
            "Ready: validated native pre-T1/T2 and approved corrected T1 mask."
            if ready
            else "Validate native pre-T1/T2 and approve the corrected T1 mask first."
            if artifact is None
            else "Inspect every stored original-T2 QC slice before approval."
        )
        self.approve_t1_to_t2.setVisible(artifact is not None)
        self.approve_t1_to_t2.setEnabled(
            artifact is not None
            and artifact.state is AtlasReviewState.DRAFT_REVIEW_REQUIRED
        )
        self.t1_to_t2_slice.setVisible(artifact is not None)
        self.t1_to_t2_slice.blockSignals(True)
        self.t1_to_t2_slice.clear()
        if artifact is not None:
            for index in range(len(artifact.qc_slice_paths)):
                self.t1_to_t2_slice.addItem(
                    f"T2 slice {index + 1}/{len(artifact.qc_slice_paths)}"
                )
            self.t1_to_t2_transform_path.setText(str(artifact.transform_path))
            self.transformed_t1_path.setText(str(artifact.transformed_t1_path))
        self.t1_to_t2_slice.blockSignals(False)
        self.t1_to_t2_details.setVisible(artifact is not None)
        self._show_t1_to_t2_slice()

    def _show_t1_to_t2_slice(self) -> None:
        artifact = self.t1_to_t2_state.t1_to_t2 if self.t1_to_t2_state else None
        index = self.t1_to_t2_slice.currentIndex()
        path = (
            artifact.qc_slice_paths[index]
            if artifact is not None and 0 <= index < len(artifact.qc_slice_paths)
            else None
        )
        if path is not None and path.is_file():
            pixmap = QPixmap(str(path))
            if not pixmap.isNull():
                self.t1_to_t2_qc.setPixmap(
                    pixmap.scaled(
                        850,
                        215,
                        Qt.KeepAspectRatio,
                        Qt.SmoothTransformation,
                    )
                )
                return
        self.t1_to_t2_qc.clear()
        self.t1_to_t2_qc.setText(
            "All-slice QC appears here after registration."
        )

    def _set_registration(self, subject: SubjectViewModel) -> None:
        clear_layout(self.registration_status)
        self.registration_status.addWidget(StatusBadge(subject.registration))
        self.run_registration.setEnabled(subject.can_run_t1_registration)
        self.run_registration.setToolTip(subject.t1_registration_blocked_reason or "")
        self.registration_readiness.setText(
            "Ready to register the validated post-Gd image to native pre-Gd space."
            if subject.can_run_t1_registration
            else subject.t1_registration_blocked_reason
            or "Complete the preceding T1 steps first."
        )

        artifact = subject.t1_registration_artifact
        self.registration_artifact.setVisible(artifact is not None)
        self.approve_registration.setVisible(artifact is not None)
        self.approve_registration.setEnabled(
            artifact is not None and artifact.can_review
        )
        if artifact is None:
            return
        _set_qc_image(
            self.registration_viewer,
            self.registration_qc,
            self.registration_qc_empty,
            artifact.qc_preview_path,
        )
        clear_layout(self.registration_stats)
        populate_stat_grid(
            self.registration_stats,
            (
                ("Before correlation", f"{artifact.before_xcorr:.3f}"),
                ("After correlation", f"{artifact.after_xcorr:.3f}"),
                (
                    "Reviewed by" if artifact.reviewer else "Created",
                    (
                        f"{artifact.reviewer} · {artifact.reviewed_at}"
                        if artifact.reviewer and artifact.reviewed_at
                        else artifact.reviewer or artifact.created_at
                    ),
                ),
                ("Method", artifact.method_label),
                ("Metric", f"{artifact.registration_metric:.4f}"),
                ("Optimizer", artifact.optimizer_stop),
            ),
        )
        self.registered_post_path.setText(str(artifact.registered_post_path))
        self.transform_path.setText(str(artifact.transform_path))

    def _set_enhancement(self, subject: SubjectViewModel) -> None:
        clear_layout(self.enhancement_status)
        self.enhancement_status.addWidget(StatusBadge(subject.t1_result))
        self.run_enhancement.setEnabled(subject.can_run_t1_enhancement)
        self.run_enhancement.setToolTip(subject.t1_enhancement_blocked_reason or "")
        self.enhancement_readiness.setText(
            "Ready to calculate an explicitly provisional enhancement result."
            if subject.can_run_t1_enhancement
            else subject.t1_enhancement_blocked_reason
            or "Complete and approve the registration first."
        )

        result = subject.t1_enhancement_result
        self.enhancement_result.setVisible(result is not None)
        if result is None:
            return
        self.enhancement_value.setText(f"{result.value_text} · provisional")
        _set_qc_image(
            self.enhancement_viewer,
            self.enhancement_qc,
            self.enhancement_qc_empty,
            result.qc_preview_path,
        )
        self.enhancement_map_path.setText(str(result.percent_enhancement_map))
        self.enhancement_summary_path.setText(str(result.summary_csv))
        self.enhancement_metadata_path.setText(str(result.metadata_path))

    def _run_registration(self) -> None:
        if self.current_subject is not None:
            self.run_registration_requested.emit(self.current_subject.subject_id)

    def _approve_registration(self) -> None:
        subject = self.current_subject
        if subject is not None and subject.t1_registration_artifact is not None:
            self.approve_registration_requested.emit(
                subject.subject_id,
                subject.t1_registration_artifact.artifact_id,
            )

    def _open_registration_qc_full_size(self) -> None:
        subject = self.current_subject
        artifact = (
            subject.t1_registration_artifact if subject is not None else None
        )
        if artifact is not None and artifact.qc_preview_path.is_file():
            QDesktopServices.openUrl(
                QUrl.fromLocalFile(str(artifact.qc_preview_path.resolve()))
            )

    def _run_enhancement(self) -> None:
        if self.current_subject is not None:
            self.run_enhancement_requested.emit(self.current_subject.subject_id)

    def _run_t1_to_t2(self) -> None:
        if self.current_subject is not None:
            self.run_t1_to_t2_requested.emit(self.current_subject.subject_id)

    def _approve_t1_to_t2(self) -> None:
        artifact = self.t1_to_t2_state.t1_to_t2 if self.t1_to_t2_state else None
        if self.current_subject is not None and artifact is not None:
            self.approve_t1_to_t2_requested.emit(
                self.current_subject.subject_id,
                artifact.id,
            )


def _qc_viewer(empty_text: str) -> tuple[QStackedWidget, QLabel, QLabel]:
    viewer = QStackedWidget()
    viewer.setMinimumHeight(190)
    viewer.setMaximumHeight(230)
    image = QLabel()
    image.setAlignment(Qt.AlignCenter)
    image.setStyleSheet("background: #101b2b; border-radius: 8px;")
    empty = QLabel(empty_text)
    empty.setAlignment(Qt.AlignCenter)
    empty.setObjectName("muted")
    viewer.addWidget(image)
    viewer.addWidget(empty)
    return viewer, image, empty


def _set_qc_image(
    viewer: QStackedWidget,
    image: QLabel,
    empty: QLabel,
    path,
) -> None:
    if path.is_file():
        pixmap = QPixmap(str(path))
        if not pixmap.isNull():
            image.setPixmap(
                pixmap.scaled(850, 215, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            )
            viewer.setCurrentWidget(image)
            return
    viewer.setCurrentWidget(empty)
