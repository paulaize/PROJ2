"""Small registry for mutually exclusive desktop background jobs."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QThread


class BackgroundJobRegistry:
    """Track active Qt worker threads without feature-specific state duplication."""

    def __init__(
        self,
        active_count_changed: Callable[[int], None] | None = None,
    ) -> None:
        self._threads: dict[str, QThread] = {}
        self._active_count_changed = active_count_changed

    def register(self, name: str, thread: QThread) -> None:
        current = self._threads.get(name)
        if current is not None and current.isRunning():
            raise RuntimeError(f"Background job {name!r} is already running.")
        self._threads[name] = thread
        self._notify_active_count()

    def get(self, name: str) -> QThread | None:
        return self._threads.get(name)

    def clear(self, name: str) -> None:
        removed = self._threads.pop(name, None)
        if removed is not None:
            self._notify_active_count()

    def is_running(self, name: str) -> bool:
        thread = self._threads.get(name)
        return thread is not None and thread.isRunning()

    @property
    def any_running(self) -> bool:
        return any(thread.isRunning() for thread in self._threads.values())

    def _notify_active_count(self) -> None:
        if self._active_count_changed is not None:
            self._active_count_changed(len(self._threads))
