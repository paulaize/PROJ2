"""Application orchestration for the reviewed atlas-mapping vertical slice."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Callable
from uuid import uuid4

from lys_bbb.atlas_mapping import (
    AtlasCompositeRequest,
    MappingApprovalGate,
    compute_native_t2_lesion_overlap,
    create_native_composite_labels,
)
from lys_bbb.atlas_qc import (
    create_atlas_to_t1_qc,
    create_composite_all_slice_qc,
    create_t1_to_t2_all_slice_qc,
)
from lys_bbb.atlas_registration import (
    AtlasToT1Config,
    AtlasToT1Request,
    run_atlas_to_t1_candidates,
)
from lys_bbb.atlas_release import (
    AIDAMRI_LABELS_SHA256,
    AIDAMRI_LOOKUP_SHA256,
    AIDAMRI_TEMPLATE_SHA256,
    AtlasReleaseSpec,
    create_annotation_support_template_mask,
    inspect_nifti_geometry,
    load_major_region_scheme,
    require_same_physical_grid,
    validate_atlas_release,
)
from lys_bbb.hashing import sha256_file
from lys_bbb.t1_t2_registration import (
    T1ToT2Config,
    T1ToT2Request,
    run_t1_to_t2_registration,
)
from lys_bbb_app.domain.atlas_mapping import AtlasMappingState, AtlasReviewState
from lys_bbb_app.domain.errors import StudyStateError
from lys_bbb_app.domain.scan_import import (
    InputValidationState,
    ScanImportState,
    ScanRole,
)
from lys_bbb_app.domain.t2_lesion import ArtifactState
from lys_bbb_app.infrastructure.atlas_mapping_repository import AtlasMappingRepository
from lys_bbb_app.infrastructure.study_database import StudyRepository


RepositoryProvider = Callable[[], StudyRepository]
ProgressCallback = Callable[[int, int, str], None]


class AtlasMappingService:
    """Keep UI orchestration separate from ANTs and SQLite implementations."""

    def __init__(
        self,
        repository_provider: RepositoryProvider,
        *,
        atlas_runner=run_atlas_to_t1_candidates,
        t1_t2_runner=run_t1_to_t2_registration,
        composite_runner=create_native_composite_labels,
    ) -> None:
        self._repository_provider = repository_provider
        self._atlas_runner = atlas_runner
        self._t1_t2_runner = t1_t2_runner
        self._composite_runner = composite_runner
        self._atlas_config = AtlasToT1Config()
        self._t1_t2_config = T1ToT2Config()

    def state(self, subject_id: str) -> AtlasMappingState:
        return self._feature_repository().state(subject_id)

    def register_aidamri_release(
        self,
        *,
        template_path: Path,
        labels_path: Path,
        source_lookup_path: Path,
        actor: str,
    ) -> AtlasMappingState | None:
        repository = self._study_repository()
        resource_root = repository.root_path / "outputs" / "atlas_resources"
        resource_root.mkdir(parents=True, exist_ok=True)
        mask_path = resource_root / "aidamri_annotation_support_mask_v1.nii.gz"
        if not mask_path.exists():
            create_annotation_support_template_mask(labels_path, mask_path)
        spec = AtlasReleaseSpec(
            template_path=template_path.resolve(),
            labels_path=labels_path.resolve(),
            source_lookup_path=source_lookup_path.resolve(),
            template_mask_path=mask_path,
            template_sha256=AIDAMRI_TEMPLATE_SHA256,
            labels_sha256=AIDAMRI_LABELS_SHA256,
            source_lookup_sha256=AIDAMRI_LOOKUP_SHA256,
            template_mask_sha256=sha256_file(mask_path),
        )
        validated = validate_atlas_release(spec)
        self._feature_repository().register_release(validated, actor=actor)
        snapshot = repository.snapshot()
        return self.state(snapshot.subjects[0].id) if snapshot.subjects else None

    def register_major_region_scheme(
        self, mapping_path: Path, *, actor: str
    ) -> AtlasMappingState | None:
        feature = self._feature_repository()
        release = self._active_release_record()
        validated = validate_atlas_release(self._release_spec(release))
        scheme = load_major_region_scheme(
            mapping_path.resolve(),
            source_label_ids=validated.label_ids,
            approved=False,
        )
        feature.register_scheme(scheme, actor=actor)
        snapshot = self._study_repository().snapshot()
        return self.state(snapshot.subjects[0].id) if snapshot.subjects else None

    def approve_major_region_scheme(self, scheme_id: str, *, reviewer: str) -> None:
        state = self._state_for_any_subject()
        if state.scheme is None or state.scheme.id != scheme_id:
            raise StudyStateError("The active major-region draft is unavailable.")
        release = self._active_release_record()
        validated = validate_atlas_release(self._release_spec(release))
        load_major_region_scheme(
            state.scheme.mapping_path,
            source_label_ids=validated.label_ids,
            approved=True,
        )
        self._feature_repository().approve_scheme(scheme_id, reviewer=reviewer)

    def import_t2_registration_support_mask(
        self,
        subject_id: str,
        source_mask_path: Path,
        *,
        actor: str,
    ) -> str:
        repository = self._study_repository()
        snapshot = repository.snapshot()
        t2 = self._validated_input(snapshot, subject_id, ScanRole.T2)
        if t2.output_path is None:
            raise StudyStateError("The managed native T2 is unavailable.")
        require_same_physical_grid(
            inspect_nifti_geometry(t2.output_path),
            inspect_nifti_geometry(source_mask_path),
            names=("native T2", "T2 registration-support mask"),
            affine_atol=1e-4,
        )
        import nibabel as nib
        import numpy as np

        data = np.asanyarray(nib.load(str(source_mask_path)).dataobj)
        values = set(float(value) for value in np.unique(data))
        if not values.issubset({0.0, 1.0}) or 1.0 not in values:
            raise StudyStateError("The T2 registration-support mask must be binary and non-empty.")
        destination = (
            repository.root_path
            / "outputs"
            / "atlas_mapping"
            / "t2_support_masks"
            / subject_id
            / f"{uuid4()}.nii.gz"
        )
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_mask_path, destination)
        return self._feature_repository().create_t2_support_mask(
            subject_id=subject_id,
            source_t2_scan_input_id=t2.id,
            mask_path=destination,
            mask_sha256=sha256_file(destination),
            actor=actor,
        )

    def approve_t2_registration_support_mask(
        self, artifact_id: str, *, reviewer: str
    ) -> None:
        self._feature_repository().approve_t2_support_mask(
            artifact_id, reviewer=reviewer
        )

    def run_atlas_to_t1(
        self,
        subject_id: str,
        *,
        actor: str,
        progress: ProgressCallback | None = None,
    ) -> AtlasMappingState:
        repository = self._study_repository()
        snapshot = repository.snapshot()
        pre = self._validated_input(snapshot, subject_id, ScanRole.T1_PRE)
        mask = self._approved_t1_mask(snapshot, subject_id)
        release_record = self._active_release_record()
        release_spec = self._release_spec(release_record)
        validate_atlas_release(release_spec)
        if pre.output_path is None:
            raise StudyStateError("The managed native pre-Gd T1 is unavailable.")
        method_id = self._feature_repository().register_method(
            "atlas_to_t1",
            method_version=self._atlas_config.method_spec()["method_version"],
            method_spec_sha256=self._atlas_config.method_spec_sha256,
            config=self._atlas_config.method_spec(),
            actor=actor,
        )
        job_id = self._feature_repository().create_job(
            "atlas_to_t1", subject_id=subject_id, method_id=method_id, actor=actor
        )
        self._feature_repository().start_job("atlas_to_t1", job_id, total=3)
        output_dir = (
            repository.root_path / "outputs" / "atlas_mapping" / "atlas_to_t1" / job_id
        )

        def report(current: int, total: int, stage: str) -> None:
            self._feature_repository().update_job(
                "atlas_to_t1", job_id, current, total, stage
            )
            if progress is not None:
                progress(current, total, stage)

        try:
            output = self._atlas_runner(
                AtlasToT1Request(
                    case_id=subject_id,
                    pre_t1_path=pre.output_path,
                    approved_brain_mask_path=mask.mask_path,
                    atlas_release=release_spec,
                    output_directory=output_dir,
                    config=self._atlas_config,
                ),
                progress=report,
            )
            qc_by_candidate = {}
            for candidate in output.candidates:
                qc_by_candidate[candidate.candidate] = create_atlas_to_t1_qc(
                    native_pre_t1_path=pre.output_path,
                    approved_brain_mask_path=mask.mask_path,
                    warped_atlas_intensity_path=candidate.warped_intensity_path,
                    warped_atlas_support_path=candidate.warped_support_path,
                    output_path=(
                        candidate.warped_intensity_path.parent
                        / f"{candidate.candidate}_atlas_to_pre_t1_qc.png"
                    ),
                    candidate=candidate.candidate,
                    transform_summary=candidate.affine_metrics,
                )
            self._feature_repository().complete_atlas_to_t1(
                job_id=job_id,
                subject_id=subject_id,
                method_id=method_id,
                source_pre_scan_input_id=pre.id,
                source_t1_mask_artifact_id=mask.id,
                atlas_release_id=release_record.id,
                output=output,
                qc_by_candidate=qc_by_candidate,
                actor=actor,
            )
        except Exception as exc:
            self._feature_repository().fail_job("atlas_to_t1", job_id, str(exc))
            if isinstance(exc, StudyStateError):
                raise
            raise StudyStateError(f"Atlas-to-pre-T1 registration failed: {exc}") from exc
        return self.state(subject_id)

    def approve_atlas_to_t1_candidate(
        self, artifact_id: str, *, reviewer: str
    ) -> None:
        self._feature_repository().approve_atlas_to_t1(
            artifact_id, reviewer=reviewer
        )

    def run_t1_to_t2(
        self,
        subject_id: str,
        *,
        actor: str,
        exclude_current_lesion: bool = False,
        progress: ProgressCallback | None = None,
    ) -> AtlasMappingState:
        repository = self._study_repository()
        snapshot = repository.snapshot()
        pre = self._validated_input(snapshot, subject_id, ScanRole.T1_PRE)
        t2 = self._validated_input(snapshot, subject_id, ScanRole.T2)
        t1_mask = self._approved_t1_mask(snapshot, subject_id)
        state = self.state(subject_id)
        support = state.t2_support_mask
        if support is None or support.state is not AtlasReviewState.APPROVED:
            raise StudyStateError(
                "Import, inspect, and approve a T2 registration-support mask first."
            )
        lesion = self._current_t2_lesion(snapshot, subject_id)
        if pre.output_path is None or t2.output_path is None:
            raise StudyStateError("The managed T1/T2 inputs are unavailable.")
        config = T1ToT2Config(exclude_lesion_from_metric=exclude_current_lesion)
        method_id = self._feature_repository().register_method(
            "t1_to_t2",
            method_version=config.method_spec()["method_version"],
            method_spec_sha256=config.method_spec_sha256,
            config=config.method_spec(),
            actor=actor,
        )
        job_id = self._feature_repository().create_job(
            "t1_to_t2", subject_id=subject_id, method_id=method_id, actor=actor
        )
        self._feature_repository().start_job("t1_to_t2", job_id, total=1)
        output_dir = (
            repository.root_path / "outputs" / "atlas_mapping" / "t1_to_t2" / job_id
        )

        def report(current: int, total: int, stage: str) -> None:
            self._feature_repository().update_job(
                "t1_to_t2", job_id, current, total, stage
            )
            if progress is not None:
                progress(current, total, stage)

        try:
            output = self._t1_t2_runner(
                T1ToT2Request(
                    case_id=subject_id,
                    pre_t1_path=pre.output_path,
                    approved_t1_brain_mask_path=t1_mask.mask_path,
                    native_t2_path=t2.output_path,
                    t2_registration_support_mask_path=support.mask_path,
                    pre_t1_identity=(
                        f"subject={subject_id};session={pre.session_id};input={pre.id}"
                    ),
                    t2_identity=(
                        f"subject={subject_id};session={t2.session_id};input={t2.id}"
                    ),
                    lesion_exclusion_mask_path=(
                        lesion.mask_path if exclude_current_lesion and lesion else None
                    ),
                    output_directory=output_dir,
                    config=config,
                ),
                progress=report,
            )
            qc = create_t1_to_t2_all_slice_qc(
                native_t2_path=t2.output_path,
                transformed_t1_path=output.transformed_t1_path,
                transformed_t1_brain_mask_path=output.transformed_t1_brain_mask_path,
                t2_registration_support_mask_path=support.mask_path,
                native_lesion_mask_path=lesion.mask_path if lesion else None,
                output_directory=output_dir / "qc",
                transform_summary=output.affine_metrics,
            )
            self._feature_repository().complete_t1_to_t2(
                job_id=job_id,
                subject_id=subject_id,
                method_id=method_id,
                source_pre_scan_input_id=pre.id,
                source_t2_scan_input_id=t2.id,
                source_t1_mask_artifact_id=t1_mask.id,
                source_t2_support_mask_id=support.id,
                lesion_exclusion_artifact_id=(
                    lesion.id if exclude_current_lesion and lesion else None
                ),
                output=output,
                qc_montage_path=qc.montage_path,
                qc_manifest_path=qc.manifest_path,
                qc_slice_paths=qc.slice_paths,
                actor=actor,
            )
        except Exception as exc:
            self._feature_repository().fail_job("t1_to_t2", job_id, str(exc))
            if isinstance(exc, StudyStateError):
                raise
            raise StudyStateError(f"Pre-T1-to-T2 registration failed: {exc}") from exc
        return self.state(subject_id)

    def approve_t1_to_t2(self, artifact_id: str, *, reviewer: str) -> None:
        self._feature_repository().approve_t1_to_t2(
            artifact_id, reviewer=reviewer
        )

    def create_composite(self, subject_id: str, *, actor: str) -> AtlasMappingState:
        repository = self._study_repository()
        snapshot = repository.snapshot()
        state = self.state(subject_id)
        if state.release is None or state.scheme is None:
            raise StudyStateError("Register the atlas release and major-region scheme first.")
        if state.scheme.state is not AtlasReviewState.APPROVED:
            raise StudyStateError("Approve the proposed major-region mapping first.")
        atlas_to_t1 = state.selected_atlas_to_t1
        t1_to_t2 = state.t1_to_t2
        if (
            atlas_to_t1 is None
            or atlas_to_t1.state is not AtlasReviewState.APPROVED
            or t1_to_t2 is None
            or t1_to_t2.state is not AtlasReviewState.APPROVED
        ):
            raise StudyStateError("Approve both exact registration artifacts first.")
        t2 = self._validated_input(snapshot, subject_id, ScanRole.T2)
        pre = self._validated_input(snapshot, subject_id, ScanRole.T1_PRE)
        lesion = self._current_t2_lesion(snapshot, subject_id)
        if lesion is None:
            raise StudyStateError("A current native T2 lesion mask is required for QC.")
        if t2.output_path is None or pre.output_path is None:
            raise StudyStateError("The managed T1/T2 inputs are unavailable.")
        release = validate_atlas_release(self._release_spec(state.release))
        scheme = load_major_region_scheme(
            state.scheme.mapping_path,
            source_label_ids=release.label_ids,
            approved=True,
        )
        output_dir = (
            repository.root_path
            / "outputs"
            / "atlas_mapping"
            / "composites"
            / str(uuid4())
        )
        output = self._composite_runner(
            AtlasCompositeRequest(
                source_atlas_labels_path=state.release.labels_path,
                major_region_scheme=scheme,
                native_pre_t1_path=pre.output_path,
                native_t2_path=t2.output_path,
                atlas_to_t1_transform_path=atlas_to_t1.transform_path,
                t1_to_t2_transform_path=t1_to_t2.transform_path,
                output_directory=output_dir,
            )
        )
        qc = create_composite_all_slice_qc(
            native_t2_path=t2.output_path,
            major_labels_path=output.labels_in_native_t2_path,
            native_lesion_mask_path=lesion.mask_path,
            allowed_major_region_ids=scheme.allowed_major_region_ids,
            output_directory=output_dir / "qc",
        )
        self._feature_repository().complete_composite(
            subject_id=subject_id,
            source_atlas_to_t1_artifact_id=atlas_to_t1.id,
            source_t1_to_t2_artifact_id=t1_to_t2.id,
            atlas_release_id=state.release.id,
            major_region_scheme_id=state.scheme.id,
            source_t2_scan_input_id=t2.id,
            output=output,
            qc_montage_path=qc.montage_path,
            qc_manifest_path=qc.manifest_path,
            qc_slice_paths=qc.slice_paths,
            actor=actor,
        )
        return self.state(subject_id)

    def approve_composite(self, artifact_id: str, *, reviewer: str) -> None:
        self._feature_repository().approve_composite(
            artifact_id, reviewer=reviewer
        )

    def calculate_result(self, subject_id: str, *, actor: str) -> AtlasMappingState:
        repository = self._study_repository()
        snapshot = repository.snapshot()
        state = self.state(subject_id)
        if state.release is None or state.scheme is None or state.composite is None:
            raise StudyStateError("The approved atlas mapping dependencies are incomplete.")
        if state.composite.state is not AtlasReviewState.APPROVED:
            raise StudyStateError("Approve the composite QC on every T2 slice first.")
        lesion = self._current_t2_lesion(snapshot, subject_id)
        if lesion is None or lesion.state is not ArtifactState.APPROVED:
            raise StudyStateError("Approve the current native T2 lesion mask first.")
        t2 = self._validated_input(snapshot, subject_id, ScanRole.T2)
        if t2.output_path is None:
            raise StudyStateError("The managed native T2 is unavailable.")
        release = validate_atlas_release(self._release_spec(state.release))
        scheme = load_major_region_scheme(
            state.scheme.mapping_path,
            source_label_ids=release.label_ids,
            approved=True,
        )
        orientation = "".join(t2.output_axis_codes)
        result = compute_native_t2_lesion_overlap(
            native_t2_path=t2.output_path,
            native_lesion_mask_path=lesion.mask_path,
            major_labels_in_t2_path=state.composite.labels_path,
            atlas_support_in_t2_path=state.composite.support_path,
            scheme=scheme,
            approval_gate=MappingApprovalGate(True, True, True, True, True),
            reviewed_orientation=orientation,
            output_directory=(
                repository.root_path
                / "outputs"
                / "atlas_mapping"
                / "results"
                / str(uuid4())
            ),
        )
        self._feature_repository().record_result(
            subject_id=subject_id,
            source_composite_artifact_id=state.composite.id,
            source_lesion_artifact_id=lesion.id,
            major_region_scheme_id=state.scheme.id,
            result=result,
            actor=actor,
        )
        return self.state(subject_id)

    def _feature_repository(self) -> AtlasMappingRepository:
        return AtlasMappingRepository(self._study_repository())

    def _study_repository(self) -> StudyRepository:
        return self._repository_provider()

    def _state_for_any_subject(self) -> AtlasMappingState:
        snapshot = self._study_repository().snapshot()
        if not snapshot.subjects:
            raise StudyStateError("Add a subject before configuring atlas mapping.")
        return self.state(snapshot.subjects[0].id)

    def _active_release_record(self):
        state = self._state_for_any_subject()
        if state.release is None:
            raise StudyStateError("Register the local AIDAmri release first.")
        return state.release

    @staticmethod
    def _release_spec(record) -> AtlasReleaseSpec:
        return AtlasReleaseSpec(
            template_path=record.template_path,
            labels_path=record.labels_path,
            source_lookup_path=record.source_lookup_path,
            template_mask_path=record.template_mask_path,
            release_version=record.release_version,
            revision=record.aidamri_revision,
            template_sha256=record.template_sha256,
            labels_sha256=record.labels_sha256,
            source_lookup_sha256=record.source_lookup_sha256,
            template_mask_sha256=record.template_mask_sha256,
        )

    @staticmethod
    def _validated_input(snapshot, subject_id: str, role: ScanRole):
        record = next(
            (
                item
                for item in snapshot.inputs_for_subject(subject_id)
                if item.active and item.role is role
            ),
            None,
        )
        if (
            record is None
            or record.state is not ScanImportState.CONVERTED
            or record.validation_state is not InputValidationState.VALID
        ):
            raise StudyStateError(
                f"A current validated {role.value} input is required for atlas mapping."
            )
        return record

    @staticmethod
    def _approved_t1_mask(snapshot, subject_id: str):
        mask = next(
            (
                item
                for item in snapshot.t1_brain_mask_artifacts
                if item.subject_id == subject_id
                and item.active
                and item.state is ArtifactState.APPROVED
            ),
            None,
        )
        if mask is None:
            raise StudyStateError(
                "Atlas mapping requires the exact current approved RS2/M-seam pre-T1 mask."
            )
        return mask

    @staticmethod
    def _current_t2_lesion(snapshot, subject_id: str):
        return next(
            (
                item
                for item in snapshot.artifacts
                if item.subject_id == subject_id and item.active
            ),
            None,
        )
