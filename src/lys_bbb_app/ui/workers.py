"""Qt worker adapters used by the desktop shell.

Workers coordinate application services off the GUI thread. They contain no scientific
processing or persistence logic themselves.
"""

from __future__ import annotations

from PySide6.QtCore import QThread, Signal

from lys_bbb_app.domain.scan_import import ScanImportAssignment, ScanImportState
from lys_bbb_app.services.study_service import StudyService


class ScanImportThread(QThread):
    progress_changed = Signal(int, int, str)
    import_completed = Signal(object, int)
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
        proposal_ids = {assignment.proposal_id for assignment in self._assignments}
        failure_count = sum(
            record.proposal_id in proposal_ids
            and record.state is ScanImportState.FAILED
            for record in snapshot.scan_inputs
        )
        self.import_completed.emit(snapshot, failure_count)
