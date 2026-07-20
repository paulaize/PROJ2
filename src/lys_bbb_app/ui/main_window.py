"""Connected main shell for the LYS BBB desktop MVP design preview."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QButtonGroup,
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
from lys_bbb_app.demo_data import demo_study, empty_study
from lys_bbb_app.domain.view_models import StudyViewModel
from lys_bbb_app.ui.pages import (
    OverviewPage,
    ResultsPage,
    ReviewsPage,
    SettingsPage,
    StudyLauncherPage,
    SubjectsPage,
    SubjectWorkspacePage,
)
from lys_bbb_app.ui.widgets import StatusBadge, secondary_button
from lys_bbb_app.domain.view_models import StatusValue


PROJECT_FILTER = f"LYS BBB legacy projects (*{PROJECT_FILE_SUFFIX})"


class MainWindow(QMainWindow):
    """Application shell with real project setup and synthetic workflow pages."""

    def __init__(self, project_service: ProjectService | None = None) -> None:
        super().__init__()
        self.project_service = project_service or ProjectService()
        self.current_study: StudyViewModel | None = None
        self.blinded_review = False
        self.nav_buttons: dict[str, QPushButton] = {}
        self.page_indices: dict[str, int] = {}

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

        create_action = QAction("&Create legacy project…", self)
        create_action.setShortcut("Ctrl+N")
        create_action.triggered.connect(self.create_project)
        file_menu.addAction(create_action)

        open_action = QAction("&Open legacy project…", self)
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
        self.launcher_page.preview_requested.connect(self.open_design_preview)
        self.launcher_page.create_requested.connect(self.create_project)
        self.launcher_page.open_requested.connect(self.open_project)
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
        self.subjects_page.preview_action.connect(self._show_preview_message)
        self.subjects_page.unblinding_requested.connect(
            lambda: self.settings_page.blinded_review.setChecked(False)
        )
        self.workspace_page.back_requested.connect(lambda: self.show_page("subjects"))
        self.workspace_page.review_requested.connect(self.open_reviews_for_subject)
        self.workspace_page.preview_action.connect(self._show_preview_message)
        self.reviews_page.decision_recorded.connect(self._show_preview_message)
        self.results_page.preview_action.connect(self._show_preview_message)
        self.settings_page.preview_action.connect(self._show_preview_message)
        self.settings_page.blinding_changed.connect(self.set_blinded_review)
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
        release = QLabel("MVP design preview\nNo scientific jobs are connected")
        release.setObjectName("navCaption")
        release.setWordWrap(True)
        layout.addWidget(release)
        return sidebar

    def open_design_preview(self) -> None:
        self._set_study(demo_study())
        self.statusBar().showMessage(
            "Design preview opened. All subjects and decisions are synthetic.",
            8000,
        )

    def create_project(self) -> None:
        selected, _filter = QFileDialog.getSaveFileName(
            self,
            "Create legacy LYS BBB project",
            str(Path.home() / f"mouse-mri-project{PROJECT_FILE_SUFFIX}"),
            PROJECT_FILTER,
        )
        if not selected:
            return
        path = Path(selected)
        if not path.name.lower().endswith(PROJECT_FILE_SUFFIX):
            path = path.with_name(path.name + PROJECT_FILE_SUFFIX)
        try:
            project = self.project_service.create_project(path)
        except (ProjectStateError, OSError) as exc:
            self._show_error("The project could not be created.", exc)
            return
        self._set_study(empty_study(project))
        self.statusBar().showMessage("Legacy project created. No dummy subjects were added.", 8000)

    def open_project(self) -> None:
        selected, _filter = QFileDialog.getOpenFileName(
            self,
            "Open legacy LYS BBB project",
            str(Path.home()),
            PROJECT_FILTER,
        )
        if selected:
            self.open_project_path(selected)

    def open_project_path(self, database_path: Path | str) -> bool:
        try:
            project = self.project_service.open_project(database_path)
        except (ProjectStateError, OSError) as exc:
            self._show_error("The project could not be opened.", exc)
            return False
        self._set_study(empty_study(project))
        self.statusBar().showMessage("Legacy project opened. No dummy subjects were added.", 8000)
        return True

    def _set_study(self, study: StudyViewModel) -> None:
        self.current_study = study
        self.study_name_label.setText(study.name)
        if study.is_demo:
            self.preview_banner.setObjectName("previewBanner")
            self.preview_banner.setText(
                "DESIGN PREVIEW — All subjects, images, reviews, jobs, and results are synthetic. "
                "Interactions are not persisted."
            )
        else:
            self.preview_banner.setObjectName("infoBanner")
            self.preview_banner.setText(
                "LEGACY PROJECT — This real schema-v1 project contains no subject records yet. "
                "Use the design preview to explore the planned workflow pages."
            )
        self.preview_banner.style().unpolish(self.preview_banner)
        self.preview_banner.style().polish(self.preview_banner)
        self.overview_page.set_study(study)
        self.subjects_page.set_study(study)
        self.reviews_page.set_study(study)
        self.results_page.set_study(study)
        self.set_blinded_review(self.settings_page.blinded_review.isChecked())
        self.close_study_action.setEnabled(True)
        self.root_stack.setCurrentIndex(1)
        self.show_page("overview")

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
        self.statusBar().showMessage(f"Opened subject {subject_id}.", 4000)

    def set_blinded_review(self, blinded: bool) -> None:
        self.blinded_review = blinded
        self.blinding_badge.setVisible(blinded)
        self.subjects_page.set_blinded_review(blinded)
        self.workspace_page.set_blinded_review(blinded)
        self.results_page.set_blinded_review(blinded)
        mode = "enabled" if blinded else "disabled"
        self.statusBar().showMessage(
            f"Blinded review mode {mode}. Preview settings are not persisted.",
            7000,
        )

    def open_reviews_for_subject(self, subject_id: str) -> None:
        self.show_page("reviews")
        self.reviews_page.focus_subject(subject_id)

    def show_launcher(self) -> None:
        self.root_stack.setCurrentIndex(0)
        self.statusBar().showMessage("Choose another study or reopen the design preview.")

    def close_study(self) -> None:
        self.project_service.close_project()
        self.current_study = None
        self.study_name_label.setText("No study open")
        self.close_study_action.setEnabled(False)
        self.show_launcher()

    def _show_preview_message(self, message: str) -> None:
        self.statusBar().showMessage(message, 9000)

    def _show_error(self, summary: str, exc: Exception) -> None:
        message = QMessageBox(self)
        message.setIcon(QMessageBox.Critical)
        message.setWindowTitle("LYS BBB Scientific Workflows")
        message.setText(summary)
        message.setInformativeText(str(exc))
        message.exec()
