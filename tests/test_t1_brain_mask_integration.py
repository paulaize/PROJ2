"""End-to-end tests for persistent T1 brain-mask generation and approval."""

from __future__ import annotations

import json
from pathlib import Path

import nibabel as nib
import numpy as np
import pytest

from lys_bbb.t1_brain_mask import T1BrainMaskOutput
from lys_bbb.t1_brain_mask_release import FrozenT1BrainMaskRelease, sha256_file
from lys_bbb.t1_enhancement import T1EnhancementOutput
from lys_bbb.t1_registration import T1RegistrationOutput
from lys_bbb_app.domain.t1_analysis import (
    T1EnhancementResultState,
    T1RegistrationState,
)
from lys_bbb_app.domain.errors import StudyStateError
from lys_bbb_app.domain.scan_import import (
    ImportConfidence,
    OrientationPolicy,
    ScanImportAssignment,
    ScanRole,
    SourceFormat,
)
from lys_bbb_app.domain.study import CreateStudyRequest
from lys_bbb_app.domain.t2_lesion import ArtifactState, ProcessingJobState
from lys_bbb_app.application.study_presenter import present_study
from lys_bbb_app.infrastructure.external_viewer import ViewerLaunch
from lys_bbb_app.services.study_service import StudyService


def _build_service_with_t1_draft(
    tmp_path: Path,
    *,
    registration_runner=None,
    enhancement_runner=None,
) -> tuple[StudyService, str, str, Path]:
    release_root = tmp_path / "t1-release"
    release_root.mkdir()
    (release_root / "release.json").write_text('{"test": true}\n')
    release = FrozenT1BrainMaskRelease(
        id="rs2net-m-seam-test-v1",
        root_path=release_root,
        source_path=release_root / "source",
        weights_path=release_root / "weights.pt",
        source_commit="reviewed-source",
        weights_sha256="reviewed-weights",
        test_time_augmentation=True,
    )

    def validate_release(_path: Path) -> FrozenT1BrainMaskRelease:
        return release

    def run_brain_mask(
        _release: FrozenT1BrainMaskRelease,
        input_path: Path,
        output_root: Path,
        *,
        case_id: str,
        device_name: str,
        disable_tta: bool,
    ) -> T1BrainMaskOutput:
        assert disable_tta is False
        output_root.mkdir(parents=True)
        reference = nib.load(input_path)
        raw = np.zeros(reference.shape, dtype=np.uint8)
        raw[1:4, 1:4, 1:3] = 1
        draft = raw.copy()
        draft[1, 1, 1] = 0
        raw_path = output_root / "raw_rs2_brain_mask.nii.gz"
        draft_path = output_root / "draft_m_seam_brain_mask.nii.gz"
        qc_path = output_root / "qc" / "draft_mask_qc.png"
        qc_path.parent.mkdir()
        nib.save(nib.Nifti1Image(raw, reference.affine), raw_path)
        nib.save(nib.Nifti1Image(draft, reference.affine), draft_path)
        qc_path.write_bytes(b"png")
        metadata_path = output_root / "metadata.json"
        metadata_path.write_text(
            json.dumps(
                {
                    "generation": {
                        "device": device_name,
                        "test_time_augmentation": True,
                    },
                    "human_review_required": True,
                }
            )
        )
        voxels = int(np.count_nonzero(draft))
        return T1BrainMaskOutput(
            case_id=case_id,
            source_t1=input_path,
            raw_rs2_mask=raw_path,
            draft_mask=draft_path,
            removed_mask=None,
            cleanup_changed_mask=None,
            qc_preview=qc_path,
            metadata_path=metadata_path,
            raw_mask_sha256=sha256_file(raw_path),
            draft_mask_sha256=sha256_file(draft_path),
            foreground_voxels=voxels,
            volume_mm3=float(voxels * np.prod(reference.header.get_zooms()[:3])),
            regularity_warnings=(),
        )

    def build_qc(_scan: Path, _mask: Path, output: Path) -> Path:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"png")
        return output

    def launch_viewer(
        image_path: Path,
        _viewer_path: Path | str | None = None,
        segmentation_path: Path | None = None,
    ) -> ViewerLaunch:
        return ViewerLaunch(Path("/test/itksnap"), image_path, 123, segmentation_path)

    service_kwargs = {}
    if registration_runner is not None:
        service_kwargs["t1_registration_runner"] = registration_runner
    if enhancement_runner is not None:
        service_kwargs["t1_enhancement_runner"] = enhancement_runner
    service = StudyService(
        t1_release_validator=validate_release,
        t1_brain_mask_runner=run_brain_mask,
        t1_qc_builder=build_qc,
        viewer_launcher=launch_viewer,
        **service_kwargs,
    )
    service.create_study(
        CreateStudyRequest(tmp_path / "study", "Study", "study", actor="Reviewer")
    )
    raw_root = tmp_path / "raw"
    raw_root.mkdir()
    affine = np.diag([0.1, 0.1, 0.5, 1.0])
    pre = raw_root / "Mouse-01_pre_t1.nii.gz"
    post = raw_root / "Mouse-01_post_t1.nii.gz"
    image = np.arange(5 * 6 * 4, dtype=np.float32).reshape(5, 6, 4)
    nib.save(nib.Nifti1Image(image, affine), pre)
    nib.save(nib.Nifti1Image(image + 10, affine), post)
    assignments = tuple(
        ScanImportAssignment(
            proposal_id=f"proposal-{role.value}",
            subject_code="Mouse-01",
            role=role,
            source_path=path,
            source_format=SourceFormat.NIFTI,
            session_id="nifti",
            scan_id=None,
            protocol="T1w",
            method="NIfTI",
            acquisition_orientation="from affine",
            confidence=ImportConfidence.HIGH,
            orientation_policy=OrientationPolicy.NATIVE,
        )
        for role, path in ((ScanRole.T1_PRE, pre), (ScanRole.T1_POST, post))
    )
    imported = service.import_confirmed_scans(assignments, actor="Reviewer")
    subject_id = imported.subjects[0].id
    service.validate_subject_inputs(subject_id, actor="Reviewer")
    service.register_t1_brain_mask_release(release_root, actor="Reviewer")
    completed = service.run_t1_brain_mask_generation(
        actor="Reviewer",
        subject_ids=(subject_id,),
        device_name="cpu",
    )
    artifact_id = completed.t1_brain_masks_for_subject(subject_id)[0].id
    reference = next(
        record.output_path
        for record in completed.inputs_for_subject(subject_id)
        if record.role is ScanRole.T1_PRE
    )
    assert reference is not None
    return service, subject_id, artifact_id, reference


def _fake_registration_runner(seen: dict[str, object]):
    def run(request) -> T1RegistrationOutput:
        seen["registration_request"] = request
        request.registered_post_path.parent.mkdir(parents=True, exist_ok=True)
        reference = nib.load(request.pre_t1_path)
        registered = np.asanyarray(reference.dataobj, dtype=np.float32) + 2.0
        nib.save(
            nib.Nifti1Image(registered, reference.affine, reference.header),
            request.registered_post_path,
        )
        request.transform_path.write_text("fake rigid transform\n")
        request.qc_preview_path.write_bytes(b"registration-qc")
        return T1RegistrationOutput(
            case_id=request.case_id,
            registered_post_path=request.registered_post_path,
            registered_post_sha256=sha256_file(request.registered_post_path),
            transform_path=request.transform_path,
            transform_sha256=sha256_file(request.transform_path),
            qc_preview_path=request.qc_preview_path,
            qc_preview_sha256=sha256_file(request.qc_preview_path),
            before_xcorr=0.5,
            after_xcorr=0.8,
            registration_metric=-0.7,
            optimizer_stop="test complete",
            method_version=request.config.method_spec()["method_version"],
            method_spec_sha256=request.config.method_spec_sha256,
            metadata={"human_review_required": True},
        )

    return run


def _fake_enhancement_runner(seen: dict[str, object]):
    def run(request) -> T1EnhancementOutput:
        seen["enhancement_request"] = request
        request.output_directory.mkdir(parents=True, exist_ok=True)
        reference = nib.load(request.pre_t1_path)
        percent_path = (
            request.output_directory / f"{request.case_id}_percent_enhancement.nii.gz"
        )
        nib.save(
            nib.Nifti1Image(
                np.full(reference.shape, 12.5, dtype=np.float32),
                reference.affine,
                reference.header,
            ),
            percent_path,
        )
        summary_path = request.output_directory / f"{request.case_id}_summary.csv"
        summary_path.write_text(
            "region,metric,median\nbrain_mask,percent_enhancement,12.5\n"
        )
        qc_path = request.output_directory / f"{request.case_id}_enhancement_qc.png"
        qc_path.write_bytes(b"enhancement-qc")
        metadata_path = request.output_directory / f"{request.case_id}_metadata.json"
        metadata = {
            "registration_recomputed": False,
            "scientific_status": "PROVISIONAL",
        }
        metadata_path.write_text(json.dumps(metadata))
        return T1EnhancementOutput(
            case_id=request.case_id,
            percent_enhancement_map=percent_path,
            percent_enhancement_sha256=sha256_file(percent_path),
            summary_csv=summary_path,
            summary_sha256=sha256_file(summary_path),
            qc_preview_path=qc_path,
            qc_preview_sha256=sha256_file(qc_path),
            metadata_path=metadata_path,
            metadata_sha256=sha256_file(metadata_path),
            method_version=request.config.method_spec()["method_version"],
            method_spec_sha256=request.config.method_spec_sha256,
            metrics=(
                {
                    "region": "brain_mask",
                    "metric": "percent_enhancement",
                    "median": "12.5",
                },
            ),
            metadata=metadata,
        )

    return run


def test_reviewed_registration_and_provisional_enhancement_reopen_exact_dependencies(
    tmp_path: Path,
) -> None:
    seen: dict[str, object] = {}
    service, subject_id, mask_id, _reference = _build_service_with_t1_draft(
        tmp_path,
        registration_runner=_fake_registration_runner(seen),
        enhancement_runner=_fake_enhancement_runner(seen),
    )
    service.approve_t1_brain_mask(subject_id, mask_id, reviewer="Reviewer A")
    service.register_t1_registration_method(actor="Reviewer A")

    registered = service.run_t1_registration(
        actor="Reviewer A",
        subject_ids=(subject_id,),
    )
    registration = registered.t1_registrations_for_subject(subject_id)[0]
    assert registration.state is T1RegistrationState.REVIEW_REQUIRED
    assert registration.active
    assert registration.source_brain_mask_artifact_id == mask_id
    assert registration.registered_post_path.is_file()
    assert present_study(registered).subject(subject_id).registration.kind == "review"
    assert service.t1_enhancement_readiness((subject_id,)).eligible_count == 0
    service.register_t1_enhancement_method(actor="Reviewer A")
    with pytest.raises(StudyStateError, match="approved T1 registration"):
        service.run_t1_enhancement(actor="Reviewer A", subject_ids=(subject_id,))

    approved = service.approve_t1_registration(
        subject_id,
        registration.id,
        reviewer="Reviewer B",
    )
    approval = approved.t1_registration_approval_for_artifact(registration.id)
    assert approval is not None
    assert approval.reviewer == "Reviewer B"
    assert approved.t1_registrations_for_subject(subject_id)[0].state is (
        T1RegistrationState.APPROVED
    )
    quantified = service.run_t1_enhancement(
        actor="Reviewer A",
        subject_ids=(subject_id,),
    )

    result = quantified.t1_enhancement_results_for_subject(subject_id)[0]
    request = seen["enhancement_request"]
    assert request.registered_post_t1_path == registration.registered_post_path
    assert request.expected_registered_post_sha256 == registration.registered_post_sha256
    assert result.state is T1EnhancementResultState.PROVISIONAL
    assert result.source_registration_artifact_id == registration.id
    assert result.source_brain_mask_artifact_id == mask_id
    assert result.metadata["registration_recomputed"] is False
    presented = present_study(quantified)
    assert presented.subject(subject_id).registration.kind == "approved"
    assert presented.subject(subject_id).t1_result.label == "Provisional enhancement"
    assert presented.results[0].t1_value == "Median 12.500% · provisional"
    assert presented.results[0].t1_state.kind == "review"

    root = quantified.root_path
    service.close_study()
    reopened = service.open_study(root)
    reopened_registration = reopened.t1_registrations_for_subject(subject_id)[0]
    reopened_result = reopened.t1_enhancement_results_for_subject(subject_id)[0]
    assert reopened_registration.state is T1RegistrationState.APPROVED
    assert reopened_registration.registered_post_sha256 == (
        registration.registered_post_sha256
    )
    assert reopened_result.state is T1EnhancementResultState.PROVISIONAL
    assert reopened_result.source_registration_artifact_id == registration.id


def test_replacing_post_t1_invalidates_registration_and_enhancement(
    tmp_path: Path,
) -> None:
    seen: dict[str, object] = {}
    service, subject_id, mask_id, reference = _build_service_with_t1_draft(
        tmp_path,
        registration_runner=_fake_registration_runner(seen),
        enhancement_runner=_fake_enhancement_runner(seen),
    )
    service.approve_t1_brain_mask(subject_id, mask_id, reviewer="Reviewer A")
    service.register_t1_registration_method(actor="Reviewer A")
    registered = service.run_t1_registration(
        actor="Reviewer A",
        subject_ids=(subject_id,),
    )
    registration_id = registered.t1_registrations_for_subject(subject_id)[0].id
    service.approve_t1_registration(subject_id, registration_id, reviewer="Reviewer A")
    service.register_t1_enhancement_method(actor="Reviewer A")
    quantified = service.run_t1_enhancement(
        actor="Reviewer A",
        subject_ids=(subject_id,),
    )
    result_id = quantified.t1_enhancement_results_for_subject(subject_id)[0].id

    replacement = tmp_path / "raw" / "Mouse-01_post_t1_replacement.nii.gz"
    pre_image = nib.load(reference)
    nib.save(
        nib.Nifti1Image(
            np.asanyarray(pre_image.dataobj, dtype=np.float32) + 20,
            pre_image.affine,
            pre_image.header,
        ),
        replacement,
    )
    changed = service.import_confirmed_scans(
        (
            ScanImportAssignment(
                proposal_id="replacement-post",
                subject_code="Mouse-01",
                role=ScanRole.T1_POST,
                source_path=replacement,
                source_format=SourceFormat.NIFTI,
                session_id="replacement",
                scan_id=None,
                protocol="T1w",
                method="NIfTI",
                acquisition_orientation="from affine",
                confidence=ImportConfidence.HIGH,
                orientation_policy=OrientationPolicy.NATIVE,
            ),
        ),
        actor="Reviewer A",
    )

    registration = next(
        item
        for item in changed.t1_registrations_for_subject(subject_id)
        if item.id == registration_id
    )
    result = next(
        item
        for item in changed.t1_enhancement_results_for_subject(subject_id)
        if item.id == result_id
    )
    assert registration.state is T1RegistrationState.OUTDATED
    assert registration.active is False
    assert result.state is T1EnhancementResultState.OUTDATED
    assert result.active is False
    assert result.outdated_reason == "The active post-Gd T1 input changed."


def test_t1_draft_approval_and_reopen_preserve_exact_artifact(tmp_path: Path) -> None:
    service, subject_id, artifact_id, _reference = _build_service_with_t1_draft(
        tmp_path
    )
    generated = service.current_study
    assert generated is not None
    artifact = generated.t1_brain_masks_for_subject(subject_id)[0]
    assert artifact.state is ArtifactState.DRAFT_REVIEW_REQUIRED
    assert artifact.active
    assert generated.t1_brain_mask_jobs[0].state is ProcessingJobState.SUCCEEDED
    assert generated.active_t1_brain_mask_release is not None
    presented = present_study(generated)
    assert len(presented.reviews) == 1
    assert presented.reviews[0].workflow_key == "t1_brain_mask"
    assert presented.reviews[0].category == "T1 brain masks"
    assert presented.subject(subject_id).brain_mask.kind == "review"

    approved = service.approve_t1_brain_mask(
        subject_id,
        artifact_id,
        reviewer="Reviewer A",
    )

    current = approved.t1_brain_masks_for_subject(subject_id)[0]
    review = approved.t1_brain_mask_approval_for_artifact(artifact_id)
    assert current.state is ArtifactState.APPROVED
    assert review is not None
    assert review.reviewer == "Reviewer A"
    assert review.study_blinding_state == "BLINDED"
    assert present_study(approved).reviews == ()
    assert present_study(approved).subject(subject_id).brain_mask.kind == "approved"
    with pytest.raises(StudyStateError, match="awaiting review"):
        service.approve_t1_brain_mask(
            subject_id,
            artifact_id,
            reviewer="Reviewer B",
        )

    service.close_study()
    reopened = service.open_study(approved.root_path)
    assert reopened.t1_brain_masks_for_subject(subject_id)[0].state is ArtifactState.APPROVED
    assert (
        reopened.t1_brain_mask_approval_for_artifact(artifact_id).reviewer
        == "Reviewer A"
    )


def test_t1_manual_edit_creates_new_version_and_requires_approval(
    tmp_path: Path,
) -> None:
    service, subject_id, artifact_id, reference_path = _build_service_with_t1_draft(
        tmp_path
    )
    original = service.current_study.t1_brain_masks_for_subject(subject_id)[0]
    session = service.start_t1_brain_mask_manual_edit(
        subject_id,
        artifact_id,
        actor="Reviewer A",
    )
    assert session.editable_mask_path != original.mask_path
    reference = nib.load(reference_path)
    corrected = np.zeros(reference.shape, dtype=np.uint8)
    corrected[1:3, 1:4, 1:3] = 1
    nib.save(nib.Nifti1Image(corrected, reference.affine), session.editable_mask_path)

    changed = service.finish_t1_brain_mask_manual_edit(session, actor="Reviewer A")

    current = next(
        item for item in changed.t1_brain_masks_for_subject(subject_id) if item.active
    )
    previous = next(
        item
        for item in changed.t1_brain_masks_for_subject(subject_id)
        if item.id == artifact_id
    )
    assert current.origin == "CORRECTED"
    assert current.version == 2
    assert current.state is ArtifactState.CORRECTED_REVIEW_REQUIRED
    assert previous.state is ArtifactState.OUTDATED
    assert previous.superseded_by == current.id
    assert changed.t1_brain_mask_approval_for_artifact(current.id) is None

    approved = service.approve_t1_brain_mask(
        subject_id,
        current.id,
        reviewer="Reviewer A",
    )
    assert next(
        item for item in approved.t1_brain_masks_for_subject(subject_id) if item.active
    ).state is ArtifactState.APPROVED


def test_empty_or_changed_t1_mask_cannot_be_approved(tmp_path: Path) -> None:
    service, subject_id, artifact_id, reference_path = _build_service_with_t1_draft(
        tmp_path
    )
    session = service.start_t1_brain_mask_manual_edit(
        subject_id,
        artifact_id,
        actor="Reviewer A",
    )
    reference = nib.load(reference_path)
    nib.save(
        nib.Nifti1Image(np.zeros(reference.shape, dtype=np.uint8), reference.affine),
        session.editable_mask_path,
    )
    with pytest.raises(StudyStateError, match="empty"):
        service.finish_t1_brain_mask_manual_edit(session, actor="Reviewer A")

    artifact = service.current_study.t1_brain_masks_for_subject(subject_id)[0]
    image = nib.load(artifact.mask_path)
    changed = np.asanyarray(image.dataobj).copy()
    changed[0, 0, 0] = 1
    nib.save(nib.Nifti1Image(changed, image.affine), artifact.mask_path)
    with pytest.raises(StudyStateError, match="changed after it was registered"):
        service.approve_t1_brain_mask(
            subject_id,
            artifact_id,
            reviewer="Reviewer A",
        )
    assert service.current_study.t1_brain_mask_approvals == ()


def test_replacing_pre_t1_marks_the_approved_brain_mask_outdated(
    tmp_path: Path,
) -> None:
    service, subject_id, artifact_id, reference_path = _build_service_with_t1_draft(
        tmp_path
    )
    service.approve_t1_brain_mask(subject_id, artifact_id, reviewer="Reviewer A")
    replacement = tmp_path / "raw" / "Mouse-01_pre_t1_replacement.nii.gz"
    reference = nib.load(reference_path)
    nib.save(
        nib.Nifti1Image(
            np.asanyarray(reference.dataobj, dtype=np.float32) + 1,
            reference.affine,
        ),
        replacement,
    )
    changed = service.import_confirmed_scans(
        (
            ScanImportAssignment(
                proposal_id="proposal-replacement-pre",
                subject_code="Mouse-01",
                role=ScanRole.T1_PRE,
                source_path=replacement,
                source_format=SourceFormat.NIFTI,
                session_id="replacement",
                scan_id=None,
                protocol="T1w",
                method="NIfTI",
                acquisition_orientation="from affine",
                confidence=ImportConfidence.HIGH,
                orientation_policy=OrientationPolicy.NATIVE,
            ),
        ),
        actor="Reviewer A",
    )

    artifact = next(
        item
        for item in changed.t1_brain_masks_for_subject(subject_id)
        if item.id == artifact_id
    )
    assert artifact.state is ArtifactState.OUTDATED
    assert artifact.active is False
    assert changed.t1_brain_mask_approval_for_artifact(artifact_id) is not None
