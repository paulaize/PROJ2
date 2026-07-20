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


class InputValidationThread(QThread):
    validation_completed = Signal(object)
    validation_failed = Signal(str)

    def __init__(
        self,
        service: StudyService,
        subject_id: str,
        *,
        actor: str,
    ) -> None:
        super().__init__()
        self._service = service
        self._subject_id = subject_id
        self._actor = actor

    def run(self) -> None:
        try:
            snapshot = self._service.validate_subject_inputs(
                self._subject_id,
                actor=self._actor,
            )
        except Exception as exc:
            self.validation_failed.emit(str(exc))
            return
        self.validation_completed.emit(snapshot)


class T2InferenceThread(QThread):
    progress_changed = Signal(int, int, str)
    inference_completed = Signal(object)
    inference_failed = Signal(str)

    def __init__(
        self,
        service: StudyService,
        *,
        actor: str,
        subject_ids: tuple[str, ...] | None = None,
        device_name: str = "auto",
    ) -> None:
        super().__init__()
        self._service = service
        self._actor = actor
        self._subject_ids = subject_ids
        self._device_name = device_name

    def run(self) -> None:
        try:
            snapshot = self._service.run_t2_lesion_inference(
                actor=self._actor,
                subject_ids=self._subject_ids,
                device_name=self._device_name,
                progress=self.progress_changed.emit,
            )
        except Exception as exc:
            self.inference_failed.emit(str(exc))
            return
        self.inference_completed.emit(snapshot)
