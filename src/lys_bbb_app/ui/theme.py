"""Application-wide visual theme for the desktop application."""

from __future__ import annotations

from PySide6.QtWidgets import QApplication


APP_STYLE = """
QMainWindow, QWidget#appRoot, QStackedWidget#rootStack {
    background: #f7f9fc;
    color: #10233f;
    font-family: "Avenir Next", "Helvetica Neue", sans-serif;
    font-size: 14px;
}
QWidget#launcherPage { background: #f4f7fa; }
QFrame#topBar { background: #ffffff; border-bottom: 1px solid #dce5ec; }
QFrame#sideBar {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 #062f55, stop:1 #041e3c);
}
QFrame#card, QFrame#workflowCard, QFrame#panel,
QFrame#recentCard, QFrame#readinessCard {
    background: #ffffff;
    border: 1px solid #dbe4eb;
    border-radius: 12px;
}
QFrame#workflowCard { border-color: #d6e1e9; }
QFrame#readinessCard { border-color: #d3e0e8; }
QFrame#subtleCard {
    background: #f6f9fb;
    border: 1px solid #e0e8ee;
    border-radius: 8px;
}
QFrame#embeddedEmptyState { background: transparent; border: 0; }
QFrame#softDivider { color: #dbe4ea; }
QLabel#appWordmark { color: #ffffff; font-size: 18px; font-weight: 700; }
QLabel#navCaption { color: #9bb2c5; font-size: 11px; font-weight: 700; }
QLabel#pageTitle { color: #071b3b; font-size: 29px; font-weight: 700; }
QLabel#sectionTitle { color: #0b2142; font-size: 19px; font-weight: 650; }
QLabel#cardTitle { color: #0a2143; font-size: 17px; font-weight: 650; }
QLabel#muted { color: #607189; }
QLabel#metadata { color: #758499; font-size: 12px; }
QLabel#readinessTitle { color: #092346; font-size: 17px; font-weight: 700; }
QLabel#readinessValue { color: #071b3b; font-size: 24px; font-weight: 700; }
QLabel#readinessLabel { color: #52657e; font-size: 12px; }
QLabel#workflowFact { color: #0b294d; font-size: 16px; font-weight: 700; }
QLabel#warningBanner {
    background: #fff6e4;
    color: #86570a;
    border: 1px solid #efd49d;
    border-radius: 6px;
    padding: 8px 12px;
}
QLabel#infoBanner {
    background: #edf5fb;
    color: #164a72;
    border: 1px solid #c8deed;
    border-radius: 6px;
    padding: 8px 12px;
}
QLabel#errorBanner {
    background: #fdecec;
    color: #9f2f2f;
    border: 1px solid #efc0c0;
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
    background: #073f78;
    color: white;
    border: 0;
    border-radius: 7px;
    padding: 8px 14px;
    min-height: 20px;
    font-weight: 600;
}
QPushButton:hover { background: #075a82; }
QPushButton:pressed { background: #052e5d; }
QPushButton:disabled { background: #dbe2e8; color: #8996a2; }
QPushButton[kind="secondary"] {
    background: #ffffff;
    color: #0a315e;
    border: 1px solid #9eb2c5;
}
QPushButton[kind="secondary"]:hover { background: #edf5f8; border-color: #4a879e; }
QPushButton[kind="secondary"]:disabled {
    background: #eef2f5;
    color: #8996a2;
    border-color: #d4dce3;
}
QToolButton[kind="disclosure"] {
    background: transparent;
    color: #36516c;
    border: 0;
    padding: 4px 2px;
    font-weight: 600;
}
QToolButton[kind="disclosure"]:hover { color: #087b85; }
QPushButton[kind="danger"] { background: #b94040; }
QPushButton[kind="danger"]:hover { background: #9e3030; }
QPushButton[kind="nav"] {
    background: transparent;
    color: #d7e2ec;
    text-align: left;
    padding: 11px 16px;
    border-radius: 7px;
    font-weight: 500;
}
QPushButton[kind="nav"]:hover { background: #124465; color: white; }
QPushButton[kind="nav"]:checked {
    background: #0b6d86;
    color: white;
    border-left: 3px solid #45d1cc;
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
    border: 1px solid #c6d3de;
    border-radius: 7px;
    padding: 7px 9px;
    selection-background-color: #0b6d86;
}
QLineEdit:focus, QComboBox:focus, QTextEdit:focus { border: 2px solid #168b9b; }
QTableView, QListWidget {
    background: #ffffff;
    border: 1px solid #d7e1e8;
    border-radius: 10px;
    gridline-color: #e8eef2;
    selection-background-color: #d8eef1;
    selection-color: #10233f;
    alternate-background-color: #f8fafc;
}
QTableView::item { padding: 8px 6px; }
QHeaderView::section {
    background: #f3f7f9;
    color: #29415d;
    border: 0;
    border-bottom: 1px solid #d4e0e7;
    padding: 9px 7px;
    font-weight: 650;
}
QGroupBox {
    font-weight: 650;
    color: #0b2142;
    border: 1px solid #d7e1e8;
    border-radius: 10px;
    margin-top: 10px;
    padding-top: 12px;
}
QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 5px; }
QTabWidget::pane { border: 1px solid #d7e1e8; background: white; border-radius: 8px; }
QTabBar::tab { padding: 8px 14px; color: #566b81; }
QTabBar::tab:selected { color: #087b85; border-bottom: 2px solid #18a7a3; }
QScrollBar:vertical { background: transparent; width: 11px; margin: 2px; }
QScrollBar::handle:vertical { background: #b8c3ca; border-radius: 5px; min-height: 30px; }
QStatusBar { background: #ffffff; color: #5d7083; border-top: 1px solid #dce5ec; }
QToolTip { background: #082a4d; color: white; border: 0; padding: 5px; }
"""


def apply_theme(app: QApplication) -> None:
    app.setStyle("Fusion")
    app.setStyleSheet(APP_STYLE)
