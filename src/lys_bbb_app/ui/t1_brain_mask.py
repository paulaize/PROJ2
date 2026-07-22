"""Subject-level controls for the persistent T1 brain-mask slice."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from lys_bbb_app.domain.view_models import SubjectViewModel
from lys_bbb_app.ui.layout_helpers import clear_layout
from lys_bbb_app.ui.widgets import (
    CollapsibleSection,
    ElidedLabel,
    StatusBadge,
    secondary_button,
)


class T1BrainMaskPanel(QWidget):
    """Mirror the study-level T1 review actions for one subject."""

    select_release_requested = Signal()
    run_subject_requested = Signal(str)
    manual_edit_requested = Signal(str, str)
    approve_requested = Signal(str, str)

    def __init__(self) -> None:
        super().__init__()
        self.current_subject: SubjectViewModel | None = None
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(18, 16, 18, 18)
        self.layout.setSpacing(12)

        run_row = QHBoxLayout()
        copy = QVBoxLayout()
        title = QLabel("T1 brain mask")
        title.setObjectName("sectionTitle")
        subtitle = QLabel(
            "Automatic draft — human approval required."
        )
        subtitle.setObjectName("muted")
        subtitle.setWordWrap(True)
        copy.addWidget(title)
        copy.addWidget(subtitle)
        run_row.addLayout(copy, 1)
        self.select_release = secondary_button("Select method…")
        self.select_release.clicked.connect(self.select_release_requested.emit)
        self.run_subject = QPushButton("Generate draft")
        self.run_subject.clicked.connect(self._run_subject)
        run_row.addWidget(self.select_release)
        run_row.addWidget(self.run_subject)
        self.layout.addLayout(run_row)

        self.release_status = QLabel("No method selected")
        self.release_status.setObjectName("infoBanner")
        self.release_status.setWordWrap(True)
        self.layout.addWidget(self.release_status)

        self.readiness = QLabel()
        self.readiness.setObjectName("muted")
        self.readiness.setWordWrap(True)
        self.layout.addWidget(self.readiness)

        self.artifact_card = QFrame()
        self.artifact_card.setObjectName("card")
        artifact_layout = QVBoxLayout(self.artifact_card)
        artifact_layout.setContentsMargins(16, 14, 16, 16)
        artifact_layout.setSpacing(12)
        header = QHBoxLayout()
        self.artifact_title = QLabel("Current brain mask")
        self.artifact_title.setObjectName("cardTitle")
        self.artifact_status = QHBoxLayout()
        header.addWidget(self.artifact_title)
        header.addStretch()
        header.addLayout(self.artifact_status)
        artifact_layout.addLayout(header)

        actions = QHBoxLayout()
        self.manual_edit = secondary_button("Manually edit in ITK-SNAP…")
        self.manual_edit.clicked.connect(self._manual_edit)
        self.approve = QPushButton("Approve mask")
        self.approve.clicked.connect(self._approve)
        actions.addWidget(self.manual_edit)
        actions.addStretch()
        actions.addWidget(self.approve)
        artifact_layout.addLayout(actions)

        self.viewer_stack = QStackedWidget()
        self.viewer_stack.setMinimumHeight(190)
        self.viewer_stack.setMaximumHeight(230)
        self.qc_image = QLabel()
        self.qc_image.setAlignment(Qt.AlignCenter)
        self.qc_image.setStyleSheet("background: #101b2b; border-radius: 8px;")
        self.empty_viewer = QLabel(
            "QC preview is unavailable. Open the mask in ITK-SNAP for full review."
        )
        self.empty_viewer.setAlignment(Qt.AlignCenter)
        self.empty_viewer.setObjectName("muted")
        self.viewer_stack.addWidget(self.qc_image)
        self.viewer_stack.addWidget(self.empty_viewer)
        artifact_layout.addWidget(self.viewer_stack)

        stats = QFrame()
        stats.setObjectName("subtleCard")
        self.stats_layout = QGridLayout(stats)
        self.stats_layout.setContentsMargins(14, 12, 14, 12)
        self.stats_layout.setHorizontalSpacing(20)
        artifact_layout.addWidget(stats)

        self.technical_details = CollapsibleSection()
        self.technical_stats_layout = QGridLayout()
        self.technical_stats_layout.setHorizontalSpacing(20)
        self.technical_details.content_layout.addLayout(self.technical_stats_layout)
        paths = QGridLayout()
        self.mask_path = ElidedLabel()
        self.raw_mask_path = ElidedLabel()
        paths.addWidget(QLabel("Current mask"), 0, 0)
        paths.addWidget(self.mask_path, 0, 1)
        paths.addWidget(QLabel("Raw RS2 mask"), 1, 0)
        paths.addWidget(self.raw_mask_path, 1, 1)
        paths.setColumnStretch(1, 1)
        self.technical_details.content_layout.addLayout(paths)
        artifact_layout.addWidget(self.technical_details)
        self.layout.addWidget(self.artifact_card)
        self.layout.addStretch()

    def set_subject(self, subject: SubjectViewModel) -> None:
        self.current_subject = subject
        self.release_status.setText(
            subject.t1_brain_mask_release_label
            or "No validated local RS2-Net/M-seam method is selected for this study."
        )
        self.run_subject.setEnabled(subject.can_run_t1_brain_mask)
        self.run_subject.setText(
            "Generate new draft"
            if subject.t1_brain_mask_artifact is not None
            else "Generate draft"
        )
        self.run_subject.setToolTip(subject.t1_brain_mask_blocked_reason or "")
        self.readiness.setText(
            "Ready to generate an automatic draft. Human review will still be required."
            if subject.can_run_t1_brain_mask
            else subject.t1_brain_mask_blocked_reason
            or "This subject is not ready for T1 brain-mask generation."
        )
        artifact = subject.t1_brain_mask_artifact
        self.artifact_card.setVisible(artifact is not None)
        if artifact is None:
            return
        self.technical_details.set_expanded(False)
        self.artifact_title.setText(f"{artifact.origin_label} · version {artifact.version}")
        clear_layout(self.artifact_status)
        self.artifact_status.addWidget(StatusBadge(artifact.state))
        clear_layout(self.stats_layout)
        clear_layout(self.technical_stats_layout)
        warnings = (
            "; ".join(artifact.regularity_warnings)
            if artifact.regularity_warnings
            else "None"
        )
        stats = (
            ("Mask volume", artifact.volume_text),
            ("QC warnings", warnings),
            (
                "Reviewed by" if artifact.reviewer else "Created",
                (
                    f"{artifact.reviewer} · {artifact.reviewed_at}"
                    if artifact.reviewer and artifact.reviewed_at
                    else artifact.reviewer or artifact.created_at
                ),
            ),
        )
        _populate_stat_grid(self.stats_layout, stats)
        technical_stats = (
            ("Foreground voxels", f"{artifact.foreground_voxels:,}"),
            ("Device", artifact.device.upper()),
            ("Method", artifact.release_label),
        )
        _populate_stat_grid(self.technical_stats_layout, technical_stats)
        self.mask_path.setText(str(artifact.mask_path))
        self.raw_mask_path.setText(
            str(artifact.raw_mask_path) if artifact.raw_mask_path is not None else "—"
        )
        preview = artifact.qc_preview_path
        if preview is not None and preview.is_file():
            pixmap = QPixmap(str(preview))
            self.qc_image.setPixmap(
                pixmap.scaled(850, 215, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            )
            self.viewer_stack.setCurrentWidget(self.qc_image)
        else:
            self.viewer_stack.setCurrentWidget(self.empty_viewer)
        self.manual_edit.setEnabled(artifact.can_correct)
        self.approve.setEnabled(artifact.can_review)

    def _run_subject(self) -> None:
        if self.current_subject is not None:
            self.run_subject_requested.emit(self.current_subject.subject_id)

    def _manual_edit(self) -> None:
        if (
            self.current_subject is not None
            and self.current_subject.t1_brain_mask_artifact is not None
        ):
            self.manual_edit_requested.emit(
                self.current_subject.subject_id,
                self.current_subject.t1_brain_mask_artifact.artifact_id,
            )

    def _approve(self) -> None:
        if (
            self.current_subject is not None
            and self.current_subject.t1_brain_mask_artifact is not None
        ):
            self.approve_requested.emit(
                self.current_subject.subject_id,
                self.current_subject.t1_brain_mask_artifact.artifact_id,
            )


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
