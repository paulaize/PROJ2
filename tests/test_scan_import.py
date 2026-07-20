"""Focused tests for reviewable MRI discovery, conversion, and persistence."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import nibabel as nib
import numpy as np

from lys_bbb.scan_conversion import convert_scan_assignment
from lys_bbb.scan_discovery import discover_mri_source, infer_subject_code
from lys_bbb_app.domain.scan_import import (
    ImportConfidence,
    OrientationPolicy,
    ScanImportAssignment,
    ScanImportState,
    ScanRole,
    SourceFormat,
)
from lys_bbb_app.domain.study import CreateStudyRequest
from lys_bbb_app.infrastructure.study_database import (
    STUDY_MANIFEST_NAME,
    StudyRepository,
)
from lys_bbb_app.services.study_service import StudyService


def _write_bruker_scan(
    session: Path,
    scan_id: int,
    *,
    protocol: str,
    method: str,
    orientation: str = "axial",
    comment: str = "",
) -> None:
    scan = session / str(scan_id)
    scan.mkdir(parents=True)
    (scan / "acqp").write_text(f"##$ACQ_protocol_name=( 64 )\n<{protocol}>\n")
    (scan / "method").write_text(
        f"##$Method=<{method}>\n"
        f"##$PVM_SPackArrSliceOrient=( 1 )\n<{orientation}>\n"
    )
    (scan / "visu_pars").write_text(
        f"##$VisuSeriesComment=( 64 )\n<{comment}>\n"
    )
    reco = scan / "pdata" / "1"
    reco.mkdir(parents=True)
    (reco / "visu_pars").write_text("##$VisuCoreDim=3\n")
    (reco / "2dseq").write_bytes(b"synthetic")


def _write_nifti(path: Path, *, value: float = 1.0) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = np.arange(24, dtype=np.float32).reshape(2, 3, 4) + value
    image = nib.Nifti1Image(data, np.diag([0.1, 0.2, 0.5, 1.0]))
    nib.save(image, path)


def test_discovery_uses_metadata_to_propose_t1_pair_and_rare_t2(tmp_path: Path) -> None:
    session = tmp_path / "raw" / "20240912_124311_C23S2_D1_MRI"
    _write_bruker_scan(session, 1, protocol="1_Localizer", method="Bruker:FLASH")
    _write_bruker_scan(
        session,
        3,
        protocol="T1_FLASH_3D_Glymphatic_Sag",
        method="Bruker:FLASH",
        orientation="sagittal",
        comment="T1w_3D_Sag_preGd",
    )
    _write_bruker_scan(
        session,
        5,
        protocol="T2_haute_resolution_Turbo",
        method="Bruker:RARE",
    )
    _write_bruker_scan(
        session,
        6,
        protocol="T1_FLASH_3D_Glymphatic_Sag",
        method="Bruker:FLASH",
        orientation="sagittal",
        comment="T1w_3D_Sag_postGd",
    )
    _write_bruker_scan(session, 7, protocol="T2s_rapide", method="Bruker:FcFLASH")

    report = discover_mri_source(tmp_path / "raw")
    proposed = {
        scan.scan_id: scan
        for scan in report.scans
        if scan.suggested_role is not ScanRole.IGNORE
    }

    assert report.session_count == 1
    assert report.proposed_subject_codes == ("C23S2_D1",)
    assert proposed[3].suggested_role is ScanRole.T1_PRE
    assert proposed[3].role_confidence is ImportConfidence.HIGH
    assert proposed[3].orientation_policy is OrientationPolicy.T1_CORONAL
    assert proposed[5].suggested_role is ScanRole.T2
    assert proposed[6].suggested_role is ScanRole.T1_POST
    assert next(scan for scan in report.scans if scan.scan_id == 7).suggested_role is ScanRole.IGNORE


def test_unknown_subject_name_is_low_confidence_and_requires_edit() -> None:
    code, confidence, issues = infer_subject_code("20260720_120000_unlabelled_mouse")

    assert code == "unlabelled_mouse"
    assert confidence is ImportConfidence.LOW
    assert issues[0].code == "SUBJECT_ID_AMBIGUOUS"


def test_equal_high_resolution_t2_candidates_are_flagged_for_review(tmp_path: Path) -> None:
    session = tmp_path / "raw" / "C1S1_D1"
    _write_bruker_scan(
        session,
        2,
        protocol="T2_haute_resolution_Turbo",
        method="Bruker:RARE",
    )
    _write_bruker_scan(
        session,
        5,
        protocol="T2_haute_resolution_Turbo_repeat",
        method="Bruker:RARE",
    )

    report = discover_mri_source(tmp_path / "raw")
    selected = [scan for scan in report.scans if scan.suggested_role is ScanRole.T2]

    assert len(selected) == 1
    assert selected[0].scan_id == 2
    assert selected[0].role_confidence is ImportConfidence.LOW
    assert any(
        issue.code == "MULTIPLE_T2_RARE_CANDIDATES" for issue in selected[0].issues
    )


def test_direct_nifti_conversion_records_affine_preserving_axis_flip(tmp_path: Path) -> None:
    source = tmp_path / "Mouse-01_t2w.nii.gz"
    _write_nifti(source)
    assignment = ScanImportAssignment(
        proposal_id="proposal-1",
        subject_code="Mouse-01",
        role=ScanRole.T2,
        source_path=source,
        source_format=SourceFormat.NIFTI,
        session_id="direct-nifti",
        scan_id=None,
        protocol="NIfTI file",
        method="NIfTI",
        acquisition_orientation="from affine",
        confidence=ImportConfidence.HIGH,
        orientation_policy=OrientationPolicy.NATIVE,
        flip_axes=(0,),
    )

    result = convert_scan_assignment(
        assignment,
        output_directory=tmp_path / "outputs" / "v001",
        work_directory=tmp_path / "work",
    )
    original = nib.load(source)
    converted = nib.load(result.output_path)

    np.testing.assert_array_equal(
        converted.get_fdata(),
        original.get_fdata()[::-1, :, :],
    )
    np.testing.assert_allclose(
        converted.affine @ np.array([0, 0, 0, 1]),
        original.affine @ np.array([original.shape[0] - 1, 0, 0, 1]),
    )
    assert result.provenance_path.is_file()
    provenance = json.loads(result.provenance_path.read_text())
    assert provenance["transform"]["storage_axis_flips"] == [0]
    assert provenance["transform"]["interpolation"] == "none"


def test_confirmed_import_creates_subject_and_versioned_active_input(tmp_path: Path) -> None:
    source = tmp_path / "raw" / "C1S1_D1_t2w.nii.gz"
    _write_nifti(source)
    service = StudyService()
    study = service.create_study(
        CreateStudyRequest(
            tmp_path / "study",
            "MRI study",
            "mri-study",
            actor="Reviewer A",
        )
    )
    assignment = ScanImportAssignment(
        proposal_id="first-proposal",
        subject_code="C1S1_D1",
        role=ScanRole.T2,
        source_path=source,
        source_format=SourceFormat.NIFTI,
        session_id="direct-nifti",
        scan_id=None,
        protocol="T2w",
        method="NIfTI",
        acquisition_orientation="from affine",
        confidence=ImportConfidence.HIGH,
        orientation_policy=OrientationPolicy.NATIVE,
    )

    imported = service.import_confirmed_scans((assignment,), actor="Reviewer A")
    record = imported.scan_inputs[0]

    assert imported.root_path == study.root_path
    assert imported.subjects[0].subject_code == "C1S1_D1"
    assert imported.subjects[0].group_name is None
    assert imported.subjects[0].expected_t2 is True
    assert record.state is ScanImportState.CONVERTED
    assert record.active is True
    assert record.version == 1
    assert record.output_path is not None and record.output_path.is_file()
    assert record.output_path.is_relative_to(imported.root_path)

    replacement = ScanImportAssignment(
        **{**assignment.__dict__, "proposal_id": "second-proposal", "flip_axes": (1,)}
    )
    replaced = service.import_confirmed_scans((replacement,), actor="Reviewer A")
    current, previous = replaced.scan_inputs
    assert current.version == 2 and current.active
    assert previous.version == 1 and not previous.active
    assert previous.state is ScanImportState.SUPERSEDED
    assert current.output_path != previous.output_path


def test_removed_subject_is_hidden_but_inputs_and_outputs_can_be_restored(
    tmp_path: Path,
) -> None:
    source = tmp_path / "raw" / "C1S1_D1_t2w.nii.gz"
    _write_nifti(source)
    service = StudyService()
    service.create_study(
        CreateStudyRequest(tmp_path / "study", "Study", "study", actor="Reviewer")
    )
    assignment = ScanImportAssignment(
        proposal_id="archive-proposal",
        subject_code="C1S1_D1",
        role=ScanRole.T2,
        source_path=source,
        source_format=SourceFormat.NIFTI,
        session_id="direct-nifti",
        scan_id=None,
        protocol="T2w",
        method="NIfTI",
        acquisition_orientation="from affine",
        confidence=ImportConfidence.HIGH,
        orientation_policy=OrientationPolicy.NATIVE,
    )
    imported = service.import_confirmed_scans((assignment,), actor="Reviewer")
    subject_id = imported.subjects[0].id
    output_path = imported.scan_inputs[0].output_path
    assert output_path is not None

    removed = service.remove_subject(subject_id, actor="Reviewer")

    assert removed.subjects == ()
    assert removed.scan_inputs == ()
    assert removed.archived_subjects[0].id == subject_id
    assert source.is_file()
    assert output_path.is_file()
    with sqlite3.connect(removed.database_path) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM subjects WHERE id = ?", (subject_id,)
        ).fetchone()[0] == 1
        assert connection.execute(
            "SELECT COUNT(*) FROM scan_inputs WHERE subject_id = ?", (subject_id,)
        ).fetchone()[0] == 1

    restored = service.restore_subject(subject_id, actor="Reviewer")

    assert restored.archived_subjects == ()
    assert restored.subjects[0].id == subject_id
    assert restored.scan_inputs[0].output_path == output_path
    assert [event.event_type for event in service.list_audit_events()[:2]] == [
        "SUBJECT_RESTORED",
        "SUBJECT_REMOVED",
    ]


def test_conversion_failure_remains_visible_in_persistent_input_state(tmp_path: Path) -> None:
    source = tmp_path / "C1S1_D1_t2w.nii.gz"
    _write_nifti(source)

    def fail_conversion(*_args, **_kwargs):
        raise RuntimeError("synthetic converter failure")

    service = StudyService(scan_converter=fail_conversion)
    service.create_study(
        CreateStudyRequest(tmp_path / "study", "Study", "study", actor="Reviewer")
    )
    assignment = ScanImportAssignment(
        proposal_id="failure-proposal",
        subject_code="C1S1_D1",
        role=ScanRole.T2,
        source_path=source,
        source_format=SourceFormat.NIFTI,
        session_id="direct-nifti",
        scan_id=None,
        protocol="T2w",
        method="NIfTI",
        acquisition_orientation="from affine",
        confidence=ImportConfidence.HIGH,
        orientation_policy=OrientationPolicy.NATIVE,
    )

    snapshot = service.import_confirmed_scans((assignment,), actor="Reviewer")

    assert snapshot.scan_inputs[0].state is ScanImportState.FAILED
    assert snapshot.scan_inputs[0].error_message == "synthetic converter failure"
    assert snapshot.scan_inputs[0].output_path is None


def test_opening_schema_v2_study_migrates_scan_input_state_and_manifest(tmp_path: Path) -> None:
    repository = StudyRepository.create(
        CreateStudyRequest(tmp_path / "study", "Study", "study", actor="Reviewer")
    )
    with sqlite3.connect(repository.database_path) as connection:
        connection.executescript(
            """
            DROP TABLE scan_inputs;
            ALTER TABLE input_folders RENAME TO input_folders_v3;
            CREATE TABLE input_folders (
                study_id TEXT NOT NULL REFERENCES studies(id) ON DELETE CASCADE,
                kind TEXT NOT NULL CHECK (kind IN ('t1', 't2')),
                path TEXT NOT NULL CHECK (length(trim(path)) > 0),
                selected_at TEXT NOT NULL,
                PRIMARY KEY(study_id, kind)
            );
            INSERT INTO input_folders SELECT * FROM input_folders_v3;
            DROP TABLE input_folders_v3;
            DROP INDEX idx_subjects_study_archived;
            ALTER TABLE subjects DROP COLUMN archived_at;
            ALTER TABLE subjects DROP COLUMN archived_by;
            DELETE FROM schema_migrations WHERE version > 2;
            INSERT INTO schema_migrations(version, applied_at) VALUES (2, 'test');
            PRAGMA user_version = 2;
            """
        )
    manifest_path = repository.root_path / STUDY_MANIFEST_NAME
    manifest = json.loads(manifest_path.read_text())
    manifest["schema_version"] = 2
    manifest_path.write_text(json.dumps(manifest))

    reopened = StudyRepository.open(repository.root_path).snapshot()

    assert reopened.schema_version == 4
    assert json.loads(manifest_path.read_text())["schema_version"] == 4
    with sqlite3.connect(repository.database_path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 4
        assert connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='scan_inputs'"
        ).fetchone() == ("scan_inputs",)
