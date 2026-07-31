"""Packaged T2 model registration, readiness, and inference orchestration."""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from lys_bbb.t2_inference import T2InferenceOutput
from lys_bbb.t2_model_release import FrozenT2ModelRelease
from lys_bbb_app.domain.errors import StudyStateError
from lys_bbb_app.domain.scan_import import (
    InputValidationState,
    ScanImportState,
    ScanRole,
)
from lys_bbb_app.domain.study import StudySnapshot
from lys_bbb_app.domain.t2_lesion import (
    T2ArtifactDraft,
    T2InferenceReadiness,
    T2ModelReleaseRecord,
)
from lys_bbb_app.infrastructure.study_database import StudyRepository


RepositoryProvider = Callable[[], StudyRepository]
ProgressCallback = Callable[[int, int, str], None]
ReleaseValidator = Callable[[Path | str], FrozenT2ModelRelease]
InferenceRunner = Callable[..., T2InferenceOutput]
QCBuilder = Callable[[Path, Path, Path], Path]


class T2InferenceService:
    """Coordinate T2 inference jobs without Qt or study-lifecycle ownership."""

    def __init__(
        self,
        repository_provider: RepositoryProvider,
        *,
        release_validator: ReleaseValidator,
        inference_runner: InferenceRunner,
        qc_builder: QCBuilder,
    ) -> None:
        self._repository_provider = repository_provider
        self._release_validator = release_validator
        self._inference_runner = inference_runner
        self._qc_builder = qc_builder

    def register_model_release(
        self,
        release_root: Path | str,
        *,
        actor: str,
    ) -> StudySnapshot:
        """Validate and activate one immutable packaged inference release."""

        repository = self._repository()
        try:
            release = self._release_validator(release_root)
        except (FileNotFoundError, OSError, ValueError) as exc:
            raise StudyStateError(f"The T2 model release is not valid: {exc}") from exc
        repository.register_t2_model_release(release, actor=actor)
        return repository.snapshot()

    def readiness(
        self,
        subject_ids: tuple[str, ...] | None = None,
    ) -> T2InferenceReadiness:
        """Return active subjects whose current native T2 is release-compatible."""

        snapshot = self._repository().snapshot()
        requested = set(subject_ids) if subject_ids is not None else None
        active_ids = {subject.id for subject in snapshot.subjects}
        subjects_with_current_drafts = {
            artifact.subject_id for artifact in snapshot.artifacts if artifact.active
        }
        if requested is not None and requested - active_ids:
            raise StudyStateError("One or more selected subjects are no longer active.")
        eligible: list[str] = []
        blocked: list[tuple[str, str]] = []
        for subject in snapshot.subjects:
            if requested is not None and subject.id not in requested:
                continue
            reason = _t2_blocked_reason(
                snapshot,
                subject.id,
                expected_t2=subject.expected_t2,
                has_current_draft=subject.id in subjects_with_current_drafts,
                skip_current_drafts=requested is None,
            )
            if reason is not None:
                blocked.append((subject.id, reason))
                continue
            eligible.append(subject.id)
        return T2InferenceReadiness(tuple(eligible), tuple(blocked))

    def run(
        self,
        *,
        actor: str,
        subject_ids: tuple[str, ...] | None = None,
        device_name: str = "auto",
        progress: ProgressCallback | None = None,
    ) -> StudySnapshot:
        """Run the frozen ensemble and commit immutable draft artifacts on success."""

        repository = self._repository()
        snapshot = repository.snapshot()
        release_record = snapshot.active_t2_model_release
        if release_record is None:
            raise StudyStateError(
                "Select and validate a packaged T2 lesion model first."
            )
        release = self._validated_release(release_record)
        readiness = self.readiness(subject_ids)
        if not readiness.eligible_subject_ids:
            raise StudyStateError(
                "No active subjects have a validated, release-compatible T2 input."
            )
        inputs_by_subject = {
            subject_id: next(
                record
                for record in snapshot.inputs_for_subject(subject_id)
                if record.active
                and record.role is ScanRole.T2
                and record.state is ScanImportState.CONVERTED
                and record.output_path is not None
            )
            for subject_id in readiness.eligible_subject_ids
        }
        job_id = repository.create_t2_inference_job(
            readiness.eligible_subject_ids,
            release_id=release.id,
            actor=actor,
        )
        work_root = repository.root_path / "work" / "t2_lesion" / job_id
        output_root = (
            repository.root_path / "outputs" / "t2_lesion" / "jobs" / job_id
        )
        repository.start_t2_inference_job(job_id)

        def report(current: int, total: int, message: str) -> None:
            repository.update_t2_inference_job(job_id, current, total, message)
            if progress is not None:
                progress(current, total, message)

        try:
            inference = self._inference_runner(
                release,
                {
                    subject_id: record.output_path
                    for subject_id, record in inputs_by_subject.items()
                },
                work_root=work_root,
                output_root=output_root,
                device_name=device_name,
                progress=report,
            )
            drafts: list[T2ArtifactDraft] = []
            for index, case in enumerate(inference.cases, start=1):
                record = inputs_by_subject.get(case.case_id)
                if record is None or record.output_path is None:
                    raise RuntimeError(
                        f"Inference returned an unexpected subject ID: {case.case_id}"
                    )
                qc_path = case.mask_path.parent / "qc_preview.png"
                self._qc_builder(record.output_path, case.mask_path, qc_path)
                drafts.append(
                    T2ArtifactDraft(
                        subject_id=case.case_id,
                        source_scan_input_id=record.id,
                        mask_path=case.mask_path,
                        mask_sha256=case.mask_sha256,
                        probability_path=case.probability_path,
                        probability_sha256=case.probability_sha256,
                        qc_preview_path=qc_path,
                        lesion_voxel_count=case.lesion_voxel_count,
                        provisional_volume_mm3=case.lesion_volume_mm3,
                        threshold=release.threshold,
                        device=inference.device,
                        metadata={
                            "shape": list(case.shape),
                            "spacing_mm": list(case.spacing_mm),
                            "axis_codes": list(case.axis_codes),
                            "model_folds": list(release.folds),
                            "postprocessing": "none",
                            "native_affine_preserved": True,
                            "predictions_are_drafts": True,
                            "human_review_required": True,
                            "inference_summary": str(inference.summary_path),
                        },
                    )
                )
                report(
                    index,
                    len(inference.cases),
                    f"Creating T2 QC preview {index} of {len(inference.cases)}",
                )
            repository.complete_t2_inference_job(
                job_id,
                tuple(drafts),
                release_id=release.id,
                output_path=output_root,
                actor=actor,
            )
        except Exception as exc:
            repository.fail_t2_inference_job(job_id, str(exc), actor=actor)
            if isinstance(exc, StudyStateError):
                raise
            raise StudyStateError(f"T2 lesion inference failed: {exc}") from exc
        return repository.snapshot()

    def _repository(self) -> StudyRepository:
        return self._repository_provider()

    def _validated_release(
        self,
        release_record: T2ModelReleaseRecord,
    ) -> FrozenT2ModelRelease:
        try:
            release = self._release_validator(release_record.root_path)
        except (FileNotFoundError, OSError, ValueError) as exc:
            raise StudyStateError(
                f"The registered T2 model release is no longer valid: {exc}"
            ) from exc
        if (
            release.id != release_record.id
            or release.manifest_sha256 != release_record.manifest_sha256
            or release.frozen_spec_sha256 != release_record.frozen_spec_sha256
            or release.threshold_sha256 != release_record.threshold_sha256
            or release.model_sha256 != release_record.model_sha256
            or release.metadata.get("runtime_sha256")
            != release_record.metadata.get("runtime_sha256")
        ):
            raise StudyStateError(
                "The installed T2 release changed after validation. Select it again."
            )
        return release


def _t2_blocked_reason(
    snapshot: StudySnapshot,
    subject_id: str,
    *,
    expected_t2: bool,
    has_current_draft: bool,
    skip_current_drafts: bool,
) -> str | None:
    if skip_current_drafts and has_current_draft:
        return "A current draft lesion mask already awaits review."
    if not expected_t2:
        return "T2 is marked not applicable."
    t2 = next(
        (
            record
            for record in snapshot.inputs_for_subject(subject_id)
            if record.active and record.role is ScanRole.T2
        ),
        None,
    )
    if t2 is None or t2.state is not ScanImportState.CONVERTED:
        return "No converted T2 input is available."
    if t2.validation_state is not InputValidationState.VALID:
        return "The active T2 input has not passed validation."
    if t2.output_path is None or not t2.output_path.is_file():
        return "The managed T2 NIfTI is unavailable."
    if len(t2.output_spacing_mm) != 3 or any(
        abs(observed - expected) > 1e-5
        for observed, expected in zip(
            t2.output_spacing_mm,
            (0.07, 0.07, 0.5),
            strict=True,
        )
    ):
        return (
            "Voxel spacing is incompatible with this release "
            "(expected 0.07 × 0.07 × 0.5 mm)."
        )
    return None
