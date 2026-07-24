"""Subject-level controls for reviewed T1 registration and enhancement."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
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

from lys_bbb_app.domain.view_models import SubjectViewModel
from lys_bbb_app.ui.layout_helpers import clear_layout
from lys_bbb_app.ui.widgets import CollapsibleSection, ElidedLabel, StatusBadge


class T1AnalysisPanel(QScrollArea):
    """Expose the two downstream T1 gates without owning scientific state."""

    run_registration_requested = Signal(str)
    approve_registration_requested = Signal(str, str)
    run_enhancement_requested = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.current_subject: SubjectViewModel | None = None
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        content = QWidget()
        self.layout = QVBoxLayout(content)
        self.layout.setContentsMargins(18, 16, 18, 18)
        self.layout.setSpacing(14)
        self.setWidget(content)

        self.layout.addWidget(self._build_registration_card())
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
        self._set_registration(subject)
        self._set_enhancement(subject)

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
        _populate_stat_grid(
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

    def _run_enhancement(self) -> None:
        if self.current_subject is not None:
            self.run_enhancement_requested.emit(self.current_subject.subject_id)


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


def _populate_stat_grid(
    grid: QGridLayout,
    stats: tuple[tuple[str, str], ...],
) -> None:
    for index, (label, value) in enumerate(stats):
        row, column = divmod(index, 3)
        block = QVBoxLayout()
        key = QLabel(label)
        key.setObjectName("metadata")
        val = QLabel(value)
        val.setWordWrap(True)
        val.setStyleSheet("font-weight: 700;")
        block.addWidget(key)
        block.addWidget(val)
        grid.addLayout(block, row, column)
