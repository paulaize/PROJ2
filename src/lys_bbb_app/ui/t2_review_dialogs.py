"""Small dialogs for explicit T2 review decisions."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QMessageBox,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from lys_bbb_app.domain.t2_lesion import T2_REJECTION_ISSUES


class T2RejectionDialog(QDialog):
    """Collect the mandatory reason and notes for one immutable rejection."""

    ISSUES = T2_REJECTION_ISSUES

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Reject T2 lesion mask")
        self.setMinimumWidth(480)
        layout = QVBoxLayout(self)
        warning = QLabel(
            "This decision is immutable. The rejected artifact remains in the study "
            "history and will not produce an official lesion volume."
        )
        warning.setWordWrap(True)
        warning.setObjectName("infoBanner")
        layout.addWidget(warning)
        form = QFormLayout()
        self.issue = QComboBox()
        for label, code in self.ISSUES:
            self.issue.addItem(label, code)
        self.notes = QTextEdit()
        self.notes.setPlaceholderText(
            "Describe what is wrong and what should be corrected."
        )
        self.notes.setMinimumHeight(110)
        form.addRow("Issue", self.issue)
        form.addRow("Required notes", self.notes)
        layout.addLayout(form)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Cancel
            | QDialogButtonBox.StandardButton.Ok
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Reject mask")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def accept(self) -> None:
        if not self.notes_text():
            QMessageBox.warning(
                self,
                "Rejection notes required",
                "Explain why this mask is being rejected.",
            )
            return
        super().accept()

    def issue_code(self) -> str:
        return str(self.issue.currentData())

    def notes_text(self) -> str:
        return self.notes.toPlainText().strip()
