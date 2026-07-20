"""Dialogs for MRI viewing and versioned batch orientation actions."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from lys_bbb_app.domain.scan_import import ScanInputRecord, ScanRole


class MRIInputSelectionDialog(QDialog):
    """Choose which active converted MRI should open in ITK-SNAP."""

    ROLE_LABELS = {
        ScanRole.T1_PRE: "T1 pre-Gd",
        ScanRole.T1_POST: "T1 post-Gd",
        ScanRole.T2: "T2-weighted",
    }

    def __init__(
        self,
        inputs: tuple[ScanInputRecord, ...],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Open MRI in ITK-SNAP")
        self.setModal(True)
        self.setMinimumWidth(620)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 22)
        layout.setSpacing(14)
        title = QLabel("Choose an MRI image")
        title.setObjectName("sectionTitle")
        layout.addWidget(title)
        detail = QLabel(
            "ITK-SNAP opens the selected immutable converted NIfTI as its main image."
        )
        detail.setObjectName("infoBanner")
        detail.setWordWrap(True)
        layout.addWidget(detail)
        self.input = QComboBox()
        for record in inputs:
            path_name = record.output_path.name if record.output_path else "Unavailable"
            self.input.addItem(
                f"{self.ROLE_LABELS[record.role]} · v{record.version:03d} · {path_name}",
                record.id,
            )
        form = QFormLayout()
        form.addRow("MRI input", self.input)
        layout.addLayout(form)
        buttons = QDialogButtonBox(QDialogButtonBox.Cancel | QDialogButtonBox.Open)
        buttons.button(QDialogButtonBox.Open).setText("Open in ITK-SNAP")
        buttons.button(QDialogButtonBox.Cancel).setProperty("kind", "secondary")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def scan_input_id(self) -> str:
        return str(self.input.currentData())


class BulkFlipDialog(QDialog):
    """Collect one explicit, versioned storage-axis operation for a subject batch."""

    def __init__(self, subject_count: int, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Create flipped MRI versions")
        self.setModal(True)
        self.setMinimumWidth(600)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 22)
        layout.setSpacing(14)
        title = QLabel(f"Create flipped MRI versions for {subject_count} subject(s)")
        title.setObjectName("sectionTitle")
        layout.addWidget(title)
        detail = QLabel(
            "This creates new versioned NIfTI inputs from the recorded sources. Existing "
            "versions and raw MRI remain unchanged. Storage axes and affines are updated "
            "without interpolation."
        )
        detail.setObjectName("infoBanner")
        detail.setWordWrap(True)
        layout.addWidget(detail)
        self.scope = QComboBox()
        self.scope.addItem(
            "All active MRI inputs",
            (ScanRole.T1_PRE.value, ScanRole.T1_POST.value, ScanRole.T2.value),
        )
        self.scope.addItem(
            "T1 pre/post only",
            (ScanRole.T1_PRE.value, ScanRole.T1_POST.value),
        )
        self.scope.addItem("T2 only", (ScanRole.T2.value,))
        axes = QHBoxLayout()
        self.axis_boxes = tuple(QCheckBox(axis) for axis in ("X", "Y", "Z"))
        for box in self.axis_boxes:
            axes.addWidget(box)
        axes.addStretch()
        form = QFormLayout()
        form.addRow("MRI inputs", self.scope)
        form.addRow("Flip storage axes", axes)
        layout.addLayout(form)
        warning = QLabel(
            "Review the new versions visually before using them in scientific workflows."
        )
        warning.setObjectName("muted")
        warning.setWordWrap(True)
        layout.addWidget(warning)
        self.error = QLabel()
        self.error.setObjectName("errorBanner")
        self.error.hide()
        layout.addWidget(self.error)
        buttons = QDialogButtonBox(QDialogButtonBox.Cancel | QDialogButtonBox.Save)
        buttons.button(QDialogButtonBox.Save).setText("Create new versions")
        buttons.button(QDialogButtonBox.Cancel).setProperty("kind", "secondary")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def flip_axes(self) -> tuple[int, ...]:
        return tuple(
            axis for axis, box in enumerate(self.axis_boxes) if box.isChecked()
        )

    def roles(self) -> tuple[ScanRole, ...]:
        return tuple(ScanRole(value) for value in self.scope.currentData())

    def accept(self) -> None:
        if not self.flip_axes():
            self.error.setText("Select at least one storage axis to flip.")
            self.error.show()
            return
        super().accept()

