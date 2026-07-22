"""Connected main shell for persistent MRI studies."""

from __future__ import annotations

from pathlib import Path

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

from lys_bbb_app.application.study_presenter import (
    present_legacy_project,
    present_study,
)
from lys_bbb_app.domain.errors import StudyStateError
from lys_bbb_app.domain.scan_import import ScanImportAssignment
from lys_bbb_app.domain.study import LEGACY_PROJECT_FILE_SUFFIX, StudySnapshot
from lys_bbb_app.domain.view_models import StatusValue, StudyViewModel
from lys_bbb_app.services.recent_studies_service import RecentStudiesService
from lys_bbb_app.services.study_service import StudyService
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
    InputValidationThread,
    ScanImportThread,
    T1BrainMaskThread,
    T2InferenceThread,
)


LEGACY_PROJECT_FILTER = (
    f"LYS BBB legacy projects (*{LEGACY_PROJECT_FILE_SUFFIX})"
)


class MainWindow(QMainWindow):
    """Application shell for canonical persistent studies and legacy inspection."""

    def __init__(
        self,
        study_service: StudyService | None = None,
        recent_studies: RecentStudiesService | None = None,
    ) -> None:
        super().__init__()
        self.study_service = study_service or StudyService()
        self.recent_studies = recent_studies or RecentStudiesService()
        self.current_study: StudyViewModel | None = None
        self.blinded_review = False
        self.nav_buttons: dict[str, QPushButton] = {}
        self.page_indices: dict[str, int] = {}
        self._scan_import_thread: ScanImportThread | None = None
        self._input_validation_thread: InputValidationThread | None = None
        self._t2_inference_thread: T2InferenceThread | None = None
        self._t2_target_subject_ids: tuple[str, ...] | None = None
        self._t1_brain_mask_thread: T1BrainMaskThread | None = None
        self._t1_target_subject_ids: tuple[str, ...] | None = None
        self._validation_subject_id: str | None = None
        self._validation_return_page = "workspace"
        self._scan_operation_name = "MRI import"

        self.setWindowTitle("LYS BBB Scientific Workflows")
        self.resize(1440, 900)
        self.setMinimumSize(1180, 760)
        self._build_actions()
        self._build_ui()
        self.statusBar().showMessage("Choose or create a study.")

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

        migrate_action = QAction("&Migrate legacy .lysbbb project…", self)
        migrate_action.triggered.connect(self.migrate_legacy_project)
        file_menu.addAction(migrate_action)

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
        self.launcher_page.migrate_requested.connect(self.migrate_legacy_project)
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
        self.reviews_page = ReviewsPage()
        self.results_page = ResultsPage()
        self.settings_page = SettingsPage()
        self.workspace_page = SubjectWorkspacePage()
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

        self.overview_page.navigate_requested.connect(self.show_page)
        self.subjects_page.subject_open_requested.connect(self.open_subject)
        self.subjects_page.subject_mri_open_requested.connect(
            self.open_subject_mri_in_itksnap
        )
        self.subjects_page.subject_validation_requested.connect(
            lambda subject_id: self.validate_subject_inputs(
                subject_id,
                return_page="subjects",
            )
        )
        self.subjects_page.subjects_flip_requested.connect(self.bulk_flip_subjects)
        self.subjects_page.subject_remove_requested.connect(self.remove_subject)
        self.subjects_page.subject_restore_requested.connect(self.restore_subject)
        self.subjects_page.add_subject_requested.connect(self.add_subject)
        self.subjects_page.import_mri_requested.connect(self.select_mri_source_folder)
        self.subjects_page.group_assignment_requested.connect(self.manage_groups)
        self.subjects_page.audit_history_requested.connect(self.show_audit_history)
        self.subjects_page.t2_inference_requested.connect(
            self.run_t2_inference_for_study
        )
        self.workspace_page.back_requested.connect(lambda: self.show_page("subjects"))
        self.workspace_page.open_mri_requested.connect(
            self.open_subject_mri_in_itksnap
        )
        self.workspace_page.input_mri_open_requested.connect(
            self.open_scan_input_in_itksnap
        )
        self.workspace_page.input_validation_requested.connect(
            self.validate_subject_inputs
        )
        self.workspace_page.input_flip_requested.connect(
            lambda subject_id: self.bulk_flip_subjects((subject_id,))
        )
        self.workspace_page.input_import_requested.connect(
            self.select_mri_source_folder
        )
        self.workspace_page.rename_requested.connect(self.rename_subject)
        self.workspace_page.t2_release_requested.connect(
            self.select_t2_model_release
        )
        self.workspace_page.t2_run_subject_requested.connect(
            lambda subject_id: self.run_t2_inference_for_study((subject_id,))
        )
        self.workspace_page.t2_run_study_requested.connect(
            self.run_t2_inference_for_study
        )
        self.workspace_page.t2_manual_edit_requested.connect(
            self.manually_edit_t2_mask
        )
        self.workspace_page.t2_approve_requested.connect(self.approve_t2_mask)
        self.workspace_page.t1_brain_mask_release_requested.connect(
            self.select_t1_brain_mask_release
        )
        self.workspace_page.t1_brain_mask_run_requested.connect(
            self.run_t1_brain_mask_for_subject
        )
        self.workspace_page.t1_brain_mask_manual_edit_requested.connect(
            self.manually_edit_t1_brain_mask
        )
        self.workspace_page.t1_brain_mask_approve_requested.connect(
            self.approve_t1_brain_mask
        )
        self.reviews_page.approve_requested.connect(
            lambda subject_id, artifact_id: self.approve_review_mask(
                subject_id,
                artifact_id,
                return_page="reviews",
            )
        )
        self.reviews_page.manual_edit_requested.connect(
            lambda subject_id, artifact_id: self.manually_edit_review_mask(
                subject_id,
                artifact_id,
                return_page="reviews",
            )
        )
        self.reviews_page.subject_requested.connect(self.open_subject)
        self.reviews_page.qc_slices_requested.connect(
            self.prepare_review_qc_slices
        )
        self.results_page.approved_csv_requested.connect(
            self.export_approved_t2_results_csv
        )
        self.settings_page.blinding_changed.connect(self._handle_blinding_toggle)
        self.settings_page.input_folder_requested.connect(self.select_input_folder)
        return root

    def _build_header(self) -> QFrame:
        header = QFrame()
        header.setObjectName("topBar")
        header.setFixedHeight(72)
        layout = QHBoxLayout(header)
        layout.setContentsMargins(22, 12, 22, 12)
        titles = QVBoxLayout()
        study_caption = QLabel("CURRENT STUDY")
        study_caption.setObjectName("metadata")
        self.study_name_label = QLabel("No study open")
        self.study_name_label.setStyleSheet("font-size: 17px; font-weight: 700;")
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
        layout.addWidget(self.jobs_label)
        return header

    def _build_sidebar(self) -> QFrame:
        sidebar = QFrame()
        sidebar.setObjectName("sideBar")
        sidebar.setFixedWidth(220)
        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(14, 18, 14, 18)
        layout.setSpacing(5)
        wordmark = QLabel("LYS BBB")
        wordmark.setObjectName("appWordmark")
        layout.addWidget(wordmark)
        layout.addSpacing(12)

        self.nav_group = QButtonGroup(self)
        self.nav_group.setExclusive(True)
        for key, label in (
            ("overview", "⌂   Overview"),
            ("subjects", "●   Subjects"),
            ("reviews", "✓   Reviews"),
            ("results", "▤   Results && exports"),
            ("settings", "⚙   Settings"),
        ):
            button = QPushButton(label)
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
            self.statusBar().showMessage(
                "Study created. Choose Import MRI folder to discover subjects and scans.",
                9000,
            )

    def open_project(self) -> None:
        selected = QFileDialog.getExistingDirectory(
            self,
            "Open LYS BBB study directory",
            str(Path.home()),
        )
        if selected:
            self.open_project_path(selected)

    def open_project_path(self, project_path: Path | str) -> bool:
        path = Path(project_path).expanduser()
        if path.suffix.lower() == LEGACY_PROJECT_FILE_SUFFIX:
            return self._open_legacy_project_path(path)
        try:
            study = self.study_service.open_study(path)
        except (StudyStateError, OSError) as exc:
            self._show_error("The study could not be opened.", exc)
            return False
        self._record_recent(study)
        self._set_study(present_study(study))
        self.statusBar().showMessage(
            f"Study reopened with {len(study.subjects)} persisted subjects.",
            8000,
        )
        return True

    def migrate_legacy_project(self) -> None:
        legacy_path, _filter = QFileDialog.getOpenFileName(
            self,
            "Select a legacy .lysbbb project",
            str(Path.home()),
            LEGACY_PROJECT_FILTER,
        )
        if not legacy_path:
            return
        parent = QFileDialog.getExistingDirectory(
            self,
            "Choose the parent directory for the migrated study",
            str(Path(legacy_path).parent),
        )
        if not parent:
            return
        target_root = Path(parent) / f"{Path(legacy_path).stem}-study"
        try:
            study = self.study_service.migrate_legacy_project(
                legacy_path,
                target_root,
                actor=self._reviewer_identity(),
            )
        except (StudyStateError, OSError) as exc:
            self._show_error("The legacy project could not be migrated.", exc)
            return
        self._record_recent(study)
        self._set_study(present_study(study))
        self.statusBar().showMessage(
            "Legacy project migrated without modifying the original .lysbbb file.",
            9000,
        )

    def _open_legacy_project_path(self, database_path: Path) -> bool:
        try:
            project = self.study_service.inspect_legacy_project(database_path)
        except (StudyStateError, OSError) as exc:
            self._show_error("The legacy project could not be opened.", exc)
            return False
        self._set_study(present_legacy_project(project))
        self.statusBar().showMessage(
            "Legacy project opened read-only for inspection. Use Migrate legacy project "
            "to add persistent subjects.",
            9000,
        )
        return True

    def _set_study(self, study: StudyViewModel, *, page_key: str = "overview") -> None:
        self.current_study = study
        self.study_name_label.setText(study.name)
        persistent = self.study_service.current_study is not None
        if persistent:
            self.study_banner.clear()
            self.study_banner.hide()
        else:
            self.study_banner.setText(
                "LEGACY PROJECT — This schema-v1 file is available for inspection. "
                "Migrate it to a study directory before adding subjects."
            )
            self.study_banner.show()
        self.overview_page.set_study(study)
        self.subjects_page.set_study(study)
        self.reviews_page.set_study(study)
        self.results_page.set_study(study)
        self.settings_page.set_study_state(
            persistent=persistent,
            blinded=study.blinded_review,
        )
        self.settings_page.set_input_folders(
            mri_path=study.mri_input_folder,
            t1_path=study.t1_input_folder,
            t2_path=study.t2_input_folder,
            enabled=persistent,
        )
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
        self.show_page("workspace")
        self.statusBar().showMessage(f"Opened subject {subject.label}.", 4000)

    def add_subject(self) -> None:
        if self.current_study is None:
            return
        if self.study_service.current_study is None:
            self._show_error(
                "Subjects cannot be added to a legacy project.",
                StudyStateError("Migrate the .lysbbb project to a study directory first."),
            )
            return
        dialog = AddSubjectDialog(
            blinded=self.current_study.blinded_review,
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
            self._show_status_message(
                "Migrate this legacy project before validating MRI inputs."
            )
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
        self._input_validation_thread = thread
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
            self.statusBar().showMessage(
                "Input validation found a problem. Review the affected scan card.",
                10000,
            )
        else:
            self.statusBar().showMessage(
                "Input validation saved. Ready workflows can now advance to their "
                "artifact step.",
                9000,
            )

    def _input_validation_failed(self, error: str) -> None:
        self._set_job_status()
        self._show_error(
            "The MRI inputs could not be validated.",
            StudyStateError(error),
        )

    def _clear_input_validation_thread(self) -> None:
        self._input_validation_thread = None
        self._validation_subject_id = None
        self._validation_return_page = "workspace"
        self._set_job_status()

    def select_t1_brain_mask_release(self) -> bool:
        if self.current_study is None or self.study_service.current_study is None:
            self._show_status_message(
                "Open a persistent study before selecting a T1 brain-mask release."
            )
            return False
        suggested = (
            Path.home()
            / "Library"
            / "Application Support"
            / "LYS BBB"
            / "models"
            / "rs2net-m-seam-v1"
        )
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
            "The RS2-Net source, weights, exact TTA, and M-seam method passed validation.",
            10000,
        )
        return True

    def run_t1_brain_mask_for_subject(self, subject_id: str) -> None:
        if self.current_study is None or self.study_service.current_study is None:
            self._show_status_message(
                "Open a persistent study before generating a T1 brain mask."
            )
            return
        if self._background_job_running():
            self._show_status_message("Another MRI background job is already running.")
            return
        if self.current_study.active_t1_brain_mask_release_label is None:
            default_release = (
                Path.home()
                / "Library"
                / "Application Support"
                / "LYS BBB"
                / "models"
                / "rs2net-m-seam-v1"
            )
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
            "Run the frozen RS2-Net/M-seam method with exact eight-way test-time "
            "augmentation?\n\nThis may take a while on CPU. The generated mask will "
            "remain a draft until explicitly approved.",
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
        self._t1_brain_mask_thread = thread
        self._t1_target_subject_ids = readiness.eligible_subject_ids
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
        self.statusBar().showMessage(
            "T1 brain-mask draft created. Human review is required.",
            12000,
        )

    def _t1_brain_mask_failed(self, error: str) -> None:
        snapshot = self.study_service.current_study
        if snapshot is not None:
            self._set_study(present_study(snapshot), page_key="subjects")
        self._show_error(
            "T1 brain-mask generation did not complete.",
            StudyStateError(error),
        )

    def _clear_t1_brain_mask_thread(self) -> None:
        self._t1_brain_mask_thread = None
        self._t1_target_subject_ids = None
        self._set_job_status()

    def select_t2_model_release(self) -> bool:
        if self.current_study is None or self.study_service.current_study is None:
            self._show_status_message(
                "Open a persistent study before selecting a T2 model release."
            )
            return False
        suggested = Path.home() / "Downloads" / "LYS_v1_RatLesNetV2_mac_inference"
        selected = QFileDialog.getExistingDirectory(
            self,
            "Select frozen RatLesNetV2 release folder",
            str(suggested if suggested.is_dir() else Path.home() / "Downloads"),
        )
        if not selected:
            return False
        try:
            snapshot = self.study_service.register_t2_model_release(
                selected,
                actor=self._reviewer_identity(),
            )
        except StudyStateError as exc:
            self._show_error("The T2 model release could not be registered.", exc)
            return False
        self._set_study(present_study(snapshot), page_key="subjects")
        self.statusBar().showMessage(
            "The five-model RatLesNetV2 release passed checksum and contract validation.",
            10000,
        )
        return True

    def run_t2_inference_for_study(
        self,
        subject_ids: tuple[str, ...] | None = None,
    ) -> None:
        if self.current_study is None:
            return
        if self.study_service.current_study is None:
            self._show_status_message(
                "Migrate this legacy project before running T2 segmentation."
            )
            return
        if self._background_job_running():
            self._show_status_message("Another MRI background job is already running.")
            return
        if self.current_study.active_t2_release_label is None:
            if not self.select_t2_model_release():
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
            f"Run the frozen five-model ensemble for "
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
        self._t2_inference_thread = thread
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
        self.statusBar().showMessage(
            f"T2 inference created {len(targets)} draft lesion mask(s). "
            "Human review is required.",
            12000,
        )

    def _t2_inference_failed(self, error: str) -> None:
        snapshot = self.study_service.current_study
        if snapshot is not None:
            self._set_study(present_study(snapshot), page_key="subjects")
        self._show_error("T2 lesion inference did not complete.", StudyStateError(error))

    def _clear_t2_inference_thread(self) -> None:
        self._t2_inference_thread = None
        self._t2_target_subject_ids = None
        self._set_job_status()

    def manually_edit_review_mask(
        self,
        subject_id: str,
        artifact_id: str,
        *,
        return_page: str = "reviews",
    ) -> None:
        if self._review_workflow_key(artifact_id) == "t1_brain_mask":
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
        if self._review_workflow_key(artifact_id) == "t1_brain_mask":
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
        if self._review_workflow_key(artifact_id) == "t1_brain_mask":
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
                "Open a persistent study before editing a T1 brain mask."
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
        self._refresh_after_t1_brain_mask_review(
            snapshot,
            subject_id,
            return_page=return_page,
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
                "Open a persistent study to approve a real T1 brain mask."
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
        self._refresh_after_t1_brain_mask_review(
            snapshot,
            subject_id,
            return_page=return_page,
        )
        self.statusBar().showMessage(
            "T1 brain mask approved for downstream registration and analysis.",
            12000,
        )

    def _refresh_after_t1_brain_mask_review(
        self,
        snapshot: StudySnapshot,
        subject_id: str,
        *,
        return_page: str,
    ) -> None:
        if return_page == "reviews":
            self._set_study(present_study(snapshot), page_key="reviews")
            self.reviews_page.focus_subject(subject_id)
            return
        self._set_study(present_study(snapshot), page_key="subjects")
        self.open_subject(subject_id)
        self.workspace_page.tabs.setCurrentWidget(
            self.workspace_page.t1_brain_mask_panel
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
                "Open a persistent study before editing a T2 lesion mask."
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
        self._refresh_after_t2_review(snapshot, subject_id, return_page=return_page)
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

    def approve_t2_mask(
        self,
        subject_id: str,
        artifact_id: str,
        *,
        return_page: str = "workspace",
    ) -> None:
        if self.current_study is None or self.study_service.current_study is None:
            self._show_status_message(
                "Open a persistent study to approve a real T2 lesion mask."
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
        self._refresh_after_t2_review(snapshot, subject_id, return_page=return_page)
        self.statusBar().showMessage(
            "T2 lesion mask approved; the official native-space volume is available.",
            12000,
        )

    def _refresh_after_t2_review(
        self,
        snapshot: StudySnapshot,
        subject_id: str,
        *,
        return_page: str,
    ) -> None:
        if return_page == "reviews":
            self._set_study(present_study(snapshot), page_key="reviews")
            self.reviews_page.focus_subject(subject_id)
            return
        self._set_study(present_study(snapshot), page_key="subjects")
        self.open_subject(subject_id)
        self.workspace_page.tabs.setCurrentWidget(self.workspace_page.t2_panel)

    def export_approved_t2_results_csv(self) -> None:
        if self.current_study is None or self.study_service.current_study is None:
            self._show_status_message(
                "Open a persistent study with approved T2 results to create this export."
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
        self.statusBar().showMessage(
            f"Exported {exported.row_count} approved T2 result(s) to {exported.path}.",
            12000,
        )

    def bulk_flip_subjects(self, subject_ids: tuple[str, ...]) -> None:
        if self.current_study is None or not subject_ids:
            return
        if self.study_service.current_study is None:
            self._show_status_message(
                "Migrate this legacy project before creating flipped MRI versions."
            )
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
            self._show_status_message(
                "Migrate this legacy project before assigning subject groups."
            )
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
            persistent=True,
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
            self._show_status_message(
                "Legacy schema-v1 projects do not contain the canonical study audit history."
            )
            return
        try:
            events = self.study_service.list_audit_events()
        except StudyStateError as exc:
            self._show_error("The audit history could not be opened.", exc)
            return
        AuditHistoryDialog(events, self).exec()

    def select_input_folder(self, kind: str) -> None:
        if self.current_study is None or self.study_service.current_study is None:
            self._show_status_message(
                "Create or migrate a persistent study before selecting source folders."
            )
            return
        current = (
            self.current_study.mri_input_folder
            if kind == "mri"
            else self.current_study.t1_input_folder
            if kind == "t1"
            else self.current_study.t2_input_folder
        )
        selected = QFileDialog.getExistingDirectory(
            self,
            "Select folder containing Bruker sessions or NIfTI MRI files"
            if kind == "mri"
            else f"Select {kind.upper()} source folder",
            str(current or Path.home()),
        )
        if not selected:
            return
        if kind == "mri":
            self._discover_and_review_mri(Path(selected))
            return
        try:
            snapshot = self.study_service.set_input_folder(
                kind,
                selected,
                actor=self._reviewer_identity(),
            )
        except StudyStateError as exc:
            self._show_error("The source folder could not be saved.", exc)
            return
        self._set_study(present_study(snapshot), page_key="settings")
        self.statusBar().showMessage(
            f"{kind.upper()} source folder saved. Files remain in their original location.",
            8000,
        )

    def select_mri_source_folder(self) -> None:
        if self.current_study is None or self.study_service.current_study is None:
            self._show_status_message(
                "Create or migrate a persistent study before importing MRI data."
            )
            return
        current = self.current_study.mri_input_folder
        selected = QFileDialog.getExistingDirectory(
            self,
            "Select folder containing Bruker sessions or NIfTI MRI files",
            str(current or Path.home()),
        )
        if selected:
            self._discover_and_review_mri(Path(selected))

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
        proposed = [
            scan for scan in report.scans if scan.suggested_role.value != "IGNORE"
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
        dialog = ScanImportReviewDialog(report, self)
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
        self._scan_import_thread = thread
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
            self.statusBar().showMessage(
                f"{self._scan_operation_name} finished with {failed} conversion "
                "failure(s). Open a subject "
                "to inspect the recorded error.",
                12000,
            )
        elif self._scan_operation_name == "MRI batch flip":
            self.statusBar().showMessage(
                "MRI batch flip finished. New versioned inputs and provenance were saved; "
                "previous versions were retained.",
                10000,
            )
        else:
            self.statusBar().showMessage(
                "MRI import finished. Converted NIfTI inputs and provenance were saved "
                "inside the study.",
                10000,
            )

    def _scan_import_failed(self, error: str) -> None:
        self._set_job_status()
        self._show_error("The MRI import plan could not be started.", StudyStateError(error))

    def _clear_scan_import_thread(self) -> None:
        self._scan_import_thread = None
        self._scan_operation_name = "MRI import"

    def _handle_blinding_toggle(self, blinded: bool) -> None:
        if self.current_study is None:
            return
        if self.study_service.current_study is None:
            self.settings_page.set_study_state(persistent=False, blinded=True)
            self.set_blinded_review(True)
            return
        if blinded:
            self.settings_page.set_study_state(persistent=True, blinded=False)
            self.set_blinded_review(False)
            self._show_status_message("An unblinded study cannot be blinded again.")
            return
        confirmation = UnblindingDialog(self)
        if confirmation.exec() != QDialog.DialogCode.Accepted:
            self.settings_page.set_study_state(persistent=True, blinded=True)
            self.set_blinded_review(True)
            return
        try:
            snapshot = self.study_service.unblind(reviewer=self._reviewer_identity())
        except StudyStateError as exc:
            self.settings_page.set_study_state(persistent=True, blinded=True)
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
        self.statusBar().showMessage(message, 9000)

    def _set_job_status(self, text: str | None = None) -> None:
        self.jobs_label.setVisible(text is not None)
        self.jobs_label.setText(text or "")

    def _reviewer_identity(self) -> str:
        reviewer = self.settings_page.reviewer.text().strip()
        return reviewer or "Local researcher"

    def _background_job_running(self) -> bool:
        return bool(
            (
                self._scan_import_thread is not None
                and self._scan_import_thread.isRunning()
            )
            or (
                self._input_validation_thread is not None
                and self._input_validation_thread.isRunning()
            )
            or (
                self._t2_inference_thread is not None
                and self._t2_inference_thread.isRunning()
            )
            or (
                self._t1_brain_mask_thread is not None
                and self._t1_brain_mask_thread.isRunning()
            )
        )

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
        message.setWindowTitle("LYS BBB Scientific Workflows")
        message.setText(summary)
        message.setInformativeText(str(exc))
        message.exec()
