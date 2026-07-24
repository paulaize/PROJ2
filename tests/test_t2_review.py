"""End-to-end tests for reviewed T2 artifacts and approved-only export."""

from __future__ import annotations

import csv
import json
from pathlib import Path
import sqlite3

import nibabel as nib
import numpy as np
import pytest

from lys_bbb.t2_inference import T2InferenceCaseOutput, T2InferenceOutput
from lys_bbb.t2_model_release import FrozenT2ModelRelease, sha256_file
from lys_bbb_app.domain.errors import StudyStateError
from lys_bbb_app.domain.scan_import import (
    ImportConfidence,
    OrientationPolicy,
    ScanImportAssignment,
    ScanRole,
    SourceFormat,
)
from lys_bbb_app.domain.study import CreateStudyRequest
from lys_bbb_app.domain.t2_lesion import ArtifactState, ResultState
from lys_bbb_app.application.study_presenter import present_study
from lys_bbb_app.infrastructure.external_viewer import ViewerLaunch
from lys_bbb_app.infrastructure.study_database import STUDY_SCHEMA_VERSION, StudyRepository
from lys_bbb_app.services.study_service import StudyService


def _build_service_with_draft(tmp_path: Path) -> tuple[StudyService, str, str, Path]:
    release_root = tmp_path / "release"
    release_root.mkdir()
    release = FrozenT2ModelRelease(
        id="ratlesnetv2-review-test",
        name="RatLesNetV2 review test",
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
        _release: FrozenT2ModelRelease,
        case_scans: dict[str, Path],
        *,
        work_root: Path,
        output_root: Path,
        device_name: str,
        progress,
    ) -> T2InferenceOutput:
        work_root.mkdir(parents=True)
        output_root.mkdir(parents=True)
        cases = []
        for case_id, scan_path in case_scans.items():
            reference = nib.load(scan_path)
            mask = np.zeros(reference.shape, dtype=np.uint8)
            mask[1:3, 1:3, 1] = 1
            probability = mask.astype(np.float32) * 0.8
            case_root = output_root / "cases" / case_id
            case_root.mkdir(parents=True)
            mask_path = case_root / "ensemble_mask.nii.gz"
            probability_path = case_root / "ensemble_probability.nii.gz"
            nib.save(nib.Nifti1Image(mask, reference.affine), mask_path)
            nib.save(nib.Nifti1Image(probability, reference.affine), probability_path)
            cases.append(
                T2InferenceCaseOutput(
                    case_id=case_id,
                    source_scan=scan_path,
                    prepared_scan=work_root / case_id / "scan.nii.gz",
                    probability_path=probability_path,
                    mask_path=mask_path,
                    probability_sha256=sha256_file(probability_path),
                    mask_sha256=sha256_file(mask_path),
                    lesion_voxel_count=4,
                    lesion_volume_mm3=4 * 0.07 * 0.07 * 0.5,
                    shape=tuple(int(value) for value in reference.shape),
                    spacing_mm=(0.07, 0.07, 0.5),
                    axis_codes=tuple(nib.aff2axcodes(reference.affine)),
                )
            )
        manifest = output_root / "inference_manifest.csv"
        manifest.write_text("case_id\n")
        summary = output_root / "inference_summary.json"
        summary.write_text("{}")
        progress(len(cases), len(cases), "segmenting")
        return T2InferenceOutput(
            release.id,
            device_name,
            release.threshold,
            tuple(cases),
            manifest,
            summary,
        )

    def build_qc(_scan: Path, _mask: Path, output: Path) -> Path:
        output.write_bytes(b"png")
        return output

    def launch_viewer(
        image_path: Path,
        _viewer_path: Path | str | None = None,
        segmentation_path: Path | None = None,
    ) -> ViewerLaunch:
        return ViewerLaunch(
            Path("/test/itksnap"),
            image_path,
            123,
            segmentation_path,
        )

    service = StudyService(
        t2_release_validator=validate_release,
        t2_inference_runner=run_inference,
        t2_qc_builder=build_qc,
        viewer_launcher=launch_viewer,
    )
    service.create_study(
        CreateStudyRequest(tmp_path / "study", "Study", "study", actor="Reviewer")
    )
    source = tmp_path / "raw" / "Mouse-01_t2w.nii.gz"
    source.parent.mkdir()
    affine = np.diag([0.07, 0.07, 0.5, 1.0])
    nib.save(nib.Nifti1Image(np.ones((5, 6, 4), dtype=np.float32), affine), source)
    imported = service.import_confirmed_scans(
        (
            ScanImportAssignment(
                proposal_id="proposal-1",
                subject_code="Mouse-01",
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
            ),
        ),
        actor="Reviewer",
    )
    subject_id = imported.subjects[0].id
    service.validate_subject_inputs(subject_id, actor="Reviewer")
    service.register_t2_model_release(release_root, actor="Reviewer")
    completed = service.run_t2_lesion_inference(actor="Reviewer")
    artifact_id = completed.artifacts[0].id
    reference_path = completed.inputs_for_subject(subject_id)[0].output_path
    assert reference_path is not None
    return service, subject_id, artifact_id, reference_path


def test_approval_creates_immutable_review_official_result_and_blinded_csv(
    tmp_path: Path,
) -> None:
    service, subject_id, artifact_id, _reference = _build_service_with_draft(tmp_path)

    approved = service.approve_t2_mask(
        subject_id,
        artifact_id,
        reviewer="Reviewer A",
    )

    artifact = approved.t2_artifacts_for_subject(subject_id)[0]
    result = approved.active_t2_result_for_subject(subject_id)
    assert artifact.state is ArtifactState.APPROVED
    assert result is not None
    assert result.state is ResultState.APPROVED
    assert result.lesion_voxel_count == 4
    assert result.lesion_volume_mm3 == pytest.approx(4 * 0.07 * 0.07 * 0.5)
    assert result.source_artifact_id == artifact_id
    review = approved.review_for_artifact(artifact_id)
    assert review is not None
    assert review.reviewer == "Reviewer A"
    assert review.study_blinding_state == "BLINDED"

    with pytest.raises(StudyStateError, match="awaiting review"):
        service.approve_t2_mask(subject_id, artifact_id, reviewer="Reviewer B")

    destination = approved.root_path / "exports" / "approved-t2.csv"
    exported = service.export_approved_t2_results_csv(
        destination,
        actor="Reviewer A",
    )
    assert exported.row_count == 1
    with destination.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert "group" not in rows[0]
    assert rows[0]["subject_id"] == "Mouse-01"
    assert rows[0]["result_state"] == "APPROVED"
    assert rows[0]["approved_mask_sha256"] == artifact.mask_sha256
    with pytest.raises(StudyStateError, match="will not be overwritten"):
        service.export_approved_t2_results_csv(destination, actor="Reviewer A")

    service.unblind(reviewer="Reviewer A")
    service.assign_groups({subject_id: "Treatment A"}, reviewer="Reviewer A")
    grouped_destination = approved.root_path / "exports" / "approved-t2-grouped.csv"
    service.export_approved_t2_results_csv(
        grouped_destination,
        actor="Reviewer A",
    )
    with grouped_destination.open(newline="", encoding="utf-8") as handle:
        grouped_rows = list(csv.DictReader(handle))
    assert grouped_rows[0]["group"] == "Treatment A"

    service.close_study()
    reopened = service.open_study(approved.root_path)
    assert reopened.review_for_artifact(artifact_id).reviewer == "Reviewer A"
    assert reopened.active_t2_result_for_subject(subject_id).source_artifact_id == artifact_id


def test_persistent_t2_draft_is_presented_in_general_review_queue(
    tmp_path: Path,
) -> None:
    service, subject_id, artifact_id, _reference = _build_service_with_draft(tmp_path)

    presented = present_study(service.current_study)

    assert len(presented.reviews) == 1
    review = presented.reviews[0]
    assert review.subject_id == subject_id
    assert review.subject_label == "Mouse-01"
    assert review.artifact_id == artifact_id
    assert review.category == "T2 lesion masks"
    assert review.status.kind == "review"
    assert "Provisional volume" in review.automatic_qc
    assert next(
        workflow for workflow in presented.workflows if workflow.key == "t2"
    ).target_page == "reviews"
    assert any(
        action.target_page == "reviews"
        for action in presented.priority_actions
        if "require human review" in action.label
    )

    service.approve_t2_mask(subject_id, artifact_id, reviewer="Reviewer A")

    assert present_study(service.current_study).reviews == ()


def test_correction_is_new_artifact_and_approval_uses_corrected_mask(
    tmp_path: Path,
) -> None:
    service, subject_id, artifact_id, reference_path = _build_service_with_draft(tmp_path)
    registered_mask = service.current_study.t2_artifacts_for_subject(subject_id)[0].mask_path
    session = service.start_t2_manual_edit(
        subject_id,
        artifact_id,
        actor="Reviewer A",
    )
    assert session.launch.segmentation_path == session.editable_mask_path
    assert session.editable_mask_path != registered_mask
    assert sha256_file(session.editable_mask_path) == sha256_file(registered_mask)
    reference = nib.load(reference_path)
    corrected = np.zeros(reference.shape, dtype=np.uint8)
    corrected[0, 0, :2] = 1
    nib.save(
        nib.Nifti1Image(corrected, reference.affine),
        session.editable_mask_path,
    )

    imported = service.finish_t2_manual_edit(
        session,
        actor="Reviewer A",
    )

    current = next(
        artifact
        for artifact in imported.t2_artifacts_for_subject(subject_id)
        if artifact.active
    )
    original = next(
        artifact
        for artifact in imported.t2_artifacts_for_subject(subject_id)
        if artifact.id == artifact_id
    )
    assert current.id != artifact_id
    assert current.origin == "CORRECTED"
    assert current.version == 2
    assert current.state is ArtifactState.CORRECTED_REVIEW_REQUIRED
    assert current.mask_path != session.editable_mask_path
    assert current.mask_path.is_file()
    assert original.state is ArtifactState.OUTDATED
    assert original.superseded_by == current.id

    approved = service.approve_t2_mask(
        subject_id,
        current.id,
        reviewer="Reviewer A",
    )
    result = approved.active_t2_result_for_subject(subject_id)
    assert result is not None
    assert result.source_artifact_id == current.id
    assert result.lesion_voxel_count == 2

    revised_session = service.start_t2_manual_edit(
        subject_id,
        current.id,
        actor="Reviewer A",
    )
    revised = np.zeros(reference.shape, dtype=np.uint8)
    revised[0, 0, 0] = 1
    nib.save(
        nib.Nifti1Image(revised, reference.affine),
        revised_session.editable_mask_path,
    )
    revised_study = service.finish_t2_manual_edit(
        revised_session,
        actor="Reviewer A",
    )
    assert revised_study.active_t2_result_for_subject(subject_id) is None
    assert revised_study.t2_results_for_subject(subject_id)[0].state is ResultState.OUTDATED
    revised_artifact = next(
        artifact
        for artifact in revised_study.t2_artifacts_for_subject(subject_id)
        if artifact.active
    )
    assert revised_artifact.version == 3
    assert revised_artifact.state is ArtifactState.CORRECTED_REVIEW_REQUIRED


def test_invalid_managed_edit_does_not_change_state(
    tmp_path: Path,
) -> None:
    service, subject_id, artifact_id, reference_path = _build_service_with_draft(tmp_path)
    reference = nib.load(reference_path)
    session = service.start_t2_manual_edit(
        subject_id,
        artifact_id,
        actor="Reviewer A",
    )
    invalid = np.zeros(reference.shape, dtype=np.uint8)
    invalid[0, 0, 0] = 2
    nib.save(nib.Nifti1Image(invalid, reference.affine), session.editable_mask_path)

    with pytest.raises(StudyStateError, match="must be binary"):
        service.finish_t2_manual_edit(
            session,
            actor="Reviewer A",
        )
    unchanged = service.current_study
    assert unchanged is not None
    assert unchanged.review_for_artifact(artifact_id) is None
    assert unchanged.active_t2_result_for_subject(subject_id) is None
    with pytest.raises(StudyStateError, match="no active approved"):
        service.export_approved_t2_results_csv(
            unchanged.root_path / "exports" / "must-not-exist.csv",
            actor="Reviewer A",
        )


def test_registered_mask_change_blocks_approval_without_creating_a_decision(
    tmp_path: Path,
) -> None:
    service, subject_id, artifact_id, _reference = _build_service_with_draft(tmp_path)
    study = service.current_study
    assert study is not None
    artifact = study.t2_artifacts_for_subject(subject_id)[0]
    image = nib.load(artifact.mask_path)
    changed = np.asanyarray(image.dataobj).copy()
    changed[0, 0, 0] = 1
    nib.save(nib.Nifti1Image(changed, image.affine), artifact.mask_path)

    with pytest.raises(StudyStateError, match="changed after it was registered"):
        service.approve_t2_mask(
            subject_id,
            artifact_id,
            reviewer="Reviewer A",
        )

    unchanged = service.current_study
    assert unchanged is not None
    assert unchanged.review_for_artifact(artifact_id) is None
    assert unchanged.active_t2_result_for_subject(subject_id) is None


def test_empty_native_grid_correction_is_a_valid_approved_zero_volume(
    tmp_path: Path,
) -> None:
    service, subject_id, artifact_id, reference_path = _build_service_with_draft(tmp_path)
    reference = nib.load(reference_path)
    session = service.start_t2_manual_edit(
        subject_id,
        artifact_id,
        actor="Reviewer A",
    )
    nib.save(
        nib.Nifti1Image(np.zeros(reference.shape, dtype=np.uint8), reference.affine),
        session.editable_mask_path,
    )
    corrected = service.finish_t2_manual_edit(
        session,
        actor="Reviewer A",
    )
    current = next(
        artifact
        for artifact in corrected.t2_artifacts_for_subject(subject_id)
        if artifact.active
    )

    approved = service.approve_t2_mask(
        subject_id,
        current.id,
        reviewer="Reviewer A",
    )

    result = approved.active_t2_result_for_subject(subject_id)
    assert result is not None
    assert result.lesion_voxel_count == 0
    assert result.lesion_volume_mm3 == 0


def test_corrected_mask_must_preserve_native_shape_and_affine(tmp_path: Path) -> None:
    service, subject_id, artifact_id, reference_path = _build_service_with_draft(tmp_path)
    reference = nib.load(reference_path)
    shape_session = service.start_t2_manual_edit(
        subject_id,
        artifact_id,
        actor="Reviewer A",
    )
    nib.save(
        nib.Nifti1Image(
            np.zeros((reference.shape[0] - 1, *reference.shape[1:]), dtype=np.uint8),
            reference.affine,
        ),
        shape_session.editable_mask_path,
    )
    with pytest.raises(StudyStateError, match="dimensions do not match"):
        service.finish_t2_manual_edit(shape_session, actor="Reviewer A")

    affine_session = service.start_t2_manual_edit(
        subject_id,
        artifact_id,
        actor="Reviewer A",
    )
    affine = reference.affine.copy()
    affine[0, 3] += 1
    nib.save(
        nib.Nifti1Image(np.zeros(reference.shape, dtype=np.uint8), affine),
        affine_session.editable_mask_path,
    )
    with pytest.raises(StudyStateError, match="affine does not match"):
        service.finish_t2_manual_edit(affine_session, actor="Reviewer A")


def test_new_inference_marks_an_approved_result_outdated(tmp_path: Path) -> None:
    service, subject_id, artifact_id, _reference = _build_service_with_draft(tmp_path)
    service.approve_t2_mask(subject_id, artifact_id, reviewer="Reviewer A")

    rerun = service.run_t2_lesion_inference(
        actor="Reviewer A",
        subject_ids=(subject_id,),
    )

    assert rerun.active_t2_result_for_subject(subject_id) is None
    old_result = rerun.t2_results_for_subject(subject_id)[0]
    assert old_result.state is ResultState.OUTDATED
    assert old_result.active is False
    assert "new automatic" in old_result.outdated_reason
    active_artifact = next(
        artifact
        for artifact in rerun.t2_artifacts_for_subject(subject_id)
        if artifact.active
    )
    assert active_artifact.state is ArtifactState.DRAFT_REVIEW_REQUIRED
    assert active_artifact.version == 2


def test_changing_the_active_model_release_marks_the_result_outdated(
    tmp_path: Path,
) -> None:
    service, subject_id, artifact_id, _reference = _build_service_with_draft(tmp_path)
    approved = service.approve_t2_mask(
        subject_id,
        artifact_id,
        reviewer="Reviewer A",
    )
    current = approved.active_t2_model_release
    assert current is not None
    replacement = FrozenT2ModelRelease(
        id="ratlesnetv2-replacement",
        name="Replacement release",
        version="test-v2",
        root_path=tmp_path / "replacement-release",
        architecture_path=tmp_path / "replacement-release" / "RatLesNetv2",
        model_paths=tuple(tmp_path / f"replacement-{index}" for index in range(5)),
        model_sha256=tuple(f"replacement-hash-{index}" for index in range(5)),
        threshold=0.4,
        expected_spacing_mm=(0.07, 0.07, 0.5),
        project_git_commit="replacement-project",
        ratlesnetv2_git_commit="replacement-upstream",
        manifest_sha256="replacement-manifest",
        frozen_spec_sha256="replacement-frozen",
        threshold_sha256="replacement-threshold",
        metadata={"predictions_are_drafts": True},
    )

    repository = StudyRepository.open(approved.root_path)
    repository.register_t2_model_release(replacement, actor="Reviewer A")
    changed = repository.snapshot()

    assert changed.active_t2_result_for_subject(subject_id) is None
    result = changed.t2_results_for_subject(subject_id)[0]
    assert result.state is ResultState.OUTDATED
    assert "model release changed" in result.outdated_reason


def test_replacing_the_native_t2_marks_mask_and_result_outdated(
    tmp_path: Path,
) -> None:
    service, subject_id, artifact_id, _reference = _build_service_with_draft(tmp_path)
    service.approve_t2_mask(subject_id, artifact_id, reviewer="Reviewer A")
    replacement = service.plan_bulk_flip(
        (subject_id,),
        (0,),
        (ScanRole.T2,),
    )

    replaced = service.import_confirmed_scans(replacement, actor="Reviewer A")

    result = replaced.t2_results_for_subject(subject_id)[0]
    artifact = next(
        item
        for item in replaced.t2_artifacts_for_subject(subject_id)
        if item.id == artifact_id
    )
    assert result.state is ResultState.OUTDATED
    assert result.active is False
    assert "native T2 input changed" in result.outdated_reason
    assert artifact.state is ArtifactState.OUTDATED
    assert artifact.active is False


def test_schema_six_draft_migrates_non_destructively_to_review_schema(
    tmp_path: Path,
) -> None:
    service, subject_id, artifact_id, _reference = _build_service_with_draft(tmp_path)
    study = service.current_study
    assert study is not None
    service.close_study()
    with sqlite3.connect(study.database_path) as connection:
        connection.execute("PRAGMA foreign_keys = OFF")
        connection.executescript(
            """
            DROP TABLE reviews;
            DROP TABLE results;
            DROP INDEX idx_artifacts_subject_type;
            DROP INDEX idx_artifacts_state;
            DROP INDEX idx_artifacts_active_type;
            ALTER TABLE artifacts RENAME TO artifacts_v7;
            CREATE TABLE artifacts (
                id TEXT PRIMARY KEY,
                study_id TEXT NOT NULL REFERENCES studies(id) ON DELETE CASCADE,
                subject_id TEXT NOT NULL REFERENCES subjects(id) ON DELETE CASCADE,
                artifact_type TEXT NOT NULL,
                state TEXT NOT NULL CHECK (
                    state IN ('DRAFT_REVIEW_REQUIRED', 'OUTDATED')
                ),
                version INTEGER NOT NULL CHECK (version > 0),
                active INTEGER NOT NULL CHECK (active IN (0, 1)),
                path TEXT NOT NULL,
                file_hash TEXT NOT NULL,
                source_scan_input_id TEXT NOT NULL REFERENCES scan_inputs(id),
                model_release_id TEXT NOT NULL REFERENCES model_releases(id),
                job_id TEXT NOT NULL REFERENCES jobs(id),
                metadata_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                created_by TEXT NOT NULL,
                superseded_by TEXT REFERENCES artifacts(id),
                UNIQUE(subject_id, artifact_type, version)
            );
            INSERT INTO artifacts
            SELECT id, study_id, subject_id, 'T2_LESION_MASK_DRAFT', state,
                   version, active, path, file_hash, source_scan_input_id,
                   model_release_id, job_id, metadata_json, created_at,
                   created_by, superseded_by
            FROM artifacts_v7;
            DROP TABLE artifacts_v7;
            CREATE INDEX idx_artifacts_subject_type
                ON artifacts(subject_id, artifact_type, version DESC);
            CREATE INDEX idx_artifacts_state ON artifacts(study_id, state);
            CREATE UNIQUE INDEX idx_artifacts_active_type
                ON artifacts(subject_id, artifact_type) WHERE active = 1;
            DELETE FROM schema_migrations;
            INSERT INTO schema_migrations(version, applied_at)
            VALUES (6, '2026-01-01T00:00:00+00:00');
            PRAGMA user_version = 6;
            """
        )
    manifest_path = study.root_path / "project.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["schema_version"] = 6
    manifest_path.write_text(json.dumps(manifest))

    migrated = service.open_study(study.root_path)

    assert migrated.schema_version == STUDY_SCHEMA_VERSION
    artifact = migrated.t2_artifacts_for_subject(subject_id)[0]
    assert artifact.id == artifact_id
    assert artifact.artifact_type == "T2_LESION_MASK"
    assert artifact.mask_path.is_file()
    with sqlite3.connect(migrated.database_path) as connection:
        assert (
            connection.execute("PRAGMA user_version").fetchone()[0]
            == STUDY_SCHEMA_VERSION
        )
        assert connection.execute(
            "SELECT version FROM schema_migrations ORDER BY version"
        ).fetchall() == [(6,), (8,), (9,), (10,), (11,)]


def test_schema_seven_review_migrates_to_approval_without_notes_or_issue_type(
    tmp_path: Path,
) -> None:
    service, subject_id, artifact_id, _reference = _build_service_with_draft(tmp_path)
    approved = service.approve_t2_mask(
        subject_id,
        artifact_id,
        reviewer="Reviewer A",
    )
    service.close_study()
    with sqlite3.connect(approved.database_path) as connection:
        connection.execute("PRAGMA foreign_keys = OFF")
        connection.executescript(
            """
            ALTER TABLE reviews RENAME TO reviews_v8;
            CREATE TABLE reviews (
                id TEXT PRIMARY KEY,
                study_id TEXT NOT NULL REFERENCES studies(id) ON DELETE CASCADE,
                subject_id TEXT NOT NULL REFERENCES subjects(id) ON DELETE CASCADE,
                artifact_id TEXT NOT NULL UNIQUE REFERENCES artifacts(id) ON DELETE CASCADE,
                decision TEXT NOT NULL CHECK (decision IN ('APPROVED', 'REJECTED')),
                reviewer TEXT NOT NULL,
                study_blinding_state TEXT NOT NULL,
                issue_code TEXT,
                notes TEXT,
                created_at TEXT NOT NULL
            );
            INSERT INTO reviews(
                id, study_id, subject_id, artifact_id, decision, reviewer,
                study_blinding_state, issue_code, notes, created_at
            )
            SELECT
                id, study_id, subject_id, artifact_id, 'APPROVED', reviewer,
                study_blinding_state, 'LEGACY_ISSUE', 'legacy review note', created_at
            FROM reviews_v8;
            DROP TABLE reviews_v8;
            CREATE INDEX idx_reviews_subject_time
                ON reviews(subject_id, created_at DESC);
            UPDATE audit_events
            SET details_json = '{"issue_code":"LEGACY_ISSUE","notes":"legacy review note"}'
            WHERE event_type = 'T2_LESION_MASK_APPROVED';
            DELETE FROM schema_migrations;
            INSERT INTO schema_migrations(version, applied_at)
            VALUES (7, '2026-01-01T00:00:00+00:00');
            PRAGMA user_version = 7;
            """
        )
    manifest_path = approved.root_path / "project.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["schema_version"] = 7
    manifest_path.write_text(json.dumps(manifest))

    migrated = service.open_study(approved.root_path)

    review = migrated.review_for_artifact(artifact_id)
    assert review is not None
    assert review.reviewer == "Reviewer A"
    assert migrated.active_t2_result_for_subject(subject_id) is not None
    with sqlite3.connect(migrated.database_path) as connection:
        columns = {
            row[1] for row in connection.execute("PRAGMA table_info(reviews)")
        }
        assert "decision" not in columns
        assert "issue_code" not in columns
        assert "notes" not in columns
        audit_json = connection.execute(
            "SELECT details_json FROM audit_events "
            "WHERE event_type = 'T2_LESION_MASK_APPROVED'"
        ).fetchone()[0]
        assert "LEGACY_ISSUE" not in audit_json
        assert "legacy review note" not in audit_json
