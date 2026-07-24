"""Focused subject workspace for reviewed major-region atlas mapping."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from lys_bbb_app.domain.atlas_mapping import AtlasMappingState, AtlasReviewState
from lys_bbb_app.domain.view_models import SubjectViewModel
from lys_bbb_app.ui.widgets import StatusBadge
from lys_bbb_app.domain.view_models import StatusValue


class AtlasMappingPanel(QScrollArea):
    configure_resource_requested = Signal(str)
    register_scheme_requested = Signal(str)
    approve_scheme_requested = Signal(str, str)
    import_support_mask_requested = Signal(str)
    approve_support_mask_requested = Signal(str, str)
    run_atlas_to_t1_requested = Signal(str)
    approve_atlas_to_t1_requested = Signal(str, str)
    run_t1_to_t2_requested = Signal(str)
    approve_t1_to_t2_requested = Signal(str, str)
    create_composite_requested = Signal(str)
    approve_composite_requested = Signal(str, str)
    calculate_result_requested = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.subject: SubjectViewModel | None = None
        self.state: AtlasMappingState | None = None
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(18, 16, 18, 18)
        layout.setSpacing(14)
        self.setWidget(content)

        warning = QLabel(
            "PROVISIONAL atlas MVP · only proposed major anatomical regions are shown. "
            "Fine Allen labels never enter result tables."
        )
        warning.setObjectName("warningBanner")
        warning.setWordWrap(True)
        layout.addWidget(warning)
        layout.addWidget(self._resource_card())
        layout.addWidget(self._atlas_to_t1_card())
        layout.addWidget(self._t1_to_t2_card())
        layout.addWidget(self._composite_card())
        layout.addWidget(self._result_card())
        layout.addStretch()

    def _resource_card(self) -> QFrame:
        card, body = _card(
            "1 · Atlas resource and major-region scheme",
            "Register the checksummed AIDAmri MRI/Allen bridge and review the proposed collapse.",
        )
        self.resource_status = QLabel()
        self.resource_status.setWordWrap(True)
        self.resource_status.setObjectName("muted")
        body.addWidget(self.resource_status)
        actions = QHBoxLayout()
        self.configure_resource = QPushButton("Register local AIDAmri resource…")
        self.configure_resource.clicked.connect(self._configure_resource)
        self.register_scheme = QPushButton("Register proposed major_regions_v1")
        self.register_scheme.clicked.connect(self._register_scheme)
        self.approve_scheme = QPushButton("Approve exact proposed scheme")
        self.approve_scheme.clicked.connect(self._approve_scheme)
        self.import_support = QPushButton("Import T2 support mask…")
        self.import_support.clicked.connect(self._import_support)
        self.approve_support = QPushButton("Approve T2 support mask")
        self.approve_support.clicked.connect(self._approve_support)
        for button in (
            self.configure_resource,
            self.register_scheme,
            self.approve_scheme,
            self.import_support,
            self.approve_support,
        ):
            actions.addWidget(button)
        actions.addStretch()
        body.addLayout(actions)
        return card

    def _atlas_to_t1_card(self) -> QFrame:
        card, body = _card(
            "2 · Atlas → native pre-Gd T1",
            "Run recorded rigid and affine candidates using mutual information, then select one exact artifact.",
        )
        actions = QHBoxLayout()
        self.run_atlas = QPushButton("Run rigid + affine candidates")
        self.run_atlas.clicked.connect(self._run_atlas)
        self.candidate = QComboBox()
        self.candidate.currentIndexChanged.connect(self._show_candidate)
        self.approve_atlas = QPushButton("Select and approve candidate")
        self.approve_atlas.clicked.connect(self._approve_atlas)
        actions.addWidget(self.run_atlas)
        actions.addWidget(self.candidate, 1)
        actions.addWidget(self.approve_atlas)
        body.addLayout(actions)
        self.atlas_status = QLabel()
        self.atlas_status.setObjectName("muted")
        self.atlas_status.setWordWrap(True)
        body.addWidget(self.atlas_status)
        self.atlas_qc = _qc_label("Rigid/affine QC appears here after a run.")
        body.addWidget(self.atlas_qc)
        return card

    def _t1_to_t2_card(self) -> QFrame:
        card, body = _card(
            "3 · Native pre-T1 → original partial T2",
            "Rigid-only mutual-information registration. Inspect all original T2 slices.",
        )
        actions = QHBoxLayout()
        self.run_t1_t2 = QPushButton("Run rigid registration")
        self.run_t1_t2.clicked.connect(self._run_t1_t2)
        self.t1_t2_slice = QComboBox()
        self.t1_t2_slice.currentIndexChanged.connect(self._show_t1_t2_slice)
        self.approve_t1_t2 = QPushButton("Approve exact rigid mapping")
        self.approve_t1_t2.clicked.connect(self._approve_t1_t2)
        actions.addWidget(self.run_t1_t2)
        actions.addWidget(self.t1_t2_slice, 1)
        actions.addWidget(self.approve_t1_t2)
        body.addLayout(actions)
        self.t1_t2_qc = _qc_label("All-slice T1→T2 QC appears here after a run.")
        body.addWidget(self.t1_t2_qc)
        return card

    def _composite_card(self) -> QFrame:
        card, body = _card(
            "4 · Major-region labels on original T2",
            "Propagate source-grid major labels directly once with atlas→pre→T2 transforms.",
        )
        actions = QHBoxLayout()
        self.create_composite = QPushButton("Generate composite labels")
        self.create_composite.clicked.connect(self._create_composite)
        self.composite_slice = QComboBox()
        self.composite_slice.currentIndexChanged.connect(self._show_composite_slice)
        self.approve_composite = QPushButton("Approve composite QC")
        self.approve_composite.clicked.connect(self._approve_composite)
        actions.addWidget(self.create_composite)
        actions.addWidget(self.composite_slice, 1)
        actions.addWidget(self.approve_composite)
        body.addLayout(actions)
        self.composite_qc = _qc_label(
            "Major-region boundaries and native lesion appear on every T2 slice."
        )
        body.addWidget(self.composite_qc)
        return card

    def _result_card(self) -> QFrame:
        card, body = _card(
            "5 · Native T2 lesion / major-region result",
            "Calculate nominal and physical ±0.5 mm AP sensitivity results only after every approval.",
        )
        actions = QHBoxLayout()
        self.calculate_result = QPushButton("Calculate approved major-region overlap")
        self.calculate_result.clicked.connect(self._calculate_result)
        self.result_badge = QHBoxLayout()
        actions.addWidget(self.calculate_result)
        actions.addStretch()
        actions.addLayout(self.result_badge)
        body.addLayout(actions)
        self.result_summary = QLabel("No approved major-region result.")
        self.result_summary.setWordWrap(True)
        self.result_summary.setObjectName("muted")
        body.addWidget(self.result_summary)
        return card

    def set_subject(
        self, subject: SubjectViewModel, state: AtlasMappingState | None
    ) -> None:
        self.subject = subject
        self.state = state
        self._refresh()

    def _refresh(self) -> None:
        state = self.state
        subject = self.subject
        if state is None or subject is None:
            self.resource_status.setText("Atlas state is unavailable for this subject.")
            for button in self._dependency_buttons():
                button.setEnabled(False)
            return
        release = state.release
        scheme = state.scheme
        support = state.t2_support_mask
        self.resource_status.setText(
            " · ".join(
                (
                    release.release_version if release else "AIDAmri not registered",
                    (
                        f"{scheme.mapping_version}: {scheme.state.value}"
                        if scheme
                        else "major scheme not registered"
                    ),
                    (
                        f"T2 support mask: {support.state.value}"
                        if support
                        else "T2 support mask missing"
                    ),
                )
            )
        )
        self.register_scheme.setEnabled(release is not None and scheme is None)
        self.approve_scheme.setEnabled(
            scheme is not None
            and scheme.state is AtlasReviewState.DRAFT_REVIEW_REQUIRED
        )
        self.approve_support.setEnabled(
            support is not None
            and support.state is AtlasReviewState.DRAFT_REVIEW_REQUIRED
        )
        self.run_atlas.setEnabled(
            release is not None and subject.brain_mask.kind == "approved"
        )

        self.candidate.blockSignals(True)
        self.candidate.clear()
        for item in state.atlas_to_t1_candidates:
            self.candidate.addItem(
                f"{item.candidate} · {item.state.value}", item.id
            )
        self.candidate.blockSignals(False)
        self._show_candidate()
        selected = state.selected_atlas_to_t1
        self.atlas_status.setText(
            f"Selected: {selected.candidate} · exact hashes approved"
            if selected is not None
            else "No candidate approved. Optimizer success remains DRAFT."
        )
        current_candidate = self._current_candidate()
        self.approve_atlas.setEnabled(
            current_candidate is not None
            and current_candidate.state is AtlasReviewState.DRAFT_REVIEW_REQUIRED
        )
        self.run_t1_t2.setEnabled(
            support is not None
            and support.state is AtlasReviewState.APPROVED
            and subject.t1_data.kind == "ready"
            and subject.t2_data.kind == "ready"
        )

        self.t1_t2_slice.blockSignals(True)
        self.t1_t2_slice.clear()
        t1_t2 = state.t1_to_t2
        if t1_t2 is not None:
            for index in range(len(t1_t2.qc_slice_paths)):
                self.t1_t2_slice.addItem(
                    f"Original T2 slice {index + 1}/{len(t1_t2.qc_slice_paths)}"
                )
        self.t1_t2_slice.blockSignals(False)
        self._show_t1_t2_slice()
        self.approve_t1_t2.setEnabled(
            t1_t2 is not None
            and t1_t2.state is AtlasReviewState.DRAFT_REVIEW_REQUIRED
        )

        scheme_approved = (
            scheme is not None and scheme.state is AtlasReviewState.APPROVED
        )
        registrations_approved = (
            selected is not None
            and selected.state is AtlasReviewState.APPROVED
            and t1_t2 is not None
            and t1_t2.state is AtlasReviewState.APPROVED
        )
        self.create_composite.setEnabled(
            scheme_approved
            and registrations_approved
            and subject.t2_artifact is not None
        )
        composite = state.composite
        self.composite_slice.blockSignals(True)
        self.composite_slice.clear()
        if composite is not None:
            for index in range(len(composite.qc_slice_paths)):
                self.composite_slice.addItem(
                    f"Original T2 slice {index + 1}/{len(composite.qc_slice_paths)}"
                )
        self.composite_slice.blockSignals(False)
        self._show_composite_slice()
        self.approve_composite.setEnabled(
            composite is not None
            and composite.state is AtlasReviewState.DRAFT_REVIEW_REQUIRED
        )
        self.calculate_result.setEnabled(
            composite is not None
            and composite.state is AtlasReviewState.APPROVED
            and subject.t2_artifact is not None
            and subject.t2_artifact.state.kind == "approved"
        )
        _clear_layout(self.result_badge)
        if state.result is not None:
            self.result_badge.addWidget(StatusBadge(StatusValue("Approved", "approved")))
            self.result_summary.setText(
                f"Lesion {state.result.lesion_voxel_count:,} voxels · "
                f"{state.result.lesion_volume_mm3:.4f} mm³ · mapped "
                f"{state.result.mapped_lesion_voxels:,} · unmapped "
                f"{state.result.unmapped_lesion_voxels:,} · outside atlas support "
                f"{state.result.outside_atlas_support_lesion_voxels:,} · boundary-near "
                f"{state.result.boundary_lesion_voxels:,} · "
                f"{state.result.sensitivity_status}\n{state.result.result_csv_path}"
            )
        else:
            self.result_summary.setText("No approved major-region result.")

    def _current_candidate(self):
        if self.state is None:
            return None
        artifact_id = self.candidate.currentData()
        return next(
            (item for item in self.state.atlas_to_t1_candidates if item.id == artifact_id),
            None,
        )

    def _show_candidate(self) -> None:
        candidate = self._current_candidate()
        _set_pixmap(self.atlas_qc, candidate.qc_path if candidate else None)

    def _show_t1_t2_slice(self) -> None:
        artifact = self.state.t1_to_t2 if self.state else None
        index = self.t1_t2_slice.currentIndex()
        path = (
            artifact.qc_slice_paths[index]
            if artifact is not None and 0 <= index < len(artifact.qc_slice_paths)
            else None
        )
        _set_pixmap(self.t1_t2_qc, path)

    def _show_composite_slice(self) -> None:
        artifact = self.state.composite if self.state else None
        index = self.composite_slice.currentIndex()
        path = (
            artifact.qc_slice_paths[index]
            if artifact is not None and 0 <= index < len(artifact.qc_slice_paths)
            else None
        )
        _set_pixmap(self.composite_qc, path)

    def _configure_resource(self) -> None:
        if self.subject:
            self.configure_resource_requested.emit(self.subject.subject_id)

    def _register_scheme(self) -> None:
        if self.subject:
            self.register_scheme_requested.emit(self.subject.subject_id)

    def _approve_scheme(self) -> None:
        if self.subject and self.state and self.state.scheme:
            self.approve_scheme_requested.emit(
                self.subject.subject_id, self.state.scheme.id
            )

    def _import_support(self) -> None:
        if self.subject:
            self.import_support_mask_requested.emit(self.subject.subject_id)

    def _approve_support(self) -> None:
        if self.subject and self.state and self.state.t2_support_mask:
            self.approve_support_mask_requested.emit(
                self.subject.subject_id, self.state.t2_support_mask.id
            )

    def _run_atlas(self) -> None:
        if self.subject:
            self.run_atlas_to_t1_requested.emit(self.subject.subject_id)

    def _approve_atlas(self) -> None:
        candidate = self._current_candidate()
        if self.subject and candidate:
            self.approve_atlas_to_t1_requested.emit(
                self.subject.subject_id, candidate.id
            )

    def _run_t1_t2(self) -> None:
        if self.subject:
            self.run_t1_to_t2_requested.emit(self.subject.subject_id)

    def _approve_t1_t2(self) -> None:
        if self.subject and self.state and self.state.t1_to_t2:
            self.approve_t1_to_t2_requested.emit(
                self.subject.subject_id, self.state.t1_to_t2.id
            )

    def _create_composite(self) -> None:
        if self.subject:
            self.create_composite_requested.emit(self.subject.subject_id)

    def _approve_composite(self) -> None:
        if self.subject and self.state and self.state.composite:
            self.approve_composite_requested.emit(
                self.subject.subject_id, self.state.composite.id
            )

    def _calculate_result(self) -> None:
        if self.subject:
            self.calculate_result_requested.emit(self.subject.subject_id)

    def _dependency_buttons(self) -> tuple[QPushButton, ...]:
        return (
            self.register_scheme,
            self.approve_scheme,
            self.import_support,
            self.approve_support,
            self.run_atlas,
            self.approve_atlas,
            self.run_t1_t2,
            self.approve_t1_t2,
            self.create_composite,
            self.approve_composite,
            self.calculate_result,
        )


def _card(title: str, detail: str) -> tuple[QFrame, QVBoxLayout]:
    card = QFrame()
    card.setObjectName("card")
    layout = QVBoxLayout(card)
    layout.setContentsMargins(16, 14, 16, 16)
    heading = QLabel(title)
    heading.setObjectName("sectionTitle")
    copy = QLabel(detail)
    copy.setObjectName("muted")
    copy.setWordWrap(True)
    layout.addWidget(heading)
    layout.addWidget(copy)
    return card, layout


def _qc_label(empty_text: str) -> QLabel:
    label = QLabel(empty_text)
    label.setAlignment(Qt.AlignCenter)
    label.setMinimumHeight(220)
    label.setWordWrap(True)
    label.setObjectName("muted")
    label.setStyleSheet("background: #101b2b; border-radius: 8px;")
    return label


def _set_pixmap(label: QLabel, path) -> None:
    if path is not None and path.is_file():
        pixmap = QPixmap(str(path))
        if not pixmap.isNull():
            label.setPixmap(
                pixmap.scaled(900, 420, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            )
            return
    label.setPixmap(QPixmap())
    label.setText("QC is not available for this stage.")


def _clear_layout(layout: QHBoxLayout) -> None:
    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget()
        if widget is not None:
            widget.deleteLater()
