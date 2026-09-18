"""Application service for persistent study and subject actions."""

from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import asdict, replace
from pathlib import Path
from typing import Callable
from uuid import uuid4

from lys_bbb.input_validation import validate_managed_nifti
from lys_bbb.brain_mask_refinement import (
    GapRefinementConfig,
    MSeamCleanupConfig,
    MaskRegularityConfig,
)
from lys_bbb.mask_qc import create_native_mask_qc_preview
from lys_bbb.t1_brain_mask import T1BrainMaskOutput, run_local_t1_brain_mask
from lys_bbb.t1_enhancement import (
    T1_ENHANCEMENT_METHOD_VERSION,
    T1EnhancementConfig,
    T1EnhancementOutput,
    T1EnhancementRequest,
    run_t1_enhancement,
)
from lys_bbb.t1_registration import (
    T1_REGISTRATION_METHOD_VERSION,
    T1RegistrationConfig,
    T1RegistrationOutput,
    T1RegistrationRequest,
    run_t1_registration,
    sha256_file as registration_sha256_file,
)
from lys_bbb.t1_brain_mask_release import (
    FrozenT1BrainMaskRelease,
    sha256_file as t1_sha256_file,
    validate_t1_brain_mask_release,
)
from lys_bbb.t2_inference import (
    T2InferenceOutput,
    create_t2_qc_preview,
    run_t2_model_inference,
)
from lys_bbb.t2_model_release import (
    FrozenT2ModelRelease,
    validate_t2_model_release,
)
from lys_bbb.scan_conversion import convert_scan_assignment
from lys_bbb.scan_discovery import discover_mri_source
from lys_bbb.registration_runtime import ANTSPYX_BACKEND
from lys_bbb_app.domain.errors import StudyStateError
from lys_bbb_app.features import AppFeatures, active_features
from lys_bbb_app.domain.scan_import import (
    InputValidationState,
    ScanDiscoveryReport,
    ScanImportAssignment,
    ScanImportState,
    ScanInputRecord,
    ScanRole,
)
from lys_bbb_app.domain.study import (
    AuditEventRecord,
    CreateStudyRequest,
    CreateSubjectRequest,
    StudySnapshot,
)
from lys_bbb_app.domain.t1_brain_mask import (
    T1_BRAIN_MASK_APP_GENERATION_METHOD_VERSION,
    T1_BRAIN_MASK_METHOD_VERSION,
    T1BrainMaskArtifactDraft,
    T1BrainMaskReadiness,
)
from lys_bbb_app.domain.t1_analysis import (
    T1EnhancementReadiness,
    T1EnhancementResultDraft,
    T1RegistrationArtifactDraft,
    T1RegistrationReadiness,
    T1RegistrationState,
)
from lys_bbb_app.domain.t2_lesion import (
    ArtifactState,
    T2InferenceReadiness,
)
from lys_bbb_app.infrastructure.study_database import StudyRepository
from lys_bbb_app.infrastructure.external_viewer import (
    ViewerLaunch,
    launch_itksnap,
)
from lys_bbb_app.services.mri_input_service import (
    InputValidator,
    MriInputService,
    ScanConverter,
    ViewerLauncher,
)
from lys_bbb_app.services.t2_export_service import (
    ApprovedT2Export,
    ApprovedT2ExcelExport,
    export_approved_t2_results,
    export_approved_t2_results_excel,
)
from lys_bbb_app.services.t1_brain_mask_service import (
    T1BrainMaskEditSession,
    T1BrainMaskReviewService,
)
from lys_bbb_app.services.t2_review_service import (
    T2ManualEditSession,
    T2ReviewService,
)
from lys_bbb_app.services.t2_inference_service import T2InferenceService
from lys_bbb_app.services.atlas_mapping_service import AtlasMappingService


ProgressCallback = Callable[[int, int, str], None]
T2ReleaseValidator = Callable[[Path | str], FrozenT2ModelRelease]
T2InferenceRunner = Callable[..., T2InferenceOutput]
T2QCBuilder = Callable[[Path, Path, Path], Path]
T1ReleaseValidator = Callable[[Path], FrozenT1BrainMaskRelease]
T1BrainMaskRunner = Callable[..., T1BrainMaskOutput]
T1QCBuilder = Callable[[Path, Path, Path], Path]
T1RegistrationRunner = Callable[[T1RegistrationRequest], T1RegistrationOutput]
T1EnhancementRunner = Callable[[T1EnhancementRequest], T1EnhancementOutput]


class StudyService:
    """Own the currently opened canonical study repository."""

    def __init__(
        self,
        *,
        scan_converter: ScanConverter = convert_scan_assignment,
        input_validator: InputValidator = validate_managed_nifti,
        viewer_launcher: ViewerLauncher = launch_itksnap,
        t2_release_validator: T2ReleaseValidator = validate_t2_model_release,
        t2_inference_runner: T2InferenceRunner = run_t2_model_inference,
        t2_qc_builder: T2QCBuilder = create_t2_qc_preview,
        t1_release_validator: T1ReleaseValidator = validate_t1_brain_mask_release,
        t1_brain_mask_runner: T1BrainMaskRunner = run_local_t1_brain_mask,
        t1_qc_builder: T1QCBuilder = create_native_mask_qc_preview,
        t1_registration_runner: T1RegistrationRunner = run_t1_registration,
        t1_registration_config: T1RegistrationConfig = T1RegistrationConfig(),
        t1_enhancement_runner: T1EnhancementRunner = run_t1_enhancement,
        t1_enhancement_config: T1EnhancementConfig = T1EnhancementConfig(),
        ants_backend: str = ANTSPYX_BACKEND,
        features: AppFeatures | None = None,
    ) -> None:
        self.features = features if features is not None else active_features()
        self._repository: StudyRepository | None = None
        self._viewer_launcher = viewer_launcher
        self._t2_qc_builder = t2_qc_builder
        self._t1_release_validator = t1_release_validator
        self._t1_brain_mask_runner = t1_brain_mask_runner
        self._t1_qc_builder = t1_qc_builder
        self._t1_registration_runner = t1_registration_runner
        self._t1_registration_config = t1_registration_config
        self._t1_enhancement_runner = t1_enhancement_runner
        self._t1_enhancement_config = t1_enhancement_config
        self.atlas_mapping = AtlasMappingService(
            self._require_repository,
            ants_backend=ants_backend,
        )
        self.mri_inputs = MriInputService(
            self._require_repository,
            scan_converter=scan_converter,
            input_validator=input_validator,
            viewer_launcher=viewer_launcher,
            discovery_runner=discover_mri_source,
        )
        self.t2_inference = T2InferenceService(
            self._require_repository,
            release_validator=t2_release_validator,
            inference_runner=t2_inference_runner,
            qc_builder=t2_qc_builder,
        )

    @property
    def current_study(self) -> StudySnapshot | None:
        if self._repository is None:
            return None
        return self._repository.snapshot()

    def create_study(self, request: CreateStudyRequest) -> StudySnapshot:
        target = request.root_path.expanduser().resolve()
        if target.exists():
            raise StudyStateError(
                f"The study directory already exists and will not be overwritten: {target}"
            )
        staging = target.with_name(f".{target.name}.creating-{uuid4().hex[:8]}")
        try:
            repository = StudyRepository.create(replace(request, root_path=staging))
            repository.snapshot()
            staging.rename(target)
            self._repository = StudyRepository.open(target)
        except Exception:
            self._repository = None
            if staging.exists():
                shutil.rmtree(staging)
            raise
        return self._repository.snapshot()

    def open_study(self, path: Path | str) -> StudySnapshot:
        self._repository = StudyRepository.open(path)
        snapshot = self._repository.snapshot()
        self._repository.record_audit_event(
            "STUDY_OPENED",
            actor="Application",
            details={"root_path": str(snapshot.root_path)},
        )
        return self._repository.snapshot()

    def add_subject(self, request: CreateSubjectRequest) -> StudySnapshot:
        return self._require_repository().add_subject(request)

    def remove_subject(self, subject_id: str, *, actor: str) -> StudySnapshot:
        return self._require_repository().archive_subject(subject_id, actor=actor)

    def restore_subject(self, subject_id: str, *, actor: str) -> StudySnapshot:
        return self._require_repository().restore_subject(subject_id, actor=actor)

    def rename_subject(
        self,
        subject_id: str,
        subject_code: str,
        *,
        actor: str,
    ) -> StudySnapshot:
        return self._require_repository().rename_subject(
            subject_id,
            subject_code,
            actor=actor,
        )

    def update_subject_longitudinal_identifiers(
        self,
        subject_id: str,
        animal_identifier: str | None,
        time_identifier: str | None,
        *,
        actor: str,
    ) -> StudySnapshot:
        return self._require_repository().update_subject_longitudinal_identifiers(
            subject_id,
            animal_identifier,
            time_identifier,
            actor=actor,
        )

    def converted_mri_inputs(self, subject_id: str) -> tuple[ScanInputRecord, ...]:
        return self.mri_inputs.converted_inputs(subject_id)

    def validate_subject_inputs(
        self,
        subject_id: str,
        *,
        actor: str,
    ) -> StudySnapshot:
        return self.mri_inputs.validate_subject_inputs(subject_id, actor=actor)

    def _require_t1_model(self) -> None:
        if not self.features.t1_brain_mask:
            raise StudyStateError("T1 model generation is unavailable in this edition.")

    def register_t1_brain_mask_release(
        self,
        release_root: Path | str,
        *,
        actor: str,
    ) -> StudySnapshot:
        """Validate and activate the reviewed local RS2/M-seam method."""

        self._require_t1_model()
        repository = self._require_repository()
        try:
            release = self._t1_release_validator(Path(release_root))
            manifest_sha256 = t1_sha256_file(release.root_path / "release.json")
        except (FileNotFoundError, OSError, ValueError) as exc:
            raise StudyStateError(
                f"The T1 brain-mask release is not valid: {exc}"
            ) from exc
        method_metadata, method_spec_sha256 = _t1_brain_mask_method_spec(release)
        repository.register_t1_brain_mask_release(
            release,
            manifest_sha256=manifest_sha256,
            method_spec_sha256=method_spec_sha256,
            method_metadata=method_metadata,
            actor=actor,
        )
        return repository.snapshot()

    def t1_brain_mask_readiness(
        self,
        subject_ids: tuple[str, ...] | None = None,
    ) -> T1BrainMaskReadiness:
        """Return active subjects with a validated native pre-Gd T1."""

        self._require_t1_model()
        snapshot = self._require_repository().snapshot()
        requested = set(subject_ids) if subject_ids is not None else None
        active_ids = {subject.id for subject in snapshot.subjects}
        if requested is not None and requested - active_ids:
            raise StudyStateError("One or more selected subjects are no longer active.")
        active_masks = {
            artifact.subject_id
            for artifact in snapshot.t1_brain_mask_artifacts
            if artifact.active
        }
        eligible: list[str] = []
        blocked: list[tuple[str, str]] = []
        for subject in snapshot.subjects:
            if requested is not None and subject.id not in requested:
                continue
            if requested is None and subject.id in active_masks:
                blocked.append(
                    (subject.id, "A current T1 brain mask already exists for review or use.")
                )
                continue
            if not subject.expected_t1:
                blocked.append((subject.id, "T1 is marked not applicable."))
                continue
            pre_t1 = next(
                (
                    record
                    for record in snapshot.inputs_for_subject(subject.id)
                    if record.active and record.role is ScanRole.T1_PRE
                ),
                None,
            )
            if pre_t1 is None or pre_t1.state is not ScanImportState.CONVERTED:
                blocked.append((subject.id, "No converted pre-Gd T1 is available."))
                continue
            if pre_t1.validation_state is not InputValidationState.VALID:
                blocked.append(
                    (subject.id, "The active pre-Gd T1 has not passed validation.")
                )
                continue
            if pre_t1.output_path is None or not pre_t1.output_path.is_file():
                blocked.append((subject.id, "The managed pre-Gd T1 NIfTI is unavailable."))
                continue
            eligible.append(subject.id)
        return T1BrainMaskReadiness(tuple(eligible), tuple(blocked))

    def run_t1_brain_mask_generation(
        self,
        *,
        actor: str,
        subject_ids: tuple[str, ...] | None = None,
        device_name: str = "auto",
        progress: ProgressCallback | None = None,
    ) -> StudySnapshot:
        """Generate low-impact no-TTA drafts and persist them only on success."""

        self._require_t1_model()
        repository = self._require_repository()
        snapshot = repository.snapshot()
        release_record = snapshot.active_t1_brain_mask_release
        if release_record is None:
            raise StudyStateError(
                "Select and validate the frozen local T1 brain-mask release first."
            )
        try:
            release = self._t1_release_validator(release_record.root_path)
            manifest_sha256 = t1_sha256_file(release.root_path / "release.json")
        except (FileNotFoundError, OSError, ValueError) as exc:
            raise StudyStateError(
                f"The registered T1 brain-mask release is no longer valid: {exc}"
            ) from exc
        _release_method_metadata, release_method_spec_sha256 = (
            _t1_brain_mask_method_spec(release)
        )
        if (
            release.id != release_record.id
            or release.source_commit != release_record.source_commit
            or release.weights_sha256 != release_record.weights_sha256
            or release.test_time_augmentation
            != release_record.test_time_augmentation
            or manifest_sha256 != release_record.manifest_sha256
            or release_method_spec_sha256 != release_record.method_spec_sha256
        ):
            raise StudyStateError(
                "The installed T1 brain-mask method changed after validation. "
                "Select it again."
            )
        readiness = self.t1_brain_mask_readiness(subject_ids)
        if not readiness.eligible_subject_ids:
            raise StudyStateError(
                "No active subjects have a validated native pre-Gd T1 input."
            )
        inputs_by_subject = {
            subject_id: next(
                record
                for record in snapshot.inputs_for_subject(subject_id)
                if record.active
                and record.role is ScanRole.T1_PRE
                and record.state is ScanImportState.CONVERTED
                and record.output_path is not None
            )
            for subject_id in readiness.eligible_subject_ids
        }
        generation_method, generation_method_spec_sha256 = (
            _t1_brain_mask_app_generation_spec(release)
        )
        job_id = repository.create_t1_brain_mask_job(
            readiness.eligible_subject_ids,
            release_id=release.id,
            generation_metadata={
                "generation_method": generation_method,
                "generation_method_spec_sha256": generation_method_spec_sha256,
            },
            actor=actor,
        )
        output_root = (
            repository.root_path / "outputs" / "t1_brain_mask" / "jobs" / job_id
        )
        repository.start_t1_brain_mask_job(job_id)

        def report(current: int, total: int, message: str) -> None:
            repository.update_t1_brain_mask_job(job_id, current, total, message)
            if progress is not None:
                progress(current, total, message)

        drafts: list[T1BrainMaskArtifactDraft] = []
        total = len(readiness.eligible_subject_ids)
        try:
            for index, subject_id in enumerate(readiness.eligible_subject_ids, start=1):
                record = inputs_by_subject[subject_id]
                if record.output_path is None:
                    raise RuntimeError(f"The pre-Gd T1 is unavailable for {subject_id}.")
                report(index - 1, total, f"Generating T1 brain mask {index} of {total}")
                case_output = self._t1_brain_mask_runner(
                    release,
                    record.output_path,
                    output_root / "cases" / subject_id,
                    case_id=subject_id,
                    device_name=device_name,
                    disable_tta=True,
                )
                metadata = json.loads(case_output.metadata_path.read_text())
                generation = metadata.get("generation", {})
                if (
                    generation.get("test_time_augmentation") is not False
                    or generation.get("generation_variant")
                    != "explicit_no_tta_local_draft"
                ):
                    raise RuntimeError(
                        "The T1 brain-mask runner did not return the required explicit "
                        "no-TTA draft variant."
                    )
                drafts.append(
                    T1BrainMaskArtifactDraft(
                        subject_id=subject_id,
                        source_scan_input_id=record.id,
                        mask_path=case_output.draft_mask,
                        mask_sha256=case_output.draft_mask_sha256,
                        raw_mask_path=case_output.raw_rs2_mask,
                        raw_mask_sha256=case_output.raw_mask_sha256,
                        qc_preview_path=case_output.qc_preview,
                        foreground_voxels=case_output.foreground_voxels,
                        volume_mm3=case_output.volume_mm3,
                        device=str(generation.get("device", device_name)),
                        regularity_warnings=case_output.regularity_warnings,
                        metadata={
                            "generator_metadata": metadata,
                            "method_version": (
                                T1_BRAIN_MASK_APP_GENERATION_METHOD_VERSION
                            ),
                            "method_spec_sha256": generation_method_spec_sha256,
                            "generation_variant": "explicit_no_tta_local_draft",
                            "test_time_augmentation": False,
                            "predictions_are_drafts": True,
                            "human_review_required": True,
                        },
                    )
                )
                report(index, total, f"Generated T1 brain mask {index} of {total}")
            repository.complete_t1_brain_mask_job(
                job_id,
                tuple(drafts),
                release_id=release.id,
                output_path=output_root,
                actor=actor,
            )
        except Exception as exc:
            repository.fail_t1_brain_mask_job(job_id, str(exc), actor=actor)
            if isinstance(exc, StudyStateError):
                raise
            raise StudyStateError(f"T1 brain-mask generation failed: {exc}") from exc
        return repository.snapshot()

    def register_t1_registration_method(self, *, actor: str) -> StudySnapshot:
        """Register the deterministic rigid method used by app-managed jobs."""

        repository = self._require_repository()
        config = self._t1_registration_config
        repository.register_t1_registration_method(
            method_version=T1_REGISTRATION_METHOD_VERSION,
            method_spec_sha256=config.method_spec_sha256,
            config=config.method_spec(),
            actor=actor,
        )
        return repository.snapshot()

    def t1_registration_readiness(
        self,
        subject_ids: tuple[str, ...] | None = None,
    ) -> T1RegistrationReadiness:
        """Return subjects with validated inputs and an approved current brain mask."""

        snapshot = self._require_repository().snapshot()
        requested = set(subject_ids) if subject_ids is not None else None
        active_ids = {subject.id for subject in snapshot.subjects}
        if requested is not None and requested - active_ids:
            raise StudyStateError("One or more selected subjects are no longer active.")
        current_registrations = {
            artifact.subject_id
            for artifact in snapshot.t1_registration_artifacts
            if artifact.active
        }
        eligible: list[str] = []
        blocked: list[tuple[str, str]] = []
        for subject in snapshot.subjects:
            if requested is not None and subject.id not in requested:
                continue
            if requested is None and subject.id in current_registrations:
                blocked.append(
                    (subject.id, "A current T1 registration already exists for review or use.")
                )
                continue
            if not subject.expected_t1:
                blocked.append((subject.id, "T1 is marked not applicable."))
                continue
            inputs = {
                record.role: record
                for record in snapshot.inputs_for_subject(subject.id)
                if record.active
            }
            pre = inputs.get(ScanRole.T1_PRE)
            post = inputs.get(ScanRole.T1_POST)
            if pre is None or post is None:
                blocked.append((subject.id, "Both pre- and post-Gd T1 inputs are required."))
                continue
            if any(
                record.state is not ScanImportState.CONVERTED
                or record.validation_state is not InputValidationState.VALID
                or record.output_path is None
                or not record.output_path.is_file()
                for record in (pre, post)
            ):
                blocked.append(
                    (subject.id, "The active pre/post T1 pair must pass validation.")
                )
                continue
            mask = next(
                (
                    artifact
                    for artifact in snapshot.t1_brain_masks_for_subject(subject.id)
                    if artifact.active and artifact.state is ArtifactState.APPROVED
                ),
                None,
            )
            if (
                mask is None
                or snapshot.t1_brain_mask_approval_for_artifact(mask.id) is None
                or not mask.mask_path.is_file()
            ):
                blocked.append(
                    (subject.id, "Approve the current native pre-Gd brain mask first.")
                )
                continue
            eligible.append(subject.id)
        return T1RegistrationReadiness(tuple(eligible), tuple(blocked))

    def run_t1_registration(
        self,
        *,
        actor: str,
        subject_ids: tuple[str, ...] | None = None,
        progress: ProgressCallback | None = None,
    ) -> StudySnapshot:
        """Create durable post-to-pre artifacts that always require human approval."""

        repository = self._require_repository()
        snapshot = repository.snapshot()
        method = snapshot.active_t1_registration_method
        config = self._t1_registration_config
        if method is None:
            raise StudyStateError("Register the frozen T1 registration method first.")
        if (
            method.method_version != T1_REGISTRATION_METHOD_VERSION
            or method.method_spec_sha256 != config.method_spec_sha256
        ):
            raise StudyStateError(
                "The active T1 registration method differs from this application build."
            )
        readiness = self.t1_registration_readiness(subject_ids)
        if not readiness.eligible_subject_ids:
            raise StudyStateError(
                "No subjects have an approved brain mask and validated pre/post T1 pair."
            )
        snapshot = repository.snapshot()
        job_id = repository.create_t1_registration_job(
            readiness.eligible_subject_ids,
            method_id=method.id,
            actor=actor,
        )
        output_root = repository.root_path / "outputs" / "t1_registration" / "jobs" / job_id
        repository.start_t1_registration_job(job_id)
        drafts: list[T1RegistrationArtifactDraft] = []
        total = len(readiness.eligible_subject_ids)
        try:
            for index, subject_id in enumerate(readiness.eligible_subject_ids, start=1):
                subject = snapshot.subject(subject_id)
                if subject is None:
                    raise StudyStateError("A selected subject is no longer active.")
                inputs = {
                    record.role: record
                    for record in snapshot.inputs_for_subject(subject_id)
                    if record.active
                }
                pre = inputs[ScanRole.T1_PRE]
                post = inputs[ScanRole.T1_POST]
                mask = next(
                    artifact
                    for artifact in snapshot.t1_brain_masks_for_subject(subject_id)
                    if artifact.active and artifact.state is ArtifactState.APPROVED
                )
                if pre.output_path is None or post.output_path is None:
                    raise StudyStateError("A managed T1 input is unavailable.")
                _verify_immutable_file(
                    pre.output_path,
                    pre.output_sha256,
                    "managed pre-Gd T1 input",
                )
                _verify_immutable_file(
                    post.output_path,
                    post.output_sha256,
                    "managed post-Gd T1 input",
                )
                _verify_immutable_file(
                    mask.mask_path,
                    mask.mask_sha256,
                    "approved brain mask",
                )
                case_root = output_root / "cases" / subject_id
                repository.update_t1_registration_job(
                    job_id,
                    index - 1,
                    total,
                    f"Registering T1 pair {index} of {total}",
                )
                if progress is not None:
                    progress(index - 1, total, f"Registering {subject.subject_code}")
                request = T1RegistrationRequest(
                    case_id=subject.subject_code,
                    pre_t1_path=pre.output_path,
                    post_t1_path=post.output_path,
                    brain_mask_path=mask.mask_path,
                    registered_post_path=case_root / "post_registered_to_pre.nii.gz",
                    transform_path=case_root / "post_to_pre_ants_0GenericAffine.mat",
                    qc_preview_path=case_root / "registration_qc.png",
                    pre_t1_identity=f"study_subject_id={subject_id}",
                    post_t1_identity=f"study_subject_id={subject_id}",
                    config=config,
                )
                output = self._t1_registration_runner(request)
                if (
                    output.method_version != method.method_version
                    or output.method_spec_sha256 != method.method_spec_sha256
                ):
                    raise StudyStateError(
                        "Registration output does not match the registered method."
                    )
                expected_outputs = (
                    (
                        output.registered_post_path,
                        request.registered_post_path,
                        output.registered_post_sha256,
                        "registered post-Gd image",
                    ),
                    (
                        output.transform_path,
                        request.transform_path,
                        output.transform_sha256,
                        "registration transform",
                    ),
                    (
                        output.qc_preview_path,
                        request.qc_preview_path,
                        output.qc_preview_sha256,
                        "registration QC",
                    ),
                )
                for returned_path, requested_path, expected_sha256, label in expected_outputs:
                    if returned_path.resolve() != requested_path.resolve():
                        raise StudyStateError(
                            f"The {label} was written outside its durable job directory."
                        )
                    _verify_immutable_file(returned_path, expected_sha256, label)
                drafts.append(
                    T1RegistrationArtifactDraft(
                        subject_id=subject_id,
                        registered_post_path=output.registered_post_path,
                        registered_post_sha256=output.registered_post_sha256,
                        transform_path=output.transform_path,
                        transform_sha256=output.transform_sha256,
                        qc_preview_path=output.qc_preview_path,
                        qc_preview_sha256=output.qc_preview_sha256,
                        source_pre_scan_input_id=pre.id,
                        source_post_scan_input_id=post.id,
                        source_brain_mask_artifact_id=mask.id,
                        before_xcorr=output.before_xcorr,
                        after_xcorr=output.after_xcorr,
                        registration_metric=output.registration_metric,
                        optimizer_stop=output.optimizer_stop,
                        metadata={
                            **output.metadata,
                            "method_version": output.method_version,
                            "method_spec_sha256": output.method_spec_sha256,
                            "registered_post_is_immutable": True,
                        },
                    )
                )
                repository.update_t1_registration_job(
                    job_id,
                    index,
                    total,
                    f"Registered T1 pair {index} of {total}",
                )
                if progress is not None:
                    progress(index, total, f"Registered {subject.subject_code}")
            repository.complete_t1_registration_job(
                job_id,
                tuple(drafts),
                method_id=method.id,
                output_path=output_root,
                actor=actor,
            )
        except Exception as exc:
            repository.fail_t1_registration_job(job_id, str(exc), actor=actor)
            if isinstance(exc, StudyStateError):
                raise
            raise StudyStateError(f"T1 registration failed: {exc}") from exc
        return repository.snapshot()

    def approve_t1_registration(
        self,
        subject_id: str,
        artifact_id: str,
        *,
        reviewer: str,
    ) -> StudySnapshot:
        """Approve the exact registered image, transform, and QC bundle."""

        repository = self._require_repository()
        snapshot = repository.snapshot()
        artifact = next(
            (
                item
                for item in snapshot.t1_registrations_for_subject(subject_id)
                if item.id == artifact_id
            ),
            None,
        )
        if artifact is None or not artifact.active:
            raise StudyStateError("Use the subject's current T1 registration.")
        if artifact.state is not T1RegistrationState.REVIEW_REQUIRED:
            raise StudyStateError("Only a T1 registration awaiting review can be approved.")
        expected_files = (
            (
                artifact.registered_post_path,
                artifact.registered_post_sha256,
                "registered post-Gd image",
            ),
            (artifact.transform_path, artifact.transform_sha256, "registration transform"),
            (artifact.qc_preview_path, artifact.qc_preview_sha256, "registration QC"),
        )
        for path, expected_sha256, label in expected_files:
            try:
                observed = registration_sha256_file(path)
            except OSError as exc:
                raise StudyStateError(f"The {label} is unavailable: {exc}") from exc
            if observed != expected_sha256:
                raise StudyStateError(f"The {label} changed after it was registered.")
        repository.record_t1_registration_approval(artifact_id, reviewer=reviewer)
        return repository.snapshot()

    def register_t1_enhancement_method(self, *, actor: str) -> StudySnapshot:
        """Register the current calculation contract without claiming validation."""

        repository = self._require_repository()
        config = self._t1_enhancement_config
        repository.register_t1_enhancement_method(
            method_version=T1_ENHANCEMENT_METHOD_VERSION,
            method_spec_sha256=config.method_spec_sha256,
            config=config.method_spec(),
            actor=actor,
        )
        return repository.snapshot()

    def t1_enhancement_readiness(
        self,
        subject_ids: tuple[str, ...] | None = None,
    ) -> T1EnhancementReadiness:
        """Return subjects whose exact mask and registration are both approved."""

        snapshot = self._require_repository().snapshot()
        requested = set(subject_ids) if subject_ids is not None else None
        active_ids = {subject.id for subject in snapshot.subjects}
        if requested is not None and requested - active_ids:
            raise StudyStateError("One or more selected subjects are no longer active.")
        eligible: list[str] = []
        blocked: list[tuple[str, str]] = []
        for subject in snapshot.subjects:
            if requested is not None and subject.id not in requested:
                continue
            if (
                requested is None
                and snapshot.active_t1_enhancement_result_for_subject(subject.id) is not None
            ):
                blocked.append((subject.id, "A current provisional T1 result already exists."))
                continue
            registration = next(
                (
                    artifact
                    for artifact in snapshot.t1_registrations_for_subject(subject.id)
                    if artifact.active and artifact.state is T1RegistrationState.APPROVED
                ),
                None,
            )
            if (
                registration is None
                or snapshot.t1_registration_approval_for_artifact(registration.id) is None
            ):
                blocked.append((subject.id, "Approve the current T1 registration first."))
                continue
            mask = next(
                (
                    artifact
                    for artifact in snapshot.t1_brain_masks_for_subject(subject.id)
                    if artifact.id == registration.source_brain_mask_artifact_id
                    and artifact.active
                    and artifact.state is ArtifactState.APPROVED
                ),
                None,
            )
            if mask is None or snapshot.t1_brain_mask_approval_for_artifact(mask.id) is None:
                blocked.append((subject.id, "The registration's approved brain mask is outdated."))
                continue
            if not registration.registered_post_path.is_file() or not mask.mask_path.is_file():
                blocked.append((subject.id, "A reviewed T1 artifact is unavailable on disk."))
                continue
            eligible.append(subject.id)
        return T1EnhancementReadiness(tuple(eligible), tuple(blocked))

    def run_t1_enhancement(
        self,
        *,
        actor: str,
        subject_ids: tuple[str, ...] | None = None,
        progress: ProgressCallback | None = None,
    ) -> StudySnapshot:
        """Persist provisional results from exact approved registration artifacts."""

        repository = self._require_repository()
        snapshot = repository.snapshot()
        method = snapshot.active_t1_enhancement_method
        config = self._t1_enhancement_config
        if method is None:
            raise StudyStateError("Register the provisional T1 enhancement method first.")
        if (
            method.method_version != T1_ENHANCEMENT_METHOD_VERSION
            or method.method_spec_sha256 != config.method_spec_sha256
            or method.scientific_status != "PROVISIONAL"
        ):
            raise StudyStateError(
                "The active T1 enhancement method differs from this application build."
            )
        readiness = self.t1_enhancement_readiness(subject_ids)
        if not readiness.eligible_subject_ids:
            raise StudyStateError("No subjects have an approved T1 registration and mask.")
        snapshot = repository.snapshot()
        job_id = repository.create_t1_enhancement_job(
            readiness.eligible_subject_ids,
            method_id=method.id,
            actor=actor,
        )
        output_root = repository.root_path / "outputs" / "t1_enhancement" / "jobs" / job_id
        repository.start_t1_enhancement_job(job_id)
        drafts: list[T1EnhancementResultDraft] = []
        total = len(readiness.eligible_subject_ids)
        try:
            for index, subject_id in enumerate(readiness.eligible_subject_ids, start=1):
                subject = snapshot.subject(subject_id)
                if subject is None:
                    raise StudyStateError("A selected subject is no longer active.")
                registration = next(
                    artifact
                    for artifact in snapshot.t1_registrations_for_subject(subject_id)
                    if artifact.active and artifact.state is T1RegistrationState.APPROVED
                )
                mask = next(
                    artifact
                    for artifact in snapshot.t1_brain_masks_for_subject(subject_id)
                    if artifact.id == registration.source_brain_mask_artifact_id
                )
                pre = next(
                    record
                    for record in snapshot.inputs_for_subject(subject_id)
                    if record.id == registration.source_pre_scan_input_id
                )
                if pre.output_path is None:
                    raise StudyStateError("The registration's pre-Gd T1 is unavailable.")
                _verify_immutable_file(
                    pre.output_path,
                    pre.output_sha256,
                    "registration's managed pre-Gd T1 input",
                )
                _verify_immutable_file(
                    registration.registered_post_path,
                    registration.registered_post_sha256,
                    "approved registered post-Gd image",
                )
                _verify_immutable_file(
                    mask.mask_path,
                    mask.mask_sha256,
                    "approved brain mask",
                )
                repository.update_t1_enhancement_job(
                    job_id,
                    index - 1,
                    total,
                    f"Quantifying T1 enhancement {index} of {total}",
                )
                if progress is not None:
                    progress(index - 1, total, f"Quantifying {subject.subject_code}")
                request = T1EnhancementRequest(
                    case_id=subject.subject_code,
                    pre_t1_path=pre.output_path,
                    registered_post_t1_path=registration.registered_post_path,
                    approved_brain_mask_path=mask.mask_path,
                    output_directory=output_root / "cases" / subject_id,
                    config=config,
                    expected_registered_post_sha256=(
                        registration.registered_post_sha256
                    ),
                    expected_brain_mask_sha256=mask.mask_sha256,
                )
                output = self._t1_enhancement_runner(request)
                if (
                    output.method_version != method.method_version
                    or output.method_spec_sha256 != method.method_spec_sha256
                    or output.metadata.get("registration_recomputed") is not False
                ):
                    raise StudyStateError(
                        "Enhancement output does not match the provisional method contract."
                    )
                expected_root = request.output_directory.resolve()
                enhancement_outputs = (
                    (
                        output.percent_enhancement_map,
                        output.percent_enhancement_sha256,
                        "percent-enhancement map",
                    ),
                    (output.summary_csv, output.summary_sha256, "enhancement summary"),
                    (output.qc_preview_path, output.qc_preview_sha256, "enhancement QC"),
                    (output.metadata_path, output.metadata_sha256, "enhancement metadata"),
                )
                for path, expected_sha256, label in enhancement_outputs:
                    if not path.resolve().is_relative_to(expected_root):
                        raise StudyStateError(
                            f"The {label} was written outside its durable job directory."
                        )
                    _verify_immutable_file(path, expected_sha256, label)
                drafts.append(
                    T1EnhancementResultDraft(
                        subject_id=subject_id,
                        percent_enhancement_map=output.percent_enhancement_map,
                        percent_enhancement_sha256=output.percent_enhancement_sha256,
                        summary_csv=output.summary_csv,
                        summary_sha256=output.summary_sha256,
                        qc_preview_path=output.qc_preview_path,
                        qc_preview_sha256=output.qc_preview_sha256,
                        metadata_path=output.metadata_path,
                        metadata_sha256=output.metadata_sha256,
                        source_registration_artifact_id=registration.id,
                        source_brain_mask_artifact_id=mask.id,
                        source_pre_scan_input_id=pre.id,
                        metrics=output.metrics,
                        metadata={
                            **output.metadata,
                            "scientific_status": "PROVISIONAL",
                            "outputs_are": (
                                "semi-quantitative T1-weighted gadolinium enhancement"
                            ),
                        },
                    )
                )
                repository.update_t1_enhancement_job(
                    job_id,
                    index,
                    total,
                    f"Quantified T1 enhancement {index} of {total}",
                )
                if progress is not None:
                    progress(index, total, f"Quantified {subject.subject_code}")
            repository.complete_t1_enhancement_job(
                job_id,
                tuple(drafts),
                method_id=method.id,
                output_path=output_root,
                actor=actor,
            )
        except Exception as exc:
            repository.fail_t1_enhancement_job(job_id, str(exc), actor=actor)
            if isinstance(exc, StudyStateError):
                raise
            raise StudyStateError(f"T1 enhancement calculation failed: {exc}") from exc
        return repository.snapshot()

    def register_t2_model_release(
        self,
        release_root: Path | str,
        *,
        actor: str,
    ) -> StudySnapshot:
        return self.t2_inference.register_model_release(release_root, actor=actor)

    def t2_inference_readiness(
        self,
        subject_ids: tuple[str, ...] | None = None,
    ) -> T2InferenceReadiness:
        return self.t2_inference.readiness(subject_ids)

    def run_t2_lesion_inference(
        self,
        *,
        actor: str,
        subject_ids: tuple[str, ...] | None = None,
        device_name: str = "auto",
        progress: ProgressCallback | None = None,
    ) -> StudySnapshot:
        return self.t2_inference.run(
            actor=actor,
            subject_ids=subject_ids,
            device_name=device_name,
            progress=progress,
        )

    def open_mri_in_itksnap(
        self,
        subject_id: str,
        scan_input_id: str,
        *,
        actor: str,
        viewer_path: Path | str | None = None,
    ) -> ViewerLaunch:
        return self.mri_inputs.open_in_itksnap(
            subject_id,
            scan_input_id,
            actor=actor,
            viewer_path=viewer_path,
        )

    def start_t1_brain_mask_manual_edit(
        self,
        subject_id: str,
        artifact_id: str,
        *,
        actor: str,
        viewer_path: Path | str | None = None,
    ) -> T1BrainMaskEditSession:
        return self._t1_brain_mask_review_service().start_manual_edit(
            subject_id,
            artifact_id,
            actor=actor,
            viewer_path=viewer_path,
        )

    def prepare_t1_brain_mask_review_qc_slices(
        self,
        subject_id: str,
        artifact_id: str,
    ) -> StudySnapshot:
        self._t1_brain_mask_review_service().prepare_review_qc_slices(
            subject_id,
            artifact_id,
        )
        return self._require_repository().snapshot()

    def finish_t1_brain_mask_manual_edit(
        self,
        session: T1BrainMaskEditSession,
        *,
        actor: str,
    ) -> StudySnapshot:
        self._t1_brain_mask_review_service().finish_manual_edit(session, actor=actor)
        return self._require_repository().snapshot()

    def approve_t1_brain_mask(
        self,
        subject_id: str,
        artifact_id: str,
        *,
        reviewer: str,
    ) -> StudySnapshot:
        self._t1_brain_mask_review_service().approve_mask(
            subject_id,
            artifact_id,
            reviewer=reviewer,
        )
        return self._require_repository().snapshot()

    def start_t2_manual_edit(
        self,
        subject_id: str,
        artifact_id: str,
        *,
        actor: str,
        viewer_path: Path | str | None = None,
    ) -> T2ManualEditSession:
        return self._t2_review_service().start_manual_edit(
            subject_id,
            artifact_id,
            actor=actor,
            viewer_path=viewer_path,
        )

    def prepare_t2_review_qc_slices(
        self,
        subject_id: str,
        artifact_id: str,
    ) -> StudySnapshot:
        self._t2_review_service().prepare_review_qc_slices(subject_id, artifact_id)
        return self._require_repository().snapshot()

    def finish_t2_manual_edit(
        self,
        session: T2ManualEditSession,
        *,
        actor: str,
    ) -> StudySnapshot:
        self._t2_review_service().finish_manual_edit(
            session,
            actor=actor,
        )
        return self._require_repository().snapshot()

    def apply_t2_probability_threshold(
        self,
        subject_id: str,
        artifact_id: str,
        threshold: float,
        *,
        actor: str,
    ) -> StudySnapshot:
        self._t2_review_service().apply_probability_threshold(
            subject_id,
            artifact_id,
            threshold,
            actor=actor,
        )
        return self._require_repository().snapshot()

    def approve_t2_mask(
        self,
        subject_id: str,
        artifact_id: str,
        *,
        reviewer: str,
    ) -> StudySnapshot:
        self._t2_review_service().approve_mask(
            subject_id,
            artifact_id,
            reviewer=reviewer,
        )
        return self._require_repository().snapshot()

    def export_approved_t2_results_csv(
        self,
        destination: Path | str,
        *,
        actor: str,
    ) -> ApprovedT2Export:
        repository = self._require_repository()
        exported = export_approved_t2_results(repository.snapshot(), destination)
        repository.record_audit_event(
            "APPROVED_T2_RESULTS_EXPORTED",
            actor=actor,
            details={
                "path": str(exported.path),
                "row_count": exported.row_count,
                "blinded": exported.blinded,
                "approved_only": True,
            },
        )
        return exported

    def export_approved_t2_results_excel(
        self,
        destination: Path | str,
        *,
        detailed: bool,
        actor: str,
    ) -> ApprovedT2ExcelExport:
        repository = self._require_repository()
        exported = export_approved_t2_results_excel(
            repository.snapshot(),
            destination,
            detailed=detailed,
        )
        repository.record_audit_event(
            "APPROVED_T2_RESULTS_EXPORTED",
            actor=actor,
            details={
                "path": str(exported.path),
                "row_count": exported.row_count,
                "slice_row_count": exported.slice_row_count,
                "blinded": exported.blinded,
                "approved_only": True,
                "format": "xlsx",
                "detailed": exported.detailed,
            },
        )
        return exported

    def plan_bulk_flip(
        self,
        subject_ids: tuple[str, ...],
        flip_axes: tuple[int, ...],
        roles: tuple[ScanRole, ...],
    ) -> tuple[ScanImportAssignment, ...]:
        return self.mri_inputs.plan_bulk_flip(subject_ids, flip_axes, roles)

    def plan_orientation_correction(
        self,
        subject_ids: tuple[str, ...],
        flip_axes: tuple[int, ...],
        roles: tuple[ScanRole, ...],
        *,
        scan_input_id: str | None = None,
    ) -> tuple[ScanImportAssignment, ...]:
        return self.mri_inputs.plan_orientation_correction(
            subject_ids, flip_axes, roles, scan_input_id=scan_input_id,
        )

    def unblind(self, *, reviewer: str) -> StudySnapshot:
        return self._require_repository().unblind(actor=reviewer)

    def assign_groups(
        self,
        assignments: dict[str, str | None],
        *,
        reviewer: str,
    ) -> StudySnapshot:
        return self._require_repository().assign_groups(
            assignments,
            actor=reviewer,
        )

    def list_audit_events(self) -> tuple[AuditEventRecord, ...]:
        return self._require_repository().list_audit_events()

    def discover_mri_folder(self, path: Path | str, *, actor: str) -> ScanDiscoveryReport:
        return self.mri_inputs.discover_folder(path, actor=actor)

    def import_confirmed_scans(
        self,
        assignments: tuple[ScanImportAssignment, ...],
        *,
        actor: str,
        progress: ProgressCallback | None = None,
    ) -> StudySnapshot:
        return self.mri_inputs.import_confirmed_scans(
            assignments,
            actor=actor,
            progress=progress,
        )

    def close_study(self) -> None:
        self._repository = None

    def _require_repository(self) -> StudyRepository:
        if self._repository is None:
            raise StudyStateError("Create or open a study before changing study state.")
        return self._repository

    def _t2_review_service(self) -> T2ReviewService:
        return T2ReviewService(
            self._require_repository(),
            viewer_launcher=self._viewer_launcher,
            qc_builder=self._t2_qc_builder,
        )

    def _t1_brain_mask_review_service(self) -> T1BrainMaskReviewService:
        return T1BrainMaskReviewService(
            self._require_repository(),
            viewer_launcher=self._viewer_launcher,
            qc_builder=self._t1_qc_builder,
        )


def _verify_immutable_file(path: Path, expected_sha256: str | None, label: str) -> None:
    """Fail closed when a persisted dependency or returned artifact has changed."""

    if not expected_sha256:
        raise StudyStateError(f"The {label} has no recorded checksum.")
    try:
        observed_sha256 = registration_sha256_file(path)
    except OSError as exc:
        raise StudyStateError(f"The {label} is unavailable: {exc}") from exc
    if observed_sha256 != expected_sha256:
        raise StudyStateError(f"The {label} does not match its recorded checksum.")


def _t1_brain_mask_method_spec(
    release: FrozenT1BrainMaskRelease,
) -> tuple[dict[str, object], str]:
    """Return the persisted reviewed method contract and its deterministic hash."""

    payload: dict[str, object] = {
        "method_version": T1_BRAIN_MASK_METHOD_VERSION,
        "release_id": release.id,
        "source_commit": release.source_commit,
        "weights_sha256": release.weights_sha256,
        "test_time_augmentation": release.test_time_augmentation,
        "generation_variant": "reviewed_eight_way_tta",
        "gap_configuration": asdict(GapRefinementConfig()),
        "cleanup_configuration": asdict(MSeamCleanupConfig()),
        "regularity_configuration": asdict(MaskRegularityConfig()),
        "human_review_required": True,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return payload, hashlib.sha256(canonical).hexdigest()


def _t1_brain_mask_app_generation_spec(
    release: FrozenT1BrainMaskRelease,
) -> tuple[dict[str, object], str]:
    """Return the desktop's explicit low-impact draft-generation contract."""

    payload: dict[str, object] = {
        "method_version": T1_BRAIN_MASK_APP_GENERATION_METHOD_VERSION,
        "release_id": release.id,
        "source_commit": release.source_commit,
        "weights_sha256": release.weights_sha256,
        "test_time_augmentation": False,
        "generation_variant": "explicit_no_tta_local_draft",
        "gap_configuration": asdict(GapRefinementConfig()),
        "cleanup_configuration": asdict(MSeamCleanupConfig()),
        "regularity_configuration": asdict(MaskRegularityConfig()),
        "human_review_required": True,
        "scientific_status": "PROVISIONAL",
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return payload, hashlib.sha256(canonical).hexdigest()
