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
    """Collect an explicit correction of the saved anatomical orientation."""

    def __init__(self, subject_count: int, parent: QWidget | None = None, *, inputs: tuple[ScanInputRecord, ...] = ()) -> None:
        super().__init__(parent)
        self._inputs = inputs
        self.setWindowTitle("Correct MRI orientation")
        self.setModal(True)
        self.setMinimumWidth(600)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 22)
        layout.setSpacing(14)
        title = QLabel(f"Correct orientation · {subject_count} subject(s)")
        title.setObjectName("sectionTitle")
        layout.addWidget(title)
        self.scope = QComboBox()
        roles = tuple(dict.fromkeys(record.role for record in inputs))
        if len(roles) > 1:
            self.scope.addItem("All selected MRI inputs", tuple(role.value for role in roles))
        for role in roles:
            self.scope.addItem(MRIInputSelectionDialog.ROLE_LABELS[role], (role.value,))
        axes = QHBoxLayout()
        self.axis_boxes = tuple(QCheckBox(axis) for axis in ("X", "Y", "Z"))
        for box in self.axis_boxes:
            box.setToolTip("Image axis, not screen direction.")
            axes.addWidget(box)
        axes.addStretch()
        form = QFormLayout()
        form.addRow("MRI inputs", self.scope)
        form.addRow("Correct image axes", axes)
        layout.addLayout(form)
        warning = QLabel(
            "Original kept. Check and validate the new image before rerunning analysis."
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
        self.scope.currentIndexChanged.connect(self._update_axes)
        self._update_axes()

    def _update_axes(self) -> None:
        orientations = {record.output_axis_codes for record in self._inputs if record.role in self.roles()}
        codes = next(iter(orientations)) if len(orientations) == 1 else ()
        opposite = {"L": "R", "R": "L", "A": "P", "P": "A", "I": "S", "S": "I"}
        for axis, box in enumerate(self.axis_boxes):
            label = "XYZ"[axis]
            if codes and codes[axis] in opposite:
                code = codes[axis]
                label += f" ({code} → {opposite[code]})"
            box.setText(label)

    def flip_axes(self) -> tuple[int, ...]:
        return tuple(
            axis for axis, box in enumerate(self.axis_boxes) if box.isChecked()
        )

    def roles(self) -> tuple[ScanRole, ...]:
        return tuple(ScanRole(value) for value in (self.scope.currentData() or ()))

    def accept(self) -> None:
        if not self.flip_axes():
            self.error.setText("Select at least one storage axis to flip.")
            self.error.show()
            return
        super().accept()
