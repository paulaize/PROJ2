"""Page widgets for the connected desktop MVP design preview."""

from __future__ import annotations

from collections import Counter

from PySide6.QtCore import QModelIndex, Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QScrollArea,
    QSlider,
    QSpinBox,
    QSplitter,
    QTableView,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from lys_bbb_app.domain.view_models import (
    ReviewItemViewModel,
    StatusValue,
    StudyViewModel,
    SubjectViewModel,
)
from lys_bbb_app.ui.dialogs import GroupAssignmentDialog, UnblindingDialog
from lys_bbb_app.ui.models import (
    ApprovedResultsProxyModel,
    ResultsTableModel,
    SubjectFilterProxyModel,
    SubjectTableModel,
)
from lys_bbb_app.ui.widgets import (
    CohortPlot,
    EmptyState,
    ReadinessSummary,
    StatusBadge,
    SyntheticSliceViewer,
    WorkflowCard,
    secondary_button,
)


def _clear_layout(layout) -> None:
    while layout.count():
        item = layout.takeAt(0)
        child = item.widget()
        if child is not None:
            # Detach immediately so repeatedly refreshed pages cannot leave a
            # deferred-deletion widget covering the replacement content.
            child.setParent(None)
            child.deleteLater()
        nested = item.layout()
        if nested is not None:
            _clear_layout(nested)


def _page_heading(title_text: str, description_text: str) -> tuple[QWidget, QHBoxLayout]:
    widget = QWidget()
    layout = QHBoxLayout(widget)
    layout.setContentsMargins(0, 0, 0, 0)
    titles = QVBoxLayout()
    title = QLabel(title_text)
    title.setObjectName("pageTitle")
    description = QLabel(description_text)
    description.setObjectName("muted")
    description.setWordWrap(True)
    titles.addWidget(title)
    titles.addWidget(description)
    layout.addLayout(titles)
    layout.addStretch()
    return widget, layout


class StudyLauncherPage(QWidget):
    preview_requested = Signal()
    create_requested = Signal()
    open_requested = Signal()

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
        create = secondary_button("Create legacy project…")
        create.setObjectName("createProjectButton")
        create.clicked.connect(self.create_requested)
        open_button = secondary_button("Open legacy project…")
        open_button.setObjectName("openProjectButton")
        open_button.clicked.connect(self.open_requested)
        actions.addWidget(preview)
        actions.addWidget(create)
        actions.addWidget(open_button)
        hero_layout.addLayout(actions)
        outer.addWidget(hero)

        recent_title = QLabel("Recent studies")
        recent_title.setObjectName("sectionTitle")
        outer.addWidget(recent_title)

        cards = QHBoxLayout()
        cards.setSpacing(16)
        cards.addWidget(self._recent_preview_card(), 1)
        cards.addWidget(self._future_recent_card(), 1)
        outer.addLayout(cards)
        outer.addStretch()

        note = QLabel(
            "Design-preview records are synthetic and never written to project state. "
            "Legacy schema-v1 projects remain available while study-root Phase 1 is built."
        )
        note.setObjectName("previewBanner")
        note.setWordWrap(True)
        outer.addWidget(note)

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

    def _future_recent_card(self) -> QFrame:
        card = QFrame()
        card.setObjectName("recentCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(20, 18, 20, 18)
        title = QLabel("Your studies will appear here")
        title.setObjectName("cardTitle")
        detail = QLabel(
            "Study-root projects will show subject counts, pending reviews, schema version, "
            "and last-opened time."
        )
        detail.setObjectName("muted")
        detail.setWordWrap(True)
        button = secondary_button("Open existing study…")
        button.setEnabled(False)
        button.setToolTip("Study-root opening arrives with schema version 2.")
        layout.addWidget(title)
        layout.addWidget(detail)
        layout.addStretch()
        layout.addWidget(button, alignment=Qt.AlignLeft)
        return card


class OverviewPage(QScrollArea):
    navigate_requested = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.NoFrame)
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
        refresh.setToolTip("Live database refresh arrives in Phase 1.")
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
    preview_action = Signal(str)
    unblinding_requested = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.blinded_review = False
        self._subjects: tuple[SubjectViewModel, ...] = ()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 28)
        layout.setSpacing(16)
        heading, heading_layout = _page_heading(
            "Subjects",
            "Central worklist for imported data, review gates, and workflow readiness.",
        )
        add_subject = QPushButton("Add subject")
        add_subject.clicked.connect(
            lambda: self.preview_action.emit("Subject import is not persisted in design preview.")
        )
        self.assign_groups = secondary_button("Assign groups…")
        self.assign_groups.clicked.connect(self._preview_group_assignment)
        heading_layout.addWidget(self.assign_groups)
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
        self.table.setSelectionMode(QTableView.SingleSelection)
        self.table.setSortingEnabled(True)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(42)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Stretch)
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(8, QHeaderView.ResizeToContents)
        self.table.sortByColumn(0, Qt.AscendingOrder)
        self.table.doubleClicked.connect(self._open_index)
        layout.addWidget(self.table, 1)

        footer = QHBoxLayout()
        self.count_label = QLabel("0 subjects")
        self.count_label.setObjectName("muted")
        validate = secondary_button("Validate selected")
        validate.setEnabled(False)
        validate.setToolTip("Backend actions arrive after artifact/workflow state.")
        run = secondary_button("Run ready jobs")
        run.setEnabled(False)
        footer.addWidget(self.count_label)
        footer.addStretch()
        footer.addWidget(validate)
        footer.addWidget(run)
        layout.addLayout(footer)

        self.search.textChanged.connect(self._apply_filters)
        self.group_filter.currentTextChanged.connect(self._apply_filters)
        self.state_filter.currentTextChanged.connect(self._apply_filters)

    def set_study(self, study: StudyViewModel) -> None:
        self._subjects = study.subjects
        self.model.set_subjects(study.subjects)
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

    def _preview_group_assignment(self) -> None:
        if self.blinded_review:
            confirmation = UnblindingDialog(self)
            if confirmation.exec() != QDialog.DialogCode.Accepted:
                return
            self.unblinding_requested.emit()
            if self.blinded_review:
                self.preview_action.emit(
                    "The page could not leave blinded mode, so no group data were shown."
                )
                return

        assignment = GroupAssignmentDialog(self._subjects, self)
        if assignment.exec() == QDialog.DialogCode.Accepted:
            self.preview_action.emit(
                "Group assignments were previewed but not persisted. The final action "
                "will be validated and recorded in the audit history."
            )

    def _apply_filters(self, *_args) -> None:
        self.proxy.set_filters(
            search=self.search.text(),
            group=self.group_filter.currentText(),
            state=self.state_filter.currentText(),
        )
        self.count_label.setText(f"{self.proxy.rowCount()} subjects shown")

    def _open_index(self, proxy_index: QModelIndex) -> None:
        source_index = self.proxy.mapToSource(proxy_index)
        subject = self.model.subject_at(source_index.row())
        if subject is not None:
            self.subject_open_requested.emit(subject.subject_id)


class SubjectWorkspacePage(QScrollArea):
    back_requested = Signal()
    review_requested = Signal(str)
    preview_action = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.NoFrame)
        self.content = QWidget()
        self.layout = QVBoxLayout(self.content)
        self.layout.setContentsMargins(28, 22, 28, 28)
        self.layout.setSpacing(16)
        self.setWidget(self.content)
        self.current_subject: SubjectViewModel | None = None
        self.blinded_review = False

        top = QHBoxLayout()
        back = secondary_button("← Subjects")
        back.clicked.connect(self.back_requested)
        top.addWidget(back)
        top.addStretch()
        history = secondary_button("Export subject report")
        history.clicked.connect(
            lambda: self.preview_action.emit("Subject report preview only; no file was created.")
        )
        top.addWidget(history)
        self.layout.addLayout(top)

        self.subject_title = QLabel("Subject")
        self.subject_title.setObjectName("pageTitle")
        self.subject_subtitle = QLabel()
        self.subject_subtitle.setObjectName("muted")
        self.layout.addWidget(self.subject_title)
        self.layout.addWidget(self.subject_subtitle)

        self.metadata_card = QFrame()
        self.metadata_card.setObjectName("card")
        self.metadata_layout = QHBoxLayout(self.metadata_card)
        self.metadata_layout.setContentsMargins(18, 14, 18, 14)
        self.layout.addWidget(self.metadata_card)

        title = QLabel("Workflow progress")
        title.setObjectName("sectionTitle")
        self.layout.addWidget(title)
        self.workflow_container = QWidget()
        self.workflow_layout = QVBoxLayout(self.workflow_container)
        self.workflow_layout.setContentsMargins(0, 0, 0, 0)
        self.workflow_layout.setSpacing(12)
        self.layout.addWidget(self.workflow_container)

        self.tabs = QTabWidget()
        self.summary_tab = QLabel()
        self.summary_tab.setWordWrap(True)
        self.summary_tab.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.summary_tab.setMargin(18)
        self.inputs_tab = QLabel(
            "Input assignments, geometry, hashes, and validation issues will appear here."
        )
        self.inputs_tab.setWordWrap(True)
        self.inputs_tab.setMargin(18)
        self.history_list = QListWidget()
        self.tabs.addTab(self.summary_tab, "Summary")
        self.tabs.addTab(self.inputs_tab, "Inputs")
        self.tabs.addTab(self.history_list, "History")
        self.tabs.setMinimumHeight(180)
        self.layout.addWidget(self.tabs)
        self.layout.addStretch()

    def set_subject(self, subject: SubjectViewModel) -> None:
        self.current_subject = subject
        self.subject_title.setText(subject.subject_id)
        self._refresh_subject_subtitle()

        _clear_layout(self.metadata_layout)
        for label, value in subject.metadata:
            block = QVBoxLayout()
            key = QLabel(label)
            key.setObjectName("metadata")
            val = QLabel(value)
            val.setStyleSheet("font-weight: 650;")
            block.addWidget(key)
            block.addWidget(val)
            self.metadata_layout.addLayout(block)
        self.metadata_layout.addStretch()
        self.metadata_layout.addWidget(StatusBadge(subject.overall))

        _clear_layout(self.workflow_layout)
        cards = (
            (
                "T1 Enhancement",
                "Imported → Mask review → Registration review → Quantification → Complete",
                subject.t1_result if subject.t1_result.kind not in {"failed", "unavailable"} else subject.brain_mask,
                "Review T1 artifacts",
            ),
            (
                "T2 Lesion",
                "Imported → Mask generated/imported → Review → Quantification → Complete",
                subject.t2_lesion,
                "Review T2 artifacts",
            ),
        )
        for title, progression, status, action in cards:
            self.workflow_layout.addWidget(
                self._workflow_row(title, progression, status, action)
            )

        self.summary_tab.setText(
            "This workspace keeps every workflow under one subject identity. Use the workflow "
            "cards above to move to the relevant review queue. Scientific actions remain "
            "disabled until their service and state contracts are implemented."
        )
        self.history_list.clear()
        self.history_list.addItems(subject.history or ("No history recorded.",))

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
        self.subject_subtitle.setText(
            f"Group: {group}   ·   Overall state: {subject.overall.label}   ·   Updated {subject.updated}"
        )

    def _workflow_row(
        self,
        title_text: str,
        progression: str,
        status: StatusValue,
        action_text: str,
    ) -> QFrame:
        card = QFrame()
        card.setObjectName("card")
        card.setMinimumHeight(105)
        layout = QHBoxLayout(card)
        layout.setContentsMargins(18, 15, 18, 15)
        text = QVBoxLayout()
        title = QLabel(title_text)
        title.setObjectName("cardTitle")
        progress = QLabel(progression)
        progress.setObjectName("muted")
        progress.setWordWrap(True)
        text.addWidget(title)
        text.addWidget(progress)
        layout.addLayout(text, 1)
        layout.addWidget(StatusBadge(status))
        button = secondary_button(action_text)
        button.clicked.connect(
            lambda _checked=False, subject_id=(self.current_subject.subject_id if self.current_subject else ""): self.review_requested.emit(subject_id)
        )
        layout.addWidget(button)
        return card


class ReviewsPage(QWidget):
    decision_recorded = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.reviews: tuple[ReviewItemViewModel, ...] = ()
        self.filtered: list[ReviewItemViewModel] = []
        self.current_item: ReviewItemViewModel | None = None
        self.current_slice = 1
        self.decisions: dict[str, StatusValue] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 28)
        layout.setSpacing(14)
        heading, _heading_layout = _page_heading(
            "Review and QC",
            "One queue for brain masks, registrations, T2 lesion masks, and results.",
        )
        layout.addWidget(heading)

        splitter = QSplitter(Qt.Horizontal)
        splitter.setChildrenCollapsible(False)
        splitter.addWidget(self._build_categories())
        splitter.addWidget(self._build_queue())
        splitter.addWidget(self._build_viewer())
        splitter.addWidget(self._build_review_panel())
        splitter.setSizes([180, 270, 560, 290])
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
        self.viewer = SyntheticSliceViewer()
        layout.addWidget(self.viewer, 1)
        controls = QHBoxLayout()
        previous = secondary_button("← Item")
        previous.clicked.connect(self._previous_item)
        next_item = secondary_button("Item →")
        next_item.clicked.connect(self._next_item)
        previous_slice = secondary_button("‹ Slice")
        previous_slice.clicked.connect(lambda: self._move_slice(-1))
        next_slice = secondary_button("Slice ›")
        next_slice.clicked.connect(lambda: self._move_slice(1))
        self.slice_label = QLabel("Slice 1 / 1")
        controls.addWidget(previous)
        controls.addWidget(next_item)
        controls.addStretch()
        controls.addWidget(previous_slice)
        controls.addWidget(self.slice_label)
        controls.addWidget(next_slice)
        layout.addLayout(controls)
        overlay = QHBoxLayout()
        visible = QCheckBox("Mask overlay")
        visible.setChecked(True)
        visible.toggled.connect(lambda enabled: self.viewer.set_overlay_opacity(self.opacity.value() / 100 if enabled else 0.0))
        self.opacity = QSlider(Qt.Horizontal)
        self.opacity.setRange(0, 100)
        self.opacity.setValue(55)
        self.opacity.valueChanged.connect(lambda value: self.viewer.set_overlay_opacity(value / 100))
        overlay.addWidget(visible)
        overlay.addWidget(QLabel("Opacity"))
        overlay.addWidget(self.opacity)
        layout.addLayout(overlay)
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
        self.review_qc.setMaximumHeight(76)
        self.review_status_holder = QHBoxLayout()
        self.issue = QComboBox()
        self.issue.addItems(
            [
                "Select issue type…",
                "Missing region",
                "False positive",
                "Inaccurate boundary",
                "Misalignment",
                "Intensity issue",
                "Other",
            ]
        )
        self.notes = QTextEdit()
        self.notes.setPlaceholderText("Optional approval note; rejection requires a reason…")
        self.notes.setMaximumHeight(100)
        approve = QPushButton("Approve")
        approve.setObjectName("approveReviewButton")
        approve.clicked.connect(self._approve)
        reject = QPushButton("Reject")
        reject.setObjectName("rejectReviewButton")
        reject.setProperty("kind", "danger")
        reject.clicked.connect(self._reject)
        correction = secondary_button("Open for correction")
        correction.clicked.connect(
            lambda: self.decision_recorded.emit("Correction launch is a preview interaction only.")
        )

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
        layout.addWidget(approve)
        layout.addWidget(reject)
        layout.addWidget(correction)
        return panel

    def set_study(self, study: StudyViewModel) -> None:
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
        if categories:
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
            item = QListWidgetItem(
                f"{review.subject_id}\n{review.artifact_name}\n{decision.label}"
            )
            self.queue_list.addItem(item)
        self.queue_list.blockSignals(False)
        if self.filtered:
            self.queue_list.setCurrentRow(0)
            self._select_review(0)
        else:
            self.current_item = None
            self.review_subject.setText("No reviews in this queue")

    def _select_review(self, row: int) -> None:
        if not 0 <= row < len(self.filtered):
            return
        self.current_item = self.filtered[row]
        review = self.current_item
        self.current_slice = max(1, review.slice_count // 2)
        self.viewer.set_context(self.current_slice, review.slice_count)
        self.slice_label.setText(f"Slice {self.current_slice} / {review.slice_count}")
        self.review_subject.setText(f"{review.subject_id} · {review.category}")
        self.review_artifact.setText(review.artifact_name)
        self.review_reason.setText(review.reason)
        self.review_qc.setText(review.automatic_qc)
        _clear_layout(self.review_status_holder)
        status = self.decisions.get(review.review_id, review.status)
        self.review_status_holder.addWidget(StatusBadge(status))
        self.review_status_holder.addStretch()
        self.issue.setCurrentIndex(0)
        self.notes.clear()

    def _move_slice(self, delta: int) -> None:
        if self.current_item is None:
            return
        self.current_slice = max(
            1,
            min(self.current_slice + delta, self.current_item.slice_count),
        )
        self.viewer.set_context(self.current_slice, self.current_item.slice_count)
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
        if self.current_item is None:
            return
        self.decisions[self.current_item.review_id] = StatusValue(
            "Human approved · preview",
            "approved",
        )
        self._refresh_decision(
            f"Preview: approved {self.current_item.artifact_name} for {self.current_item.subject_id}."
        )

    def _reject(self) -> None:
        if self.current_item is None:
            return
        if self.issue.currentIndex() == 0 or not self.notes.toPlainText().strip():
            self.decision_recorded.emit(
                "Choose an issue type and enter reviewer notes before rejecting."
            )
            return
        self.decisions[self.current_item.review_id] = StatusValue(
            "Rejected · preview",
            "failed",
        )
        self._refresh_decision(
            f"Preview: rejected {self.current_item.artifact_name} for {self.current_item.subject_id}."
        )

    def _refresh_decision(self, message: str) -> None:
        row = self.queue_list.currentRow()
        current_category = self.category_list.currentItem()
        category = current_category.data(Qt.UserRole) if current_category else "All reviews"
        self._populate_queue(category)
        self.queue_list.setCurrentRow(min(row, self.queue_list.count() - 1))
        self.decision_recorded.emit(message + " Nothing was saved.")


class ResultsPage(QWidget):
    preview_action = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.blinded_review = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 28)
        layout.setSpacing(16)
        heading, heading_layout = _page_heading(
            "Results and export",
            "Subject-level measurements with approval, method, and missingness preserved.",
        )
        export = QPushButton("Export results…")
        export.setObjectName("exportResultsButton")
        export.clicked.connect(lambda: self._preview_export("Approved results CSV"))
        heading_layout.addWidget(export)
        layout.addWidget(heading)

        warning = QLabel(
            "Provisional measurements are shown for design review. Approved-only export excludes them by default."
        )
        warning.setObjectName("previewBanner")
        warning.setWordWrap(True)
        layout.addWidget(warning)

        self.blinding_note = QLabel()
        self.blinding_note.setObjectName("infoBanner")
        self.blinding_note.setWordWrap(True)
        layout.addWidget(self.blinding_note)

        controls = QHBoxLayout()
        self.approved_only = QCheckBox("Show subjects with at least one approved result")
        controls.addWidget(self.approved_only)
        controls.addStretch()
        provenance = secondary_button("View provenance")
        provenance.clicked.connect(
            lambda: self.preview_action.emit(
                "Provenance detail is a connected design-preview action; no record was changed."
            )
        )
        controls.addWidget(provenance)
        layout.addLayout(controls)

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
        self.table.setMinimumHeight(220)
        layout.addWidget(self.table)
        self.approved_only.toggled.connect(self.proxy.set_approved_only)

        lower = QHBoxLayout()
        plot_card = QFrame()
        plot_card.setObjectName("card")
        plot_layout = QVBoxLayout(plot_card)
        self.plot_title = QLabel("T2 lesion volume by group")
        self.plot_title.setObjectName("cardTitle")
        plot_caption = QLabel("Descriptive preview only · dots are synthetic")
        plot_caption.setObjectName("metadata")
        plot_layout.addWidget(self.plot_title)
        plot_layout.addWidget(plot_caption)
        self.cohort_plot = CohortPlot()
        plot_layout.addWidget(self.cohort_plot, 1)
        lower.addWidget(plot_card, 2)

        export_card = QFrame()
        export_card.setObjectName("card")
        export_layout = QVBoxLayout(export_card)
        export_title = QLabel("Export safeguards")
        export_title.setObjectName("cardTitle")
        export_layout.addWidget(export_title)
        for text in (
            "Approved results CSV",
            "QC report · HTML/PDF",
            "Reproducibility bundle",
        ):
            button = secondary_button(text)
            button.clicked.connect(
                lambda _checked=False, name=text: self._preview_export(name)
            )
            export_layout.addWidget(button)
        export_layout.addStretch()
        safeguard = QLabel("Missing values are never converted to zero.")
        safeguard.setObjectName("infoBanner")
        safeguard.setWordWrap(True)
        export_layout.addWidget(safeguard)
        lower.addWidget(export_card, 1)
        layout.addLayout(lower, 1)
        self.set_blinded_review(False)

    def set_study(self, study: StudyViewModel) -> None:
        self.model.set_results(study.results)

    def set_blinded_review(self, blinded: bool) -> None:
        self.blinded_review = blinded
        self.table.setColumnHidden(1, blinded)
        self.blinding_note.setVisible(blinded)
        self.blinding_note.setText(
            "BLINDED REVIEW — Experimental groups are hidden. Approved exports can omit "
            "groups; grouped summaries require an explicit audited unblinding step."
        )
        self.plot_title.setText(
            "T2 lesion volume · blinded cohort"
            if blinded
            else "T2 lesion volume by group"
        )
        self.cohort_plot.set_blinded(blinded)

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

        note = QLabel("Preview controls are not persisted yet.")
        note.setObjectName("previewBanner")
        layout.addWidget(note)

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

        standard = QGroupBox("Standard settings")
        form = QFormLayout(standard)
        reviewer = QLineEdit("Paul-Andréas")
        editor = QLineEdit("/Applications/ITK-SNAP.app")
        export_dir = QLineEdit("~/Documents/LYS exports")
        backups = QCheckBox("Create automatic project backups")
        backups.setChecked(True)
        form.addRow("Reviewer display name", reviewer)
        form.addRow("External editor", editor)
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
