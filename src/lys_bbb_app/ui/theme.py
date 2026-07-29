"""Application-wide visual theme for the desktop application."""

from __future__ import annotations

from PySide6.QtWidgets import QApplication


APP_STYLE = """
QMainWindow, QWidget#appRoot, QStackedWidget#rootStack {
    background: #f2f5f7;
    color: #13283f;
    font-family: "Avenir Next", "Segoe UI", "Helvetica Neue", sans-serif;
    font-size: 14px;
}
QWidget#launcherPage { background: #f3f6f8; }
QScrollArea, QScrollArea > QWidget > QWidget, QStackedWidget {
    background: transparent;
    border: 0;
}
QMenuBar {
    background: #fbfcfd;
    color: #31465d;
    border-bottom: 1px solid #d8e1e7;
    padding: 2px 6px;
}
QMenuBar::item { background: transparent; padding: 4px 8px; }
QMenuBar::item:selected { background: #e8f0f3; border-radius: 4px; }
QMenu {
    background: #ffffff;
    color: #183149;
    border: 1px solid #cfdbe3;
    padding: 5px;
}
QMenu::item { padding: 6px 24px 6px 9px; border-radius: 4px; }
QMenu::item:selected { background: #e1eff1; color: #0a4f61; }
QMenu::separator { height: 1px; background: #e1e8ed; margin: 5px 7px; }
QFrame#topBar { background: #fbfcfd; border-bottom: 1px solid #d8e1e7; }
QFrame#sideBar {
    background: #0b2942;
    border-right: 1px solid #163b55;
}
QFrame#card, QFrame#workflowCard, QFrame#panel,
QFrame#recentCard, QFrame#readinessCard {
    background: #ffffff;
    border: 1px solid #d3dee6;
    border-radius: 8px;
}
QFrame#launcherHero {
    background: #ffffff;
    border: 1px solid #d3dee6;
    border-left: 4px solid #18a5a6;
    border-radius: 8px;
}
QFrame#workflowCard {
    border-color: #d3dee6;
    border-top-width: 3px;
}
QFrame#workflowCard[workflow="t1"] { border-top-color: #168b96; }
QFrame#workflowCard[workflow="t2"] { border-top-color: #5876a9; }
QFrame#workflowCard[workflow="combined"] { border-top-color: #78909c; }
QFrame#readinessCard { border-color: #cbd9e2; }
QFrame#nextActionCard {
    background: #ffffff;
    border: 1px solid #cbdbe3;
    border-left: 4px solid #168b96;
    border-radius: 8px;
}
QFrame#subtleCard {
    background: #f7f9fa;
    border: 1px solid #dce5ea;
    border-radius: 6px;
}
QFrame#embeddedEmptyState { background: transparent; border: 0; }
QFrame#softDivider { color: #d7e1e7; }
QFrame#brandMark {
    background: #16a0a1;
    border: 1px solid #4fc0bf;
    border-radius: 6px;
}
QLabel#brandMarkText {
    color: #ffffff;
    font-size: 12px;
    font-weight: 800;
}
QLabel#appWordmark { color: #ffffff; font-size: 19px; font-weight: 750; }
QLabel#brandCaption, QLabel#navCaption {
    color: #91aabd;
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 1px;
}
QLabel#sidebarFoot {
    color: #91aabd;
    font-size: 10px;
    letter-spacing: 1px;
}
QLabel#launcherWordmark { color: #0c2b45; font-size: 20px; font-weight: 750; }
QLabel#launcherCaption, QLabel#pageEyebrow {
    color: #557083;
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 1px;
}
QLabel#pageTitle { color: #0b2039; font-size: 27px; font-weight: 700; }
QLabel#sectionTitle { color: #102943; font-size: 18px; font-weight: 650; }
QLabel#cardTitle { color: #102943; font-size: 16px; font-weight: 650; }
QLabel#studyName { color: #102943; font-size: 17px; font-weight: 700; }
QLabel#muted { color: #5c7085; }
QLabel#metadata { color: #6f8193; font-size: 11px; }
QLabel[technicalValue="true"] {
    color: #344d62;
    font-family: "Menlo", "Consolas", monospace;
    font-size: 12px;
}
QLabel#readinessTitle { color: #092346; font-size: 17px; font-weight: 700; }
QLabel#readinessValue { color: #071b3b; font-size: 24px; font-weight: 700; }
QLabel#readinessLabel { color: #52657e; font-size: 12px; }
QLabel#workflowFact { color: #0b294d; font-size: 16px; font-weight: 700; }
QLabel#emptyStateMark { color: #8295a3; font-size: 28px; font-weight: 300; }
QLabel#warningBanner {
    background: #fff7e8;
    color: #79510e;
    border: 1px solid #ead5a7;
    border-left: 3px solid #d29a2d;
    border-radius: 6px;
    padding: 8px 12px;
}
QLabel#infoBanner {
    background: #eef5f7;
    color: #194d61;
    border: 1px solid #cbdfe5;
    border-left: 3px solid #4c96a3;
    border-radius: 6px;
    padding: 8px 12px;
}
QLabel#errorBanner {
    background: #fdecec;
    color: #9f2f2f;
    border: 1px solid #efc0c0;
    border-left: 3px solid #c94a4a;
    border-radius: 6px;
    padding: 8px 12px;
}
QLabel[issueSeverity="warning"] {
    background: #fff6e4;
    color: #86570a;
    border: 1px solid #efd49d;
    border-radius: 6px;
    padding: 7px 9px;
}
QLabel[issueSeverity="error"] {
    background: #fdecec;
    color: #9f2f2f;
    border: 1px solid #efc0c0;
    border-radius: 6px;
    padding: 7px 9px;
}
QPushButton {
    background: #0b5573;
    color: white;
    border: 0;
    border-radius: 6px;
    padding: 8px 14px;
    min-height: 20px;
    font-weight: 600;
}
QPushButton:hover { background: #0a6b7c; }
QPushButton:pressed { background: #083f59; }
QPushButton:focus { border: 1px solid #54b9bd; }
QPushButton:disabled { background: #dce4e9; color: #8a99a5; }
QPushButton[kind="secondary"] {
    background: #fbfcfd;
    color: #173f5d;
    border: 1px solid #aebfcb;
}
QPushButton[kind="secondary"]:hover {
    background: #eaf3f5;
    color: #0b5364;
    border-color: #6299a7;
}
QPushButton[kind="secondary"]:disabled {
    background: #eef2f4;
    color: #8996a2;
    border-color: #d5dee4;
}
QToolButton[kind="disclosure"] {
    background: transparent;
    color: #3e596e;
    border: 0;
    padding: 4px 2px;
    font-weight: 600;
}
QToolButton[kind="disclosure"]:hover { color: #087b85; }
QPushButton[kind="danger"] { background: #b94040; }
QPushButton[kind="danger"]:hover { background: #9e3030; }
QPushButton[kind="nav"] {
    background: transparent;
    color: #d2dee7;
    text-align: left;
    padding: 10px 13px;
    border-radius: 5px;
    font-weight: 500;
}
QPushButton[kind="nav"]:hover { background: #143a54; color: white; }
QPushButton[kind="nav"]:checked {
    background: #15576d;
    color: white;
    border-left: 3px solid #43c4c0;
    font-weight: 650;
}
QPushButton[kind="reviewFilter"] {
    background: #ffffff;
    color: #0a315e;
    border: 1px solid #b8c8d5;
    text-align: left;
    padding: 10px 12px;
}
QPushButton[kind="reviewFilter"]:checked {
    background: #dceff1;
    color: #075269;
    border: 1px solid #4d9aa4;
}
QPushButton[kind="reviewItem"] {
    background: #f7fafc;
    color: #163653;
    border: 1px solid #d5e0e8;
    text-align: left;
    padding: 11px 12px;
}
QPushButton[kind="reviewItem"]:hover { background: #edf5f8; }
QPushButton[kind="reviewItem"]:checked {
    background: #d8eef1;
    color: #073f56;
    border: 1px solid #51a0a8;
}
QLineEdit, QComboBox, QSpinBox, QTextEdit, QPlainTextEdit {
    background: #ffffff;
    color: #17304f;
    border: 1px solid #bdccd6;
    border-radius: 6px;
    padding: 7px 9px;
    selection-background-color: #168b96;
}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus,
QTextEdit:focus, QPlainTextEdit:focus { border: 1px solid #168b96; }
QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled {
    background: #eef2f4;
    color: #83929e;
    border-color: #d5dee4;
}
QComboBox::drop-down { border: 0; width: 24px; }
QCheckBox { color: #2a4258; spacing: 7px; }
QTableView, QListWidget {
    background: #ffffff;
    border: 1px solid #d1dde5;
    border-radius: 7px;
    gridline-color: #e5ebef;
    selection-background-color: #dceff0;
    selection-color: #10233f;
    alternate-background-color: #f7f9fa;
    outline: 0;
}
QTableView::item { padding: 8px 6px; }
QTableView::item:selected { border-bottom: 1px solid #b9dadd; }
QHeaderView::section {
    background: #edf2f4;
    color: #3e5569;
    border: 0;
    border-bottom: 1px solid #cfdbe2;
    padding: 8px 7px;
    font-weight: 650;
    font-size: 12px;
}
QGroupBox {
    font-weight: 650;
    color: #0b2142;
    background: #ffffff;
    border: 1px solid #d2dde5;
    border-radius: 7px;
    margin-top: 10px;
    padding: 14px 10px 10px 10px;
}
QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 5px; }
QTabWidget::pane {
    background: #ffffff;
    border: 1px solid #d2dde5;
    border-radius: 0 0 7px 7px;
    top: -1px;
}
QTabBar { background: transparent; }
QTabBar::tab {
    background: transparent;
    color: #5b6f82;
    border: 0;
    border-bottom: 2px solid transparent;
    padding: 10px 13px;
    margin-right: 2px;
    font-weight: 550;
}
QTabBar::tab:hover { color: #174f62; background: #eaf1f3; }
QTabBar::tab:selected {
    color: #0b6873;
    border-bottom: 2px solid #18a5a6;
    font-weight: 650;
}
QSplitter::handle { background: #dbe4e9; }
QSplitter::handle:horizontal { width: 1px; margin: 10px 2px; }
QProgressBar {
    background: #e4eaee;
    color: #294357;
    border: 0;
    border-radius: 4px;
    text-align: center;
    min-height: 8px;
}
QProgressBar::chunk { background: #168b96; border-radius: 4px; }
QScrollBar:vertical { background: transparent; width: 11px; margin: 2px; }
QScrollBar::handle:vertical { background: #aebcc5; border-radius: 5px; min-height: 30px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QStatusBar {
    background: #fbfcfd;
    color: #5b6f80;
    border-top: 1px solid #d8e1e7;
    font-size: 12px;
}
QToolTip { background: #082a4d; color: white; border: 0; padding: 5px; }
"""


def apply_theme(app: QApplication) -> None:
    app.setStyle("Fusion")
    app.setStyleSheet(APP_STYLE)
