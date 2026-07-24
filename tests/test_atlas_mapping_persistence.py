"""Focused persistence, approval, reopening, and invalidation tests for atlas mapping."""

from __future__ import annotations

import sqlite3
import json
from pathlib import Path

import pytest

from lys_bbb.hashing import sha256_file
from lys_bbb.atlas_mapping import AtlasCompositeOutput, MajorRegionLesionResult
from lys_bbb.t1_t2_registration import T1ToT2Output
from lys_bbb_app.domain.atlas_mapping import AtlasReviewState
from lys_bbb_app.domain.errors import StudyStateError
from lys_bbb_app.domain.study import CreateStudyRequest, CreateSubjectRequest
from lys_bbb_app.infrastructure.atlas_mapping_repository import (
    AtlasMappingRepository,
    invalidate_atlas_for_input_change,
    invalidate_atlas_for_lesion_change,
)
from lys_bbb_app.infrastructure.study_database import StudyRepository


def _study(tmp_path: Path) -> tuple[StudyRepository, str, str]:
    repository = StudyRepository.create(
        CreateStudyRequest(
            tmp_path / "study",
            "Atlas persistence",
            "atlas-persistence",
            actor="Reviewer",
        )
    )
    snapshot = repository.add_subject(
        CreateSubjectRequest("Mouse-001", True, True, actor="Reviewer")
    )
    with sqlite3.connect(repository.database_path) as connection:
        study_id = connection.execute("SELECT id FROM studies").fetchone()[0]
    return repository, study_id, snapshot.subjects[0].id


def _write(root: Path, name: str, content: bytes) -> tuple[str, str]:
    path = root / "outputs" / "atlas_mapping" / "test" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return str(path.relative_to(root)), sha256_file(path)


def _insert_atlas_candidate(
    repository: StudyRepository,
    study_id: str,
    subject_id: str,
) -> tuple[str, Path]:
    transform, transform_hash = _write(repository.root_path, "rigid.mat", b"transform")
    warped, warped_hash = _write(repository.root_path, "warped.nii.gz", b"warped")
    support, support_hash = _write(
        repository.root_path, "warped-support.nii.gz", b"support"
    )
    qc, qc_hash = _write(repository.root_path, "qc.png", b"qc")
    metadata, metadata_hash = _write(repository.root_path, "metadata.json", b"{}")
    artifact_id = "atlas-rigid-draft"
    with sqlite3.connect(repository.database_path) as connection:
        connection.execute(
            """
            INSERT INTO atlas_to_t1_artifacts(
                id, study_id, subject_id, active, state, candidate,
                transform_path, transform_sha256, warped_intensity_path,
                warped_intensity_sha256, warped_support_path,
                warped_support_sha256, qc_path, qc_sha256, metadata_path,
                metadata_sha256, source_pre_scan_input_id,
                source_t1_mask_artifact_id, atlas_release_id, method_id,
                job_id, created_at, created_by
            ) VALUES (?, ?, ?, 0, 'DRAFT_REVIEW_REQUIRED', 'rigid', ?, ?, ?, ?, ?,
                      ?, ?, ?, ?, ?, 'pre-input', 't1-mask', 'atlas-release', 'method',
                      'job', '2026-07-22T10:00:00+00:00', 'Runner')
            """,
            (
                artifact_id,
                study_id,
                subject_id,
                transform,
                transform_hash,
                warped,
                warped_hash,
                support,
                support_hash,
                qc,
                qc_hash,
                metadata,
                metadata_hash,
            ),
        )
    return artifact_id, repository.root_path / transform


def test_candidate_success_is_not_approval_and_exact_approval_reopens(
    tmp_path: Path,
) -> None:
    repository, study_id, subject_id = _study(tmp_path)
    feature = AtlasMappingRepository(repository)
    artifact_id, transform_path = _insert_atlas_candidate(
        repository, study_id, subject_id
    )

    draft = feature.state(subject_id).atlas_to_t1_candidates[0]
    assert draft.state is AtlasReviewState.DRAFT_REVIEW_REQUIRED
    assert feature.state(subject_id).selected_atlas_to_t1 is None

    transform_path.write_bytes(b"changed")
    with pytest.raises(StudyStateError, match="checksum changed"):
        feature.approve_atlas_to_t1(artifact_id, reviewer="Reviewer")
    transform_path.write_bytes(b"transform")
    feature.approve_atlas_to_t1(artifact_id, reviewer="Reviewer")

    reopened = StudyRepository.open(repository.root_path)
    state = AtlasMappingRepository(reopened).state(subject_id)
    assert state.selected_atlas_to_t1 is not None
    assert state.selected_atlas_to_t1.id == artifact_id
    assert state.selected_atlas_to_t1.state is AtlasReviewState.APPROVED
    assert state.selected_atlas_to_t1.transform_sha256 == sha256_file(transform_path)


def _insert_downstream_rows(
    repository: StudyRepository,
    study_id: str,
    subject_id: str,
) -> None:
    with sqlite3.connect(repository.database_path) as connection:
        connection.execute(
            """
            INSERT INTO t2_registration_support_masks(
                id, study_id, subject_id, active, state, version, mask_path,
                mask_sha256, source_t2_scan_input_id, created_at, created_by
            ) VALUES ('support', ?, ?, 1, 'APPROVED', 1, 'support.nii.gz',
                      'support-hash', 't2-input', 'now', 'Reviewer')
            """,
            (study_id, subject_id),
        )
        connection.execute(
            """
            INSERT INTO t1_to_t2_artifacts(
                id, study_id, subject_id, active, state, transform_path,
                transform_sha256, transformed_t1_path, transformed_t1_sha256,
                transformed_t1_mask_path, transformed_t1_mask_sha256,
                qc_montage_path, qc_montage_sha256, qc_manifest_path,
                qc_manifest_sha256, qc_slice_paths_json, metadata_path,
                metadata_sha256, source_pre_scan_input_id,
                source_t2_scan_input_id, source_t1_mask_artifact_id,
                source_t2_support_mask_id, lesion_exclusion_artifact_id,
                lesion_exclusion_sha256, method_id, job_id, created_at, created_by
            ) VALUES ('t1-t2', ?, ?, 1, 'APPROVED', 'transform.mat', 'h',
                      't1.nii.gz', 'h', 'mask.nii.gz', 'h', 'qc.png', 'h',
                      'qc.json', 'h', '[]', 't1-t2.json', 'h', 'pre-input',
                      't2-input', 't1-mask',
                      'support', 'lesion-old', 'lesion-hash', 'method', 'job',
                      'now', 'Reviewer')
            """,
            (study_id, subject_id),
        )
        connection.execute(
            """
            INSERT INTO atlas_t2_composites(
                id, study_id, subject_id, active, state, labels_path, labels_sha256,
                support_path, support_sha256, qc_montage_path, qc_montage_sha256,
                qc_manifest_path, qc_manifest_sha256, qc_slice_paths_json,
                metadata_path, metadata_sha256,
                source_atlas_to_t1_artifact_id, source_t1_to_t2_artifact_id,
                atlas_release_id, major_region_scheme_id, source_t2_scan_input_id,
                created_at, created_by
            ) VALUES ('composite', ?, ?, 1, 'APPROVED', 'labels.nii.gz', 'h',
                      'atlas-support.nii.gz', 'h', 'qc.png', 'h', 'qc.json', 'h',
                      '[]', 'composite.json', 'h', 'atlas-rigid-draft', 't1-t2',
                      'atlas-release', 'scheme',
                      't2-input', 'now', 'Reviewer')
            """,
            (study_id, subject_id),
        )
        connection.execute(
            """
            INSERT INTO major_region_lesion_results(
                id, study_id, subject_id, active, state, result_csv_path,
                result_csv_sha256, metadata_path, metadata_sha256,
                lesion_voxel_count, lesion_volume_mm3, mapped_lesion_voxels,
                unmapped_lesion_voxels, outside_atlas_support_lesion_voxels,
                boundary_lesion_voxels, sensitivity_status,
                source_composite_artifact_id, source_lesion_artifact_id,
                source_lesion_sha256, major_region_scheme_id, created_at, created_by
            ) VALUES ('result', ?, ?, 1, 'APPROVED', 'result.csv', 'h',
                      'result.json', 'h', 10, 0.01, 8, 2, 2, 1, 'STABLE',
                      'composite', 'lesion-old', 'lesion-hash', 'scheme', 'now',
                      'Reviewer')
            """,
            (study_id, subject_id),
        )


def _active(connection: sqlite3.Connection, table: str) -> int:
    return int(connection.execute(f"SELECT active FROM {table}").fetchone()[0])


def test_dependency_invalidation_keeps_post_t1_independent_and_tracks_lesion_mask(
    tmp_path: Path,
) -> None:
    repository, study_id, subject_id = _study(tmp_path)
    _insert_atlas_candidate(repository, study_id, subject_id)
    _insert_downstream_rows(repository, study_id, subject_id)
    with sqlite3.connect(repository.database_path) as connection, connection:
        invalidate_atlas_for_input_change(
            connection,
            subject_id=subject_id,
            role="T1_POST",
            reason="post changed",
            changed_at="now",
        )
        assert connection.execute(
            "SELECT state FROM atlas_to_t1_artifacts"
        ).fetchone()[0] == "DRAFT_REVIEW_REQUIRED"
        assert _active(connection, "t1_to_t2_artifacts") == 1
        assert _active(connection, "atlas_t2_composites") == 1

        invalidate_atlas_for_lesion_change(
            connection,
            subject_id=subject_id,
            lesion_artifact_id="different-lesion",
            reason="lesion changed",
            changed_at="now",
        )
        assert _active(connection, "t1_to_t2_artifacts") == 1
        assert _active(connection, "atlas_t2_composites") == 1
        assert _active(connection, "major_region_lesion_results") == 0

        connection.execute(
            "UPDATE major_region_lesion_results SET active = 1, state = 'APPROVED'"
        )
        invalidate_atlas_for_lesion_change(
            connection,
            subject_id=subject_id,
            lesion_artifact_id="lesion-old",
            reason="bound lesion changed",
            changed_at="now",
        )
        assert _active(connection, "t1_to_t2_artifacts") == 0
        assert _active(connection, "atlas_t2_composites") == 0
        assert _active(connection, "major_region_lesion_results") == 0


def test_pre_t1_and_t2_invalidation_have_distinct_branches(tmp_path: Path) -> None:
    repository, study_id, subject_id = _study(tmp_path)
    _insert_atlas_candidate(repository, study_id, subject_id)
    _insert_downstream_rows(repository, study_id, subject_id)
    with sqlite3.connect(repository.database_path) as connection, connection:
        invalidate_atlas_for_input_change(
            connection,
            subject_id=subject_id,
            role="T2",
            reason="T2 changed",
            changed_at="now",
        )
        assert connection.execute(
            "SELECT state FROM atlas_to_t1_artifacts"
        ).fetchone()[0] == "DRAFT_REVIEW_REQUIRED"
        assert _active(connection, "t2_registration_support_masks") == 0
        assert _active(connection, "t1_to_t2_artifacts") == 0

        connection.execute(
            "UPDATE atlas_to_t1_artifacts SET active = 1, state = 'APPROVED'"
        )
        connection.execute(
            "UPDATE t2_registration_support_masks SET active = 1, state = 'APPROVED'"
        )
        connection.execute(
            "UPDATE t1_to_t2_artifacts SET active = 1, state = 'APPROVED'"
        )
        connection.execute(
            "UPDATE atlas_t2_composites SET active = 1, state = 'APPROVED'"
        )
        connection.execute(
            "UPDATE major_region_lesion_results SET active = 1, state = 'APPROVED'"
        )
        invalidate_atlas_for_input_change(
            connection,
            subject_id=subject_id,
            role="T1_PRE",
            reason="pre changed",
            changed_at="now",
        )
        assert connection.execute(
            "SELECT state FROM atlas_to_t1_artifacts"
        ).fetchone()[0] == "OUTDATED"
        assert _active(connection, "t1_to_t2_artifacts") == 0
        assert _active(connection, "atlas_t2_composites") == 0
        assert _active(connection, "major_region_lesion_results") == 0
        assert _active(connection, "t2_registration_support_masks") == 1


def _insert_vertical_slice_parents(
    repository: StudyRepository,
    study_id: str,
    subject_id: str,
) -> None:
    with sqlite3.connect(repository.database_path) as connection:
        for input_id, role in (("pre-input", "T1_PRE"), ("t2-input", "T2")):
            connection.execute(
                """
                INSERT INTO scan_inputs(
                    id, proposal_id, study_id, subject_id, role, version, active,
                    state, source_path, source_format, session_id, protocol, method,
                    acquisition_orientation, confidence, orientation_policy,
                    output_path, output_sha256, source_sha256, validation_state,
                    validated_at, validated_by, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, 1, 1, 'CONVERTED', 'source', 'NIFTI',
                          'D1', 'MRI', 'NIfTI', 'from affine', 'HIGH', 'NATIVE',
                          'input.nii.gz', 'input-hash', 'source-hash', 'VALID',
                          'now', 'Reviewer', 'now', 'now')
                """,
                (input_id, f"proposal-{input_id}", study_id, subject_id, role),
            )
        connection.execute(
            """
            INSERT INTO t1_brain_mask_artifacts(
                id, study_id, subject_id, origin, state, version, active,
                mask_path, mask_sha256, source_scan_input_id, release_id, job_id,
                foreground_voxels, volume_mm3, device, created_at, created_by
            ) VALUES ('t1-mask', ?, ?, 'AUTOMATIC', 'APPROVED', 1, 1,
                      'mask.nii.gz', 'mask-hash', 'pre-input', 'mask-release',
                      'mask-job', 10, 0.01, 'cpu', 'now', 'Reviewer')
            """,
            (study_id, subject_id),
        )
        connection.execute(
            """
            INSERT INTO atlas_releases(
                id, study_id, active, release_version, aidamri_revision,
                template_path, template_sha256, labels_path, labels_sha256,
                source_lookup_path, source_lookup_sha256, template_mask_path,
                template_mask_sha256, geometry_json, registered_at, registered_by
            ) VALUES ('atlas-release', ?, 1, 'release-v1', 'revision', 'template',
                      'h', 'labels', 'h', 'lookup', 'h', 'atlas-mask', 'h', '{}',
                      'now', 'Reviewer')
            """,
            (study_id,),
        )
        connection.execute(
            """
            INSERT INTO major_region_schemes(
                id, study_id, active, state, mapping_version, mapping_path,
                mapping_sha256, source_label_count, major_region_count,
                registered_at, registered_by
            ) VALUES ('scheme', ?, 1, 'APPROVED', 'major-v1', 'scheme.csv',
                      'scheme-hash', 2, 2, 'now', 'Reviewer')
            """,
            (study_id,),
        )
        connection.execute(
            """
            INSERT INTO t2_registration_support_masks(
                id, study_id, subject_id, active, state, version, mask_path,
                mask_sha256, source_t2_scan_input_id, created_at, created_by
            ) VALUES ('support', ?, ?, 1, 'APPROVED', 1, 'support.nii.gz',
                      'support-hash', 't2-input', 'now', 'Reviewer')
            """,
            (study_id, subject_id),
        )


def _path(repository: StudyRepository, name: str, content: bytes) -> Path:
    path = repository.root_path / "outputs" / "atlas_mapping" / "complete" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def _qc_bundle(repository: StudyRepository, prefix: str) -> tuple[Path, Path, tuple[Path, ...]]:
    montage = _path(repository, f"{prefix}-montage.png", b"montage")
    slice_path = _path(repository, f"{prefix}-slice-001.png", b"slice")
    manifest = _path(
        repository,
        f"{prefix}-manifest.json",
        json.dumps({"slice_sha256": {slice_path.name: sha256_file(slice_path)}}).encode(),
    )
    return montage, manifest, (slice_path,)


def test_completed_t1_t2_and_composite_bind_all_outputs_and_reopen(
    tmp_path: Path,
) -> None:
    repository, study_id, subject_id = _study(tmp_path)
    _insert_vertical_slice_parents(repository, study_id, subject_id)
    feature = AtlasMappingRepository(repository)
    atlas_id, _ = _insert_atlas_candidate(repository, study_id, subject_id)
    feature.approve_atlas_to_t1(atlas_id, reviewer="Reviewer")

    method_id = feature.register_method(
        "t1_to_t2",
        method_version="rigid-v1",
        method_spec_sha256="method-hash",
        config={"engine_version": "2.6.5"},
        actor="Reviewer",
    )
    job_id = feature.create_job(
        "t1_to_t2", subject_id=subject_id, method_id=method_id, actor="Reviewer"
    )
    feature.start_job("t1_to_t2", job_id, total=1)
    transform = _path(repository, "t1-t2.mat", b"transform")
    transformed = _path(repository, "t1-in-t2.nii.gz", b"image")
    transformed_mask = _path(repository, "mask-in-t2.nii.gz", b"mask")
    metadata = _path(repository, "t1-t2.json", b"{}")
    montage, manifest, slices = _qc_bundle(repository, "t1-t2")
    output = T1ToT2Output(
        case_id=subject_id,
        transform_path=transform,
        transform_sha256=sha256_file(transform),
        transformed_t1_path=transformed,
        transformed_t1_sha256=sha256_file(transformed),
        transformed_t1_brain_mask_path=transformed_mask,
        transformed_t1_brain_mask_sha256=sha256_file(transformed_mask),
        command_record_path=metadata,
        command_record_sha256=sha256_file(metadata),
        cost_mask_path=None,
        cost_mask_sha256=None,
        affine_metrics={"determinant": 1.0},
        method_version="rigid-v1",
        method_spec_sha256="method-hash",
        input_sha256={},
        metadata_path=metadata,
        metadata_sha256=sha256_file(metadata),
    )
    t1_t2_id = feature.complete_t1_to_t2(
        job_id=job_id,
        subject_id=subject_id,
        method_id=method_id,
        source_pre_scan_input_id="pre-input",
        source_t2_scan_input_id="t2-input",
        source_t1_mask_artifact_id="t1-mask",
        source_t2_support_mask_id="support",
        lesion_exclusion_artifact_id=None,
        output=output,
        qc_montage_path=montage,
        qc_manifest_path=manifest,
        qc_slice_paths=slices,
        actor="Reviewer",
    )
    feature.approve_t1_to_t2(t1_t2_id, reviewer="Reviewer")

    labels = _path(repository, "major-labels.nii.gz", b"labels")
    support = _path(repository, "atlas-support.nii.gz", b"support")
    composite_metadata = _path(repository, "composite.json", b"{}")
    montage, manifest, slices = _qc_bundle(repository, "composite")
    composite_output = AtlasCompositeOutput(
        source_major_labels_path=labels,
        source_major_labels_sha256=sha256_file(labels),
        labels_in_pre_t1_path=labels,
        labels_in_pre_t1_sha256=sha256_file(labels),
        labels_in_native_t2_path=labels,
        labels_in_native_t2_sha256=sha256_file(labels),
        atlas_support_in_native_t2_path=support,
        atlas_support_in_native_t2_sha256=sha256_file(support),
        command_record_paths=(),
        metadata_path=composite_metadata,
        metadata_sha256=sha256_file(composite_metadata),
    )
    composite_id = feature.complete_composite(
        subject_id=subject_id,
        source_atlas_to_t1_artifact_id=atlas_id,
        source_t1_to_t2_artifact_id=t1_t2_id,
        atlas_release_id="atlas-release",
        major_region_scheme_id="scheme",
        source_t2_scan_input_id="t2-input",
        output=composite_output,
        qc_montage_path=montage,
        qc_manifest_path=manifest,
        qc_slice_paths=slices,
        actor="Reviewer",
    )
    feature.approve_composite(composite_id, reviewer="Reviewer")

    lesion = _path(repository, "lesion.nii.gz", b"lesion")
    probability = _path(repository, "probability.nii.gz", b"probability")
    lesion_metadata = json.dumps(
        {
            "probability_path": str(probability.relative_to(repository.root_path)),
            "probability_sha256": sha256_file(probability),
            "lesion_voxel_count": 4,
            "provisional_volume_mm3": 0.004,
            "threshold": 0.4,
            "device": "cpu",
        }
    )
    with sqlite3.connect(repository.database_path) as connection:
        connection.execute(
            """
            INSERT INTO artifacts(
                id, study_id, subject_id, artifact_type, state, version, active,
                path, file_hash, source_scan_input_id, model_release_id, job_id,
                metadata_json, created_at, created_by
                ) VALUES ('lesion', ?, ?, 'T2_LESION_MASK', 'APPROVED', 1, 1, ?, ?,
                          't2-input', 'release', 'job', ?, 'now', 'Reviewer')
            """,
            (
                study_id,
                subject_id,
                str(lesion.relative_to(repository.root_path)),
                sha256_file(lesion),
                lesion_metadata,
            ),
        )
        connection.execute(
            """
            INSERT INTO reviews(
                id, study_id, subject_id, artifact_id, reviewer,
                study_blinding_state, created_at
            ) VALUES ('lesion-review', ?, ?, 'lesion', 'Reviewer', 'BLINDED', 'now')
            """,
            (study_id, subject_id),
        )
    result_csv = _path(repository, "result.csv", b"major_region_id,lesion_voxels\n101,4\n")
    result_metadata = _path(repository, "result.json", b"{}")
    feature.record_result(
        subject_id=subject_id,
        source_composite_artifact_id=composite_id,
        source_lesion_artifact_id="lesion",
        major_region_scheme_id="scheme",
        result=MajorRegionLesionResult(
            lesion_voxel_count=4,
            lesion_volume_mm3=0.004,
            mapped_lesion_voxels=3,
            unmapped_lesion_voxels=1,
            outside_atlas_support_lesion_voxels=1,
            boundary_lesion_voxels=1,
            nominal_dominant_region_id=101,
            sensitivity_status="STABLE_UNDER_AP_STRESS_TEST",
            result_csv_path=result_csv,
            result_csv_sha256=sha256_file(result_csv),
            metadata_path=result_metadata,
            metadata_sha256=sha256_file(result_metadata),
            lesion_sha256=sha256_file(lesion),
        ),
        actor="Reviewer",
    )

    state = AtlasMappingRepository(StudyRepository.open(repository.root_path)).state(
        subject_id
    )
    assert state.t1_to_t2 is not None
    assert state.t1_to_t2.state is AtlasReviewState.APPROVED
    assert state.t1_to_t2.metadata_sha256 == sha256_file(metadata)
    assert state.composite is not None
    assert state.composite.state is AtlasReviewState.APPROVED
    assert state.composite.metadata_sha256 == sha256_file(composite_metadata)
    assert state.result is not None
    assert state.result.outside_atlas_support_lesion_voxels == 1
