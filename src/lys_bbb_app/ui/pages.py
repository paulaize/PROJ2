"""Page widgets for the connected desktop MVP design preview."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QModelIndex, Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLayout,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QStackedWidget,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from lys_bbb_app.domain.view_models import StatusValue, StudyViewModel, SubjectViewModel
from lys_bbb_app.domain.study import RecentStudy
from lys_bbb_app.ui.models import (
    ApprovedResultsProxyModel,
    ResultsTableModel,
    SubjectFilterProxyModel,
    SubjectTableModel,
)
from lys_bbb_app.ui.layout_helpers import (
    clear_layout as _clear_layout,
    page_heading as _page_heading,
)
from lys_bbb_app.ui.widgets import (
    CohortPlot,
    EmptyState,
    ReadinessSummary,
    StatusBadge,
    WorkflowCard,
    secondary_button,
)


class StudyLauncherPage(QWidget):
    preview_requested = Signal()
    create_requested = Signal()
    open_requested = Signal()
    migrate_requested = Signal()
    recent_open_requested = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("launcherPage")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(56, 42, 56, 42)
        outer.setSpacing(24)

        brand = QHBoxLayout()
        wordmark = QLabel("LYS BBB")
        wordmark.setStyleSheet("font-size: 18px; font-weight: 750; color: #17374a;")
        subtitle = QLabel("Scientific workflow desktop")
        subtitle.setObjectName("muted")
        brand.addWidget(wordmark)
        brand.addSpacing(10)
        brand.addWidget(subtitle)
        brand.addStretch()
        backend = StatusBadge(StatusValue("Backend ready", "ready"))
        brand.addWidget(backend)
        outer.addLayout(brand)

        hero = QFrame()
        hero.setObjectName("card")
        hero_layout = QHBoxLayout(hero)
        hero_layout.setContentsMargins(30, 28, 30, 28)
        hero_text = QVBoxLayout()
        title = QLabel("Mouse T1 and T2 MRI analysis, organised by subject")
        title.setObjectName("pageTitle")
        intro = QLabel(
            "Create or resume a study, review scientific artifacts, and keep every "
            "measurement connected to its method and provenance."
        )
        intro.setObjectName("muted")
        intro.setWordWrap(True)
        intro.setMaximumWidth(720)
        hero_text.addWidget(title)
        hero_text.addWidget(intro)
        hero_layout.addLayout(hero_text, 1)

        actions = QVBoxLayout()
        preview = QPushButton("Open design preview")
        preview.setObjectName("openDesignPreviewButton")
        preview.setMinimumWidth(190)
        preview.clicked.connect(self.preview_requested)
        create = secondary_button("Create study…")
        create.setObjectName("createProjectButton")
        create.clicked.connect(self.create_requested)
        open_button = secondary_button("Open existing study…")
        open_button.setObjectName("openProjectButton")
        open_button.clicked.connect(self.open_requested)
        migrate = secondary_button("Migrate legacy .lysbbb…")
        migrate.clicked.connect(self.migrate_requested)
        actions.addWidget(preview)
        actions.addWidget(create)
        actions.addWidget(open_button)
        actions.addWidget(migrate)
        hero_layout.addLayout(actions)
        outer.addWidget(hero)

        recent_title = QLabel("Recent studies")
        recent_title.setObjectName("sectionTitle")
        outer.addWidget(recent_title)

        self.recent_layout = QHBoxLayout()
        self.recent_layout.setSpacing(16)
        outer.addLayout(self.recent_layout)
        self.set_recent_studies(())
        outer.addStretch()

        note = QLabel(
            "Design-preview records are synthetic and never written to project state. "
            "Persistent studies use a versioned study directory; source images may stay "
            "on mounted hard drives."
        )
        note.setObjectName("previewBanner")
        note.setWordWrap(True)
        outer.addWidget(note)

    def set_recent_studies(self, studies: tuple[RecentStudy, ...]) -> None:
        _clear_layout(self.recent_layout)
        if studies:
            for study in studies[:3]:
                self.recent_layout.addWidget(self._recent_study_card(study), 1)
        else:
            self.recent_layout.addWidget(self._empty_recent_card(), 1)
        self.recent_layout.addWidget(self._recent_preview_card(), 1)

    def _recent_preview_card(self) -> QFrame:
        card = QFrame()
        card.setObjectName("recentCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(20, 18, 20, 18)
        title = QLabel("LYS Design Preview 2026")
        title.setObjectName("cardTitle")
        detail = QLabel("Synthetic study · 24 subjects · 8 pending reviews")
        detail.setObjectName("muted")
        state = StatusBadge(StatusValue("Preview data", "review"))
        button = secondary_button("Open preview")
        button.clicked.connect(self.preview_requested)
        layout.addWidget(title)
        layout.addWidget(detail)
        layout.addWidget(state, alignment=Qt.AlignLeft)
        layout.addStretch()
        layout.addWidget(button, alignment=Qt.AlignLeft)
        return card

    def _empty_recent_card(self) -> QFrame:
        card = QFrame()
        card.setObjectName("recentCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(20, 18, 20, 18)
        title = QLabel("No recent persistent studies")
        title.setObjectName("cardTitle")
        detail = QLabel(
            "Create a study or open an existing study directory to add it here."
        )
        detail.setObjectName("muted")
        detail.setWordWrap(True)
        button = secondary_button("Open existing study…")
        button.clicked.connect(self.open_requested)
        layout.addWidget(title)
        layout.addWidget(detail)
        layout.addStretch()
        layout.addWidget(button, alignment=Qt.AlignLeft)
        return card

    def _recent_study_card(self, study: RecentStudy) -> QFrame:
        card = QFrame()
        card.setObjectName("recentCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(20, 18, 20, 18)
        title = QLabel(study.name)
        title.setObjectName("cardTitle")
        detail = QLabel(study.path)
        detail.setObjectName("muted")
        detail.setWordWrap(True)
        opened = QLabel(f"Last opened: {study.last_opened}")
        opened.setObjectName("metadata")
        button = secondary_button("Open study")
        button.clicked.connect(
            lambda _checked=False, path=study.path: self.recent_open_requested.emit(path)
        )
        layout.addWidget(title)
        layout.addWidget(detail)
        layout.addWidget(opened)
        layout.addStretch()
        layout.addWidget(button, alignment=Qt.AlignLeft)
        return card


class OverviewPage(QScrollArea):
    navigate_requested = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.content = QWidget()
        self.layout = QVBoxLayout(self.content)
        self.layout.setContentsMargins(28, 24, 28, 28)
        self.layout.setSpacing(20)
        self.setWidget(self.content)

        heading, heading_layout = _page_heading(
            "Overview",
            "Study readiness, scientific workflow status, and the next required actions.",
        )
        refresh = secondary_button("Refresh")
        refresh.setEnabled(False)
        refresh.setToolTip("The current study refreshes after each completed action.")
        heading_layout.addWidget(refresh)
        self.layout.addWidget(heading)

        self.metric_container = QWidget()
        self.metric_layout = QHBoxLayout(self.metric_container)
        self.metric_layout.setContentsMargins(0, 0, 0, 0)
        self.metric_layout.setSpacing(12)
        self.layout.addWidget(self.metric_container)

        workflow_title = QLabel("Workflows")
        workflow_title.setObjectName("sectionTitle")
        self.layout.addWidget(workflow_title)
        self.workflow_container = QWidget()
        self.workflow_layout = QGridLayout(self.workflow_container)
        self.workflow_layout.setContentsMargins(0, 0, 0, 0)
        self.workflow_layout.setHorizontalSpacing(14)
        self.workflow_layout.setVerticalSpacing(14)
        self.layout.addWidget(self.workflow_container)

        action_title = QLabel("Priority actions")
        action_title.setObjectName("sectionTitle")
        self.layout.addWidget(action_title)
        self.action_container = QFrame()
        self.action_container.setObjectName("card")
        self.action_layout = QVBoxLayout(self.action_container)
        self.action_layout.setContentsMargins(10, 8, 10, 8)
        self.action_layout.setSpacing(0)
        self.layout.addWidget(self.action_container)
        self.layout.addStretch()

    def set_study(self, study: StudyViewModel) -> None:
        _clear_layout(self.metric_layout)
        _clear_layout(self.workflow_layout)
        _clear_layout(self.action_layout)
        if study.metrics:
            self.metric_layout.addWidget(ReadinessSummary(study.metrics), 1)

        if study.workflows:
            columns = min(3, len(study.workflows))
            for index, workflow in enumerate(study.workflows):
                card = WorkflowCard(workflow)
                card.action_requested.connect(self.navigate_requested)
                self.workflow_layout.addWidget(card, index // columns, index % columns)
        else:
            self.workflow_layout.addWidget(
                EmptyState(
                    "No subjects yet",
                    "Import subjects to populate T1, T2, and combined workflow cards.",
                    "Import subjects",
                ),
                0,
                0,
                1,
                2,
            )

        if study.priority_actions:
            for index, action in enumerate(study.priority_actions):
                row = QPushButton()
                row.setProperty("kind", "secondary")
                row.setStyleSheet("text-align: left; padding: 10px 12px;")
                row.setText(f"{action.label}\n{action.detail}")
                row.clicked.connect(
                    lambda _checked=False, target=action.target_page: self.navigate_requested.emit(target)
                )
                self.action_layout.addWidget(row)
                if index < len(study.priority_actions) - 1:
                    separator = QFrame()
                    separator.setFrameShape(QFrame.HLine)
                    separator.setStyleSheet("color: #e7ecef;")
                    self.action_layout.addWidget(separator)
        else:
            self.action_layout.addWidget(
                EmptyState("No pending actions", "Subjects and reviews will appear here.")
            )


class SubjectsPage(QWidget):
    subject_open_requested = Signal(str)
    subject_mri_open_requested = Signal(str)
    subjects_flip_requested = Signal(object)
    subject_remove_requested = Signal(str)
    subject_restore_requested = Signal()
    preview_action = Signal(str)
    add_subject_requested = Signal()
    import_mri_requested = Signal()
    group_assignment_requested = Signal()
    audit_history_requested = Signal()
    t2_inference_requested = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.blinded_review = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 28)
        layout.setSpacing(16)
        heading, heading_layout = _page_heading(
            "Subjects",
            "Central worklist for imported data, review gates, and workflow readiness.",
        )
        history = secondary_button("Audit history")
        history.clicked.connect(self.audit_history_requested)
        add_subject = QPushButton("Add subject")
        add_subject.clicked.connect(self.add_subject_requested)
        import_mri = QPushButton("Import MRI folder…")
        import_mri.clicked.connect(self.import_mri_requested)
        self.run_t2 = QPushButton("Run T2 segmentation…")
        self.run_t2.clicked.connect(self.t2_inference_requested.emit)
        self.assign_groups = secondary_button("Assign groups…")
        self.assign_groups.clicked.connect(self.group_assignment_requested)
        heading_layout.addWidget(history)
        heading_layout.addWidget(self.assign_groups)
        heading_layout.addWidget(import_mri)
        heading_layout.addWidget(self.run_t2)
        heading_layout.addWidget(add_subject)
        layout.addWidget(heading)

        filters = QFrame()
        filters.setObjectName("card")
        filter_layout = QHBoxLayout(filters)
        filter_layout.setContentsMargins(14, 12, 14, 12)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search subject ID…")
        self.search.setClearButtonEnabled(True)
        self.group_filter = QComboBox()
        self.group_filter.addItem("All groups")
        self.state_filter = QComboBox()
        self.state_filter.addItems(
            [
                "All states",
                "Awaiting review",
                "Blocked",
                "Processing",
                "Provisional",
                "Human approved",
                "Result outdated",
                "Not available",
            ]
        )
        filter_layout.addWidget(self.search, 2)
        filter_layout.addWidget(self.group_filter, 1)
        filter_layout.addWidget(self.state_filter, 1)
        layout.addWidget(filters)

        self.model = SubjectTableModel()
        self.proxy = SubjectFilterProxyModel()
        self.proxy.setSourceModel(self.model)
        self.table = QTableView()
        self.table.setObjectName("subjectsTable")
        self.table.setModel(self.proxy)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QTableView.SelectRows)
        self.table.setSelectionMode(QTableView.ExtendedSelection)
        self.table.setSortingEnabled(True)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(42)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Stretch)
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(9, QHeaderView.ResizeToContents)
        self.table.sortByColumn(0, Qt.AscendingOrder)
        self.table.doubleClicked.connect(self._open_index)
        self.table.selectionModel().selectionChanged.connect(self._selection_changed)
        layout.addWidget(self.table, 1)

        footer = QHBoxLayout()
        self.count_label = QLabel("0 subjects")
        self.count_label.setObjectName("muted")
        self.count_label.setToolTip(
            "Use Shift or Command/Ctrl to select multiple subject rows."
        )
        self.restore_subjects = secondary_button("Removed subjects…")
        self.restore_subjects.setEnabled(False)
        self.restore_subjects.clicked.connect(self.subject_restore_requested)
        self.remove_subject = secondary_button("Remove selected…")
        self.remove_subject.setEnabled(False)
        self.remove_subject.clicked.connect(self._remove_selected)
        self.open_mri = secondary_button("Open MRI in ITK-SNAP")
        self.open_mri.setEnabled(False)
        self.open_mri.clicked.connect(self._open_selected_mri)
        self.flip_subjects = secondary_button("Create flipped versions…")
        self.flip_subjects.setEnabled(False)
        self.flip_subjects.clicked.connect(self._flip_selected)
        footer.addWidget(self.count_label)
        footer.addStretch()
        footer.addWidget(self.restore_subjects)
        footer.addWidget(self.open_mri)
        footer.addWidget(self.flip_subjects)
        footer.addWidget(self.remove_subject)
        layout.addLayout(footer)

        self.search.textChanged.connect(self._apply_filters)
        self.group_filter.currentTextChanged.connect(self._apply_filters)
        self.state_filter.currentTextChanged.connect(self._apply_filters)

    def set_study(self, study: StudyViewModel) -> None:
        self.model.set_subjects(study.subjects)
        self.table.clearSelection()
        self._selection_changed()
        self.restore_subjects.setEnabled(bool(study.archived_subjects))
        self.restore_subjects.setText(
            f"Removed subjects… ({len(study.archived_subjects)})"
            if study.archived_subjects
            else "Removed subjects…"
        )
        groups = sorted(
            {subject.group for subject in study.subjects if subject.group is not None}
        )
        current = self.group_filter.currentText()
        self.group_filter.blockSignals(True)
        self.group_filter.clear()
        self.group_filter.addItem("All groups")
        self.group_filter.addItems(groups)
        if current in ["All groups", *groups]:
            self.group_filter.setCurrentText(current)
        self.group_filter.blockSignals(False)
        self.count_label.setText(f"{len(study.subjects)} subjects")
        self.run_t2.setEnabled(
            study.t2_eligible_subject_count > 0 and study.t2_running_job_count == 0
        )
        self.run_t2.setText(
            f"Run T2 segmentation… ({study.t2_eligible_subject_count})"
            if study.t2_eligible_subject_count
            else "Run T2 segmentation…"
        )
        self.run_t2.setToolTip(
            "Runs every active subject with a validated, release-compatible T2 input."
            if study.t2_eligible_subject_count
            else "Validate a compatible T2 input before running segmentation."
        )
        self._apply_filters()

    def set_blinded_review(self, blinded: bool) -> None:
        self.blinded_review = blinded
        if blinded:
            self.group_filter.setCurrentText("All groups")
        self.group_filter.setVisible(not blinded)
        self.table.setColumnHidden(1, blinded)
        self.assign_groups.setText(
            "Unblind and assign groups…" if blinded else "Assign groups…"
        )

    def _apply_filters(self, *_args) -> None:
        self.proxy.set_filters(
            search=self.search.text(),
            group=self.group_filter.currentText(),
            state=self.state_filter.currentText(),
        )
        self._update_count_label()

    def _open_index(self, proxy_index: QModelIndex) -> None:
        source_index = self.proxy.mapToSource(proxy_index)
        subject = self.model.subject_at(source_index.row())
        if subject is not None:
            self.subject_open_requested.emit(subject.subject_id)

    def _selection_changed(self, *_args) -> None:
        subjects = self._selected_subjects()
        one_subject = subjects[0] if len(subjects) == 1 else None
        self.remove_subject.setEnabled(one_subject is not None)
        self.open_mri.setEnabled(
            one_subject is not None and one_subject.mri_input_count > 0
        )
        self.flip_subjects.setEnabled(
            bool(subjects) and all(subject.mri_input_count > 0 for subject in subjects)
        )
        self._update_count_label()

    def _selected_subjects(self) -> tuple[SubjectViewModel, ...]:
        rows = self.table.selectionModel().selectedRows()
        subjects = (
            self.model.subject_at(self.proxy.mapToSource(index).row())
            for index in rows
        )
        return tuple(subject for subject in subjects if subject is not None)

    def _selected_subject(self) -> SubjectViewModel | None:
        subjects = self._selected_subjects()
        return subjects[0] if len(subjects) == 1 else None

    def _update_count_label(self) -> None:
        selected = len(self._selected_subjects())
        suffix = f" · {selected} selected" if selected else ""
        self.count_label.setText(f"{self.proxy.rowCount()} subjects shown{suffix}")

    def _remove_selected(self) -> None:
        subject = self._selected_subject()
        if subject is not None:
            self.subject_remove_requested.emit(subject.subject_id)

    def _open_selected_mri(self) -> None:
        subject = self._selected_subject()
        if subject is not None:
            self.subject_mri_open_requested.emit(subject.subject_id)

    def _flip_selected(self) -> None:
        subject_ids = tuple(
            subject.subject_id for subject in self._selected_subjects()
        )
        if subject_ids:
            self.subjects_flip_requested.emit(subject_ids)


class ResultsPage(QScrollArea):
    preview_action = Signal(str)
    approved_csv_requested = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.blinded_review = False
        self.is_demo = False
        self.has_results = False
        self.has_approved_results = False
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(28, 24, 28, 28)
        layout.setSpacing(16)
        layout.setSizeConstraint(QLayout.SetMinimumSize)
        self.setWidget(content)

        heading, _heading_layout = _page_heading(
            "Results and exports",
            "Subject-level measurements with approval, method, and missingness preserved.",
        )
        layout.addWidget(heading)

        self.provisional_warning = QLabel(
            "Provisional measurements are shown for design review. Approved-only export excludes them by default."
        )
        self.provisional_warning.setObjectName("previewBanner")
        self.provisional_warning.setWordWrap(True)
        layout.addWidget(self.provisional_warning)

        self.blinding_note = QLabel()
        self.blinding_note.setObjectName("infoBanner")
        self.blinding_note.setWordWrap(True)
        layout.addWidget(self.blinding_note)

        self.results_card = QFrame()
        self.results_card.setObjectName("card")
        results_layout = QVBoxLayout(self.results_card)
        results_layout.setContentsMargins(14, 14, 14, 14)
        results_layout.setSpacing(12)
        results_heading = QHBoxLayout()
        result_titles = QVBoxLayout()
        result_title = QLabel("Subject results")
        result_title.setObjectName("cardTitle")
        result_caption = QLabel(
            "Approval state, method version, and missingness remain visible in every row."
        )
        result_caption.setObjectName("metadata")
        result_caption.setWordWrap(True)
        result_titles.addWidget(result_title)
        result_titles.addWidget(result_caption)
        results_heading.addLayout(result_titles, 1)
        results_heading.addStretch()
        self.provenance_button = secondary_button("View provenance")
        self.provenance_button.clicked.connect(
            lambda: self.preview_action.emit(
                "Provenance detail is a connected design-preview action; no record was changed."
            )
        )
        results_heading.addWidget(self.provenance_button)
        results_layout.addLayout(results_heading)

        controls = QHBoxLayout()
        self.approved_only = QCheckBox("Show subjects with at least one approved result")
        controls.addWidget(self.approved_only)
        controls.addStretch()
        results_layout.addLayout(controls)

        self.model = ResultsTableModel()
        self.proxy = ApprovedResultsProxyModel()
        self.proxy.setSourceModel(self.model)
        self.table = QTableView()
        self.table.setObjectName("resultsTable")
        self.table.setModel(self.proxy)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QTableView.SelectRows)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(42)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.results_stack = QStackedWidget()
        self.results_stack.setMinimumHeight(214)
        self.results_stack.setMaximumHeight(260)
        self.results_empty = EmptyState(
            "No subject results yet",
            "Approved and provisional measurements will appear after scientific workflows run.",
            embedded=True,
        )
        self.results_stack.addWidget(self.table)
        self.results_stack.addWidget(self.results_empty)
        results_layout.addWidget(self.results_stack)
        self.approved_only.toggled.connect(self.proxy.set_approved_only)
        layout.addWidget(self.results_card)

        lower = QHBoxLayout()
        lower.setSpacing(16)
        self.plot_card = QFrame()
        self.plot_card.setObjectName("card")
        self.plot_card.setMinimumHeight(300)
        plot_layout = QVBoxLayout(self.plot_card)
        plot_layout.setContentsMargins(14, 14, 14, 14)
        plot_layout.setSpacing(6)
        self.plot_title = QLabel("T2 lesion volume by group")
        self.plot_title.setObjectName("cardTitle")
        self.plot_caption = QLabel("Descriptive preview only · dots are synthetic")
        self.plot_caption.setObjectName("metadata")
        plot_layout.addWidget(self.plot_title)
        plot_layout.addWidget(self.plot_caption)
        self.plot_stack = QStackedWidget()
        self.cohort_plot = CohortPlot()
        self.plot_empty = EmptyState(
            "No cohort results yet",
            "Approved T1 or T2 measurements will appear here after scientific workflows are connected.",
            embedded=True,
        )
        self.plot_stack.addWidget(self.cohort_plot)
        self.plot_stack.addWidget(self.plot_empty)
        plot_layout.addWidget(self.plot_stack, 1)
        lower.addWidget(self.plot_card, 2)

        self.export_card = QFrame()
        self.export_card.setObjectName("card")
        self.export_card.setMinimumHeight(300)
        self.export_card.setMinimumWidth(280)
        export_layout = QVBoxLayout(self.export_card)
        export_layout.setContentsMargins(14, 14, 14, 14)
        export_layout.setSpacing(10)
        export_title = QLabel("Export safeguards")
        export_title.setObjectName("cardTitle")
        export_layout.addWidget(export_title)
        export_caption = QLabel(
            "Exports keep approval state, method version, and missing values explicit."
        )
        export_caption.setObjectName("metadata")
        export_caption.setWordWrap(True)
        export_layout.addWidget(export_caption)
        self.approved_csv = secondary_button("Approved T2 results CSV")
        self.approved_csv.clicked.connect(self.approved_csv_requested.emit)
        export_layout.addWidget(self.approved_csv)
        self.preview_export_buttons: list[QPushButton] = []
        for text in ("QC report · HTML/PDF", "Reproducibility bundle"):
            button = secondary_button(text)
            button.clicked.connect(
                lambda _checked=False, name=text: self._preview_export(name)
            )
            export_layout.addWidget(button)
            self.preview_export_buttons.append(button)
        self.export_buttons = [self.approved_csv, *self.preview_export_buttons]
        export_layout.addStretch()
        safeguard = QLabel("Missing values are never converted to zero.")
        safeguard.setObjectName("infoBanner")
        safeguard.setWordWrap(True)
        export_layout.addWidget(safeguard)
        lower.addWidget(self.export_card, 1)
        layout.addLayout(lower)
        layout.addStretch()
        self.set_blinded_review(False)

    def set_study(self, study: StudyViewModel) -> None:
        self.is_demo = study.is_demo
        self.has_results = bool(study.results)
        self.has_approved_results = any(
            result.t2_state.kind == "approved" for result in study.results
        )
        self.model.set_results(study.results)
        has_preview_results = study.is_demo and self.has_results
        self.provisional_warning.setVisible(has_preview_results)
        self.results_stack.setCurrentWidget(
            self.table if self.has_results else self.results_empty
        )
        self.plot_stack.setCurrentWidget(
            self.cohort_plot if has_preview_results else self.plot_empty
        )
        self.plot_caption.setVisible(has_preview_results)
        self.approved_only.setEnabled(self.has_results)
        self.provenance_button.setEnabled(has_preview_results)
        self.approved_csv.setEnabled(
            self.has_approved_results and not study.is_demo
        )
        self.approved_csv.setToolTip(
            ""
            if self.approved_csv.isEnabled()
            else "Available when this persistent study has an approved T2 lesion result."
        )
        for button in self.preview_export_buttons:
            button.setEnabled(has_preview_results)
            button.setToolTip(
                "Available only when the study contains exportable results."
                if not has_preview_results
                else ""
            )
        self._refresh_plot_title()

    def set_blinded_review(self, blinded: bool) -> None:
        self.blinded_review = blinded
        self.table.setColumnHidden(1, blinded)
        self.blinding_note.setVisible(blinded)
        self.blinding_note.setText(
            "BLINDED REVIEW — Experimental groups are hidden. Approved exports can omit "
            "groups; grouped summaries require an explicit audited unblinding step."
        )
        self._refresh_plot_title()
        self.cohort_plot.set_blinded(blinded)

    def _refresh_plot_title(self) -> None:
        if not self.has_results:
            self.plot_title.setText("Cohort summary")
        else:
            self.plot_title.setText(
                "T2 lesion volume · blinded cohort"
                if self.blinded_review
                else "T2 lesion volume by group"
            )

    def _preview_export(self, name: str) -> None:
        suffix = (
            " Group assignments would be omitted while the study remains blinded."
            if self.blinded_review
            else ""
        )
        self.preview_action.emit(
            f"{name} is a connected design-preview action; no file was created.{suffix}"
        )


class SettingsPage(QScrollArea):
    preview_action = Signal(str)
    blinding_changed = Signal(bool)
    input_folder_requested = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.NoFrame)
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(28, 24, 28, 28)
        layout.setSpacing(16)
        self.setWidget(content)
        heading, _heading_layout = _page_heading(
            "Settings",
            "User preferences, processing resources, and installed scientific releases.",
        )
        layout.addWidget(heading)

        self.persistence_note = QLabel("Preview controls are not persisted yet.")
        self.persistence_note.setObjectName("previewBanner")
        layout.addWidget(self.persistence_note)

        blinding = QGroupBox("Review blinding")
        blinding_layout = QVBoxLayout(blinding)
        self.blinded_review = QCheckBox(
            "Enable blinded review mode and hide experimental groups"
        )
        self.blinded_review.setChecked(True)
        blinding_detail = QLabel(
            "Reviewer identity is still recorded for audit. Group assignment is deferred "
            "until an explicit unblinding action before grouped analysis or grouped export."
        )
        blinding_detail.setObjectName("muted")
        blinding_detail.setWordWrap(True)
        blinding_layout.addWidget(self.blinded_review)
        blinding_layout.addWidget(blinding_detail)
        layout.addWidget(blinding)
        self.blinded_review.toggled.connect(self.blinding_changed)

        inputs = QGroupBox("Study input locations")
        input_form = QFormLayout(inputs)
        self.mri_input_folder = QLineEdit()
        self.mri_input_folder.setReadOnly(True)
        self.mri_input_folder.setPlaceholderText("No MRI source folder selected")
        self.t1_input_folder = QLineEdit()
        self.t1_input_folder.setReadOnly(True)
        self.t2_input_folder = QLineEdit()
        self.t2_input_folder.setReadOnly(True)
        browse = secondary_button("Choose and review…")
        browse.clicked.connect(lambda: self.input_folder_requested.emit("mri"))
        self.mri_input_row = QWidget()
        mri_layout = QHBoxLayout(self.mri_input_row)
        mri_layout.setContentsMargins(0, 0, 0, 0)
        mri_layout.addWidget(self.mri_input_folder, 1)
        mri_layout.addWidget(browse)
        input_form.addRow("MRI source root", self.mri_input_row)
        self.legacy_input_note = QLabel()
        self.legacy_input_note.setObjectName("muted")
        self.legacy_input_note.setWordWrap(True)
        self.legacy_input_note.hide()
        input_form.addRow(self.legacy_input_note)
        input_note = QLabel(
            "The selected root is scanned read-only for Bruker sessions and recognisable "
            "NIfTI files. You review subject IDs, T1 pre/post/T2 roles, coronal orientation, "
            "and optional storage-axis flips before versioned NIfTI copies are created "
            "inside the study. A disconnected drive path is retained for reconnection."
        )
        input_note.setObjectName("muted")
        input_note.setWordWrap(True)
        input_form.addRow(input_note)
        layout.addWidget(inputs)

        standard = QGroupBox("Standard settings")
        form = QFormLayout(standard)
        self.reviewer = QLineEdit("Paul-Andréas")
        self.external_editor = QLineEdit("/Applications/ITK-SNAP.app")
        self.external_editor.setPlaceholderText(
            "Leave blank to find ITK-SNAP automatically"
        )
        export_dir = QLineEdit("~/Documents/LYS exports")
        backups = QCheckBox("Create automatic project backups")
        backups.setChecked(True)
        form.addRow("Reviewer display name", self.reviewer)
        form.addRow("External editor", self.external_editor)
        form.addRow("Default export directory", export_dir)
        form.addRow("Backups", backups)
        layout.addWidget(standard)

        resources = QGroupBox("Processing resources")
        resource_form = QFormLayout(resources)
        workers = QSpinBox()
        workers.setRange(1, 16)
        workers.setValue(4)
        mps = QCheckBox("Use Apple MPS when a compatible backend declares support")
        mps.setChecked(True)
        concurrent = QSpinBox()
        concurrent.setRange(1, 8)
        concurrent.setValue(2)
        resource_form.addRow("CPU worker count", workers)
        resource_form.addRow("Acceleration", mps)
        resource_form.addRow("Maximum concurrent jobs", concurrent)
        layout.addWidget(resources)

        releases = QGroupBox("Scientific backend releases")
        release_layout = QVBoxLayout(releases)
        t2 = QFrame()
        t2.setObjectName("card")
        t2_layout = QHBoxLayout(t2)
        t2_text = QVBoxLayout()
        t2_title = QLabel("RatLesNetV2")
        t2_title.setObjectName("cardTitle")
        t2_detail = QLabel("No frozen LYS_PROJ1 release installed")
        t2_detail.setObjectName("muted")
        t2_text.addWidget(t2_title)
        t2_text.addWidget(t2_detail)
        t2_layout.addLayout(t2_text, 1)
        t2_layout.addWidget(StatusBadge(StatusValue("Not installed", "unavailable")))
        install = secondary_button("Install release…")
        install.clicked.connect(
            lambda: self.preview_action.emit("Release installation UI is preview-only.")
        )
        t2_layout.addWidget(install)
        release_layout.addWidget(t2)

        layout.addWidget(releases)

        save = QPushButton("Save preferences")
        save.clicked.connect(
            lambda: self.preview_action.emit("Preferences changed in preview only; nothing was saved.")
        )
        layout.addWidget(save, alignment=Qt.AlignRight)
        layout.addStretch()

    def set_study_state(self, *, persistent: bool, blinded: bool) -> None:
        self.blinded_review.blockSignals(True)
        self.blinded_review.setChecked(blinded)
        self.blinded_review.blockSignals(False)
        self.blinded_review.setEnabled(not persistent or blinded)
        if persistent:
            self.persistence_note.setObjectName("infoBanner")
            self.persistence_note.setText(
                "Study-level blinding is persisted. Unblinding is one-way and creates "
                "an audit event. Other user preferences are not persisted yet."
                if blinded
                else "This study has been unblinded. It cannot be marked blinded again; "
                "other user preferences are not persisted yet."
            )
        else:
            self.persistence_note.setObjectName("previewBanner")
            self.persistence_note.setText("Preview controls are not persisted yet.")
        self.persistence_note.style().unpolish(self.persistence_note)
        self.persistence_note.style().polish(self.persistence_note)

    def set_input_folders(
        self,
        *,
        mri_path: Path | None,
        t1_path: Path | None,
        t2_path: Path | None,
        enabled: bool,
    ) -> None:
        self.mri_input_folder.setText(str(mri_path) if mri_path is not None else "")
        self.t1_input_folder.setText(str(t1_path) if t1_path is not None else "")
        self.t2_input_folder.setText(str(t2_path) if t2_path is not None else "")
        legacy = []
        if t1_path is not None:
            legacy.append(f"T1: {t1_path}")
        if t2_path is not None:
            legacy.append(f"T2: {t2_path}")
        self.legacy_input_note.setText(
            "Legacy source references retained from an older project — " + " · ".join(legacy)
            if legacy
            else ""
        )
        self.legacy_input_note.setVisible(bool(legacy))
        self.mri_input_row.setEnabled(enabled)
