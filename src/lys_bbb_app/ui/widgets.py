"""Reusable widgets for the MVP design-preview pages."""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QRadialGradient,
)
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QGraphicsPixmapItem,
    QGraphicsScene,
    QGraphicsView,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from lys_bbb_app.domain.view_models import (
    MetricViewModel,
    StatusValue,
    WorkflowSummaryViewModel,
)


STATUS_COLOURS = {
    "approved": ("#dcf4ef", "#087268", "#25a596"),
    "ready": ("#dff5f2", "#087268", "#25a596"),
    "review": ("#fff1d9", "#9a5d00", "#efa522"),
    "failed": ("#fde4e4", "#932f2f", "#c94a4a"),
    "processing": ("#e2ecff", "#28549e", "#4a78d0"),
    "unavailable": ("#e9edef", "#5f6c75", "#85929a"),
    "outdated": ("#eee6f7", "#68418b", "#8b62ad"),
    "neutral": ("#edf0f2", "#52616a", "#75828a"),
}

def secondary_button(text: str) -> QPushButton:
    button = QPushButton(text)
    button.setProperty("kind", "secondary")
    return button


class StatusBadge(QLabel):
    def __init__(self, status: StatusValue, parent: QWidget | None = None) -> None:
        super().__init__(status.label, parent)
        self.set_status(status)
        self.setAlignment(Qt.AlignCenter)
        self.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)

    def set_status(self, status: StatusValue) -> None:
        self.setText(status.label)
        background, foreground, border = STATUS_COLOURS.get(
            status.kind,
            STATUS_COLOURS["neutral"],
        )
        self.setStyleSheet(
            "QLabel {"
            f"background: {background}; color: {foreground}; border: 1px solid {border};"
            "border-radius: 9px; padding: 3px 8px; font-size: 11px; font-weight: 650;"
            "}"
        )


class ReadinessRing(QWidget):
    """Compact progress ring used by the study readiness summary."""

    def __init__(self, progress: float, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.progress = max(0.0, min(progress, 1.0))
        self.setFixedSize(78, 78)

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt API
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        ring = QRectF(8, 8, 62, 62)
        painter.setPen(QPen(QColor("#dce9ec"), 9, Qt.SolidLine, Qt.RoundCap))
        painter.drawArc(ring, 0, 360 * 16)
        painter.setPen(QPen(QColor("#159a91"), 9, Qt.SolidLine, Qt.RoundCap))
        painter.drawArc(ring, 90 * 16, -int(360 * 16 * self.progress))
        painter.setPen(QPen(QColor("#087b75"), 3, Qt.SolidLine, Qt.RoundCap))
        painter.drawLine(28, 40, 36, 48)
        painter.drawLine(36, 48, 52, 29)
        painter.end()


class ReadinessSummary(QFrame):
    """One reusable study-level readiness strip built from metric view models."""

    def __init__(
        self,
        metrics: tuple[MetricViewModel, ...],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("readinessCard")
        self.setMinimumHeight(126)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(16)

        total = _metric_number(metrics, "Subjects")
        ready = _metric_number(metrics, "Ready")
        progress = ready / total if total else 0.0
        layout.addWidget(ReadinessRing(progress))

        introduction = QVBoxLayout()
        title = QLabel("Study readiness")
        title.setObjectName("readinessTitle")
        readiness_message = (
            "The study is moving forward. Review the highlighted items before "
            "approved analysis and export."
            if total
            else "Add subjects to begin tracking T1 and T2 workflow readiness."
        )
        detail = QLabel(readiness_message)
        detail.setObjectName("muted")
        detail.setWordWrap(True)
        detail.setMaximumWidth(245)
        introduction.addStretch()
        introduction.addWidget(title)
        introduction.addWidget(detail)
        introduction.addStretch()
        layout.addLayout(introduction, 2)

        separator = QFrame()
        separator.setFrameShape(QFrame.VLine)
        separator.setObjectName("softDivider")
        layout.addWidget(separator)

        for metric in metrics:
            block = QVBoxLayout()
            block.setSpacing(2)
            value = QLabel(metric.value)
            value.setObjectName("readinessValue")
            value.setProperty("accent", metric.kind)
            label = QLabel(metric.label)
            label.setObjectName("readinessLabel")
            label.setWordWrap(True)
            block.addStretch()
            block.addWidget(value)
            block.addWidget(label)
            block.addStretch()
            layout.addLayout(block, 1)


def _metric_number(metrics: tuple[MetricViewModel, ...], label: str) -> int:
    for metric in metrics:
        if metric.label == label:
            try:
                return int(metric.value)
            except ValueError:
                return 0
    return 0


class WorkflowPreview(QWidget):
    """Code-drawn synthetic preview shared by all overview workflow cards."""

    def __init__(self, workflow_key: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.workflow_key = workflow_key
        self.setMinimumHeight(82)
        self.setMaximumHeight(82)

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt API
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        bounds = QRectF(0, 0, max(self.width() - 1, 1), max(self.height() - 1, 1))
        background = QLinearGradient(0, 0, self.width(), self.height())
        background.setColorAt(0, QColor("#08151f"))
        background.setColorAt(1, QColor("#152d3a"))
        painter.setPen(QPen(QColor("#29424f"), 1))
        painter.setBrush(background)
        painter.drawRoundedRect(bounds, 8, 8)

        if self.workflow_key == "combined":
            colours = ("#2d7daf", "#22a69b", "#7bc9c1", "#5b8dd2")
            for index, height in enumerate((28, 40, 23, 51)):
                x = 32 + index * 32
                painter.setPen(Qt.NoPen)
                painter.setBrush(QColor(colours[index]))
                painter.drawRoundedRect(QRectF(x, 66 - height, 19, height), 3, 3)
            painter.setPen(QPen(QColor("#9bb2bf"), 1))
            painter.drawLine(22, 67, 162, 67)
        else:
            brain = QRectF(self.width() / 2 - 78, 9, 156, 63)
            gradient = QRadialGradient(brain.center(), 85)
            gradient.setColorAt(0, QColor("#b8c1c6"))
            gradient.setColorAt(0.7, QColor("#68757d"))
            gradient.setColorAt(1, QColor("#303c43"))
            painter.setPen(QPen(QColor("#d5dcdf"), 1.2))
            painter.setBrush(gradient)
            painter.drawEllipse(brain)
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor("#36454d"))
            painter.drawEllipse(QRectF(brain.center().x() - 31, 30, 23, 26))
            painter.drawEllipse(QRectF(brain.center().x() + 8, 30, 23, 26))
            accent = QColor("#35a8df" if self.workflow_key == "t2" else "#f0f3f4")
            accent.setAlpha(205)
            painter.setBrush(accent)
            painter.drawEllipse(QRectF(brain.center().x() + 35, 31, 21, 19))
            if self.workflow_key == "t2":
                painter.drawEllipse(QRectF(brain.center().x() - 57, 40, 17, 14))

        painter.setPen(QColor("#c7d4db"))
        painter.setFont(QFont("Avenir Next", 8, QFont.DemiBold))
        painter.drawText(10, 16, "SYNTHETIC PREVIEW")
        painter.end()


class WorkflowCard(QFrame):
    action_requested = Signal(str)

    def __init__(
        self,
        workflow: WorkflowSummaryViewModel,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("workflowCard")
        self.setMinimumHeight(310)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 16)
        layout.setSpacing(10)

        top = QHBoxLayout()
        title = QLabel(workflow.title)
        title.setObjectName("cardTitle")
        top.addWidget(title)
        top.addStretch()
        top.addWidget(StatusBadge(workflow.status))
        layout.addLayout(top)

        description = QLabel(workflow.description)
        description.setObjectName("muted")
        description.setWordWrap(True)
        layout.addWidget(description)

        layout.addWidget(WorkflowPreview(workflow.key))

        facts = QGridLayout()
        facts.setHorizontalSpacing(12)
        facts.setVerticalSpacing(6)
        for index, (label, value) in enumerate(workflow.facts):
            block = QVBoxLayout()
            block.setSpacing(1)
            fact_label = QLabel(label)
            fact_label.setObjectName("metadata")
            fact_value = QLabel(value)
            fact_value.setObjectName("workflowFact")
            block.addWidget(fact_value)
            block.addWidget(fact_label)
            facts.addLayout(block, index // 2, index % 2)
        layout.addLayout(facts)

        layout.addStretch()
        button = secondary_button(workflow.action_label)
        button.clicked.connect(
            lambda _checked=False, target=workflow.target_page: self.action_requested.emit(target)
        )
        layout.addWidget(button)


class EmptyState(QFrame):
    def __init__(
        self,
        title: str,
        detail: str,
        action: str | None = None,
        embedded: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("embeddedEmptyState" if embedded else "card")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 28, 28, 28)
        layout.setAlignment(Qt.AlignCenter)
        icon = QLabel("○")
        icon.setAlignment(Qt.AlignCenter)
        icon.setStyleSheet("font-size: 36px; color: #91a0aa;")
        heading = QLabel(title)
        heading.setObjectName("sectionTitle")
        heading.setAlignment(Qt.AlignCenter)
        body = QLabel(detail)
        body.setObjectName("muted")
        body.setWordWrap(True)
        body.setAlignment(Qt.AlignCenter)
        body.setMaximumWidth(520)
        layout.addWidget(icon)
        layout.addWidget(heading)
        layout.addWidget(body)
        if action:
            button = QPushButton(action)
            button.setEnabled(False)
            button.setToolTip("This action will be connected in a later implementation phase.")
            layout.addWidget(button, alignment=Qt.AlignCenter)


class SyntheticSliceViewer(QGraphicsView):
    """A synthetic slice for evaluating review controls without biomedical data."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setScene(QGraphicsScene(self))
        self.setRenderHint(QPainter.Antialiasing, True)
        self.setDragMode(QGraphicsView.ScrollHandDrag)
        self.setBackgroundBrush(QColor("#0c1217"))
        self.setMinimumSize(420, 340)
        self._overlay_opacity = 0.55
        self._slice = 12
        self._slice_count = 30
        self._pixmap_item: QGraphicsPixmapItem | None = None
        self._render_slice()

    def set_context(self, slice_number: int, slice_count: int) -> None:
        self._slice = max(1, min(slice_number, max(slice_count, 1)))
        self._slice_count = max(slice_count, 1)
        self._render_slice()

    def set_overlay_opacity(self, opacity: float) -> None:
        self._overlay_opacity = max(0.0, min(opacity, 1.0))
        self._render_slice()

    def _render_slice(self) -> None:
        width, height = 720, 520
        pixmap = QPixmap(width, height)
        pixmap.fill(QColor("#0b1116"))
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing, True)

        background = QLinearGradient(0, 0, 0, height)
        background.setColorAt(0, QColor("#111a21"))
        background.setColorAt(1, QColor("#080c10"))
        painter.fillRect(0, 0, width, height, background)

        brain_rect = QRectF(150, 70, 420, 380)
        brain_gradient = QRadialGradient(brain_rect.center(), 235)
        brain_gradient.setColorAt(0, QColor("#bec4c8"))
        brain_gradient.setColorAt(0.55, QColor("#777f85"))
        brain_gradient.setColorAt(1, QColor("#343a3f"))
        painter.setBrush(brain_gradient)
        painter.setPen(QPen(QColor("#ccd1d4"), 2))
        painter.drawEllipse(brain_rect)

        painter.setBrush(QColor("#2a3035"))
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(QRectF(270, 178, 72, 110))
        painter.drawEllipse(QRectF(378, 178, 72, 110))
        painter.setBrush(QColor("#555d63"))
        painter.drawEllipse(QRectF(200, 145, 115, 190))
        painter.drawEllipse(QRectF(405, 145, 115, 190))

        overlay = QColor("#23b8a6")
        overlay.setAlphaF(self._overlay_opacity * 0.55)
        painter.setBrush(overlay)
        painter.setPen(QPen(QColor("#38d1be"), 4))
        overlay_path = QPainterPath()
        overlay_path.addEllipse(QRectF(165, 82, 390, 355))
        painter.drawPath(overlay_path)

        lesion = QColor("#ef8f33")
        lesion.setAlphaF(self._overlay_opacity)
        painter.setBrush(lesion)
        painter.setPen(QPen(QColor("#ffbd69"), 3))
        lesion_path = QPainterPath()
        lesion_path.moveTo(414, 276)
        lesion_path.cubicTo(450, 240, 502, 260, 500, 316)
        lesion_path.cubicTo(494, 356, 442, 367, 410, 332)
        lesion_path.closeSubpath()
        painter.drawPath(lesion_path)

        painter.setPen(QColor("#d7e1e7"))
        painter.setFont(QFont("Helvetica Neue", 12, QFont.DemiBold))
        painter.drawText(18, 28, "DESIGN PREVIEW · SYNTHETIC MRI SLICE")
        painter.setPen(QColor("#92a3ae"))
        painter.setFont(QFont("Helvetica Neue", 11))
        painter.drawText(18, height - 18, f"Slice {self._slice} / {self._slice_count}")
        painter.drawText(width - 175, height - 18, "Teal: brain · Orange: lesion")
        painter.end()

        scene = self.scene()
        scene.clear()
        self._pixmap_item = scene.addPixmap(pixmap)
        scene.setSceneRect(QRectF(pixmap.rect()))
        self.fitInView(scene.sceneRect(), Qt.KeepAspectRatio)

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt API
        super().resizeEvent(event)
        if self.scene() is not None:
            self.fitInView(self.scene().sceneRect(), Qt.KeepAspectRatio)


class CohortPlot(QWidget):
    """Small descriptive dot plot used only by the design preview."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._blinded = False
        self.setMinimumHeight(230)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    def set_blinded(self, blinded: bool) -> None:
        self._blinded = blinded
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt API
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.fillRect(self.rect(), QColor("#ffffff"))
        margin_left, margin_top, margin_bottom = 56, 24, 58
        plot_width = max(self.width() - margin_left - 24, 1)
        plot_height = max(self.height() - margin_top - margin_bottom, 1)
        axis = QPen(QColor("#a9b5bd"), 1)
        painter.setPen(axis)
        painter.drawLine(margin_left, margin_top, margin_left, margin_top + plot_height)
        painter.drawLine(
            margin_left,
            margin_top + plot_height,
            margin_left + plot_width,
            margin_top + plot_height,
        )
        painter.setPen(QColor("#71808a"))
        painter.drawText(8, margin_top + 5, "15")
        painter.drawText(18, margin_top + plot_height + 5, "0")

        groups = (
            (
                "Blinded cohort",
                (2.1, 3.0, 4.4, 5.1, 3.8, 4.7, 7.1, 8.3, 10.4, 9.2, 6.3, 8.7, 11.3, 12.4, 9.8),
                QColor("#16847a"),
            ),
        ) if self._blinded else (
            ("Vehicle", (2.1, 3.0, 4.4, 5.1, 3.8), QColor("#7b8992")),
            ("Treatment A", (4.7, 7.1, 8.3, 10.4, 9.2), QColor("#2f6fed")),
            ("Treatment B", (6.3, 8.7, 11.3, 12.4, 9.8), QColor("#16847a")),
        )
        for index, (label, values, colour) in enumerate(groups):
            x_center = margin_left + int(plot_width * (index + 0.5) / len(groups))
            for point_index, value in enumerate(values):
                jitter = (-28, -21, -14, -7, 0, 7, 14, 21, 28)[point_index % 9]
                y = margin_top + plot_height - int((value / 15.0) * plot_height)
                painter.setBrush(colour)
                painter.setPen(Qt.NoPen)
                painter.drawEllipse(QRectF(x_center + jitter - 4, y - 4, 8, 8))
            mean = sum(values) / len(values)
            mean_y = margin_top + plot_height - int((mean / 15.0) * plot_height)
            painter.setPen(QPen(colour, 3))
            painter.drawLine(x_center - 24, mean_y, x_center + 24, mean_y)
            painter.setPen(QColor("#475761"))
            label_width = min(max(120, plot_width // len(groups) - 12), plot_width)
            painter.drawText(
                x_center - label_width // 2,
                margin_top + plot_height + 24,
                label_width,
                20,
                Qt.AlignCenter,
                label,
            )
        painter.end()
