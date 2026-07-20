"""Connected main shell for persistent MRI studies and the design preview."""

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

from lys_bbb.project_service import ProjectService
from lys_bbb.project_state import PROJECT_FILE_SUFFIX, ProjectStateError
from lys_bbb_app.application.study_presenter import present_study
from lys_bbb_app.demo_data import demo_study, empty_study
from lys_bbb_app.domain.scan_import import ScanImportAssignment
from lys_bbb_app.domain.study import StudySnapshot
from lys_bbb_app.domain.view_models import StatusValue, StudyViewModel
from lys_bbb_app.infrastructure.recent_studies import RecentStudiesStore
from lys_bbb_app.infrastructure.scan_import_worker import ScanImportThread
from lys_bbb_app.infrastructure.study_database import StudyStateError
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
    ReviewsPage,
    SettingsPage,
    StudyLauncherPage,
    SubjectsPage,
    SubjectWorkspacePage,
)
from lys_bbb_app.ui.scan_import_dialog import ScanImportReviewDialog
from lys_bbb_app.ui.widgets import StatusBadge, secondary_button


LEGACY_PROJECT_FILTER = f"LYS BBB legacy projects (*{PROJECT_FILE_SUFFIX})"


class MainWindow(QMainWindow):
    """Application shell with persistent MRI import and synthetic downstream pages."""

    def __init__(
        self,
        project_service: ProjectService | None = None,
        study_service: StudyService | None = None,
        recent_store: RecentStudiesStore | None = None,
    ) -> None:
        super().__init__()
        self.project_service = project_service or ProjectService()
        self.study_service = study_service or StudyService()
        self.recent_store = recent_store or RecentStudiesStore()
        self.current_study: StudyViewModel | None = None
        self.blinded_review = False
        self.nav_buttons: dict[str, QPushButton] = {}
        self.page_indices: dict[str, int] = {}
        self._scan_import_thread: ScanImportThread | None = None
        self._scan_operation_name = "MRI import"

        self.setWindowTitle("LYS BBB Scientific Workflows")
        self.resize(1440, 900)
        self.setMinimumSize(1180, 760)
        self._build_actions()
        self._build_ui()
        self.statusBar().showMessage("Choose a study or open the design preview.")

    def _build_actions(self) -> None:
        file_menu = self.menuBar().addMenu("&File")
        preview_action = QAction("Open &design preview", self)
        preview_action.setShortcut("Ctrl+D")
        preview_action.triggered.connect(self.open_design_preview)
        file_menu.addAction(preview_action)

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
        self.launcher_page.preview_requested.connect(self.open_design_preview)
        self.launcher_page.create_requested.connect(self.create_project)
        self.launcher_page.open_requested.connect(self.open_project)
        self.launcher_page.migrate_requested.connect(self.migrate_legacy_project)
        self.launcher_page.recent_open_requested.connect(self.open_project_path)
        self.launcher_page.set_recent_studies(self.recent_store.list())
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
        self.preview_banner = QLabel()
        self.preview_banner.setObjectName("previewBanner")
        self.preview_banner.setWordWrap(True)
        self.preview_banner.setContentsMargins(20, 4, 20, 4)
        content_layout.addWidget(self.preview_banner)

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
        self.subjects_page.subjects_flip_requested.connect(self.bulk_flip_subjects)
        self.subjects_page.subject_remove_requested.connect(self.remove_subject)
        self.subjects_page.subject_restore_requested.connect(self.restore_subject)
        self.subjects_page.preview_action.connect(self._show_preview_message)
        self.subjects_page.add_subject_requested.connect(self.add_subject)
        self.subjects_page.import_mri_requested.connect(self.select_mri_source_folder)
        self.subjects_page.group_assignment_requested.connect(self.manage_groups)
        self.subjects_page.audit_history_requested.connect(self.show_audit_history)
        self.workspace_page.back_requested.connect(lambda: self.show_page("subjects"))
        self.workspace_page.open_mri_requested.connect(
            self.open_subject_mri_in_itksnap
        )
        self.workspace_page.rename_requested.connect(self.rename_subject)
        self.workspace_page.review_requested.connect(self.open_reviews_for_subject)
        self.workspace_page.preview_action.connect(self._show_preview_message)
        self.reviews_page.decision_recorded.connect(self._show_preview_message)
        self.results_page.preview_action.connect(self._show_preview_message)
        self.settings_page.preview_action.connect(self._show_preview_message)
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
        layout.addWidget(self.jobs_label)
        layout.addSpacing(16)
        layout.addWidget(StatusBadge(StatusValue("Backend ready", "ready")))
        help_button = secondary_button("Help")
        help_button.setEnabled(False)
        help_button.setToolTip("Help content will be added after the navigation stabilizes.")
        layout.addWidget(help_button)
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
        caption = QLabel("STUDY WORKSPACE")
        caption.setObjectName("navCaption")
        layout.addWidget(caption)
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
        self.release_label = QLabel("MVP design preview\nNo scientific jobs are connected")
        self.release_label.setObjectName("navCaption")
        self.release_label.setWordWrap(True)
        layout.addWidget(self.release_label)
        return sidebar

    def open_design_preview(self) -> None:
        self.project_service.close_project()
        self.study_service.close_study()
        self._set_study(demo_study())
        self.statusBar().showMessage(
            "Design preview opened. All subjects and decisions are synthetic.",
            8000,
        )

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
        self.project_service.close_project()
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
        if path.suffix.lower() == PROJECT_FILE_SUFFIX:
            return self._open_legacy_project_path(path)
        try:
            study = self.study_service.open_study(path)
        except (StudyStateError, OSError) as exc:
            self._show_error("The study could not be opened.", exc)
            return False
        self._record_recent(study)
        self.project_service.close_project()
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
        except (ProjectStateError, StudyStateError, OSError) as exc:
            self._show_error("The legacy project could not be migrated.", exc)
            return
        self._record_recent(study)
        self.project_service.close_project()
        self._set_study(present_study(study))
        self.statusBar().showMessage(
            "Legacy project migrated without modifying the original .lysbbb file.",
            9000,
        )

    def _open_legacy_project_path(self, database_path: Path) -> bool:
        try:
            project = self.project_service.open_project(database_path)
        except (ProjectStateError, OSError) as exc:
            self._show_error("The legacy project could not be opened.", exc)
            return False
        self.study_service.close_study()
        self._set_study(empty_study(project))
        self.statusBar().showMessage(
            "Legacy project opened read-only for inspection. Use Migrate legacy project "
            "to add persistent subjects.",
            9000,
        )
        return True

    def _set_study(self, study: StudyViewModel, *, page_key: str = "overview") -> None:
        self.current_study = study
        self.study_name_label.setText(study.name)
        persistent = self.study_service.current_study is not None and not study.is_demo
        if study.is_demo:
            self.release_label.setText(
                "MVP design preview\nNo scientific jobs are connected"
            )
            self.preview_banner.setObjectName("previewBanner")
            self.preview_banner.setText(
                "DESIGN PREVIEW — All subjects, images, reviews, jobs, and results are synthetic. "
                "Interactions are not persisted."
            )
        elif persistent:
            self.release_label.setText(
                "Persistent study\nMRI import and conversion connected"
            )
            self.preview_banner.setObjectName("infoBanner")
            self.preview_banner.setText(
                f"PERSISTENT STUDY — {len(study.subjects)} subjects stored in "
                f"{study.root_path}. MRI discovery and versioned NIfTI conversion are "
                "connected; mask, registration, quantification, and review jobs remain pending."
            )
        else:
            self.release_label.setText(
                "Legacy project inspection\nMigration is required for subjects"
            )
            self.preview_banner.setObjectName("infoBanner")
            self.preview_banner.setText(
                "LEGACY PROJECT — This schema-v1 file is available for inspection. "
                "Migrate it to a study directory before adding subjects."
            )
        self.preview_banner.style().unpolish(self.preview_banner)
        self.preview_banner.style().polish(self.preview_banner)
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
        if self.current_study.is_demo:
            self._show_preview_message(
                "Subject creation is disabled for synthetic preview records. Create a "
                "persistent study to add real subjects."
            )
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
        if self.current_study.is_demo:
            self._show_preview_message(
                "Synthetic subjects cannot be removed. Create a persistent study to "
                "test subject removal."
            )
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
        if self.current_study.is_demo:
            self._show_preview_message(
                "Synthetic subject names cannot be changed. Open a persistent study to "
                "rename a subject."
            )
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
        if self.current_study.is_demo:
            self._show_preview_message(
                "The design preview has no real NIfTI files to open in ITK-SNAP."
            )
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

    def bulk_flip_subjects(self, subject_ids: tuple[str, ...]) -> None:
        if self.current_study is None or not subject_ids:
            return
        if self.current_study.is_demo:
            self._show_preview_message(
                "Synthetic preview images cannot create persistent flipped versions."
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
        if self.current_study.blinded_review:
            confirmation = UnblindingDialog(self)
            if confirmation.exec() != QDialog.DialogCode.Accepted:
                return
            if self.current_study.is_demo:
                self.settings_page.blinded_review.setChecked(False)
            else:
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
        persistent = not self.current_study.is_demo and self.study_service.current_study is not None
        assignment = GroupAssignmentDialog(
            self.current_study.subjects,
            self.current_study.group_definitions,
            persistent=persistent,
            parent=self,
        )
        if assignment.exec() != QDialog.DialogCode.Accepted:
            return
        if not persistent:
            self._show_preview_message(
                "Group assignments were previewed but not persisted."
            )
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
        if self.current_study.is_demo:
            self._show_preview_message(
                "Synthetic preview interactions do not create persistent audit events."
            )
            return
        if self.study_service.current_study is None:
            self._show_preview_message(
                "Legacy schema-v1 projects do not contain the Phase 1 audit history."
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
            self._show_preview_message(
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
            self._show_preview_message(
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
        if self._scan_import_thread is not None and self._scan_import_thread.isRunning():
            self._show_preview_message("An MRI conversion import is already running.")
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
        self.jobs_label.setText(f"1 {operation_name.lower()} running")
        self.statusBar().showMessage(
            f"{operation_name}: creating {len(assignments)} versioned NIfTI input(s)…"
        )
        thread.start()

    def _show_scan_import_progress(self, current: int, total: int, message: str) -> None:
        self.jobs_label.setText(f"MRI import {current}/{total}")
        self.statusBar().showMessage(message)

    def _scan_import_completed(
        self,
        snapshot: StudySnapshot,
        failed: int,
    ) -> None:
        self._set_study(present_study(snapshot), page_key="subjects")
        self.jobs_label.setText("0 jobs running")
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
        self.jobs_label.setText("0 jobs running")
        self._show_error("The MRI import plan could not be started.", StudyStateError(error))

    def _clear_scan_import_thread(self) -> None:
        self._scan_import_thread = None
        self._scan_operation_name = "MRI import"

    def _handle_blinding_toggle(self, blinded: bool) -> None:
        if self.current_study is None or self.current_study.is_demo:
            self.set_blinded_review(blinded)
            return
        if self.study_service.current_study is None:
            self.settings_page.set_study_state(persistent=False, blinded=True)
            self.set_blinded_review(True)
            return
        if blinded:
            self.settings_page.set_study_state(persistent=True, blinded=False)
            self.set_blinded_review(False)
            self._show_preview_message("An unblinded study cannot be blinded again.")
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

    def open_reviews_for_subject(self, subject_id: str) -> None:
        self.show_page("reviews")
        self.reviews_page.focus_subject(subject_id)

    def show_launcher(self) -> None:
        if self._scan_import_thread is not None and self._scan_import_thread.isRunning():
            self._show_preview_message(
                "Wait for the current MRI conversion import before changing studies."
            )
            return
        self.launcher_page.set_recent_studies(self.recent_store.list())
        self.root_stack.setCurrentIndex(0)
        self.statusBar().showMessage("Choose another study or open the design preview.")

    def close_study(self) -> None:
        if self._scan_import_thread is not None and self._scan_import_thread.isRunning():
            self._show_preview_message(
                "Wait for the current MRI conversion import before closing the study."
            )
            return
        self.project_service.close_project()
        self.study_service.close_study()
        self.current_study = None
        self.study_name_label.setText("No study open")
        self.close_study_action.setEnabled(False)
        self.show_launcher()

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._scan_import_thread is not None and self._scan_import_thread.isRunning():
            self._show_preview_message(
                "Wait for the current MRI conversion import before quitting."
            )
            event.ignore()
            return
        super().closeEvent(event)

    def _show_preview_message(self, message: str) -> None:
        self.statusBar().showMessage(message, 9000)

    def _reviewer_identity(self) -> str:
        reviewer = self.settings_page.reviewer.text().strip()
        return reviewer or "Local researcher"

    def _record_recent(self, study: StudySnapshot) -> None:
        try:
            self.recent_store.record(study)
            self.launcher_page.set_recent_studies(self.recent_store.list())
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
