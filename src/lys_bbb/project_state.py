"""Versioned SQLite state for a LYS BBB desktop project.

This module deliberately has no Qt imports.  It owns only durable application state;
scientific processing modules consume paths and metadata through separate services.
"""

from __future__ import annotations

import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from uuid import uuid4


CURRENT_SCHEMA_VERSION = 1
PROJECT_APPLICATION_ID = 0x4C595342  # "LYSB" in a SQLite application_id.
PROJECT_FILE_SUFFIX = ".lysbbb"


class ProjectStateError(RuntimeError):
    """Base error for project creation, opening, and updates."""


class ProjectAlreadyExistsError(ProjectStateError):
    """Raised when project creation would overwrite an existing file."""


class InvalidProjectError(ProjectStateError):
    """Raised when a file is not a valid LYS BBB project database."""


class UnsupportedProjectVersionError(ProjectStateError):
    """Raised when a project was created by a newer application version."""


class InputFolderKind(str, Enum):
    """Input locations understood by the desktop foundation."""

    T1 = "t1"
    T2 = "t2"


@dataclass(frozen=True)
class ProjectSnapshot:
    """Small immutable view of the current project state."""

    database_path: Path
    project_id: str
    name: str
    created_at: str
    updated_at: str
    schema_version: int
    t1_input_folder: Path | None = None
    t2_input_folder: Path | None = None

    def input_folder(self, kind: InputFolderKind | str) -> Path | None:
        folder_kind = InputFolderKind(kind)
        if folder_kind is InputFolderKind.T1:
            return self.t1_input_folder
        return self.t2_input_folder

    def input_folder_is_available(self, kind: InputFolderKind | str) -> bool:
        folder = self.input_folder(kind)
        return folder is not None and folder.is_dir()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _connect(database_path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(database_path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def _pragma_int(connection: sqlite3.Connection, name: str) -> int:
    row = connection.execute(f"PRAGMA {name}").fetchone()
    return int(row[0])


def _apply_migrations(connection: sqlite3.Connection) -> None:
    version = _pragma_int(connection, "user_version")
    if version > CURRENT_SCHEMA_VERSION:
        raise UnsupportedProjectVersionError(
            f"This project uses schema version {version}; this application supports "
            f"up to version {CURRENT_SCHEMA_VERSION}."
        )

    if version < 1:
        connection.execute(
            """
            CREATE TABLE schema_migrations (
                version INTEGER PRIMARY KEY,
                applied_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE project_info (
                singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
                project_id TEXT NOT NULL UNIQUE,
                name TEXT NOT NULL CHECK (length(trim(name)) > 0),
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE input_folders (
                kind TEXT PRIMARY KEY CHECK (kind IN ('t1', 't2')),
                path TEXT NOT NULL CHECK (length(trim(path)) > 0),
                selected_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
            (1, _utc_now()),
        )
        connection.execute("PRAGMA user_version = 1")


class ProjectDatabase:
    """Create, validate, migrate, and update one project database."""

    def __init__(self, database_path: Path):
        self.database_path = database_path

    @classmethod
    def create(cls, database_path: Path | str, *, name: str) -> ProjectDatabase:
        path = Path(database_path).expanduser().resolve()
        project_name = name.strip()
        if not project_name:
            raise ProjectStateError("Project name cannot be empty.")
        if path.exists():
            raise ProjectAlreadyExistsError(f"A file already exists at {path}.")
        if not path.parent.is_dir():
            raise ProjectStateError(f"The project folder does not exist: {path.parent}")

        connection: sqlite3.Connection | None = None
        try:
            connection = _connect(path)
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(f"PRAGMA application_id = {PROJECT_APPLICATION_ID}")
            _apply_migrations(connection)
            now = _utc_now()
            connection.execute(
                """
                INSERT INTO project_info(
                    singleton, project_id, name, created_at, updated_at
                ) VALUES (1, ?, ?, ?, ?)
                """,
                (str(uuid4()), project_name, now, now),
            )
            connection.commit()
        except Exception as exc:
            if connection is not None:
                connection.rollback()
            path.unlink(missing_ok=True)
            if isinstance(exc, ProjectStateError):
                raise
            raise ProjectStateError(f"Could not create project at {path}: {exc}") from exc
        finally:
            if connection is not None:
                connection.close()

        project = cls(path)
        project.snapshot()  # Validate the committed file before returning it.
        return project

    @classmethod
    def open(cls, database_path: Path | str) -> ProjectDatabase:
        path = Path(database_path).expanduser().resolve()
        if not path.is_file():
            raise InvalidProjectError(f"Project file does not exist: {path}")

        connection: sqlite3.Connection | None = None
        try:
            connection = _connect(path)
            application_id = _pragma_int(connection, "application_id")
            if application_id != PROJECT_APPLICATION_ID:
                raise InvalidProjectError(
                    "The selected file is not a LYS BBB project database."
                )
            connection.execute("BEGIN IMMEDIATE")
            _apply_migrations(connection)
            connection.commit()
            _read_snapshot(connection, path)
        except ProjectStateError:
            if connection is not None:
                connection.rollback()
            raise
        except sqlite3.Error as exc:
            if connection is not None:
                connection.rollback()
            raise InvalidProjectError(
                f"The selected project database could not be read: {exc}"
            ) from exc
        finally:
            if connection is not None:
                connection.close()
        return cls(path)

    def snapshot(self) -> ProjectSnapshot:
        try:
            with closing(_connect(self.database_path)) as connection:
                application_id = _pragma_int(connection, "application_id")
                if application_id != PROJECT_APPLICATION_ID:
                    raise InvalidProjectError(
                        "The selected file is not a LYS BBB project database."
                    )
                return _read_snapshot(connection, self.database_path)
        except ProjectStateError:
            raise
        except sqlite3.Error as exc:
            raise InvalidProjectError(f"Could not read project state: {exc}") from exc

    def set_input_folder(
        self,
        kind: InputFolderKind | str,
        folder: Path | str,
    ) -> ProjectSnapshot:
        folder_kind = InputFolderKind(kind)
        try:
            selected_folder = Path(folder).expanduser().resolve(strict=True)
        except OSError as exc:
            raise ProjectStateError(
                f"The selected input folder is unavailable: {folder}"
            ) from exc
        if not selected_folder.is_dir():
            raise ProjectStateError(
                f"The selected input path is not a folder: {selected_folder}"
            )

        now = _utc_now()
        try:
            with closing(_connect(self.database_path)) as connection:
                with connection:
                    connection.execute(
                        """
                        INSERT INTO input_folders(kind, path, selected_at)
                        VALUES (?, ?, ?)
                        ON CONFLICT(kind) DO UPDATE SET
                            path = excluded.path,
                            selected_at = excluded.selected_at
                        """,
                        (folder_kind.value, str(selected_folder), now),
                    )
                    connection.execute(
                        "UPDATE project_info SET updated_at = ? WHERE singleton = 1",
                        (now,),
                    )
        except sqlite3.Error as exc:
            raise ProjectStateError(f"Could not save the input folder: {exc}") from exc
        return self.snapshot()


def _read_snapshot(
    connection: sqlite3.Connection,
    database_path: Path,
) -> ProjectSnapshot:
    try:
        info = connection.execute(
            """
            SELECT project_id, name, created_at, updated_at
            FROM project_info
            WHERE singleton = 1
            """
        ).fetchone()
        if info is None:
            raise InvalidProjectError("The project database has no project metadata.")
        folder_rows = connection.execute(
            "SELECT kind, path FROM input_folders"
        ).fetchall()
    except sqlite3.Error as exc:
        raise InvalidProjectError(f"The project schema is incomplete: {exc}") from exc

    folders = {row["kind"]: Path(row["path"]) for row in folder_rows}
    return ProjectSnapshot(
        database_path=database_path,
        project_id=info["project_id"],
        name=info["name"],
        created_at=info["created_at"],
        updated_at=info["updated_at"],
        schema_version=_pragma_int(connection, "user_version"),
        t1_input_folder=folders.get(InputFolderKind.T1.value),
        t2_input_folder=folders.get(InputFolderKind.T2.value),
    )
