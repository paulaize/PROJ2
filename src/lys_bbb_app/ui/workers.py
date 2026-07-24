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


class T1BrainMaskThread(QThread):
    progress_changed = Signal(int, int, str)
    generation_completed = Signal(object)
    generation_failed = Signal(str)

    def __init__(
        self,
        service: StudyService,
        *,
        actor: str,
        subject_ids: tuple[str, ...],
        device_name: str = "auto",
    ) -> None:
        super().__init__()
        self._service = service
        self._actor = actor
        self._subject_ids = subject_ids
        self._device_name = device_name

    def run(self) -> None:
        try:
            snapshot = self._service.run_t1_brain_mask_generation(
                actor=self._actor,
                subject_ids=self._subject_ids,
                device_name=self._device_name,
                progress=self.progress_changed.emit,
            )
        except Exception as exc:
            self.generation_failed.emit(str(exc))
            return
        self.generation_completed.emit(snapshot)


class T1RegistrationThread(QThread):
    progress_changed = Signal(int, int, str)
    registration_completed = Signal(object)
    registration_failed = Signal(str)

    def __init__(
        self,
        service: StudyService,
        *,
        actor: str,
        subject_ids: tuple[str, ...],
    ) -> None:
        super().__init__()
        self._service = service
        self._actor = actor
        self._subject_ids = subject_ids

    def run(self) -> None:
        try:
            snapshot = self._service.run_t1_registration(
                actor=self._actor,
                subject_ids=self._subject_ids,
                progress=self.progress_changed.emit,
            )
        except Exception as exc:
            self.registration_failed.emit(str(exc))
            return
        self.registration_completed.emit(snapshot)


class T1EnhancementThread(QThread):
    progress_changed = Signal(int, int, str)
    calculation_completed = Signal(object)
    calculation_failed = Signal(str)

    def __init__(
        self,
        service: StudyService,
        *,
        actor: str,
        subject_ids: tuple[str, ...],
    ) -> None:
        super().__init__()
        self._service = service
        self._actor = actor
        self._subject_ids = subject_ids

    def run(self) -> None:
        try:
            snapshot = self._service.run_t1_enhancement(
                actor=self._actor,
                subject_ids=self._subject_ids,
                progress=self.progress_changed.emit,
            )
        except Exception as exc:
            self.calculation_failed.emit(str(exc))
            return
        self.calculation_completed.emit(snapshot)


class AtlasMappingThread(QThread):
    """Run one durable atlas stage without blocking the Qt event loop."""

    progress_changed = Signal(int, int, str)
    stage_completed = Signal(object)
    stage_failed = Signal(str)

    def __init__(
        self,
        service: StudyService,
        *,
        subject_id: str,
        action: str,
        actor: str,
    ) -> None:
        super().__init__()
        self._service = service
        self._subject_id = subject_id
        self._action = action
        self._actor = actor

    def run(self) -> None:
        try:
            if self._action == "atlas_to_t1":
                state = self._service.atlas_mapping.run_atlas_to_t1(
                    self._subject_id,
                    actor=self._actor,
                    progress=self.progress_changed.emit,
                )
            elif self._action == "t1_to_t2":
                state = self._service.atlas_mapping.run_t1_to_t2(
                    self._subject_id,
                    actor=self._actor,
                    progress=self.progress_changed.emit,
                )
            elif self._action == "composite":
                self.progress_changed.emit(0, 1, "Propagating major labels")
                state = self._service.atlas_mapping.create_composite(
                    self._subject_id,
                    actor=self._actor,
                )
                self.progress_changed.emit(1, 1, "Composite QC ready")
            else:
                raise ValueError(f"Unknown atlas action: {self._action}")
        except Exception as exc:
            self.stage_failed.emit(str(exc))
            return
        self.stage_completed.emit(state)
