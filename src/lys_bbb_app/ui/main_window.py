"""Connected main shell for MRI studies."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QElapsedTimer, QSize, QTimer, Qt
from PySide6.QtGui import QAction, QCloseEvent
from PySide6.QtWidgets import (
    QButtonGroup,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from lys_bbb_app.application.study_presenter import present_study
from lys_bbb_app.domain.errors import StudyStateError
from lys_bbb_app.domain.scan_import import ScanImportAssignment, ScanRole
from lys_bbb_app.domain.study import StudySnapshot
from lys_bbb_app.domain.view_models import StatusValue, StudyViewModel
from lys_bbb_app.features import AppFeatures, FULL_FEATURES
from lys_bbb_app.platform_paths import (
    default_t1_brain_mask_release_path,
    default_t2_model_release_path,
    default_t2_model_release_suggestion,
    t2_model_choice,
)
from lys_bbb_app.services.recent_studies_service import RecentStudiesService
from lys_bbb_app.services.study_service import StudyService
from lys_bbb_app.ui.background_jobs import BackgroundJobRegistry
from lys_bbb_app.ui.fluent import (
    FluentIcon,
    IndeterminateProgressRing,
    NotificationKind,
    show_notification,
)
from lys_bbb_app.ui.main_window_connections import connect_main_window_signals
from lys_bbb_app.ui.dialogs import (
    AddSubjectDialog,
    AuditHistoryDialog,
    CreateStudyDialog,
    GroupAssignmentDialog,
    RenameSubjectDialog,
    RestoreSubjectDialog,
    UnblindingDialog,
)
from lys_bbb_app.ui.mri_action_dialogs import (
    BulkFlipDialog,
    MRIInputSelectionDialog,
)
from lys_bbb_app.ui.pages import (
    OverviewPage,
    ResultsPage,
    SettingsPage,
    StudyLauncherPage,
    SubjectsPage,
)
from lys_bbb_app.ui.reviews import ReviewsPage
from lys_bbb_app.ui.scan_import_dialog import ScanImportReviewDialog
from lys_bbb_app.ui.subject_workspace import SubjectWorkspacePage
from lys_bbb_app.ui.t2_manual_edit_dialog import (
    T1BrainMaskManualEditDialog,
    T2ManualEditDialog,
)
from lys_bbb_app.ui.widgets import StatusBadge, secondary_button
from lys_bbb_app.ui.workers import (
    AtlasMappingThread,
    InputValidationThread,
    ScanImportThread,
    T1BrainMaskThread,
    T1EnhancementThread,
    T1RegistrationThread,
    T2InferenceThread,
)

class MainWindow(QMainWindow):
    """Application shell for canonical persistent studies."""

    def __init__(
        self,
        study_service: StudyService | None = None,
        recent_studies: RecentStudiesService | None = None,
        *,
        features: AppFeatures = FULL_FEATURES,
    ) -> None:
        super().__init__()
        self.features = features
        self.study_service = study_service or StudyService(
            ants_backend=self.features.ants_backend
        )
        self.recent_studies = recent_studies or RecentStudiesService()
        self.current_study: StudyViewModel | None = None
        self.blinded_review = False
        self.nav_buttons: dict[str, QPushButton] = {}
        self.page_indices: dict[str, int] = {}
        self._background_jobs = BackgroundJobRegistry(
            self._background_job_count_changed
        )
        self._t2_target_subject_ids: tuple[str, ...] | None = None
        self._t1_target_subject_ids: tuple[str, ...] | None = None
        self._t1_brain_mask_elapsed = QElapsedTimer()
        self._t1_brain_mask_heartbeat = QTimer(self)
        self._t1_brain_mask_heartbeat.setInterval(5000)
        self._t1_brain_mask_heartbeat.timeout.connect(
            self._show_t1_brain_mask_heartbeat
        )
        self._t1_registration_target_subject_ids: tuple[str, ...] | None = None
        self._t1_enhancement_target_subject_ids: tuple[str, ...] | None = None
        self._atlas_mapping_subject_id: str | None = None
        self._atlas_mapping_action: str | None = None
        self._validation_subject_id: str | None = None
        self._validation_return_page = "workspace"
        self._scan_operation_name = "MRI import"

        window_title = "LYS IRM"
        if self.features.window_title_suffix:
            window_title = f"{window_title} — {self.features.window_title_suffix}"
        self.setWindowTitle(window_title)
        self.resize(1440, 900)
        self.setMinimumSize(1180, 760)
        self._build_actions()
        self._build_ui()
        self.statusBar().showMessage(
            self.features.runtime_notice or "Choose or create a study."
        )

    def _build_actions(self) -> None:
        file_menu = self.menuBar().addMenu("&File")
        create_action = QAction("&Create study…", self)
        create_action.setShortcut("Ctrl+N")
        create_action.triggered.connect(self.create_project)
        file_menu.addAction(create_action)

        open_action = QAction("&Open study…", self)
        open_action.setShortcut("Ctrl+O")
        open_action.triggered.connect(self.open_project)
        file_menu.addAction(open_action)

        self.close_study_action = QAction("&Close study", self)
        self.close_study_action.setEnabled(False)
        self.close_study_action.triggered.connect(self.close_study)
        file_menu.addAction(self.close_study_action)
        file_menu.addSeparator()
        quit_action = QAction("&Quit", self)
        quit_action.setShortcut("Ctrl+Q")
        quit_action.triggered.connect(self.close)
        file_menu.addAction(quit_action)

    def _build_ui(self) -> None:
        self.root_stack = QStackedWidget()
        self.root_stack.setObjectName("rootStack")
        self.launcher_page = StudyLauncherPage()
        self.launcher_page.create_requested.connect(self.create_project)
        self.launcher_page.open_requested.connect(self.open_project)
        self.launcher_page.recent_open_requested.connect(self.open_project_path)
        self.launcher_page.set_recent_studies(self.recent_studies.list())
        self.root_stack.addWidget(self.launcher_page)
        self.root_stack.addWidget(self._build_shell())
        self.setCentralWidget(self.root_stack)

    def _build_shell(self) -> QWidget:
        root = QWidget()
        root.setObjectName("appRoot")
        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        root_layout.addWidget(self._build_header())
        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        body.addWidget(self._build_sidebar())

        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)
        self.study_banner = QLabel()
        self.study_banner.setObjectName("infoBanner")
        self.study_banner.setWordWrap(True)
        self.study_banner.setContentsMargins(20, 4, 20, 4)
        content_layout.addWidget(self.study_banner)

        self.content_stack = QStackedWidget()
        self.overview_page = OverviewPage()
        self.subjects_page = SubjectsPage()
        self.reviews_page = ReviewsPage(features=self.features)
        self.results_page = ResultsPage()
        self.settings_page = SettingsPage()
        self.workspace_page = SubjectWorkspacePage(features=self.features)
        pages = (
            ("overview", self.overview_page),
            ("subjects", self.subjects_page),
            ("reviews", self.reviews_page),
            ("results", self.results_page),
            ("settings", self.settings_page),
            ("workspace", self.workspace_page),
        )
        for key, page in pages:
            self.page_indices[key] = self.content_stack.addWidget(page)
        content_layout.addWidget(self.content_stack, 1)
        body.addWidget(content, 1)
        root_layout.addLayout(body, 1)

        connect_main_window_signals(self)
        return root

    def _build_header(self) -> QFrame:
        header = QFrame()
        header.setObjectName("topBar")
        header.setFixedHeight(72)
        layout = QHBoxLayout(header)
        layout.setContentsMargins(22, 12, 22, 12)
        titles = QVBoxLayout()
        titles.setSpacing(1)
        study_caption = QLabel("CURRENT STUDY")
        study_caption.setObjectName("metadata")
        self.study_name_label = QLabel("No study open")
        self.study_name_label.setObjectName("studyName")
        titles.addWidget(study_caption)
        titles.addWidget(self.study_name_label)
        layout.addLayout(titles)
        change = secondary_button("Change study")
        change.clicked.connect(self.show_launcher)
        layout.addWidget(change)
        layout.addStretch()
        self.blinding_badge = StatusBadge(StatusValue("Blinded review", "processing"))
        self.blinding_badge.setVisible(False)
        layout.addWidget(self.blinding_badge)
        layout.addSpacing(8)
        self.jobs_label = QLabel("0 jobs running")
        self.jobs_label.setObjectName("muted")
        self.jobs_label.hide()
        self.job_progress_ring = IndeterminateProgressRing(header, start=False)
        self.job_progress_ring.setFixedSize(22, 22)
        self.job_progress_ring.setStrokeWidth(3)
        self.job_progress_ring.hide()
        layout.addWidget(self.job_progress_ring)
        layout.addWidget(self.jobs_label)
        return header

    def _build_sidebar(self) -> QFrame:
        sidebar = QFrame()
        sidebar.setObjectName("sideBar")
        sidebar.setFixedWidth(220)
        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(14, 18, 14, 18)
        layout.setSpacing(5)
        brand = QHBoxLayout()
        brand.setSpacing(9)
        brand_mark = QFrame()
        brand_mark.setObjectName("brandMark")
        brand_mark.setFixedSize(34, 30)
        brand_mark_layout = QVBoxLayout(brand_mark)
        brand_mark_layout.setContentsMargins(0, 0, 0, 0)
        brand_mark_text = QLabel("LYS")
        brand_mark_text.setObjectName("brandMarkText")
        brand_mark_text.setAlignment(Qt.AlignmentFlag.AlignCenter)
        brand_mark_layout.addWidget(brand_mark_text)
        brand.addWidget(brand_mark)
        brand_text = QVBoxLayout()
        brand_text.setSpacing(0)
        wordmark = QLabel("LYS IRM")
        wordmark.setObjectName("appWordmark")
        brand_caption = QLabel("SCIENTIFIC MRI")
        brand_caption.setObjectName("brandCaption")
        brand_text.addWidget(wordmark)
        brand_text.addWidget(brand_caption)
        brand.addLayout(brand_text)
        layout.addLayout(brand)
        layout.addSpacing(18)

        nav_caption = QLabel("WORKSPACE")
        nav_caption.setObjectName("navCaption")
        layout.addWidget(nav_caption)
        layout.addSpacing(3)

        self.nav_group = QButtonGroup(self)
        self.nav_group.setExclusive(True)
        for key, label, icon in (
            ("overview", "Overview", FluentIcon.HOME),
            ("subjects", "Subjects", FluentIcon.PEOPLE),
            ("reviews", "Reviews", FluentIcon.ACCEPT),
            ("results", "Results && exports", FluentIcon.DOCUMENT),
            ("settings", "Settings", FluentIcon.SETTING),
        ):
            button = QPushButton(label)
            button.setIcon(icon.icon(color="#d2dee7"))
            button.setIconSize(QSize(17, 17))
            button.setProperty("kind", "nav")
            button.setCheckable(True)
            button.setObjectName(f"nav_{key}")
            button.clicked.connect(
                lambda _checked=False, page_key=key: self.show_page(page_key)
            )
            self.nav_group.addButton(button)
            self.nav_buttons[key] = button
            layout.addWidget(button)
        layout.addStretch()
        self.sidebar_foot = QLabel("T1 · T2")
        self.sidebar_foot.setObjectName("sidebarFoot")
        self.sidebar_foot.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.sidebar_foot)
        return sidebar

    def create_project(self) -> None:
        dialog = CreateStudyDialog(self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        mri_source = dialog.mri_source_path()
        try:
            study = self.study_service.create_study(
                dialog.request(actor=self._reviewer_identity())
            )
        except (StudyStateError, OSError) as exc:
            self._show_error("The study could not be created.", exc)
            return
        self._record_recent(study)
        self._set_study(present_study(study))
        if mri_source is not None:
            self._discover_and_review_mri(mri_source)
        else:
            self._notify(
                "Study created",
                "Choose Import MRI folder to discover subjects and scans.",
                kind="success",
            )

    def open_project(self) -> None:
        selected = QFileDialog.getExistingDirectory(
            self,
            "Open LYS IRM study directory",
            str(Path.home()),
        )
        if selected:
            self.open_project_path(selected)

    def open_project_path(self, project_path: Path | str) -> bool:
        path = Path(project_path).expanduser()
        try:
            study = self.study_service.open_study(path)
        except (StudyStateError, OSError) as exc:
            self._show_error("The study could not be opened.", exc)
            return False
        self._record_recent(study)
        self._set_study(present_study(study))
        self._notify(
            "Study opened",
            f"Reopened with {len(study.subjects)} persisted subject(s).",
            kind="success",
        )
        return True

    def _set_study(self, study: StudyViewModel, *, page_key: str = "overview") -> None:
        self.current_study = study
        self.study_name_label.setText(study.name)
        self.sidebar_foot.setText(
            "T1 · T2"
            if study.analysis_scope.includes_t1
            and study.analysis_scope.includes_t2
            else "T1 ENHANCEMENT"
            if study.analysis_scope.includes_t1
            else "T2 LESION"
        )
        banner_messages: list[str] = []
        if self.features.runtime_notice:
            banner_messages.append(self.features.runtime_notice)
        if banner_messages:
            self.study_banner.setText("\n\n".join(banner_messages))
            self.study_banner.show()
        else:
            self.study_banner.clear()
            self.study_banner.hide()
        self.overview_page.set_study(study)
        self.subjects_page.set_study(study)
        self.reviews_page.set_study(study)
        self.results_page.set_study(study)
        self.settings_page.set_study_state(
            blinded=study.blinded_review,
        )
        self.settings_page.set_input_folders(
            mri_path=study.mri_input_folder,
            enabled=True,
        )
        self.settings_page.set_t2_model_choice(study.active_t2_release_id)
        self.set_blinded_review(study.blinded_review)
        self.close_study_action.setEnabled(True)
        self.root_stack.setCurrentIndex(1)
        self.show_page(page_key)

    def show_page(self, page_key: str) -> None:
        if page_key not in self.page_indices:
            return
        self.content_stack.setCurrentIndex(self.page_indices[page_key])
        if page_key in self.nav_buttons:
            self.nav_buttons[page_key].setChecked(True)
        elif page_key == "workspace":
            self.nav_buttons["subjects"].setChecked(True)

    def open_subject(self, subject_id: str) -> None:
        if self.current_study is None:
            return
        subject = self.current_study.subject(subject_id)
        if subject is None:
            return
        self.workspace_page.set_subject(subject)
        if (
            self.current_study.analysis_scope.includes_t1
            and self.current_study.analysis_scope.includes_t2
        ):
            try:
                registration_state = self.study_service.atlas_mapping.state(subject_id)
            except StudyStateError:
                registration_state = None
            self.workspace_page.set_atlas_mapping_state(registration_state)
        self.show_page("workspace")
        self.statusBar().showMessage(f"Opened subject {subject.label}.", 4000)

    def open_review_subject(self, subject_id: str) -> None:
        workflow_key = (
            self.reviews_page.current_item.workflow_key
            if self.reviews_page.current_item is not None
            else ""
        )
        self.open_subject(subject_id)
        if workflow_key in {"t1_registration", "t1_to_t2_registration"}:
            self.workspace_page.tabs.setCurrentWidget(
                self.workspace_page.t1_analysis_panel
            )
        elif workflow_key == "t1_brain_mask":
            self.workspace_page.tabs.setCurrentWidget(
                self.workspace_page.t1_brain_mask_panel
            )
        elif workflow_key == "t2_lesion":
            self.workspace_page.tabs.setCurrentWidget(self.workspace_page.t2_panel)
        elif (
            self.features.atlas_mapping
            and workflow_key.startswith("atlas_")
            and self.workspace_page.atlas_mapping_panel is not None
        ):
            self.workspace_page.tabs.setCurrentWidget(
                self.workspace_page.atlas_mapping_panel
            )

    def add_subject(self) -> None:
        if self.current_study is None:
            return
        if self.study_service.current_study is None:
            self._show_error(
                "The subject could not be added.",
                StudyStateError("Open a study before adding subjects."),
            )
            return
        dialog = AddSubjectDialog(
            blinded=self.current_study.blinded_review,
            analysis_scope=self.current_study.analysis_scope,
            group_definitions=self.current_study.group_definitions,
            parent=self,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            snapshot = self.study_service.add_subject(
                dialog.request(actor=self._reviewer_identity())
            )
        except StudyStateError as exc:
            self._show_error("The subject could not be added.", exc)
            return
        self._set_study(present_study(snapshot), page_key="subjects")
        self.statusBar().showMessage(
            f"Subject {dialog.subject_code.text().strip()} was saved.",
            7000,
        )

    def remove_subject(self, subject_id: str) -> None:
        if self.current_study is None:
            return
        subject = self.current_study.subject(subject_id)
        if subject is None:
            return
        confirmation = QMessageBox.question(
            self,
            "Remove subject from study?",
            f"Remove {subject.label} from active study worklists?\n\n"
            "Original Bruker/NIfTI source data will not be changed. Converted NIfTI "
            "inputs and provenance remain retained inside the study, and the subject "
            "can be restored from Removed subjects.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if confirmation != QMessageBox.StandardButton.Yes:
            return
        try:
            snapshot = self.study_service.remove_subject(
                subject_id,
                actor=self._reviewer_identity(),
            )
        except StudyStateError as exc:
            self._show_error("The subject could not be removed.", exc)
            return
        self._set_study(present_study(snapshot), page_key="subjects")
        self.statusBar().showMessage(
            f"{subject.label} was removed from active worklists. Its data was retained.",
            9000,
        )

    def restore_subject(self) -> None:
        if self.current_study is None or not self.current_study.archived_subjects:
            return
        dialog = RestoreSubjectDialog(self.current_study.archived_subjects, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        subject_id = dialog.subject_id()
        subject = next(
            (
                item
                for item in self.current_study.archived_subjects
                if item.subject_id == subject_id
            ),
            None,
        )
        try:
            snapshot = self.study_service.restore_subject(
                subject_id,
                actor=self._reviewer_identity(),
            )
        except StudyStateError as exc:
            self._show_error("The subject could not be restored.", exc)
            return
        self._set_study(present_study(snapshot), page_key="subjects")
        self.statusBar().showMessage(
            f"{subject.label if subject is not None else 'Subject'} was restored.",
            8000,
        )

    def rename_subject(self, subject_id: str) -> None:
        if self.current_study is None:
            return
        subject = self.current_study.subject(subject_id)
        if subject is None:
            return
        dialog = RenameSubjectDialog(subject.label, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            snapshot = self.study_service.rename_subject(
                subject_id,
                dialog.new_name(),
                actor=self._reviewer_identity(),
            )
        except StudyStateError as exc:
            self._show_error("The subject could not be renamed.", exc)
            return
        self._set_study(present_study(snapshot), page_key="subjects")
        self.open_subject(subject_id)
        self.statusBar().showMessage(
            f"Subject renamed to {dialog.new_name()}. Existing files were not moved.",
            9000,
        )

    def update_subject_longitudinal_identifiers(
        self,
        subject_id: str,
        animal_identifier: str,
        time_identifier: str,
        *,
        return_page: str = "subjects",
    ) -> None:
        """Persist user-editable animal/time labels used for longitudinal grouping."""

        try:
            snapshot = self.study_service.update_subject_longitudinal_identifiers(
                subject_id,
                animal_identifier,
                time_identifier,
                actor=self._reviewer_identity(),
            )
        except StudyStateError as exc:
            self._show_error("The subject identifiers could not be saved.", exc)
            if self.current_study is not None:
                self._set_study(self.current_study, page_key=return_page)
                if return_page == "workspace":
                    self.open_subject(subject_id)
            return
        self._set_study(present_study(snapshot), page_key=return_page)
        if return_page == "workspace":
            self.open_subject(subject_id)
        self.statusBar().showMessage("Animal and time identifiers were saved.", 6000)

    def open_subject_mri_in_itksnap(self, subject_id: str) -> None:
        if self.current_study is None:
            return
        try:
            inputs = self.study_service.converted_mri_inputs(subject_id)
        except StudyStateError as exc:
            self._show_error("The subject MRI could not be selected.", exc)
            return
        if not inputs:
            self._show_error(
                "No MRI can be opened for this subject.",
                StudyStateError(
                    "Import and successfully convert a T1 or T2 MRI input first."
                ),
            )
            return
        scan_input_id = inputs[0].id
        if len(inputs) > 1:
            dialog = MRIInputSelectionDialog(inputs, self)
            if dialog.exec() != QDialog.DialogCode.Accepted:
                return
            scan_input_id = dialog.scan_input_id()
        self.open_scan_input_in_itksnap(subject_id, scan_input_id)

    def open_scan_input_in_itksnap(
        self,
        subject_id: str,
        scan_input_id: str,
    ) -> None:
        if self.current_study is None:
            return
        configured_viewer = self.settings_page.external_editor.text().strip() or None
        try:
            launch = self.study_service.open_mri_in_itksnap(
                subject_id,
                scan_input_id,
                actor=self._reviewer_identity(),
                viewer_path=configured_viewer,
            )
        except StudyStateError as exc:
            self._show_error("The MRI could not be opened in ITK-SNAP.", exc)
            return
        self.statusBar().showMessage(
            f"Opened {launch.image_path.name} in ITK-SNAP.",
            7000,
        )

    def validate_subject_inputs(
        self,
        subject_id: str,
        *,
        return_page: str = "workspace",
    ) -> None:
        if self.current_study is None:
            return
        if self.study_service.current_study is None:
            self._show_status_message("Open a study before validating MRI inputs.")
            return
        if self._background_job_running():
            self._show_status_message("Another MRI background job is already running.")
            return
        thread = InputValidationThread(
            self.study_service,
            subject_id,
            actor=self._reviewer_identity(),
        )
        thread.validation_completed.connect(self._input_validation_completed)
        thread.validation_failed.connect(self._input_validation_failed)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._clear_input_validation_thread)
        self._background_jobs.register("input_validation", thread)
        self._validation_subject_id = subject_id
        self._validation_return_page = return_page
        self._set_job_status("Input validation running")
        self.statusBar().showMessage(
            "Validating managed NIfTI geometry and provenance…"
        )
        thread.start()

    def _input_validation_completed(self, snapshot: StudySnapshot) -> None:
        subject_id = self._validation_subject_id
        if subject_id is None:
            return
        return_page = self._validation_return_page
        self._set_study(present_study(snapshot), page_key="subjects")
        subject = self.current_study.subject(subject_id) if self.current_study else None
        validation_failed = subject is not None and (
            subject.t1_data.kind == "failed" or subject.t2_data.kind == "failed"
        )
        if return_page == "workspace" or validation_failed:
            self.open_subject(subject_id)
            self.workspace_page.tabs.setCurrentWidget(
                self.workspace_page.inputs_panel
            )
        if validation_failed:
            self._notify(
                "Validation needs attention",
                "Review the affected scan card before continuing.",
                kind="warning",
            )
        else:
            self._notify(
                "Inputs validated",
                "Ready workflows can now advance to their artifact step.",
                kind="success",
            )

    def _input_validation_failed(self, error: str) -> None:
        self._set_job_status()
        self._show_error(
            "The MRI inputs could not be validated.",
            StudyStateError(error),
        )

    def _clear_input_validation_thread(self) -> None:
        self._background_jobs.clear("input_validation")
        self._validation_subject_id = None
        self._validation_return_page = "workspace"
        self._set_job_status()

    def select_t1_brain_mask_release(self) -> bool:
        if self.current_study is None or self.study_service.current_study is None:
            self._show_status_message(
                "Open a study before selecting a T1 brain-mask release."
            )
            return False
        suggested = default_t1_brain_mask_release_path()
        selected = QFileDialog.getExistingDirectory(
            self,
            "Select frozen RS2-Net/M-seam release folder",
            str(suggested if suggested.is_dir() else Path.home()),
        )
        if not selected:
            return False
        return self._register_t1_brain_mask_release(Path(selected))

    def _register_t1_brain_mask_release(self, release_root: Path) -> bool:
        try:
            snapshot = self.study_service.register_t1_brain_mask_release(
                release_root,
                actor=self._reviewer_identity(),
            )
        except StudyStateError as exc:
            self._show_error(
                "The T1 brain-mask release could not be registered.",
                exc,
            )
            return False
        self._set_study(present_study(snapshot), page_key="subjects")
        self.statusBar().showMessage(
            "The RS2-Net source, weights, and M-seam method passed validation.",
            10000,
        )
        return True

    def run_t1_brain_mask_for_subject(self, subject_id: str) -> None:
        if self.current_study is None or self.study_service.current_study is None:
            self._show_status_message(
                "Open a study before generating a T1 brain mask."
            )
            return
        if self._background_job_running():
            self._show_status_message("Another MRI background job is already running.")
            return
        if self.current_study.active_t1_brain_mask_release_label is None:
            default_release = default_t1_brain_mask_release_path()
            if not default_release.is_dir() or not self._register_t1_brain_mask_release(
                default_release
            ):
                return
        try:
            readiness = self.study_service.t1_brain_mask_readiness((subject_id,))
        except StudyStateError as exc:
            self._show_error(
                "T1 brain-mask readiness could not be calculated.",
                exc,
            )
            return
        if not readiness.eligible_subject_ids:
            self._show_error(
                "This subject is not ready for T1 brain-mask generation.",
                StudyStateError(
                    readiness.blocked_reasons[0][1]
                    if readiness.blocked_reasons
                    else "Import and validate the native pre-Gd T1 first."
                ),
            )
            return
        confirmation = QMessageBox.question(
            self,
            "Generate T1 brain-mask draft?",
            "Run the low-impact RS2-Net/M-seam draft method without test-time "
            "augmentation?\n\nThe measured development case took about 83 seconds "
            "on Apple Silicon. This provisional method is designed to keep the "
            "desktop more usable, and its generated mask will remain a draft until "
            "explicitly reviewed and approved.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if confirmation != QMessageBox.StandardButton.Yes:
            return
        thread = T1BrainMaskThread(
            self.study_service,
            actor=self._reviewer_identity(),
            subject_ids=readiness.eligible_subject_ids,
            device_name="auto",
        )
        thread.progress_changed.connect(self._show_t1_brain_mask_progress)
        thread.generation_completed.connect(self._t1_brain_mask_completed)
        thread.generation_failed.connect(self._t1_brain_mask_failed)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._clear_t1_brain_mask_thread)
        self._background_jobs.register("t1_brain_mask", thread)
        self._t1_target_subject_ids = readiness.eligible_subject_ids
        self._t1_brain_mask_elapsed.start()
        self._t1_brain_mask_heartbeat.start()
        self._set_job_status("T1 brain-mask generation running")
        self.statusBar().showMessage("Starting T1 brain-mask generation…")
        thread.start()

    def _show_t1_brain_mask_progress(
        self,
        current: int,
        total: int,
        message: str,
    ) -> None:
        self._set_job_status(f"T1 brain mask {current}/{total}")
        self.statusBar().showMessage(message)

    def _t1_brain_mask_completed(self, snapshot: StudySnapshot) -> None:
        targets = self._t1_target_subject_ids or ()
        self._set_study(present_study(snapshot), page_key="reviews")
        if targets:
            self.reviews_page.focus_subject(targets[0])
        self._notify(
            "T1 draft ready",
            "The brain-mask draft was created. Human review is required.",
            kind="warning",
        )

    def _t1_brain_mask_failed(self, error: str) -> None:
        snapshot = self.study_service.current_study
        if snapshot is not None:
            self._set_study(present_study(snapshot), page_key="subjects")
        self._show_error(
            "T1 brain-mask generation did not complete.",
            StudyStateError(error),
        )

    def _show_t1_brain_mask_heartbeat(self) -> None:
        if (
            not self._background_jobs.is_running("t1_brain_mask")
            or not self._t1_brain_mask_elapsed.isValid()
        ):
            return
        elapsed_seconds = self._t1_brain_mask_elapsed.elapsed() // 1000
        minutes, seconds = divmod(elapsed_seconds, 60)
        elapsed = f"{minutes}:{seconds:02d}"
        self._set_job_status(f"T1 brain mask running · {elapsed}")
        self.statusBar().showMessage(
            f"Low-impact no-TTA draft generation is running · elapsed {elapsed}"
        )

    def _clear_t1_brain_mask_thread(self) -> None:
        self._t1_brain_mask_heartbeat.stop()
        self._t1_brain_mask_elapsed.invalidate()
        self._background_jobs.clear("t1_brain_mask")
        self._t1_target_subject_ids = None
        self._set_job_status()

    def run_t1_registration_for_subject(self, subject_id: str) -> None:
        if self.current_study is None or self.study_service.current_study is None:
            self._show_status_message(
                "Open a study before running T1 registration."
            )
            return
        if self._background_job_running():
            self._show_status_message("Another MRI background job is already running.")
            return
        snapshot = self.study_service.current_study
        if snapshot.active_t1_registration_method is None:
            try:
                self.study_service.register_t1_registration_method(
                    actor=self._reviewer_identity()
                )
            except StudyStateError as exc:
                self._show_error(
                    "The frozen T1 registration method could not be registered.",
                    exc,
                )
                return
        try:
            readiness = self.study_service.t1_registration_readiness((subject_id,))
        except StudyStateError as exc:
            self._show_error("T1 registration readiness could not be calculated.", exc)
            return
        if not readiness.eligible_subject_ids:
            self._show_error(
                "This subject is not ready for T1 registration.",
                StudyStateError(
                    readiness.blocked_reasons[0][1]
                    if readiness.blocked_reasons
                    else "Validate the pre/post pair and approve the brain mask first."
                ),
            )
            return
        confirmation = QMessageBox.question(
            self,
            "Run T1 registration?",
            "Register the post-Gd T1 to native pre-Gd space using the frozen rigid "
            "method?\n\nThe registered image and transform will remain awaiting "
            "human review before enhancement can be calculated.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if confirmation != QMessageBox.StandardButton.Yes:
            return
        thread = T1RegistrationThread(
            self.study_service,
            actor=self._reviewer_identity(),
            subject_ids=readiness.eligible_subject_ids,
        )
        thread.progress_changed.connect(self._show_t1_registration_progress)
        thread.registration_completed.connect(self._t1_registration_completed)
        thread.registration_failed.connect(self._t1_registration_failed)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._clear_t1_registration_thread)
        self._background_jobs.register("t1_registration", thread)
        self._t1_registration_target_subject_ids = readiness.eligible_subject_ids
        self._set_job_status("T1 registration running")
        self.statusBar().showMessage("Starting post-to-pre T1 registration…")
        thread.start()

    def _show_t1_registration_progress(
        self,
        current: int,
        total: int,
        message: str,
    ) -> None:
        self._set_job_status(f"T1 registration {current}/{total}")
        self.statusBar().showMessage(message)

    def _t1_registration_completed(self, snapshot: StudySnapshot) -> None:
        targets = self._t1_registration_target_subject_ids or ()
        self._set_study(present_study(snapshot), page_key="reviews")
        if targets:
            self.reviews_page.focus_subject(targets[0])
        self._notify(
            "T1 registration ready",
            "Inspect and approve the exact registration QC before calculating a result.",
            kind="warning",
        )

    def _t1_registration_failed(self, error: str) -> None:
        snapshot = self.study_service.current_study
        if snapshot is not None:
            self._set_study(present_study(snapshot), page_key="subjects")
        self._show_error("T1 registration did not complete.", StudyStateError(error))

    def _clear_t1_registration_thread(self) -> None:
        self._background_jobs.clear("t1_registration")
        self._t1_registration_target_subject_ids = None
        self._set_job_status()

    def approve_t1_registration(
        self,
        subject_id: str,
        artifact_id: str,
        *,
        return_page: str = "workspace",
    ) -> None:
        if self.current_study is None or self.study_service.current_study is None:
            self._show_status_message(
                "Open a study before approving a T1 registration."
            )
            return
        confirmation = QMessageBox.question(
            self,
            "Approve T1 registration?",
            "Approve this exact registered post-Gd image, transform, and QC bundle?"
            "\n\nAny changed input or mask will make this approval and dependent "
            "results outdated.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if confirmation != QMessageBox.StandardButton.Yes:
            return
        try:
            snapshot = self.study_service.approve_t1_registration(
                subject_id,
                artifact_id,
                reviewer=self._reviewer_identity(),
            )
        except StudyStateError as exc:
            self._show_error("The T1 registration could not be approved.", exc)
            return
        self._refresh_after_review(
            snapshot,
            subject_id,
            return_page=return_page,
            panel=self.workspace_page.t1_analysis_panel,
        )
        self.statusBar().showMessage(
            "T1 registration approved. Provisional enhancement can now be calculated.",
            12000,
        )

    def _refresh_after_review(
        self,
        snapshot: StudySnapshot,
        subject_id: str,
        *,
        return_page: str,
        panel: QWidget,
    ) -> None:
        if return_page == "reviews":
            self._set_study(present_study(snapshot), page_key="reviews")
            self.reviews_page.focus_subject(subject_id)
            return
        self._set_study(present_study(snapshot), page_key="subjects")
        self.open_subject(subject_id)
        self.workspace_page.tabs.setCurrentWidget(panel)

    def run_t1_enhancement_for_subject(self, subject_id: str) -> None:
        if self.current_study is None or self.study_service.current_study is None:
            self._show_status_message(
                "Open a study before calculating T1 enhancement."
            )
            return
        if self._background_job_running():
            self._show_status_message("Another MRI background job is already running.")
            return
        snapshot = self.study_service.current_study
        if snapshot.active_t1_enhancement_method is None:
            try:
                self.study_service.register_t1_enhancement_method(
                    actor=self._reviewer_identity()
                )
            except StudyStateError as exc:
                self._show_error(
                    "The provisional T1 enhancement method could not be registered.",
                    exc,
                )
                return
        try:
            readiness = self.study_service.t1_enhancement_readiness((subject_id,))
        except StudyStateError as exc:
            self._show_error("T1 enhancement readiness could not be calculated.", exc)
            return
        if not readiness.eligible_subject_ids:
            self._show_error(
                "This subject is not ready for T1 enhancement calculation.",
                StudyStateError(
                    readiness.blocked_reasons[0][1]
                    if readiness.blocked_reasons
                    else "Approve the current T1 registration and brain mask first."
                ),
            )
            return
        confirmation = QMessageBox.question(
            self,
            "Calculate provisional T1 enhancement?",
            "Calculate semi-quantitative T1-weighted gadolinium enhancement from "
            "the exact approved registration and mask?\n\nThe result will be labelled "
            "Provisional because signal-preservation validation is still pending.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if confirmation != QMessageBox.StandardButton.Yes:
            return
        thread = T1EnhancementThread(
            self.study_service,
            actor=self._reviewer_identity(),
            subject_ids=readiness.eligible_subject_ids,
        )
        thread.progress_changed.connect(self._show_t1_enhancement_progress)
        thread.calculation_completed.connect(self._t1_enhancement_completed)
        thread.calculation_failed.connect(self._t1_enhancement_failed)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._clear_t1_enhancement_thread)
        self._background_jobs.register("t1_enhancement", thread)
        self._t1_enhancement_target_subject_ids = readiness.eligible_subject_ids
        self._set_job_status("T1 enhancement running")
        self.statusBar().showMessage("Starting provisional T1 enhancement calculation…")
        thread.start()

    def _show_t1_enhancement_progress(
        self,
        current: int,
        total: int,
        message: str,
    ) -> None:
        self._set_job_status(f"T1 enhancement {current}/{total}")
        self.statusBar().showMessage(message)

    def _t1_enhancement_completed(self, snapshot: StudySnapshot) -> None:
        targets = self._t1_enhancement_target_subject_ids or ()
        self._set_study(present_study(snapshot), page_key="results")
        if targets:
            self.open_subject(targets[0])
            self.workspace_page.tabs.setCurrentWidget(
                self.workspace_page.t1_analysis_panel
            )
        self._notify(
            "Provisional T1 result saved",
            "Enhancement was calculated and saved with its exact dependencies.",
            kind="info",
        )

    def _t1_enhancement_failed(self, error: str) -> None:
        snapshot = self.study_service.current_study
        if snapshot is not None:
            self._set_study(present_study(snapshot), page_key="subjects")
        self._show_error(
            "The provisional T1 enhancement calculation did not complete.",
            StudyStateError(error),
        )

    def _clear_t1_enhancement_thread(self) -> None:
        self._background_jobs.clear("t1_enhancement")
        self._t1_enhancement_target_subject_ids = None
        self._set_job_status()

    def configure_atlas_resource(self, subject_id: str) -> None:
        if self.study_service.current_study is None:
            self._show_status_message(
                "Open a study before registering atlas resources."
            )
            return
        template = QFileDialog.getOpenFileName(
            self,
            "Select AIDAmri MRI template",
            str(Path.home()),
            "NIfTI images (*.nii *.nii.gz)",
        )[0]
        if not template:
            return
        labels = QFileDialog.getOpenFileName(
            self,
            "Select AIDAmri Allen annotation volume",
            str(Path(template).parent),
            "NIfTI images (*.nii *.nii.gz)",
        )[0]
        if not labels:
            return
        lookup = QFileDialog.getOpenFileName(
            self,
            "Select normalized AIDAmri source-label lookup",
            str(Path(labels).parent),
            "CSV tables (*.csv)",
        )[0]
        if not lookup:
            return
        try:
            self.study_service.atlas_mapping.register_aidamri_release(
                template_path=Path(template),
                labels_path=Path(labels),
                source_lookup_path=Path(lookup),
                actor=self._reviewer_identity(),
            )
        except Exception as exc:
            self._show_error(
                "The checksummed AIDAmri release could not be registered.",
                StudyStateError(str(exc)),
            )
            return
        self._refresh_atlas_mapping(subject_id)
        self.statusBar().showMessage(
            "AIDAmri MRI template, Allen labels, lookup, and atlas support mask "
            "were hash-bound.",
            10000,
        )

    def register_major_region_scheme(self, subject_id: str) -> None:
        mapping_path = (
            Path(__file__).resolve().parents[3]
            / "config"
            / "atlas"
            / "major_regions_v1.csv"
        )
        try:
            self.study_service.atlas_mapping.register_major_region_scheme(
                mapping_path,
                actor=self._reviewer_identity(),
            )
        except Exception as exc:
            self._show_error(
                "The proposed major-region scheme could not be registered.",
                StudyStateError(str(exc)),
            )
            return
        self._refresh_atlas_mapping(subject_id)
        self.statusBar().showMessage(
            "Proposed major_regions_v1 registered as DRAFT. Scientific approval is "
            "required before regional results.",
            11000,
        )

    def approve_major_region_scheme(
        self,
        subject_id: str,
        scheme_id: str,
        *,
        return_page: str = "workspace",
    ) -> None:
        confirmation = QMessageBox.question(
            self,
            "Approve proposed major-region scheme?",
            "Approve this exact checksummed source-label collapse as the study-wide "
            "major_regions_v1 contract?\n\nThis is a scientific classification "
            "decision, not an optimizer result.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if confirmation != QMessageBox.StandardButton.Yes:
            return
        try:
            self.study_service.atlas_mapping.approve_major_region_scheme(
                scheme_id, reviewer=self._reviewer_identity()
            )
        except Exception as exc:
            self._show_error(
                "The major-region scheme could not be approved.",
                StudyStateError(str(exc)),
            )
            return
        self._refresh_atlas_mapping(subject_id, return_page=return_page)

    def import_t2_registration_support_mask(self, subject_id: str) -> None:
        selected = QFileDialog.getOpenFileName(
            self,
            "Select T2 registration-support mask",
            str(Path.home()),
            "NIfTI images (*.nii *.nii.gz)",
        )[0]
        if not selected:
            return
        try:
            self.study_service.atlas_mapping.import_t2_registration_support_mask(
                subject_id,
                Path(selected),
                actor=self._reviewer_identity(),
            )
        except Exception as exc:
            self._show_error(
                "The T2 registration-support mask could not be imported.",
                StudyStateError(str(exc)),
            )
            return
        self._refresh_atlas_mapping(subject_id)
        self.statusBar().showMessage(
            "T2 registration-support mask imported as DRAFT; review is required.",
            9000,
        )

    def approve_t2_registration_support_mask(
        self,
        subject_id: str,
        artifact_id: str,
        *,
        return_page: str = "workspace",
    ) -> None:
        confirmation = QMessageBox.question(
            self,
            "Approve T2 registration-support mask?",
            "Approve this exact whole-brain support mask for partial-T2 registration?"
            "\n\nThe lesion mask is not used as the whole-brain support mask.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if confirmation != QMessageBox.StandardButton.Yes:
            return
        try:
            self.study_service.atlas_mapping.approve_t2_registration_support_mask(
                artifact_id, reviewer=self._reviewer_identity()
            )
        except Exception as exc:
            self._show_error(
                "The T2 registration-support mask could not be approved.",
                StudyStateError(str(exc)),
            )
            return
        self._refresh_atlas_mapping(subject_id, return_page=return_page)

    def start_atlas_mapping_stage(self, subject_id: str, action: str) -> None:
        if action != "t1_to_t2" and not self.features.atlas_mapping:
            return
        if self.study_service.current_study is None:
            self._show_status_message(
                "Open a study before running MRI registration."
            )
            return
        if self._background_job_running():
            self._show_status_message("Another MRI background job is already running.")
            return
        descriptions = {
            "atlas_to_t1": (
                "Run provisional rigid and affine atlas→pre-T1 candidates?",
                "Both candidates and their QC remain DRAFT until one exact artifact "
                "is selected and approved.",
            ),
            "t1_to_t2": (
                "Run provisional rigid pre-T1→T2 registration?",
                "The fixed image is the original T2. QC will be rendered for every "
                "original T2 slice.",
            ),
            "composite": (
                "Generate major-region labels on native T2?",
                "Original atlas labels will be collapsed first and propagated directly "
                "once through the approved transform composition.",
            ),
        }
        if action not in descriptions:
            return
        title, detail = descriptions[action]
        if action == "t1_to_t2" and self.current_study is not None:
            subject = self.current_study.subject(subject_id)
            pre = next(
                (
                    scan
                    for scan in subject.inputs
                    if scan.role_label == "Pre-Gd T1"
                ),
                None,
            ) if subject is not None else None
            t2 = next(
                (scan for scan in subject.inputs if scan.role_label == "T2"),
                None,
            ) if subject is not None else None
            detail += (
                "\n\nConfirm this explicit pairing:\n"
                f"Subject: {subject.label if subject is not None else subject_id}\n"
                f"Pre-T1 session/timepoint: {pre.session_id if pre else 'missing'}\n"
                f"T2 session/timepoint: {t2.session_id if t2 else 'missing'}"
            )
        confirmation = QMessageBox.question(
            self,
            title,
            detail,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if confirmation != QMessageBox.StandardButton.Yes:
            return
        thread = AtlasMappingThread(
            self.study_service,
            subject_id=subject_id,
            action=action,
            actor=self._reviewer_identity(),
        )
        thread.progress_changed.connect(self._show_atlas_mapping_progress)
        thread.stage_completed.connect(self._atlas_mapping_completed)
        thread.stage_failed.connect(self._atlas_mapping_failed)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._clear_atlas_mapping_thread)
        job_key = "t1_to_t2_registration" if action == "t1_to_t2" else "atlas_mapping"
        self._background_jobs.register(job_key, thread)
        self._atlas_mapping_subject_id = subject_id
        self._atlas_mapping_action = action
        self._set_job_status(
            "T1→T2 registration running"
            if action == "t1_to_t2"
            else "Atlas mapping running"
        )
        thread.start()

    def _show_atlas_mapping_progress(
        self, current: int, total: int, message: str
    ) -> None:
        self._set_job_status(
            f"T1→T2 registration {current}/{total}"
            if self._atlas_mapping_action == "t1_to_t2"
            else f"Atlas mapping {current}/{total}"
        )
        self.statusBar().showMessage(message)

    def _atlas_mapping_completed(self, _state) -> None:
        subject_id = self._atlas_mapping_subject_id
        if subject_id is not None:
            self._refresh_atlas_mapping(subject_id)
        if self._atlas_mapping_action == "t1_to_t2":
            self._notify(
                "T1→T2 registration draft ready",
                "Inspect every original-T2 QC slice before human approval.",
                kind="warning",
            )
        else:
            self._notify(
                "Atlas draft ready",
                "Inspect the required QC before approving this atlas stage.",
                kind="warning",
            )

    def _atlas_mapping_failed(self, error: str) -> None:
        subject_id = self._atlas_mapping_subject_id
        if subject_id is not None:
            self._refresh_atlas_mapping(subject_id)
        self._show_error(
            "The T1→T2 registration did not complete."
            if self._atlas_mapping_action == "t1_to_t2"
            else "The atlas-mapping stage did not complete.",
            StudyStateError(error),
        )

    def _clear_atlas_mapping_thread(self) -> None:
        self._background_jobs.clear("atlas_mapping")
        self._background_jobs.clear("t1_to_t2_registration")
        self._atlas_mapping_subject_id = None
        self._atlas_mapping_action = None
        self._set_job_status()

    def approve_atlas_to_t1(
        self,
        subject_id: str,
        artifact_id: str,
        *,
        return_page: str = "workspace",
    ) -> None:
        confirmation = QMessageBox.question(
            self,
            "Select and approve atlas→pre-T1 candidate?",
            "Approve this exact transform, warped intensity, metadata, and QC hashes?"
            "\n\nOptimizer success alone is not approval.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if confirmation != QMessageBox.StandardButton.Yes:
            return
        try:
            self.study_service.atlas_mapping.approve_atlas_to_t1_candidate(
                artifact_id, reviewer=self._reviewer_identity()
            )
        except Exception as exc:
            self._show_error(
                "The atlas→pre-T1 candidate could not be approved.",
                StudyStateError(str(exc)),
            )
            return
        self._refresh_atlas_mapping(subject_id, return_page=return_page)

    def approve_atlas_t1_to_t2(
        self,
        subject_id: str,
        artifact_id: str,
        *,
        return_page: str = "workspace",
    ) -> None:
        confirmation = QMessageBox.question(
            self,
            "Approve rigid pre-T1→T2 registration?",
            "Approve this exact rigid transform after inspecting all original T2 slices?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if confirmation != QMessageBox.StandardButton.Yes:
            return
        try:
            self.study_service.atlas_mapping.approve_t1_to_t2(
                artifact_id, reviewer=self._reviewer_identity()
            )
        except Exception as exc:
            self._show_error(
                "The rigid pre-T1→T2 mapping could not be approved.",
                StudyStateError(str(exc)),
            )
            return
        self._refresh_atlas_mapping(subject_id, return_page=return_page)

    def approve_atlas_composite(
        self,
        subject_id: str,
        artifact_id: str,
        *,
        return_page: str = "workspace",
    ) -> None:
        confirmation = QMessageBox.question(
            self,
            "Approve major labels on native T2?",
            "Approve this exact composite after inspecting major-region boundaries and "
            "the native lesion on every original T2 slice?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if confirmation != QMessageBox.StandardButton.Yes:
            return
        try:
            self.study_service.atlas_mapping.approve_composite(
                artifact_id, reviewer=self._reviewer_identity()
            )
        except Exception as exc:
            self._show_error(
                "The composite labels could not be approved.",
                StudyStateError(str(exc)),
            )
            return
        self._refresh_atlas_mapping(subject_id, return_page=return_page)

    def calculate_atlas_result(self, subject_id: str) -> None:
        try:
            self.study_service.atlas_mapping.calculate_result(
                subject_id, actor=self._reviewer_identity()
            )
        except Exception as exc:
            self._show_error(
                "The approved major-region overlap could not be calculated.",
                StudyStateError(str(exc)),
            )
            return
        self._refresh_atlas_mapping(subject_id)
        self.statusBar().showMessage(
            "Approved native-grid overlap and ±0.5 mm AP sensitivity saved.",
            10000,
        )

    def _refresh_atlas_mapping(
        self, subject_id: str, *, return_page: str = "workspace"
    ) -> None:
        snapshot = self.study_service.current_study
        if snapshot is None:
            return
        self._set_study(present_study(snapshot), page_key=return_page)
        if return_page == "reviews":
            self.reviews_page.focus_subject(subject_id)
            return
        self.open_subject(subject_id)
        self.workspace_page.tabs.setCurrentWidget(
            self.workspace_page.atlas_mapping_panel
            if self.workspace_page.atlas_mapping_panel is not None
            else self.workspace_page.t1_analysis_panel
        )

    def select_t2_model_release(self) -> bool:
        if self.current_study is None or self.study_service.current_study is None:
            self._show_status_message(
                "Open a study before selecting a T2 model release."
            )
            return False
        suggested = default_t2_model_release_suggestion()
        selected = QFileDialog.getExistingDirectory(
            self,
            "Select packaged T2 model folder",
            str(suggested if suggested.is_dir() else Path.home() / "Downloads"),
        )
        if not selected:
            return False
        return self._register_t2_model_release(Path(selected))

    def _register_t2_model_release(self, release_root: Path) -> bool:
        try:
            snapshot = self.study_service.register_t2_model_release(
                release_root,
                actor=self._reviewer_identity(),
            )
        except StudyStateError as exc:
            self._show_error("The T2 model release could not be registered.", exc)
            return False
        self._set_study(present_study(snapshot), page_key="subjects")
        self.statusBar().showMessage(
            "The T2 model passed checkpoint, checksum, and inference-contract validation.",
            10000,
        )
        return True

    def _handle_t2_model_choice(self, model_id: str) -> None:
        if self.current_study is None or self.study_service.current_study is None:
            self._show_status_message(
                "Open a study before changing the T2 segmentation model."
            )
            return
        try:
            choice = t2_model_choice(model_id)
        except KeyError as exc:
            self._show_error("The T2 model choice is unknown.", StudyStateError(str(exc)))
            return
        if not choice.path.is_dir():
            self._show_error(
                "The selected T2 model is unavailable.",
                StudyStateError(f"Packaged model resources not found: {choice.path}"),
            )
            self.settings_page.set_t2_model_choice(
                self.current_study.active_t2_release_id
            )
            return
        self._register_t2_model_release(choice.path)

    def run_t2_inference_for_study(
        self,
        subject_ids: tuple[str, ...] | None = None,
    ) -> None:
        if self.current_study is None:
            return
        if self.study_service.current_study is None:
            self._show_status_message("Open a study before running T2 segmentation.")
            return
        if self._background_job_running():
            self._show_status_message("Another MRI background job is already running.")
            return
        if self.current_study.active_t2_release_label is None:
            default_release = default_t2_model_release_path()
            registered = (
                self._register_t2_model_release(default_release)
                if default_release.is_dir()
                else self.select_t2_model_release()
            )
            if not registered:
                return
        try:
            readiness = self.study_service.t2_inference_readiness(subject_ids)
        except StudyStateError as exc:
            self._show_error("T2 inference readiness could not be calculated.", exc)
            return
        if not readiness.eligible_subject_ids:
            self._show_error(
                "No subjects are ready for T2 lesion inference.",
                StudyStateError(
                    readiness.blocked_reasons[0][1]
                    if readiness.blocked_reasons
                    else "Import and validate a compatible native T2 first."
                ),
            )
            return
        blocked = len(readiness.blocked_reasons)
        confirmation = QMessageBox.question(
            self,
            "Run T2 lesion segmentation?",
            f"Run {self.current_study.active_t2_release_label} for "
            f"{readiness.eligible_count} eligible subject(s)?\n\n"
            f"{blocked} subject(s) will be skipped because a current draft already "
            "awaits review, or T2 is missing, unvalidated, not applicable, or "
            "incompatible. New masks will require human review.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if confirmation != QMessageBox.StandardButton.Yes:
            return
        thread = T2InferenceThread(
            self.study_service,
            actor=self._reviewer_identity(),
            subject_ids=readiness.eligible_subject_ids,
            device_name="auto",
        )
        thread.progress_changed.connect(self._show_t2_inference_progress)
        thread.inference_completed.connect(self._t2_inference_completed)
        thread.inference_failed.connect(self._t2_inference_failed)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._clear_t2_inference_thread)
        self._background_jobs.register("t2_inference", thread)
        self._t2_target_subject_ids = readiness.eligible_subject_ids
        self._set_job_status("T2 inference running")
        self.statusBar().showMessage(
            f"Starting T2 lesion segmentation for {readiness.eligible_count} subject(s)…"
        )
        thread.start()

    def _show_t2_inference_progress(
        self,
        current: int,
        total: int,
        message: str,
    ) -> None:
        self._set_job_status(f"T2 inference {current}/{total}")
        self.statusBar().showMessage(message)

    def _t2_inference_completed(self, snapshot: StudySnapshot) -> None:
        targets = self._t2_target_subject_ids or ()
        self._set_study(present_study(snapshot), page_key="reviews")
        if targets:
            self.reviews_page.focus_subject(targets[0])
        self._notify(
            "T2 draft ready",
            f"Created {len(targets)} draft lesion mask(s). Human review is required.",
            kind="warning",
        )

    def _t2_inference_failed(self, error: str) -> None:
        snapshot = self.study_service.current_study
        if snapshot is not None:
            self._set_study(present_study(snapshot), page_key="subjects")
        self._show_error("T2 lesion inference did not complete.", StudyStateError(error))

    def _clear_t2_inference_thread(self) -> None:
        self._background_jobs.clear("t2_inference")
        self._t2_target_subject_ids = None
        self._set_job_status()

    def manually_edit_review_mask(
        self,
        subject_id: str,
        artifact_id: str,
        *,
        return_page: str = "reviews",
    ) -> None:
        workflow_key = self._review_workflow_key(artifact_id)
        if workflow_key.startswith("atlas_"):
            self._show_status_message(
                "Atlas mappings are reviewed from their immutable QC and cannot be "
                "manually edited as lesion masks."
            )
            return
        if workflow_key == "t1_registration":
            self._show_status_message(
                "Registrations are reviewed from their QC bundle and cannot be "
                "manually edited as masks."
            )
            return
        if workflow_key == "t1_brain_mask":
            self.manually_edit_t1_brain_mask(
                subject_id,
                artifact_id,
                return_page=return_page,
            )
            return
        self.manually_edit_t2_mask(
            subject_id,
            artifact_id,
            return_page=return_page,
        )

    def approve_review_mask(
        self,
        subject_id: str,
        artifact_id: str,
        *,
        return_page: str = "reviews",
    ) -> None:
        workflow_key = self._review_workflow_key(artifact_id)
        if workflow_key == "atlas_scheme":
            self.approve_major_region_scheme(
                subject_id, artifact_id, return_page=return_page
            )
            return
        if workflow_key == "atlas_t2_support":
            self.approve_t2_registration_support_mask(
                subject_id, artifact_id, return_page=return_page
            )
            return
        if workflow_key == "atlas_to_t1":
            self.approve_atlas_to_t1(
                subject_id, artifact_id, return_page=return_page
            )
            return
        if workflow_key == "t1_to_t2_registration":
            self.approve_atlas_t1_to_t2(
                subject_id, artifact_id, return_page=return_page
            )
            return
        if workflow_key == "atlas_composite":
            self.approve_atlas_composite(
                subject_id, artifact_id, return_page=return_page
            )
            return
        if workflow_key == "t1_registration":
            self.approve_t1_registration(
                subject_id,
                artifact_id,
                return_page=return_page,
            )
            return
        if workflow_key == "t1_brain_mask":
            self.approve_t1_brain_mask(
                subject_id,
                artifact_id,
                return_page=return_page,
            )
            return
        self.approve_t2_mask(
            subject_id,
            artifact_id,
            return_page=return_page,
        )

    def prepare_review_qc_slices(
        self,
        subject_id: str,
        artifact_id: str,
    ) -> None:
        workflow_key = self._review_workflow_key(artifact_id)
        if workflow_key.startswith("atlas_"):
            return
        if workflow_key == "t1_registration":
            return
        if workflow_key == "t1_brain_mask":
            self.prepare_t1_brain_mask_review_qc_slices(subject_id, artifact_id)
            return
        self.prepare_t2_review_qc_slices(subject_id, artifact_id)

    def _review_workflow_key(self, artifact_id: str) -> str:
        if self.current_study is None:
            return ""
        item = next(
            (
                review
                for review in self.current_study.reviews
                if review.artifact_id == artifact_id
            ),
            None,
        )
        return item.workflow_key if item is not None else ""

    def manually_edit_t1_brain_mask(
        self,
        subject_id: str,
        artifact_id: str,
        *,
        return_page: str = "workspace",
    ) -> None:
        if self.current_study is None or self.study_service.current_study is None:
            self._show_status_message(
                "Open a study before editing a T1 brain mask."
            )
            return
        configured_viewer = self.settings_page.external_editor.text().strip() or None
        try:
            session = self.study_service.start_t1_brain_mask_manual_edit(
                subject_id,
                artifact_id,
                actor=self._reviewer_identity(),
                viewer_path=configured_viewer,
            )
        except StudyStateError as exc:
            self._show_error(
                "The T1 brain mask could not be opened for manual editing.",
                exc,
            )
            return
        dialog = T1BrainMaskManualEditDialog(session.editable_mask_path, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            snapshot = self.study_service.finish_t1_brain_mask_manual_edit(
                session,
                actor=self._reviewer_identity(),
            )
        except StudyStateError as exc:
            self._show_error(
                "The manually edited T1 brain mask could not be saved.",
                exc,
            )
            return
        self._refresh_after_review(
            snapshot,
            subject_id,
            return_page=return_page,
            panel=self.workspace_page.t1_brain_mask_panel,
        )
        self.statusBar().showMessage(
            "The edited brain mask is now the current version and awaits approval.",
            12000,
        )

    def prepare_t1_brain_mask_review_qc_slices(
        self,
        subject_id: str,
        artifact_id: str,
    ) -> None:
        if self.current_study is None or self.study_service.current_study is None:
            return
        try:
            snapshot = self.study_service.prepare_t1_brain_mask_review_qc_slices(
                subject_id,
                artifact_id,
            )
        except StudyStateError as exc:
            self._show_error(
                "The T1 brain-mask review slices could not be prepared.",
                exc,
            )
            return
        self._set_study(present_study(snapshot), page_key="reviews")
        self.reviews_page.focus_subject(subject_id)

    def approve_t1_brain_mask(
        self,
        subject_id: str,
        artifact_id: str,
        *,
        return_page: str = "workspace",
    ) -> None:
        if self.current_study is None or self.study_service.current_study is None:
            self._show_status_message(
                "Open a study to approve a real T1 brain mask."
            )
            return
        confirmation = QMessageBox.question(
            self,
            "Approve T1 brain mask?",
            "Approve this exact native pre-Gd brain mask?\n\nThe approval is immutable. "
            "Any later correction or regenerated draft will be a new version and "
            "will require its own approval.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if confirmation != QMessageBox.StandardButton.Yes:
            return
        try:
            snapshot = self.study_service.approve_t1_brain_mask(
                subject_id,
                artifact_id,
                reviewer=self._reviewer_identity(),
            )
        except StudyStateError as exc:
            self._show_error("The T1 brain mask could not be approved.", exc)
            return
        self._refresh_after_review(
            snapshot,
            subject_id,
            return_page=return_page,
            panel=self.workspace_page.t1_brain_mask_panel,
        )
        self.statusBar().showMessage(
            "T1 brain mask approved for downstream registration and analysis.",
            12000,
        )

    def manually_edit_t2_mask(
        self,
        subject_id: str,
        artifact_id: str,
        *,
        return_page: str = "workspace",
    ) -> None:
        if self.current_study is None or self.study_service.current_study is None:
            self._show_status_message(
                "Open a study before editing a T2 lesion mask."
            )
            return
        configured_viewer = self.settings_page.external_editor.text().strip() or None
        try:
            session = self.study_service.start_t2_manual_edit(
                subject_id,
                artifact_id,
                actor=self._reviewer_identity(),
                viewer_path=configured_viewer,
            )
        except StudyStateError as exc:
            self._show_error("The T2 mask could not be opened for manual editing.", exc)
            return
        dialog = T2ManualEditDialog(session.editable_mask_path, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            snapshot = self.study_service.finish_t2_manual_edit(
                session,
                actor=self._reviewer_identity(),
            )
        except StudyStateError as exc:
            self._show_error("The manually edited T2 mask could not be saved.", exc)
            return
        self._refresh_after_review(
            snapshot,
            subject_id,
            return_page=return_page,
            panel=self.workspace_page.t2_panel,
        )
        self.statusBar().showMessage(
            "The edited mask is now the subject's current mask version and awaits approval.",
            12000,
        )

    def prepare_t2_review_qc_slices(
        self,
        subject_id: str,
        artifact_id: str,
    ) -> None:
        """Backfill navigable QC slices for artifacts created by older app versions."""

        if self.current_study is None or self.study_service.current_study is None:
            return
        try:
            snapshot = self.study_service.prepare_t2_review_qc_slices(
                subject_id,
                artifact_id,
            )
        except StudyStateError as exc:
            self._show_error("The T2 review slices could not be prepared.", exc)
            return
        self._set_study(present_study(snapshot), page_key="reviews")
        self.reviews_page.focus_subject(subject_id)

    def apply_review_t2_probability_threshold(
        self,
        subject_id: str,
        artifact_id: str,
        threshold: float,
    ) -> None:
        """Apply one explicitly reviewed probability cutoff to one animal."""

        if self.current_study is None or self.study_service.current_study is None:
            self._show_status_message(
                "Open a study before applying a case-specific T2 threshold."
            )
            return
        if self._review_workflow_key(artifact_id) != "t2_lesion":
            self._show_status_message(
                "Case-specific probability thresholds are available only for "
                "T2 lesion reviews."
            )
            return
        confirmation = QMessageBox.question(
            self,
            "Apply case-specific T2 threshold?",
            f"Create a new draft lesion mask for this animal using probability "
            f"threshold {threshold:.8g}?\n\nThis does not change the model default "
            "or any other animal. The new mask will require explicit human review.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if confirmation != QMessageBox.StandardButton.Yes:
            return
        try:
            snapshot = self.study_service.apply_t2_probability_threshold(
                subject_id,
                artifact_id,
                threshold,
                actor=self._reviewer_identity(),
            )
        except StudyStateError as exc:
            self._show_error("The case-specific T2 threshold could not be applied.", exc)
            return
        self._set_study(present_study(snapshot), page_key="reviews")
        self.reviews_page.focus_subject(subject_id)
        self.statusBar().showMessage(
            "The case-specific threshold created a new mask version that awaits review.",
            12000,
        )

    def approve_t2_mask(
        self,
        subject_id: str,
        artifact_id: str,
        *,
        return_page: str = "workspace",
    ) -> None:
        if self.current_study is None or self.study_service.current_study is None:
            self._show_status_message(
                "Open a study to approve a real T2 lesion mask."
            )
            return
        confirmation = QMessageBox.question(
            self,
            "Approve T2 lesion mask?",
            "Approve this exact mask and create the official native-space lesion "
            "volume?\n\nThe approval is immutable. Any later replacement "
            "will create a new artifact and mark this result outdated.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if confirmation != QMessageBox.StandardButton.Yes:
            return
        try:
            snapshot = self.study_service.approve_t2_mask(
                subject_id,
                artifact_id,
                reviewer=self._reviewer_identity(),
            )
        except StudyStateError as exc:
            self._show_error("The T2 lesion mask could not be approved.", exc)
            return
        self._refresh_after_review(
            snapshot,
            subject_id,
            return_page=return_page,
            panel=self.workspace_page.t2_panel,
        )
        self.statusBar().showMessage(
            "T2 lesion mask approved; the official native-space volume is available.",
            12000,
        )

    def export_approved_t2_results_csv(self) -> None:
        if self.current_study is None or self.study_service.current_study is None:
            self._show_status_message(
                "Open a study with approved T2 results to create this export."
            )
            return
        root = self.current_study.root_path
        default_path = root / "exports" / "approved_t2_lesion_results.csv"
        selected, _filter = QFileDialog.getSaveFileName(
            self,
            "Export approved T2 lesion results",
            str(default_path),
            "CSV files (*.csv)",
        )
        if not selected:
            return
        destination = Path(selected)
        if destination.suffix.casefold() != ".csv":
            destination = destination.with_suffix(".csv")
        try:
            exported = self.study_service.export_approved_t2_results_csv(
                destination,
                actor=self._reviewer_identity(),
            )
        except StudyStateError as exc:
            self._show_error("The approved T2 results could not be exported.", exc)
            return
        self._notify(
            "Export complete",
            f"Saved {exported.row_count} approved T2 result(s) to {exported.path}.",
            kind="success",
        )

    def export_approved_t2_results_excel(self, detailed: bool = False) -> None:
        if self.current_study is None or self.study_service.current_study is None:
            self._show_status_message(
                "Open a study with approved T2 results to create this export."
            )
            return
        root = self.current_study.root_path
        filename = (
            "approved_t2_lesion_results_detailed.xlsx"
            if detailed
            else "approved_t2_lesion_results.xlsx"
        )
        selected, _filter = QFileDialog.getSaveFileName(
            self,
            "Export detailed approved T2 results"
            if detailed
            else "Export approved T2 lesion results",
            str(root / "exports" / filename),
            "Excel workbooks (*.xlsx)",
        )
        if not selected:
            return
        destination = Path(selected)
        if destination.suffix.casefold() != ".xlsx":
            destination = destination.with_suffix(".xlsx")
        try:
            exported = self.study_service.export_approved_t2_results_excel(
                destination,
                detailed=detailed,
                actor=self._reviewer_identity(),
            )
        except StudyStateError as exc:
            self._show_error("The approved T2 Excel export could not be created.", exc)
            return
        detail = (
            f" and {exported.slice_row_count} per-slice row(s)"
            if exported.detailed
            else ""
        )
        self._notify(
            "Export complete",
            f"Saved {exported.row_count} approved result(s){detail} to {exported.path}.",
            kind="success",
        )

    def bulk_flip_subjects(self, subject_ids: tuple[str, ...]) -> None:
        if self.current_study is None or not subject_ids:
            return
        if self.study_service.current_study is None:
            self._show_status_message("Open a study before creating flipped MRI versions.")
            return
        dialog = BulkFlipDialog(len(subject_ids), self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            assignments = self.study_service.plan_bulk_flip(
                subject_ids,
                dialog.flip_axes(),
                dialog.roles(),
            )
        except StudyStateError as exc:
            self._show_error("The batch flip could not be prepared.", exc)
            return
        self._start_scan_import(assignments, operation_name="MRI batch flip")

    def manage_groups(self) -> None:
        if self.current_study is None:
            return
        if self.study_service.current_study is None:
            self._show_status_message("Open a study before assigning subject groups.")
            return
        if self.current_study.blinded_review:
            confirmation = UnblindingDialog(self)
            if confirmation.exec() != QDialog.DialogCode.Accepted:
                return
            try:
                snapshot = self.study_service.unblind(
                    reviewer=self._reviewer_identity()
                )
            except StudyStateError as exc:
                self._show_error("The study could not be unblinded.", exc)
                return
            self._set_study(present_study(snapshot), page_key="subjects")

        if self.current_study is None:
            return
        assignment = GroupAssignmentDialog(
            self.current_study.subjects,
            self.current_study.group_definitions,
            parent=self,
        )
        if assignment.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            snapshot = self.study_service.assign_groups(
                assignment.assignments(),
                reviewer=self._reviewer_identity(),
            )
        except StudyStateError as exc:
            self._show_error("The group assignments could not be saved.", exc)
            return
        self._set_study(present_study(snapshot), page_key="subjects")
        self.statusBar().showMessage(
            "Subject group assignments were saved and added to the audit history.",
            8000,
        )

    def show_audit_history(self) -> None:
        if self.current_study is None:
            return
        if self.study_service.current_study is None:
            self._show_status_message("Open a study before viewing its audit history.")
            return
        try:
            events = self.study_service.list_audit_events()
        except StudyStateError as exc:
            self._show_error("The audit history could not be opened.", exc)
            return
        AuditHistoryDialog(events, self).exec()

    def select_input_folder(self, kind: str) -> None:
        if self.current_study is None or self.study_service.current_study is None:
            self._show_status_message("Open or create a study before selecting MRI data.")
            return
        if kind != "mri":
            self._show_status_message(f"Unsupported input-folder kind: {kind}")
            return
        current = self.current_study.mri_input_folder
        selected = QFileDialog.getExistingDirectory(
            self,
            "Select folder containing Bruker sessions or NIfTI MRI files",
            str(current or Path.home()),
        )
        if selected:
            self._discover_and_review_mri(Path(selected))

    def select_mri_source_folder(self) -> None:
        self.select_input_folder("mri")

    def _discover_and_review_mri(self, source_root: Path) -> None:
        try:
            report = self.study_service.discover_mri_folder(
                source_root,
                actor=self._reviewer_identity(),
            )
        except (StudyStateError, OSError) as exc:
            self._show_error("The MRI source folder could not be inspected.", exc)
            return
        snapshot = self.study_service.current_study
        if snapshot is not None:
            self._set_study(present_study(snapshot), page_key="subjects")
        scope = self.current_study.analysis_scope
        proposed = [
            scan
            for scan in report.scans
            if scan.suggested_role is not ScanRole.IGNORE
            and (
                scan.suggested_role is ScanRole.T2
                and scope.includes_t2
                or scan.suggested_role in {ScanRole.T1_PRE, ScanRole.T1_POST}
                and scope.includes_t1
            )
        ]
        if not proposed:
            details = " ".join(issue.message for issue in report.failures)
            self._show_error(
                "No importable MRI scans were proposed.",
                StudyStateError(
                    details
                    or "The folder reference was saved, but no recognisable Bruker or "
                    "NIfTI T1/T2 inputs were found."
                ),
            )
            return
        dialog = ScanImportReviewDialog(
            report,
            analysis_scope=scope,
            parent=self,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            self.statusBar().showMessage(
                "MRI discovery was reviewed but no inputs were imported.",
                7000,
            )
            return
        self._start_scan_import(dialog.assignments())

    def _start_scan_import(
        self,
        assignments: tuple[ScanImportAssignment, ...],
        *,
        operation_name: str = "MRI import",
    ) -> None:
        if self._background_job_running():
            self._show_status_message("Another MRI background job is already running.")
            return
        thread = ScanImportThread(
            self.study_service,
            assignments,
            actor=self._reviewer_identity(),
        )
        thread.progress_changed.connect(self._show_scan_import_progress)
        thread.import_completed.connect(self._scan_import_completed)
        thread.import_failed.connect(self._scan_import_failed)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._clear_scan_import_thread)
        self._background_jobs.register("scan_import", thread)
        self._scan_operation_name = operation_name
        self._set_job_status(f"{operation_name} running")
        self.statusBar().showMessage(
            f"{operation_name}: creating {len(assignments)} versioned NIfTI input(s)…"
        )
        thread.start()

    def _show_scan_import_progress(self, current: int, total: int, message: str) -> None:
        self._set_job_status(f"MRI import {current}/{total}")
        self.statusBar().showMessage(message)

    def _scan_import_completed(
        self,
        snapshot: StudySnapshot,
        failed: int,
    ) -> None:
        self._set_study(present_study(snapshot), page_key="subjects")
        self._set_job_status()
        if failed:
            self._notify(
                f"{self._scan_operation_name} needs attention",
                f"Finished with {failed} conversion failure(s). Open a subject to "
                "inspect the recorded error.",
                kind="warning",
            )
        elif self._scan_operation_name == "MRI batch flip":
            self._notify(
                "MRI batch flip complete",
                "New versioned inputs and provenance were saved; previous versions "
                "were retained.",
                kind="success",
            )
        else:
            self._notify(
                "MRI import complete",
                "Converted NIfTI inputs and provenance were saved inside the study.",
                kind="success",
            )

    def _scan_import_failed(self, error: str) -> None:
        self._set_job_status()
        self._show_error("The MRI import plan could not be started.", StudyStateError(error))

    def _clear_scan_import_thread(self) -> None:
        self._background_jobs.clear("scan_import")
        self._scan_operation_name = "MRI import"

    def _handle_blinding_toggle(self, blinded: bool) -> None:
        if self.current_study is None:
            return
        if self.study_service.current_study is None:
            self.settings_page.set_study_state(blinded=True)
            self.set_blinded_review(True)
            return
        if blinded:
            self.settings_page.set_study_state(blinded=False)
            self.set_blinded_review(False)
            self._show_status_message("An unblinded study cannot be blinded again.")
            return
        confirmation = UnblindingDialog(self)
        if confirmation.exec() != QDialog.DialogCode.Accepted:
            self.settings_page.set_study_state(blinded=True)
            self.set_blinded_review(True)
            return
        try:
            snapshot = self.study_service.unblind(reviewer=self._reviewer_identity())
        except StudyStateError as exc:
            self.settings_page.set_study_state(blinded=True)
            self.set_blinded_review(True)
            self._show_error("The study could not be unblinded.", exc)
            return
        self._set_study(present_study(snapshot), page_key="settings")
        self.statusBar().showMessage(
            "Study unblinded. The action was recorded and cannot be reversed.",
            9000,
        )

    def set_blinded_review(self, blinded: bool) -> None:
        self.blinded_review = blinded
        self.blinding_badge.setVisible(blinded)
        self.subjects_page.set_blinded_review(blinded)
        self.workspace_page.set_blinded_review(blinded)
        self.results_page.set_blinded_review(blinded)

    def show_launcher(self) -> None:
        if self._background_job_running():
            self._show_status_message(
                "Wait for the current MRI background job before changing studies."
            )
            return
        self.launcher_page.set_recent_studies(self.recent_studies.list())
        self.root_stack.setCurrentIndex(0)
        self.statusBar().showMessage("Choose or create a study.")

    def close_study(self) -> None:
        if self._background_job_running():
            self._show_status_message(
                "Wait for the current MRI background job before closing the study."
            )
            return
        self.study_service.close_study()
        self.current_study = None
        self.study_name_label.setText("No study open")
        self.close_study_action.setEnabled(False)
        self.show_launcher()

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._background_job_running():
            self._show_status_message(
                "Wait for the current MRI background job before quitting."
            )
            event.ignore()
            return
        super().closeEvent(event)

    def _show_status_message(self, message: str) -> None:
        self._notify("Action unavailable", message, kind="warning")

    def _set_job_status(self, text: str | None = None) -> None:
        self.jobs_label.setVisible(text is not None)
        self.jobs_label.setText(text or "")

    def _background_job_count_changed(self, active_count: int) -> None:
        running = active_count > 0
        self.job_progress_ring.setVisible(running)
        if running:
            self.job_progress_ring.start()
        else:
            self.job_progress_ring.stop()

    def _notify(
        self,
        title: str,
        content: str,
        *,
        kind: NotificationKind = "info",
    ) -> None:
        duration = 7500 if kind == "warning" else 6000
        self.statusBar().showMessage(content, duration)
        show_notification(
            self,
            title=title,
            content=content,
            kind=kind,
            duration=duration,
        )

    def _reviewer_identity(self) -> str:
        reviewer = self.settings_page.reviewer.text().strip()
        return reviewer or "Local researcher"

    def _background_job_running(self) -> bool:
        return self._background_jobs.any_running

    def _record_recent(self, study: StudySnapshot) -> None:
        try:
            self.recent_studies.record(study)
            self.launcher_page.set_recent_studies(self.recent_studies.list())
        except OSError:
            # Recent history is a convenience and must never block study access.
            pass

    def _show_error(self, summary: str, exc: Exception) -> None:
        message = QMessageBox(self)
        message.setIcon(QMessageBox.Critical)
        message.setWindowTitle("LYS IRM")
        message.setText(summary)
        message.setInformativeText(str(exc))
        message.exec()
