"""Restrained QFluentWidgets integration for shared desktop presentation."""

from __future__ import annotations

from typing import Literal

from PySide6.QtGui import QColor, QIcon
from PySide6.QtWidgets import QPushButton, QWidget
from qfluentwidgets import (
    ComboBox as FluentComboBox,
    FluentIcon,
    IndeterminateProgressRing,
    InfoBar,
    InfoBarPosition,
    PrimaryPushButton,
    PushButton,
    TabWidget as _FluentTabWidget,
    Theme,
    TransparentTogglePushButton,
    setTheme,
    setThemeColor,
    setFontFamilies,
)


NotificationKind = Literal["success", "warning", "info"]


class FluentTabWidget(_FluentTabWidget):
    """Tab widget with a PySide 6.11-compatible visibility query.

    QFluentWidgets 1.11.2 forwards ``isTabVisible`` to a tab-bar method that
    passes an index to QWidget.isVisible(), which PySide correctly rejects.
    Keep the workaround local so it can be removed after an upstream fix.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setTabsClosable(False)
        self.tabBar.setAddButtonVisible(False)

    def isTabVisible(self, index: int) -> bool:  # noqa: N802 - Qt API spelling
        if not 0 <= index < len(self.tabBar.items):
            return False
        return not self.tabBar.items[index].isHidden()


def configure_fluent_theme(font_families: list[str] | None = None) -> None:
    """Keep Fluent controls aligned with the existing light LYS IRM palette."""

    if font_families:
        # QFluentWidgets otherwise requests Segoe UI on every platform.  Using
        # Qt's native application font avoids missing-font alias work on macOS.
        setFontFamilies(font_families, save=False)
    setTheme(Theme.LIGHT)
    setThemeColor(QColor("#168b96"))


def primary_button(
    text: str,
    icon: FluentIcon | QIcon | None = None,
    parent: QWidget | None = None,
) -> QPushButton:
    """Create a Fluent primary action without leaking its concrete type."""

    if icon is None:
        return PrimaryPushButton(text, parent)
    return PrimaryPushButton(icon, text, parent)


def secondary_button(
    text: str,
    icon: FluentIcon | QIcon | None = None,
    parent: QWidget | None = None,
) -> QPushButton:
    """Create a Fluent secondary action without changing callers' Qt contract."""

    if icon is None:
        button = PushButton(text, parent)
    else:
        button = PushButton(icon, text, parent)
    button.setProperty("kind", "secondary")
    return button


def show_notification(
    parent: QWidget,
    *,
    title: str,
    content: str,
    kind: NotificationKind = "info",
    duration: int | None = None,
) -> InfoBar:
    """Show a non-blocking message while leaving critical errors modal."""

    durations = {"success": 5000, "warning": 7500, "info": 6000}
    factory = getattr(InfoBar, kind)
    return factory(
        title=title,
        content=content,
        isClosable=True,
        duration=duration or durations[kind],
        position=InfoBarPosition.TOP_RIGHT,
        parent=parent,
    )


__all__ = [
    "FluentComboBox",
    "FluentIcon",
    "FluentTabWidget",
    "IndeterminateProgressRing",
    "NotificationKind",
    "TransparentTogglePushButton",
    "configure_fluent_theme",
    "primary_button",
    "secondary_button",
    "show_notification",
]
