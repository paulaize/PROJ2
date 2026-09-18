"""Small asynchronously loaded coronal preview for an MRI input card."""

from pathlib import Path
from threading import Event

from PySide6.QtCore import QObject, QRunnable, QThreadPool, QTimer, Qt, Signal, Slot
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from lys_bbb_app.services.mri_preview import CoronalPreview, render_coronal_preview


class _PreviewSignals(QObject):
    finished = Signal(object, object, str)


class _PreviewTask(QRunnable):
    def __init__(self, path: Path, position: int, cancelled: Event) -> None:
        super().__init__()
        self.path, self.position, self.cancelled = path, position, cancelled
        self.signals = _PreviewSignals()

    def run(self) -> None:
        if self.cancelled.is_set():
            return
        try:
            result, error = render_coronal_preview(self.path, self.position), ""
        except Exception as exc:
            result, error = None, str(exc)
        if not self.cancelled.is_set():
            self.signals.finished.emit(self.cancelled, result, error)


# Limit concurrent volume decompression when users switch subjects quickly.
_PREVIEW_POOL = QThreadPool()
_PREVIEW_POOL.setMaxThreadCount(1)


class CoronalPreviewWidget(QWidget):
    position_changed = Signal(int)

    def __init__(self, path: Path, *, position: int = 50) -> None:
        super().__init__()
        self.path = path
        self._cancelled = Event()
        self._started = False
        self._task = None
        self.setObjectName("coronalPreview")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(3)
        heading = QLabel("Coronal")
        heading.setObjectName("metadata")
        layout.addWidget(heading)
        plane = QGridLayout()
        plane.setSpacing(2)
        self.image = QLabel("Loading preview…")
        self.image.setAlignment(Qt.AlignCenter)
        self.image.setFixedSize(320, 240)
        self.image.setStyleSheet(
            "background: #101820; color: #dce5ec; border-radius: 4px;"
        )
        self.image.setToolTip(
            "Radiological view: right on the left. Labels follow the saved MRI orientation."
        )
        plane.addWidget(self.image, 1, 1)
        for text, row, column in (("S", 0, 1), ("R", 1, 0), ("L", 1, 2), ("I", 2, 1)):
            label = QLabel(text)
            label.setAlignment(Qt.AlignCenter)
            plane.addWidget(label, row, column)
        container = QHBoxLayout()
        container.addStretch()
        container.addLayout(plane)
        container.addStretch()
        layout.addLayout(container)
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(0, 100)
        self.slider.setValue(position)
        self.slider.setMaximumWidth(320)
        self.slider.setToolTip("Coronal slice: posterior to anterior")
        self.slider.setAccessibleName("Coronal slice position")
        layout.addWidget(self.slider, alignment=Qt.AlignHCenter)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(180)
        self._timer.timeout.connect(self._load)
        self.slider.valueChanged.connect(self._position_changed)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if not self._started:
            self._started = True
            self._load()

    def cancel(self) -> None:
        self._cancelled.set()
        self._timer.stop()

    def _position_changed(self, position: int) -> None:
        self.position_changed.emit(position)
        self._cancelled.set()
        self.image.clear()
        self.image.setText("Loading preview…")
        self._timer.start()

    def _load(self) -> None:
        self._cancelled.set()
        self._cancelled = Event()
        task = _PreviewTask(self.path, self.slider.value(), self._cancelled)
        task.signals.finished.connect(self._loaded)
        self._task = task
        _PREVIEW_POOL.start(task)

    @Slot(object, object, str)
    def _loaded(
        self, request: Event, preview: CoronalPreview | None, error: str
    ) -> None:
        if request is not self._cancelled or request.is_set():
            return
        if preview is None:
            self.image.setText("Preview unavailable")
            self.image.setToolTip(error)
            return
        image = QImage(
            preview.pixels,
            preview.width,
            preview.height,
            preview.width,
            QImage.Format_Grayscale8,
        ).copy()
        self.image.setPixmap(
            QPixmap.fromImage(image).scaled(
                self.image.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation
            )
        )
