"""Tests for versioned SQLite project state and application services."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from lys_bbb.project_service import ProjectService
from lys_bbb.project_state import (
    CURRENT_SCHEMA_VERSION,
    PROJECT_APPLICATION_ID,
    InputFolderKind,
    InvalidProjectError,
    ProjectAlreadyExistsError,
    ProjectDatabase,
    ProjectStateError,
    UnsupportedProjectVersionError,
)


def test_create_project_writes_identified_versioned_sqlite_state(tmp_path: Path):
    project_path = tmp_path / "stroke-study.lysbbb"

    project = ProjectDatabase.create(project_path, name="Stroke study")
    snapshot = project.snapshot()

    assert snapshot.database_path == project_path.resolve()
    assert snapshot.name == "Stroke study"
    assert snapshot.project_id
    assert snapshot.schema_version == CURRENT_SCHEMA_VERSION
    assert snapshot.t1_input_folder is None
    assert snapshot.t2_input_folder is None

    with sqlite3.connect(project_path) as connection:
        assert connection.execute("PRAGMA application_id").fetchone()[0] == PROJECT_APPLICATION_ID
        assert connection.execute("PRAGMA user_version").fetchone()[0] == CURRENT_SCHEMA_VERSION
        assert connection.execute(
            "SELECT version FROM schema_migrations ORDER BY version"
        ).fetchall() == [(1,)]


def test_input_folders_persist_when_project_is_reopened(tmp_path: Path):
    project_path = tmp_path / "external-data.lysbbb"
    t1_folder = tmp_path / "mounted-drive" / "t1"
    t2_folder = tmp_path / "mounted-drive" / "t2w"
    t1_folder.mkdir(parents=True)
    t2_folder.mkdir()

    first_session = ProjectService()
    first_session.create_project(project_path, name="External drive study")
    first_session.set_input_folder(InputFolderKind.T1, t1_folder)
    first_session.set_input_folder(InputFolderKind.T2, t2_folder)
    first_session.close_project()

    reopened_session = ProjectService()
    reopened = reopened_session.open_project(project_path)

    assert reopened.t1_input_folder == t1_folder.resolve()
    assert reopened.t2_input_folder == t2_folder.resolve()
    assert reopened.input_folder_is_available(InputFolderKind.T1)
    assert reopened.input_folder_is_available(InputFolderKind.T2)


def test_reopen_preserves_temporarily_unavailable_drive_path(tmp_path: Path):
    project_path = tmp_path / "drive-reconnect.lysbbb"
    mounted_folder = tmp_path / "drive" / "t1"
    mounted_folder.mkdir(parents=True)
    service = ProjectService()
    service.create_project(project_path)
    service.set_input_folder(InputFolderKind.T1, mounted_folder)
    mounted_folder.rename(tmp_path / "disconnected-drive")

    reopened = ProjectDatabase.open(project_path).snapshot()

    assert reopened.t1_input_folder == mounted_folder.resolve()
    assert not reopened.input_folder_is_available(InputFolderKind.T1)


def test_project_creation_never_overwrites_an_existing_file(tmp_path: Path):
    project_path = tmp_path / "existing.lysbbb"
    project_path.write_text("keep me")

    with pytest.raises(ProjectAlreadyExistsError):
        ProjectDatabase.create(project_path, name="Would overwrite")

    assert project_path.read_text() == "keep me"


def test_open_rejects_an_unidentified_sqlite_database(tmp_path: Path):
    unrelated = tmp_path / "unrelated.sqlite"
    with sqlite3.connect(unrelated) as connection:
        connection.execute("CREATE TABLE notes(value TEXT)")

    with pytest.raises(InvalidProjectError, match="not a LYS BBB project"):
        ProjectDatabase.open(unrelated)


def test_open_rejects_schema_from_a_newer_application(tmp_path: Path):
    project_path = tmp_path / "future.lysbbb"
    ProjectDatabase.create(project_path, name="Future project")
    with sqlite3.connect(project_path) as connection:
        connection.execute(f"PRAGMA user_version = {CURRENT_SCHEMA_VERSION + 1}")

    with pytest.raises(UnsupportedProjectVersionError, match="supports up to"):
        ProjectDatabase.open(project_path)


def test_service_requires_an_open_project_and_a_real_input_folder(tmp_path: Path):
    service = ProjectService()
    with pytest.raises(ProjectStateError, match="Create or open"):
        service.set_input_folder(InputFolderKind.T1, tmp_path)

    service.create_project(tmp_path / "validation.lysbbb")
    not_a_folder = tmp_path / "scan.nii.gz"
    not_a_folder.touch()
    with pytest.raises(ProjectStateError, match="not a folder"):
        service.set_input_folder(InputFolderKind.T1, not_a_folder)
