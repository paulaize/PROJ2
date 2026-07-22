"""Small reusable layout helpers shared by page widgets."""

from __future__ import annotations

from PySide6.QtWidgets import QHBoxLayout, QLabel, QLayout, QVBoxLayout, QWidget


def clear_layout(layout: QLayout) -> None:
    """Detach every widget and nested layout before repopulating a dynamic view."""

    while layout.count():
        item = layout.takeAt(0)
        child = item.widget()
        if child is not None:
            child.setParent(None)
            child.deleteLater()
        nested = item.layout()
        if nested is not None:
            clear_layout(nested)


def page_heading(
    title_text: str,
    description_text: str | None = None,
) -> tuple[QWidget, QHBoxLayout]:
    """Build a consistent page title with optional supporting copy."""

    widget = QWidget()
    layout = QHBoxLayout(widget)
    layout.setContentsMargins(0, 0, 0, 0)
    titles = QVBoxLayout()
    title = QLabel(title_text)
    title.setObjectName("pageTitle")
    titles.addWidget(title)
    if description_text:
        description = QLabel(description_text)
        description.setObjectName("muted")
        description.setWordWrap(True)
        titles.addWidget(description)
    layout.addLayout(titles)
    layout.addStretch()
    return widget, layout
