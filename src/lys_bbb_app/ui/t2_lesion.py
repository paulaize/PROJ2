"""Subject-owned T2 lesion inference, correction, and review panel."""

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
from lys_bbb_app.ui.widgets import (
    ElidedLabel,
    StatusBadge,
    SyntheticSliceViewer,
    secondary_button,
)


class T2LesionPanel(QScrollArea):
    select_release_requested = Signal()
    run_subject_requested = Signal(str)
    run_study_requested = Signal()
    open_artifact_requested = Signal(str, str)
    import_correction_requested = Signal(str, str)
    approve_requested = Signal(str, str)
    reject_requested = Signal(str, str)

    def __init__(self) -> None:
        super().__init__()
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.content = QWidget()
        self.layout = QVBoxLayout(self.content)
        self.layout.setContentsMargins(18, 16, 18, 20)
        self.layout.setSpacing(12)
        self.setWidget(self.content)
        self.current_subject: SubjectViewModel | None = None

        header = QHBoxLayout()
        heading = QVBoxLayout()
        title = QLabel("T2 lesion segmentation")
        title.setObjectName("sectionTitle")
        intro = QLabel(
            "Run the frozen five-model RatLesNetV2 ensemble on the validated native T2. "
            "Predictions remain drafts until a researcher reviews them."
        )
        intro.setObjectName("muted")
        intro.setWordWrap(True)
        heading.addWidget(title)
        heading.addWidget(intro)
        header.addLayout(heading, 1)
        self.select_release = secondary_button("Select model release…")
        self.select_release.clicked.connect(self.select_release_requested.emit)
        self.run_study = secondary_button("Run all eligible subjects…")
        self.run_study.clicked.connect(self.run_study_requested.emit)
        self.run_subject = QPushButton("Run this subject")
        self.run_subject.clicked.connect(self._run_subject)
        header.addWidget(self.select_release)
        header.addWidget(self.run_study)
        header.addWidget(self.run_subject)
        self.layout.addLayout(header)

        release_card = QFrame()
        release_card.setObjectName("card")
        release_layout = QGridLayout(release_card)
        release_layout.setContentsMargins(16, 13, 16, 13)
        release_layout.setColumnStretch(1, 1)
        release_title = QLabel("Active frozen release")
        release_title.setObjectName("cardTitle")
        self.release_status = QLabel("No release selected")
        self.release_status.setObjectName("muted")
        self.release_status.setWordWrap(True)
        release_layout.addWidget(release_title, 0, 0)
        release_layout.addWidget(self.release_status, 0, 1)
        release_layout.addWidget(
            QLabel("5 models · mean probability · threshold 0.40 · no postprocessing"),
            1,
            1,
        )
        self.layout.addWidget(release_card)

        self.readiness = QLabel()
        self.readiness.setObjectName("infoBanner")
        self.readiness.setWordWrap(True)
        self.readiness.setContentsMargins(14, 9, 14, 9)
        self.layout.addWidget(self.readiness)

        self.artifact_card = QFrame()
        self.artifact_card.setObjectName("card")
        artifact_layout = QVBoxLayout(self.artifact_card)
        artifact_layout.setContentsMargins(16, 14, 16, 16)
        artifact_layout.setSpacing(12)
        artifact_header = QHBoxLayout()
        self.artifact_title = QLabel("Current lesion artifact")
        self.artifact_title.setObjectName("cardTitle")
        artifact_header.addWidget(self.artifact_title)
        artifact_header.addStretch()
        self.artifact_status_container = QHBoxLayout()
        artifact_header.addLayout(self.artifact_status_container)
        artifact_layout.addLayout(artifact_header)

        actions = QHBoxLayout()
        self.open_artifact = QPushButton("Correct a copy in ITK-SNAP")
        self.open_artifact.clicked.connect(self._open_artifact)
        self.import_correction = secondary_button("Import corrected mask…")
        self.import_correction.clicked.connect(self._import_correction)
        self.reject = secondary_button("Reject…")
        self.reject.clicked.connect(self._reject)
        self.approve = QPushButton("Approve mask")
        self.approve.clicked.connect(self._approve)
        actions.addWidget(self.open_artifact)
        actions.addWidget(self.import_correction)
        actions.addStretch()
        actions.addWidget(self.reject)
        actions.addWidget(self.approve)
        artifact_layout.addLayout(actions)

        self.viewer_stack = QStackedWidget()
        self.viewer_stack.setMinimumHeight(190)
        self.viewer_stack.setMaximumHeight(230)
        self.qc_image = QLabel()
        self.qc_image.setAlignment(Qt.AlignCenter)
        self.qc_image.setStyleSheet("background: #101b2b; border-radius: 8px;")
        self.qc_image.setScaledContents(False)
        self.synthetic_viewer = SyntheticSliceViewer()
        self.synthetic_viewer.setMinimumSize(420, 190)
        self.empty_viewer = QLabel(
            "QC preview is unavailable. Open the mask in ITK-SNAP."
        )
        self.empty_viewer.setAlignment(Qt.AlignCenter)
        self.empty_viewer.setObjectName("muted")
        self.viewer_stack.addWidget(self.qc_image)
        self.viewer_stack.addWidget(self.synthetic_viewer)
        self.viewer_stack.addWidget(self.empty_viewer)
        artifact_layout.addWidget(self.viewer_stack)

        stats = QFrame()
        stats.setObjectName("subtleCard")
        self.stats_layout = QGridLayout(stats)
        self.stats_layout.setContentsMargins(14, 12, 14, 12)
        self.stats_layout.setHorizontalSpacing(20)
        artifact_layout.addWidget(stats)

        paths = QGridLayout()
        self.mask_path = ElidedLabel()
        self.probability_path = ElidedLabel()
        self.mask_path_label = QLabel("Current mask")
        paths.addWidget(self.mask_path_label, 0, 0)
        paths.addWidget(self.mask_path, 0, 1)
        paths.addWidget(QLabel("Probability map"), 1, 0)
        paths.addWidget(self.probability_path, 1, 1)
        paths.setColumnStretch(1, 1)
        artifact_layout.addLayout(paths)

        self.layout.addWidget(self.artifact_card)
        self.layout.addStretch()

    def set_subject(self, subject: SubjectViewModel) -> None:
        self.current_subject = subject
        self.release_status.setText(
            subject.t2_release_label or "No validated release selected for this study."
        )
        self.run_subject.setEnabled(subject.can_run_t2_inference)
        self.run_subject.setText(
            "Re-run this subject"
            if subject.t2_artifact is not None
            else "Run this subject"
        )
        self.run_subject.setToolTip(subject.t2_inference_blocked_reason or "")
        self.readiness.setText(
            "The T2 input is ready. Select the frozen model release to continue."
            if subject.can_run_t2_inference and subject.t2_release_label is None
            else "Ready to run the frozen ensemble. The existing draft will be preserved as "
            "an older version."
            if subject.can_run_t2_inference and subject.t2_artifact is not None
            else "Ready to run the frozen ensemble on this validated native T2."
            if subject.can_run_t2_inference
            else subject.t2_inference_blocked_reason
            or "This subject is not ready for T2 inference."
        )
        artifact = subject.t2_artifact
        self.artifact_card.setVisible(artifact is not None)
        if artifact is None:
            return
        self.artifact_title.setText(
            f"{artifact.origin_label} · version {artifact.version}"
        )
        clear_layout(self.artifact_status_container)
        self.artifact_status_container.addWidget(StatusBadge(artifact.state))
        clear_layout(self.stats_layout)
        volume_label = (
            "Official volume" if artifact.official_volume_text else "Provisional volume"
        )
        volume_value = artifact.official_volume_text or artifact.provisional_volume_text
        stats = (
            (volume_label, volume_value),
            ("Lesion voxels", f"{artifact.lesion_voxel_count:,}"),
            ("Threshold", artifact.threshold_text),
            ("Device", artifact.device.upper()),
            ("Release", artifact.release_label),
            (
                "Reviewed by" if artifact.reviewer else "Created",
                (
                    f"{artifact.reviewer} · {artifact.reviewed_at}"
                    if artifact.reviewer and artifact.reviewed_at
                    else artifact.reviewer or artifact.created_at
                ),
            ),
        )
        for index, (label, value) in enumerate(stats):
            row, column = divmod(index, 3)
            block = QVBoxLayout()
            key = QLabel(label)
            key.setObjectName("metadata")
            val = QLabel(value)
            val.setStyleSheet("font-weight: 700;")
            block.addWidget(key)
            block.addWidget(val)
            self.stats_layout.addLayout(block, row, column)
        self.mask_path.setText(str(artifact.mask_path))
        self.probability_path.setText(str(artifact.probability_path))
        preview = artifact.qc_preview_path
        if preview is not None and preview.is_file():
            pixmap = QPixmap(str(preview))
            self.qc_image.setPixmap(
                pixmap.scaled(850, 215, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            )
            self.viewer_stack.setCurrentWidget(self.qc_image)
        elif str(artifact.mask_path).startswith("/synthetic-preview/"):
            self.viewer_stack.setCurrentWidget(self.synthetic_viewer)
        else:
            self.viewer_stack.setCurrentWidget(self.empty_viewer)
        self.mask_path_label.setText(
            "Approved mask"
            if artifact.official_volume_text
            else "Corrected mask"
            if "correction" in artifact.origin_label.casefold()
            else "Draft mask"
        )
        review_tooltip = (
            ""
            if artifact.can_review
            else "This artifact already has a decision or is no longer current."
        )
        correction_tooltip = (
            ""
            if artifact.can_correct
            else "Only the current mask can be opened or replaced."
        )
        for button in (self.open_artifact, self.import_correction):
            button.setEnabled(artifact.can_correct)
            button.setToolTip(correction_tooltip)
        for button in (self.approve, self.reject):
            button.setEnabled(artifact.can_review)
            button.setToolTip(review_tooltip)

    def _run_subject(self) -> None:
        if self.current_subject is not None:
            self.run_subject_requested.emit(self.current_subject.subject_id)

    def _open_artifact(self) -> None:
        if (
            self.current_subject is not None
            and self.current_subject.t2_artifact is not None
        ):
            self.open_artifact_requested.emit(
                self.current_subject.subject_id,
                self.current_subject.t2_artifact.artifact_id,
            )

    def _import_correction(self) -> None:
        if (
            self.current_subject is not None
            and self.current_subject.t2_artifact is not None
        ):
            self.import_correction_requested.emit(
                self.current_subject.subject_id,
                self.current_subject.t2_artifact.artifact_id,
            )

    def _approve(self) -> None:
        if (
            self.current_subject is not None
            and self.current_subject.t2_artifact is not None
        ):
            self.approve_requested.emit(
                self.current_subject.subject_id,
                self.current_subject.t2_artifact.artifact_id,
            )

    def _reject(self) -> None:
        if (
            self.current_subject is not None
            and self.current_subject.t2_artifact is not None
        ):
            self.reject_requested.emit(
                self.current_subject.subject_id,
                self.current_subject.t2_artifact.artifact_id,
            )
