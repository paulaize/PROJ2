"""Qt worker wrapper for MRI import services.

The worker owns no scientific logic; it keeps conversion calls out of widgets and off
the GUI thread while the application-level service updates durable state.
"""

from __future__ import annotations

from PySide6.QtCore import QThread, Signal

from lys_bbb_app.domain.scan_import import ScanImportAssignment
from lys_bbb_app.services.study_service import StudyService


class ScanImportThread(QThread):
    progress_changed = Signal(int, int, str)
    import_completed = Signal(object)
    import_failed = Signal(str)

    def __init__(
        self,
        service: StudyService,
        assignments: tuple[ScanImportAssignment, ...],
        *,
        actor: str,
    ) -> None:
        super().__init__()
        self._service = service
        self._assignments = assignments
        self._actor = actor

    def run(self) -> None:
        try:
            snapshot = self._service.import_confirmed_scans(
                self._assignments,
                actor=self._actor,
                progress=self.progress_changed.emit,
            )
        except Exception as exc:
            self.import_failed.emit(str(exc))
            return
        self.import_completed.emit(snapshot)
