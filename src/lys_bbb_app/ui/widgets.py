"""Reusable widgets for the desktop application pages."""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QPainter,
    QPen,
)
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QToolButton,
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


class CollapsibleSection(QWidget):
    """Disclosure container that keeps technical material out of the primary flow."""

    def __init__(
        self,
        title: str = "Technical details",
        *,
        expanded: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        self.toggle = QToolButton()
        self.toggle.setText(title)
        self.toggle.setCheckable(True)
        self.toggle.setChecked(expanded)
        self.toggle.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.toggle.setArrowType(Qt.DownArrow if expanded else Qt.RightArrow)
        self.toggle.setProperty("kind", "disclosure")
        self.toggle.toggled.connect(self._set_expanded)
        layout.addWidget(self.toggle, alignment=Qt.AlignLeft)

        self.content = QWidget()
        self.content_layout = QVBoxLayout(self.content)
        self.content_layout.setContentsMargins(14, 4, 0, 2)
        self.content_layout.setSpacing(8)
        self.content.setVisible(expanded)
        layout.addWidget(self.content)

    @property
    def is_expanded(self) -> bool:
        return self.toggle.isChecked()

    def set_expanded(self, expanded: bool) -> None:
        self.toggle.setChecked(expanded)

    def _set_expanded(self, expanded: bool) -> None:
        self.toggle.setArrowType(Qt.DownArrow if expanded else Qt.RightArrow)
        self.content.setVisible(expanded)


class ElidedLabel(QLabel):
    """A label that preserves its value while eliding it to the available width."""

    def __init__(
        self,
        text: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._full_text = ""
        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.setText(text)

    @property
    def full_text(self) -> str:
        return self._full_text

    def setText(self, text: str) -> None:  # noqa: N802 - Qt API
        self._full_text = text
        self.setAccessibleDescription(text)
        self._refresh_display_text()

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt API
        super().resizeEvent(event)
        self._refresh_display_text()

    def _refresh_display_text(self) -> None:
        available_width = max(self.contentsRect().width(), 0)
        display_text = self.fontMetrics().elidedText(
            self._full_text,
            Qt.ElideMiddle,
            available_width,
        )
        super().setText(display_text)
        self.setToolTip(self._full_text if display_text != self._full_text else "")


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

        title = QLabel("Study state")
        title.setObjectName("readinessTitle")
        layout.addWidget(title)

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


class WorkflowCard(QFrame):
    action_requested = Signal(str)

    def __init__(
        self,
        workflow: WorkflowSummaryViewModel,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("workflowCard")
        self.setMinimumHeight(220)
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
