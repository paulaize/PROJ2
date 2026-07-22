"""UI guidance for a managed external T2 mask edit session."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from lys_bbb_app.ui.widgets import ElidedLabel


class T2ManualEditDialog(QDialog):
    """Wait for the user to save a managed mask copy in ITK-SNAP."""

    def __init__(
        self,
        editable_mask_path: Path,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Edit T2 lesion mask in ITK-SNAP")
        self.setMinimumWidth(540)
        layout = QVBoxLayout(self)

        instructions = QLabel(
            "ITK-SNAP has opened the native T2 with an editable copy of the current "
            "mask. Make any corrections, save over that mask, and close ITK-SNAP. "
            "Then choose Use saved mask below."
        )
        instructions.setWordWrap(True)
        instructions.setObjectName("infoBanner")
        layout.addWidget(instructions)

        consequence = QLabel(
            "The saved edit will be validated and stored as the subject's new active "
            "human-corrected mask version. The previous mask remains unchanged in the "
            "study history. Explicit approval is still required for an official volume."
        )
        consequence.setWordWrap(True)
        consequence.setObjectName("muted")
        layout.addWidget(consequence)

        path_label = QLabel("Managed editable mask")
        path_label.setObjectName("metadata")
        layout.addWidget(path_label)
        path_value = ElidedLabel(str(editable_mask_path))
        path_value.setToolTip(str(editable_mask_path))
        layout.addWidget(path_value)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Cancel
            | QDialogButtonBox.StandardButton.Ok
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Use saved mask")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)


class T1BrainMaskManualEditDialog(QDialog):
    """Wait for the user to save a managed T1 brain-mask copy in ITK-SNAP."""

    def __init__(
        self,
        editable_mask_path: Path,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Edit T1 brain mask in ITK-SNAP")
        self.setMinimumWidth(540)
        layout = QVBoxLayout(self)
        instructions = QLabel(
            "ITK-SNAP has opened the native pre-Gd T1 with an editable copy of the "
            "current brain mask. Make any corrections, save over that mask, and "
            "close ITK-SNAP. Then choose Use saved mask below."
        )
        instructions.setWordWrap(True)
        instructions.setObjectName("infoBanner")
        layout.addWidget(instructions)
        consequence = QLabel(
            "The saved edit will be validated and stored as the subject's new active "
            "human-corrected brain-mask version. The previous mask remains unchanged "
            "in study history, and explicit approval is still required."
        )
        consequence.setWordWrap(True)
        consequence.setObjectName("muted")
        layout.addWidget(consequence)
        path_label = QLabel("Managed editable mask")
        path_label.setObjectName("metadata")
        layout.addWidget(path_label)
        path_value = ElidedLabel(str(editable_mask_path))
        path_value.setToolTip(str(editable_mask_path))
        layout.addWidget(path_value)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Cancel
            | QDialogButtonBox.StandardButton.Ok
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Use saved mask")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
