"""Focused tests for the frozen RatLesNetV2 release and application handoff."""

from __future__ import annotations

import json
from pathlib import Path

import nibabel as nib
import numpy as np
import pytest

from lys_bbb.t2_inference import (
    T2InferenceCaseOutput,
    T2InferenceOutput,
    _prediction_to_native_shape,
    prepare_t2_inference_scan,
)
from lys_bbb.t2_model_release import (
    FrozenT2ModelRelease,
    sha256_file,
    validate_frozen_t2_model_release,
)
from lys_bbb_app.domain.scan_import import (
    ImportConfidence,
    OrientationPolicy,
    ScanImportAssignment,
    ScanRole,
    SourceFormat,
)
from lys_bbb_app.domain.errors import StudyStateError
from lys_bbb_app.application.study_presenter import present_study
from lys_bbb_app.domain.study import CreateStudyRequest
from lys_bbb_app.domain.t2_lesion import ArtifactState, ProcessingJobState
from lys_bbb_app.services.study_service import StudyService


def _write_scan(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = np.arange(6 * 7 * 8, dtype=np.float32).reshape(6, 7, 8)
    nib.save(nib.Nifti1Image(data, np.diag([0.07, 0.07, 0.5, 1.0])), path)


def _write_release(root: Path) -> Path:
    models = root / "models"
    runtime = root / "RatLesNetv2" / "lib"
    models.mkdir(parents=True)
    runtime.mkdir(parents=True)
    (root / "RatLesNetv2" / "LICENSE").write_text("MIT")
    (root / "RatLesNetv2" / "UPSTREAM_GIT_COMMIT.txt").write_text("upstream-123\n")
    (runtime / "RatLesNetv2.py").write_text("# runtime")
    (runtime / "RatLesNetv2Blocks.py").write_text("# blocks")
    model_records = []
    frozen_models = []
    for fold in range(5):
        model = models / f"fold_{fold}.model"
        model.write_bytes(f"model-{fold}".encode())
        digest = sha256_file(model)
        model_records.append(
            {"file": f"models/fold_{fold}.model", "fold": fold, "sha256": digest}
        )
        frozen_models.append({"fold": fold, "path": f"fold-{fold}", "sha256": digest})
    (root / "bundle_manifest.json").write_text(
        json.dumps(
            {
                "ensemble": "unweighted mean lesion probability",
                "models": model_records,
                "postprocessing": "none",
                "ratlesnetv2_git_commit": "upstream-123",
                "threshold": 0.4,
            }
        )
    )
    (root / "frozen_spec.json").write_text(
        json.dumps(
            {
                "architecture": "RatLesNetV2",
                "dataset": "LYS_v1",
                "ensemble": "unweighted mean lesion probability",
                "fold_models": frozen_models,
                "postprocessing": "none",
                "project_git_commit": "project-456",
                "ratlesnetv2_git_commit": "upstream-123",
                "threshold": 0.4,
            }
        )
    )
    (root / "selected_threshold.json").write_text(
        json.dumps(
            {
                "selected_threshold": 0.4,
                "selection_data": "out_of_fold_validation_only",
                "locked_test_used": False,
            }
        )
    )
    return root


def test_release_validation_checks_all_five_model_hashes(tmp_path: Path) -> None:
    root = _write_release(tmp_path / "release")

    release = validate_frozen_t2_model_release(root)

    assert release.id == "ratlesnetv2-lys_v1-project-"
    assert release.threshold == 0.4
    assert len(release.model_paths) == 5
    assert release.metadata["human_review_required"] is True

    release.model_paths[2].write_bytes(b"changed")
    with pytest.raises(ValueError, match="checksum mismatch"):
        validate_frozen_t2_model_release(root)


def test_registered_release_detects_runtime_changes(tmp_path: Path) -> None:
    root = _write_release(tmp_path / "release")
    service = StudyService()
    service.create_study(
        CreateStudyRequest(tmp_path / "study", "Study", "study", actor="Reviewer")
    )
    service.register_t2_model_release(root, actor="Reviewer")
    (root / "RatLesNetv2" / "lib" / "RatLesNetv2.py").write_text("# changed runtime")

    with pytest.raises(StudyStateError, match="changed after validation"):
        service.run_t2_lesion_inference(actor="Reviewer")


def test_preparation_adds_only_singleton_channel_and_preserves_geometry(
    tmp_path: Path,
) -> None:
    source = tmp_path / "scan.nii.gz"
    target = tmp_path / "prepared" / "case-1" / "scan.nii.gz"
    _write_scan(source)

    prepare_t2_inference_scan(
        source,
        target,
        expected_spacing=(0.07, 0.07, 0.5),
    )

    original = nib.load(source)
    prepared = nib.load(target)
    assert prepared.shape == (*original.shape, 1)
    np.testing.assert_allclose(prepared.affine, original.affine)
    np.testing.assert_array_equal(
        np.asanyarray(prepared.dataobj)[..., 0],
        np.asanyarray(original.dataobj),
    )


def test_prediction_uses_the_frozen_depth_height_width_mapping() -> None:
    model_order = np.arange(8 * 6 * 7).reshape(8, 6, 7)

    native_order = _prediction_to_native_shape(model_order, (6, 7, 8))

    assert native_order.shape == (6, 7, 8)
    assert native_order[4, 5, 3] == model_order[3, 4, 5]
    with pytest.raises(ValueError, match="Unexpected RatLesNetV2 lesion-map shape"):
        _prediction_to_native_shape(model_order, (8, 6, 7))


def test_service_runs_all_eligible_t2_subjects_and_persists_drafts(
    tmp_path: Path,
) -> None:
    release_root = tmp_path / "release"
    release_root.mkdir()
    release = FrozenT2ModelRelease(
        id="ratlesnetv2-test",
        name="RatLesNetV2 test",
        version="test-v1",
        root_path=release_root,
        architecture_path=release_root / "RatLesNetv2",
        model_paths=tuple(release_root / f"model-{index}" for index in range(5)),
        model_sha256=tuple(f"hash-{index}" for index in range(5)),
        threshold=0.4,
        expected_spacing_mm=(0.07, 0.07, 0.5),
        project_git_commit="project",
        ratlesnetv2_git_commit="upstream",
        manifest_sha256="manifest",
        frozen_spec_sha256="frozen",
        threshold_sha256="threshold",
        metadata={"predictions_are_drafts": True},
    )

    def validate_release(_path: Path | str) -> FrozenT2ModelRelease:
        return release

    def run_inference(
        active_release: FrozenT2ModelRelease,
        case_scans: dict[str, Path],
        *,
        work_root: Path,
        output_root: Path,
        device_name: str,
        progress,
    ) -> T2InferenceOutput:
        assert active_release.id == release.id
        work_root.mkdir(parents=True)
        outputs = []
        output_root.mkdir(parents=True)
        for index, (case_id, scan_path) in enumerate(case_scans.items(), start=1):
            reference = nib.load(scan_path)
            probability = np.full(reference.shape, 0.6, dtype=np.float32)
            mask = np.ones(reference.shape, dtype=np.uint8)
            case_root = output_root / "cases" / case_id
            case_root.mkdir(parents=True)
            probability_path = case_root / "ensemble_probability.nii.gz"
            mask_path = case_root / "ensemble_mask.nii.gz"
            nib.save(nib.Nifti1Image(probability, reference.affine), probability_path)
            nib.save(nib.Nifti1Image(mask, reference.affine), mask_path)
            outputs.append(
                T2InferenceCaseOutput(
                    case_id=case_id,
                    source_scan=scan_path,
                    prepared_scan=work_root / case_id / "scan.nii.gz",
                    probability_path=probability_path,
                    mask_path=mask_path,
                    probability_sha256=sha256_file(probability_path),
                    mask_sha256=sha256_file(mask_path),
                    lesion_voxel_count=int(mask.size),
                    lesion_volume_mm3=float(mask.size * 0.07 * 0.07 * 0.5),
                    shape=tuple(int(value) for value in reference.shape),
                    spacing_mm=(0.07, 0.07, 0.5),
                    axis_codes=tuple(nib.aff2axcodes(reference.affine)),
                )
            )
            progress(index, len(case_scans), "segmenting")
        manifest = output_root / "inference_manifest.csv"
        manifest.write_text("case_id\n")
        summary = output_root / "inference_summary.json"
        summary.write_text("{}")
        return T2InferenceOutput(
            release.id,
            device_name,
            release.threshold,
            tuple(outputs),
            manifest,
            summary,
        )

    def build_qc(_scan: Path, _mask: Path, output: Path) -> Path:
        output.write_bytes(b"png")
        return output

    service = StudyService(
        t2_release_validator=validate_release,
        t2_inference_runner=run_inference,
        t2_qc_builder=build_qc,
    )
    service.create_study(
        CreateStudyRequest(tmp_path / "study", "Study", "study", actor="Reviewer")
    )
    assignments = []
    for index in range(2):
        source = tmp_path / "raw" / f"Mouse-{index + 1:02d}_t2w.nii.gz"
        _write_scan(source)
        assignments.append(
            ScanImportAssignment(
                proposal_id=f"proposal-{index}",
                subject_code=f"Mouse-{index + 1:02d}",
                role=ScanRole.T2,
                source_path=source,
                source_format=SourceFormat.NIFTI,
                session_id="nifti",
                scan_id=None,
                protocol="T2w",
                method="NIfTI",
                acquisition_orientation="from affine",
                confidence=ImportConfidence.HIGH,
                orientation_policy=OrientationPolicy.NATIVE,
            )
        )
    imported = service.import_confirmed_scans(tuple(assignments), actor="Reviewer")
    for subject in imported.subjects:
        service.validate_subject_inputs(subject.id, actor="Reviewer")
    validated = service.current_study
    assert validated is not None
    before_release = present_study(validated)
    assert before_release.t2_eligible_subject_count == 2
    assert all(subject.can_run_t2_inference for subject in before_release.subjects)
    service.register_t2_model_release(release_root, actor="Reviewer")

    completed = service.run_t2_lesion_inference(actor="Reviewer")

    assert len(completed.artifacts) == 2
    assert all(
        artifact.state is ArtifactState.DRAFT_REVIEW_REQUIRED
        for artifact in completed.artifacts
    )
    assert all(artifact.mask_path.is_file() for artifact in completed.artifacts)
    assert all(artifact.probability_path.is_file() for artifact in completed.artifacts)
    assert all(artifact.qc_preview_path.is_file() for artifact in completed.artifacts)
    assert completed.processing_jobs[0].state is ProcessingJobState.SUCCEEDED
    assert completed.processing_jobs[0].subject_ids == tuple(
        subject.id for subject in imported.subjects
    )

    first_subject_id, second_subject_id = (subject.id for subject in imported.subjects)
    renamed = service.rename_subject(
        first_subject_id,
        "Renamed-Mouse",
        actor="Reviewer",
    )
    assert any(
        artifact.active
        for artifact in renamed.t2_artifacts_for_subject(first_subject_id)
    )

    archived = service.remove_subject(second_subject_id, actor="Reviewer")
    assert archived.subject(second_subject_id) is None
    assert service.t2_inference_readiness().eligible_subject_ids == ()
    assert service.t2_inference_readiness((first_subject_id,)).eligible_subject_ids == (
        first_subject_id,
    )
    service.restore_subject(second_subject_id, actor="Reviewer")
    assert set(
        service.t2_inference_readiness(
            (first_subject_id, second_subject_id)
        ).eligible_subject_ids
    ) == {
        first_subject_id,
        second_subject_id,
    }

    flip_plan = service.plan_bulk_flip(
        (first_subject_id,),
        (0,),
        (ScanRole.T2,),
    )
    replaced = service.import_confirmed_scans(flip_plan, actor="Reviewer")
    previous = next(
        artifact
        for artifact in replaced.artifacts
        if artifact.subject_id == first_subject_id
    )
    assert previous.state is ArtifactState.OUTDATED
    assert previous.active is False
    assert first_subject_id not in service.t2_inference_readiness().eligible_subject_ids

    service.validate_subject_inputs(first_subject_id, actor="Reviewer")
    rerun = service.run_t2_lesion_inference(
        actor="Reviewer",
        subject_ids=(first_subject_id,),
    )
    versions = tuple(
        artifact
        for artifact in rerun.artifacts
        if artifact.subject_id == first_subject_id
    )
    assert {artifact.version for artifact in versions} == {1, 2}
    assert sum(artifact.active for artifact in versions) == 1

    service.close_study()
    reopened = service.open_study(rerun.root_path)
    assert len(reopened.artifacts) == 3
    assert reopened.active_t2_model_release.id == release.id
