"""Small registry for mutually exclusive desktop background jobs."""

from __future__ import annotations

from PySide6.QtCore import QThread


class BackgroundJobRegistry:
    """Track active Qt worker threads without feature-specific state duplication."""

    def __init__(self) -> None:
        self._threads: dict[str, QThread] = {}

    def register(self, name: str, thread: QThread) -> None:
        current = self._threads.get(name)
        if current is not None and current.isRunning():
            raise RuntimeError(f"Background job {name!r} is already running.")
        self._threads[name] = thread

    def get(self, name: str) -> QThread | None:
        return self._threads.get(name)

    def clear(self, name: str) -> None:
        self._threads.pop(name, None)

    def is_running(self, name: str) -> bool:
        thread = self._threads.get(name)
        return thread is not None and thread.isRunning()

    @property
    def any_running(self) -> bool:
        return any(thread.isRunning() for thread in self._threads.values())
