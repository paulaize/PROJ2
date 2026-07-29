"""Focused tests for canonical study-root persistence and migration."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from lys_bbb_app.domain.study import (
    AnalysisScope,
    CreateStudyRequest,
    CreateSubjectRequest,
)
from lys_bbb_app.infrastructure.recent_studies import RecentStudiesStore
from lys_bbb_app.infrastructure.study_database import (
    STUDY_APPLICATION_ID,
    STUDY_DATABASE_NAME,
    STUDY_DIRECTORIES,
    STUDY_MANIFEST_FORMAT,
    STUDY_MANIFEST_NAME,
    STUDY_SCHEMA_VERSION,
    DuplicateSubjectError,
    StudyAlreadyExistsError,
    StudyRepository,
    StudyStateError,
)
def _create_study(tmp_path: Path, *, blinded: bool = True) -> StudyRepository:
    return StudyRepository.create(
        CreateStudyRequest(
            root_path=tmp_path / "eae-study",
            name="EAE Mouse Study",
            identifier="EAE-2026",
            description="Persistent canonical study test",
            blinded=blinded,
            group_definitions=("Vehicle", "Treatment A"),
            actor="Test researcher",
        )
    )


def test_create_study_root_writes_manifest_database_and_managed_directories(
    tmp_path: Path,
) -> None:
    repository = _create_study(tmp_path)
    snapshot = repository.snapshot()

    assert snapshot.root_path == (tmp_path / "eae-study").resolve()
    assert snapshot.database_path.name == STUDY_DATABASE_NAME
    assert snapshot.schema_version == STUDY_SCHEMA_VERSION
    assert snapshot.is_blinded
    assert snapshot.group_definitions == ("Vehicle", "Treatment A")
    assert (snapshot.root_path / STUDY_MANIFEST_NAME).is_file()
    assert all((snapshot.root_path / name).is_dir() for name in STUDY_DIRECTORIES)
    manifest = json.loads((snapshot.root_path / STUDY_MANIFEST_NAME).read_text())
    assert manifest["format"] == STUDY_MANIFEST_FORMAT

    with sqlite3.connect(snapshot.database_path) as connection:
        assert connection.execute("PRAGMA application_id").fetchone()[0] == STUDY_APPLICATION_ID
        assert connection.execute("PRAGMA user_version").fetchone()[0] == STUDY_SCHEMA_VERSION
        assert connection.execute(
            "SELECT version FROM schema_migrations"
        ).fetchall() == [(STUDY_SCHEMA_VERSION,)]
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        assert {
            "t1_brain_mask_releases",
            "t1_brain_mask_jobs",
            "t1_brain_mask_artifacts",
            "t1_brain_mask_reviews",
            "t1_registration_methods",
            "t1_registration_jobs",
            "t1_registration_artifacts",
            "t1_registration_reviews",
            "t1_enhancement_methods",
            "t1_enhancement_jobs",
            "t1_enhancement_results",
        } <= tables


def test_study_creation_never_reuses_an_existing_directory(tmp_path: Path) -> None:
    root = tmp_path / "existing"
    root.mkdir()
    marker = root / "keep.txt"
    marker.write_text("do not overwrite")

    with pytest.raises(StudyAlreadyExistsError, match="will not be overwritten"):
        StudyRepository.create(
            CreateStudyRequest(root, "Study", "study-1")
        )

    assert marker.read_text() == "do not overwrite"


def test_schema_nine_study_migrates_to_t1_analysis_contract(tmp_path: Path) -> None:
    repository = _create_study(tmp_path)
    snapshot = repository.snapshot()
    with sqlite3.connect(snapshot.database_path) as connection:
        connection.execute("PRAGMA foreign_keys = OFF")
        connection.executescript(
            """
            DROP TABLE t1_enhancement_results;
            DROP TABLE t1_enhancement_jobs;
            DROP TABLE t1_enhancement_methods;
            DROP TABLE t1_registration_reviews;
            DROP TABLE t1_registration_artifacts;
            DROP TABLE t1_registration_jobs;
            DROP TABLE t1_registration_methods;
            DELETE FROM schema_migrations WHERE version = 10;
            PRAGMA user_version = 9;
            """
        )
    manifest_path = snapshot.root_path / STUDY_MANIFEST_NAME
    manifest = json.loads(manifest_path.read_text())
    manifest["schema_version"] = 9
    manifest_path.write_text(json.dumps(manifest))

    migrated = StudyRepository.open(snapshot.root_path).snapshot()

    assert migrated.schema_version == STUDY_SCHEMA_VERSION
    with sqlite3.connect(migrated.database_path) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        assert {
            "t1_registration_artifacts",
            "t1_registration_reviews",
            "t1_enhancement_methods",
            "t1_enhancement_results",
        } <= tables


def test_subjects_reopen_with_expected_workflows_and_no_invented_group(
    tmp_path: Path,
) -> None:
    repository = _create_study(tmp_path)
    repository.add_subject(
        CreateSubjectRequest(
            subject_code="Mouse-001",
            expected_t1=True,
            expected_t2=True,
            actor="Reviewer A",
        )
    )

    reopened = StudyRepository.open(repository.root_path).snapshot()

    assert len(reopened.subjects) == 1
    subject = reopened.subjects[0]
    assert subject.subject_code == "Mouse-001"
    assert subject.group_name is None
    assert subject.expected_t1 is True
    assert subject.expected_t2 is True


@pytest.mark.parametrize(
    ("scope", "expected_t1", "expected_t2"),
    (
        (AnalysisScope.T1_ONLY, True, False),
        (AnalysisScope.T2_ONLY, False, True),
    ),
)
def test_single_modality_scope_persists_and_rejects_incompatible_subjects(
    tmp_path: Path,
    scope: AnalysisScope,
    expected_t1: bool,
    expected_t2: bool,
) -> None:
    repository = StudyRepository.create(
        CreateStudyRequest(
            root_path=tmp_path / scope.value.lower(),
            name="Single-modality study",
            identifier=scope.value.lower(),
            analysis_scope=scope,
            actor="Reviewer A",
        )
    )
    repository.add_subject(
        CreateSubjectRequest(
            "Mouse-001",
            expected_t1,
            expected_t2,
            actor="Reviewer A",
        )
    )

    reopened = StudyRepository.open(repository.root_path).snapshot()

    assert reopened.analysis_scope is scope
    assert reopened.subjects[0].expected_t1 is expected_t1
    assert reopened.subjects[0].expected_t2 is expected_t2
    with pytest.raises(StudyStateError, match="configured for"):
        repository.add_subject(
            CreateSubjectRequest(
                "Mouse-002",
                not expected_t1,
                not expected_t2,
                actor="Reviewer A",
            )
        )


def test_schema_eleven_study_migrates_to_combined_analysis_scope(
    tmp_path: Path,
) -> None:
    repository = _create_study(tmp_path)
    with sqlite3.connect(repository.database_path) as connection:
        connection.executescript(
            """
            ALTER TABLE studies DROP COLUMN analysis_scope;
            DELETE FROM schema_migrations WHERE version = 12;
            PRAGMA user_version = 11;
            """
        )
    manifest_path = repository.root_path / STUDY_MANIFEST_NAME
    manifest = json.loads(manifest_path.read_text())
    manifest["schema_version"] = 11
    manifest_path.write_text(json.dumps(manifest))

    reopened = StudyRepository.open(repository.root_path).snapshot()

    assert reopened.analysis_scope is AnalysisScope.T1_T2


def test_blinded_study_rejects_group_assignment_until_audited_unblinding(
    tmp_path: Path,
) -> None:
    repository = _create_study(tmp_path)
    snapshot = repository.add_subject(
        CreateSubjectRequest("Mouse-001", True, True, actor="Reviewer A")
    )
    subject_id = snapshot.subjects[0].id

    with pytest.raises(StudyStateError, match="Unblind the study"):
        repository.assign_groups({subject_id: "Treatment A"}, actor="Reviewer A")

    unblinded = repository.unblind(actor="Reviewer A")
    assigned = repository.assign_groups(
        {subject_id: "Treatment A"},
        actor="Reviewer A",
    )

    assert unblinded.is_blinded is False
    assert unblinded.unblinded_by == "Reviewer A"
    assert assigned.subjects[0].group_name == "Treatment A"
    events = repository.list_audit_events()
    assert [event.event_type for event in events[:2]] == [
        "SUBJECT_GROUPS_ASSIGNED",
        "STUDY_UNBLINDED",
    ]
    assert events[0].details["subjects_assigned"] == 1


def test_unassigned_group_remains_a_valid_persistent_value(tmp_path: Path) -> None:
    repository = _create_study(tmp_path, blinded=False)
    snapshot = repository.add_subject(
        CreateSubjectRequest("Mouse-001", True, False, actor="Reviewer A")
    )
    subject_id = snapshot.subjects[0].id

    reassigned = repository.assign_groups({subject_id: None}, actor="Reviewer A")

    assert reassigned.subjects[0].group_name is None
    assert repository.list_audit_events()[0].details["subjects_unassigned"] == 1


def test_subject_codes_are_unique_within_a_study(tmp_path: Path) -> None:
    repository = _create_study(tmp_path)
    request = CreateSubjectRequest("Mouse-001", True, False, actor="Reviewer A")
    repository.add_subject(request)

    with pytest.raises(DuplicateSubjectError, match="already exists"):
        repository.add_subject(request)


def test_subject_rename_preserves_stable_identity_and_is_audited(
    tmp_path: Path,
) -> None:
    repository = _create_study(tmp_path)
    snapshot = repository.add_subject(
        CreateSubjectRequest("Mouse-001", True, True, actor="Reviewer A")
    )
    subject_id = snapshot.subjects[0].id

    renamed = repository.rename_subject(
        subject_id,
        "Mouse-treatment-001",
        actor="Reviewer A",
    )
    reopened = StudyRepository.open(repository.root_path).snapshot()

    assert renamed.subjects[0].id == subject_id
    assert renamed.subjects[0].subject_code == "Mouse-treatment-001"
    assert reopened.subjects[0].subject_code == "Mouse-treatment-001"
    event = repository.list_audit_events()[0]
    assert event.event_type == "SUBJECT_RENAMED"
    assert event.details == {
        "managed_files_moved": False,
        "previous_subject_code": "Mouse-001",
        "subject_code": "Mouse-treatment-001",
    }


def test_subject_rename_rejects_a_case_insensitive_duplicate(tmp_path: Path) -> None:
    repository = _create_study(tmp_path)
    first = repository.add_subject(
        CreateSubjectRequest("Mouse-001", True, False, actor="Reviewer A")
    ).subjects[0]
    repository.add_subject(
        CreateSubjectRequest("Mouse-002", True, False, actor="Reviewer A")
    )

    with pytest.raises(DuplicateSubjectError, match="already exists"):
        repository.rename_subject(first.id, "mouse-002", actor="Reviewer A")


def test_recent_studies_round_trip_without_touching_study_state(tmp_path: Path) -> None:
    repository = _create_study(tmp_path)
    store = RecentStudiesStore(tmp_path / "preferences" / "recent.json")

    store.record(repository.snapshot())
    recent = store.list()

    assert len(recent) == 1
    assert recent[0].name == "EAE Mouse Study"
    assert Path(recent[0].path) == repository.root_path


def test_recent_studies_reads_historical_brand_location_until_new_store_exists(
    tmp_path: Path,
) -> None:
    current_path = tmp_path / "LYS IRM" / "recent_studies.json"
    legacy_path = tmp_path / ".lys_bbb" / "recent_studies.json"
    legacy_path.parent.mkdir()
    legacy_path.write_text(
        json.dumps(
            {
                "recent_studies": [
                    {
                        "name": "Existing study",
                        "path": str(tmp_path / "existing-study"),
                        "last_opened": "2026-07-01T12:00:00+00:00",
                    }
                ]
            }
        )
    )
    store = RecentStudiesStore(current_path, legacy_path=legacy_path)

    recent = store.list()

    assert recent[0].name == "Existing study"


def test_source_folder_is_referenced_in_place_and_audited(tmp_path: Path) -> None:
    repository = _create_study(tmp_path)
    source = tmp_path / "mounted-hard-drive" / "t1-data"
    source.mkdir(parents=True)

    snapshot = repository.set_input_folder_reference(
        "t1",
        source,
        actor="Reviewer A",
        require_available=True,
    )
    source.rename(tmp_path / "temporarily-disconnected")
    reopened = StudyRepository.open(repository.root_path).snapshot()

    assert snapshot.t1_input_folder == source.resolve()
    assert reopened.t1_input_folder == source.resolve()
    assert not reopened.t1_input_folder.is_dir()
    event = repository.list_audit_events()[0]
    assert event.event_type == "INPUT_FOLDER_SELECTED"
    assert event.details["path"] == str(source.resolve())
