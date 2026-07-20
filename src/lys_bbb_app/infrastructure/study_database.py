"""Versioned SQLite repository for canonical desktop study roots."""

from __future__ import annotations

import json
import re
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from lys_bbb_app.domain.study import (
    AuditEventRecord,
    BlindingState,
    CreateStudyRequest,
    CreateSubjectRequest,
    StudySnapshot,
    SubjectRecord,
)


STUDY_SCHEMA_VERSION = 2
STUDY_APPLICATION_ID = 0x4C595342  # "LYSB"
STUDY_MANIFEST_FORMAT = "lys-bbb-study"
STUDY_DATABASE_NAME = "project.sqlite"
STUDY_MANIFEST_NAME = "project.json"
STUDY_DIRECTORIES = ("imports", "work", "outputs", "reports", "exports", "logs")


class StudyStateError(RuntimeError):
    """Base error for persistent study state."""


class StudyAlreadyExistsError(StudyStateError):
    """Raised when study creation could overwrite an existing path."""


class InvalidStudyError(StudyStateError):
    """Raised when a path does not contain a valid LYS BBB study."""


class UnsupportedStudyVersionError(StudyStateError):
    """Raised when a study uses a newer or unsupported schema."""


class DuplicateSubjectError(StudyStateError):
    """Raised when a subject code is already present in the study."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _connect(database_path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(database_path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def _normalize_required(value: str, field_name: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise StudyStateError(f"{field_name} cannot be empty.")
    return normalized


def _normalize_optional(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


def _normalize_identifier(identifier: str) -> str:
    normalized = _normalize_required(identifier, "Study identifier")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", normalized):
        raise StudyStateError(
            "Study identifier may contain letters, numbers, periods, underscores, "
            "and hyphens, and must start with a letter or number."
        )
    return normalized


class StudyRepository:
    """Create, validate, read, and update one canonical study root."""

    def __init__(self, root_path: Path):
        self.root_path = root_path
        self.database_path = root_path / STUDY_DATABASE_NAME

    @classmethod
    def create(cls, request: CreateStudyRequest) -> StudyRepository:
        root = request.root_path.expanduser().resolve()
        name = _normalize_required(request.name, "Study name")
        identifier = _normalize_identifier(request.identifier)
        actor = _normalize_required(request.actor, "Actor")
        if root.exists():
            raise StudyAlreadyExistsError(
                f"The study directory already exists and will not be overwritten: {root}"
            )
        if not root.parent.is_dir():
            raise StudyStateError(f"The parent directory does not exist: {root.parent}")

        root.mkdir()
        for directory in STUDY_DIRECTORIES:
            (root / directory).mkdir()

        repository = cls(root)
        study_id = str(uuid4())
        now = _utc_now()
        connection: sqlite3.Connection | None = None
        try:
            connection = _connect(repository.database_path)
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(f"PRAGMA application_id = {STUDY_APPLICATION_ID}")
            _create_schema(connection)
            connection.execute(
                """
                INSERT INTO studies(
                    id, identifier, name, description, blinding_state,
                    created_at, updated_at, unblinded_at, unblinded_by
                ) VALUES (?, ?, ?, ?, ?, ?, ?, NULL, NULL)
                """,
                (
                    study_id,
                    identifier,
                    name,
                    _normalize_optional(request.description),
                    (
                        BlindingState.BLINDED.value
                        if request.blinded
                        else BlindingState.UNBLINDED.value
                    ),
                    now,
                    now,
                ),
            )
            for position, group_name in enumerate(request.group_definitions):
                normalized_group = _normalize_optional(group_name)
                if normalized_group is not None:
                    connection.execute(
                        """
                        INSERT OR IGNORE INTO study_groups(study_id, name, sort_order)
                        VALUES (?, ?, ?)
                        """,
                        (study_id, normalized_group, position),
                    )
            _insert_audit(
                connection,
                study_id=study_id,
                event_type="STUDY_CREATED",
                actor=actor,
                details={
                    "identifier": identifier,
                    "blinding_state": (
                        BlindingState.BLINDED.value
                        if request.blinded
                        else BlindingState.UNBLINDED.value
                    ),
                },
                created_at=now,
            )
            connection.commit()
            _write_manifest(
                root,
                study_id=study_id,
                identifier=identifier,
                name=name,
            )
        except Exception as exc:
            if connection is not None:
                connection.rollback()
            if isinstance(exc, StudyStateError):
                raise
            raise StudyStateError(f"Could not create study at {root}: {exc}") from exc
        finally:
            if connection is not None:
                connection.close()

        repository.snapshot()
        return repository

    @classmethod
    def open(cls, path: Path | str) -> StudyRepository:
        root = _resolve_study_root(Path(path))
        manifest = _read_manifest(root)
        database_path = root / STUDY_DATABASE_NAME
        if not database_path.is_file():
            raise InvalidStudyError(
                f"The study database is missing: {database_path}"
            )

        try:
            with closing(_connect(database_path)) as connection:
                application_id = int(
                    connection.execute("PRAGMA application_id").fetchone()[0]
                )
                version = int(connection.execute("PRAGMA user_version").fetchone()[0])
                if application_id != STUDY_APPLICATION_ID:
                    raise InvalidStudyError(
                        "The selected folder does not contain a LYS BBB study database."
                    )
                if version != STUDY_SCHEMA_VERSION:
                    raise UnsupportedStudyVersionError(
                        f"This study uses schema version {version}; this application "
                        f"requires version {STUDY_SCHEMA_VERSION}."
                    )
                row = connection.execute("SELECT id FROM studies").fetchone()
                if row is None or row["id"] != manifest["study_id"]:
                    raise InvalidStudyError(
                        "The project manifest and database identify different studies."
                    )
        except StudyStateError:
            raise
        except sqlite3.Error as exc:
            raise InvalidStudyError(f"The study database could not be read: {exc}") from exc

        repository = cls(root)
        repository.snapshot()
        return repository

    def snapshot(self) -> StudySnapshot:
        try:
            with closing(_connect(self.database_path)) as connection:
                study = connection.execute(
                    """
                    SELECT id, identifier, name, description, blinding_state,
                           created_at, updated_at, unblinded_at, unblinded_by
                    FROM studies
                    """
                ).fetchone()
                if study is None:
                    raise InvalidStudyError("The study database has no study record.")
                subjects = tuple(
                    _subject_from_row(row)
                    for row in connection.execute(
                        """
                        SELECT id, subject_code, group_name, metadata_json,
                               expected_t1, expected_t2, created_at, updated_at
                        FROM subjects
                        WHERE study_id = ?
                        ORDER BY subject_code COLLATE NOCASE
                        """,
                        (study["id"],),
                    ).fetchall()
                )
                groups = tuple(
                    row["name"]
                    for row in connection.execute(
                        """
                        SELECT name FROM study_groups
                        WHERE study_id = ?
                        ORDER BY sort_order, name COLLATE NOCASE
                        """,
                        (study["id"],),
                    ).fetchall()
                )
                folders = {
                    row["kind"]: Path(row["path"])
                    for row in connection.execute(
                        "SELECT kind, path FROM input_folders WHERE study_id = ?",
                        (study["id"],),
                    ).fetchall()
                }
        except StudyStateError:
            raise
        except (sqlite3.Error, json.JSONDecodeError) as exc:
            raise InvalidStudyError(f"Could not read study state: {exc}") from exc

        return StudySnapshot(
            id=study["id"],
            identifier=study["identifier"],
            name=study["name"],
            description=study["description"],
            root_path=self.root_path,
            database_path=self.database_path,
            schema_version=STUDY_SCHEMA_VERSION,
            blinding_state=BlindingState(study["blinding_state"]),
            created_at=study["created_at"],
            updated_at=study["updated_at"],
            unblinded_at=study["unblinded_at"],
            unblinded_by=study["unblinded_by"],
            subjects=subjects,
            group_definitions=groups,
            t1_input_folder=folders.get("t1"),
            t2_input_folder=folders.get("t2"),
        )

    def add_subject(self, request: CreateSubjectRequest) -> StudySnapshot:
        subject_code = _normalize_required(request.subject_code, "Subject ID")
        actor = _normalize_required(request.actor, "Actor")
        if not request.expected_t1 and not request.expected_t2:
            raise StudyStateError("Select at least one expected workflow for the subject.")
        group_name = _normalize_optional(request.group_name)
        now = _utc_now()
        subject_id = str(uuid4())

        try:
            with closing(_connect(self.database_path)) as connection:
                with connection:
                    study = _single_study(connection)
                    if (
                        study["blinding_state"] == BlindingState.BLINDED.value
                        and group_name is not None
                    ):
                        raise StudyStateError(
                            "A group cannot be assigned while the study is blinded."
                        )
                    connection.execute(
                        """
                        INSERT INTO subjects(
                            id, study_id, subject_code, group_name, metadata_json,
                            expected_t1, expected_t2, created_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            subject_id,
                            study["id"],
                            subject_code,
                            group_name,
                            json.dumps(request.metadata or {}, sort_keys=True),
                            int(request.expected_t1),
                            int(request.expected_t2),
                            now,
                            now,
                        ),
                    )
                    if group_name is not None:
                        _ensure_group(connection, study["id"], group_name)
                    _touch_study(connection, study["id"], now)
                    _insert_audit(
                        connection,
                        study_id=study["id"],
                        subject_id=subject_id,
                        event_type="SUBJECT_CREATED",
                        actor=actor,
                        details={
                            "subject_code": subject_code,
                            "expected_t1": request.expected_t1,
                            "expected_t2": request.expected_t2,
                        },
                        created_at=now,
                    )
        except sqlite3.IntegrityError as exc:
            if "subjects.study_id, subjects.subject_code" in str(exc):
                raise DuplicateSubjectError(
                    f"Subject ID already exists in this study: {subject_code}"
                ) from exc
            raise StudyStateError(f"Could not add the subject: {exc}") from exc
        except sqlite3.Error as exc:
            raise StudyStateError(f"Could not add the subject: {exc}") from exc
        return self.snapshot()

    def unblind(self, *, actor: str) -> StudySnapshot:
        reviewer = _normalize_required(actor, "Reviewer identity")
        now = _utc_now()
        try:
            with closing(_connect(self.database_path)) as connection:
                with connection:
                    study = _single_study(connection)
                    if study["blinding_state"] != BlindingState.UNBLINDED.value:
                        connection.execute(
                            """
                            UPDATE studies
                            SET blinding_state = ?, unblinded_at = ?, unblinded_by = ?,
                                updated_at = ?
                            WHERE id = ?
                            """,
                            (
                                BlindingState.UNBLINDED.value,
                                now,
                                reviewer,
                                now,
                                study["id"],
                            ),
                        )
                        _insert_audit(
                            connection,
                            study_id=study["id"],
                            event_type="STUDY_UNBLINDED",
                            actor=reviewer,
                            details={"previous_state": BlindingState.BLINDED.value},
                            created_at=now,
                        )
        except sqlite3.Error as exc:
            raise StudyStateError(f"Could not unblind the study: {exc}") from exc
        return self.snapshot()

    def assign_groups(
        self,
        assignments: dict[str, str | None],
        *,
        actor: str,
    ) -> StudySnapshot:
        reviewer = _normalize_required(actor, "Reviewer identity")
        now = _utc_now()
        try:
            with closing(_connect(self.database_path)) as connection:
                with connection:
                    study = _single_study(connection)
                    if study["blinding_state"] != BlindingState.UNBLINDED.value:
                        raise StudyStateError(
                            "Unblind the study before assigning experimental groups."
                        )
                    rows = connection.execute(
                        "SELECT id, subject_code FROM subjects WHERE study_id = ?",
                        (study["id"],),
                    ).fetchall()
                    subject_ids = {row["id"] for row in rows}
                    unknown = sorted(set(assignments) - subject_ids)
                    if unknown:
                        raise StudyStateError(
                            "Group assignments contain unknown subject IDs: "
                            + ", ".join(unknown)
                        )
                    assigned_count = 0
                    for subject_id, group_name in assignments.items():
                        normalized_group = _normalize_optional(group_name)
                        connection.execute(
                            """
                            UPDATE subjects
                            SET group_name = ?, updated_at = ?
                            WHERE id = ? AND study_id = ?
                            """,
                            (normalized_group, now, subject_id, study["id"]),
                        )
                        if normalized_group is not None:
                            assigned_count += 1
                            _ensure_group(connection, study["id"], normalized_group)
                    _touch_study(connection, study["id"], now)
                    _insert_audit(
                        connection,
                        study_id=study["id"],
                        event_type="SUBJECT_GROUPS_ASSIGNED",
                        actor=reviewer,
                        details={
                            "subjects_updated": len(assignments),
                            "subjects_assigned": assigned_count,
                            "subjects_unassigned": len(assignments) - assigned_count,
                        },
                        created_at=now,
                    )
        except StudyStateError:
            raise
        except sqlite3.Error as exc:
            raise StudyStateError(f"Could not assign subject groups: {exc}") from exc
        return self.snapshot()

    def set_input_folder_reference(
        self,
        kind: str,
        path: Path | str,
        *,
        actor: str = "Application",
        require_available: bool = False,
    ) -> StudySnapshot:
        if kind not in {"t1", "t2"}:
            raise StudyStateError(f"Unsupported input-folder kind: {kind}")
        referenced_path = Path(path).expanduser().resolve()
        normalized_actor = _normalize_required(actor, "Actor")
        if require_available and not referenced_path.is_dir():
            raise StudyStateError(
                f"The selected input folder is unavailable: {referenced_path}"
            )
        now = _utc_now()
        try:
            with closing(_connect(self.database_path)) as connection:
                with connection:
                    study = _single_study(connection)
                    connection.execute(
                        """
                        INSERT INTO input_folders(study_id, kind, path, selected_at)
                        VALUES (?, ?, ?, ?)
                        ON CONFLICT(study_id, kind) DO UPDATE SET
                            path = excluded.path,
                            selected_at = excluded.selected_at
                        """,
                        (study["id"], kind, str(referenced_path), now),
                    )
                    _touch_study(connection, study["id"], now)
                    _insert_audit(
                        connection,
                        study_id=study["id"],
                        event_type="INPUT_FOLDER_SELECTED",
                        actor=normalized_actor,
                        details={
                            "kind": kind,
                            "path": str(referenced_path),
                            "available": referenced_path.is_dir(),
                        },
                        created_at=now,
                    )
        except sqlite3.Error as exc:
            raise StudyStateError(f"Could not store the input-folder reference: {exc}") from exc
        return self.snapshot()

    def record_audit_event(
        self,
        event_type: str,
        *,
        actor: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        normalized_type = _normalize_required(event_type, "Audit event type")
        normalized_actor = _normalize_required(actor, "Actor")
        try:
            with closing(_connect(self.database_path)) as connection:
                with connection:
                    study = _single_study(connection)
                    _insert_audit(
                        connection,
                        study_id=study["id"],
                        event_type=normalized_type,
                        actor=normalized_actor,
                        details=details or {},
                    )
        except sqlite3.Error as exc:
            raise StudyStateError(f"Could not record the audit event: {exc}") from exc

    def list_audit_events(self, *, limit: int = 500) -> tuple[AuditEventRecord, ...]:
        try:
            with closing(_connect(self.database_path)) as connection:
                study = _single_study(connection)
                rows = connection.execute(
                    """
                    SELECT id, event_type, actor, created_at, subject_id, details_json
                    FROM audit_events
                    WHERE study_id = ?
                    ORDER BY created_at DESC, id DESC
                    LIMIT ?
                    """,
                    (study["id"], max(1, limit)),
                ).fetchall()
        except sqlite3.Error as exc:
            raise StudyStateError(f"Could not read audit history: {exc}") from exc
        return tuple(
            AuditEventRecord(
                id=row["id"],
                event_type=row["event_type"],
                actor=row["actor"],
                created_at=row["created_at"],
                subject_id=row["subject_id"],
                details=json.loads(row["details_json"]),
            )
            for row in rows
        )


def _create_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE schema_migrations (
            version INTEGER PRIMARY KEY,
            applied_at TEXT NOT NULL
        );
        CREATE TABLE studies (
            id TEXT PRIMARY KEY,
            identifier TEXT NOT NULL UNIQUE,
            name TEXT NOT NULL CHECK (length(trim(name)) > 0),
            description TEXT,
            blinding_state TEXT NOT NULL CHECK (blinding_state IN ('BLINDED', 'UNBLINDED')),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            unblinded_at TEXT,
            unblinded_by TEXT
        );
        CREATE TABLE subjects (
            id TEXT PRIMARY KEY,
            study_id TEXT NOT NULL REFERENCES studies(id) ON DELETE CASCADE,
            subject_code TEXT NOT NULL CHECK (length(trim(subject_code)) > 0),
            group_name TEXT,
            metadata_json TEXT NOT NULL DEFAULT '{}',
            expected_t1 INTEGER NOT NULL CHECK (expected_t1 IN (0, 1)),
            expected_t2 INTEGER NOT NULL CHECK (expected_t2 IN (0, 1)),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(study_id, subject_code)
        );
        CREATE TABLE study_groups (
            study_id TEXT NOT NULL REFERENCES studies(id) ON DELETE CASCADE,
            name TEXT NOT NULL CHECK (length(trim(name)) > 0),
            sort_order INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY(study_id, name)
        );
        CREATE TABLE input_folders (
            study_id TEXT NOT NULL REFERENCES studies(id) ON DELETE CASCADE,
            kind TEXT NOT NULL CHECK (kind IN ('t1', 't2')),
            path TEXT NOT NULL CHECK (length(trim(path)) > 0),
            selected_at TEXT NOT NULL,
            PRIMARY KEY(study_id, kind)
        );
        CREATE TABLE audit_events (
            id TEXT PRIMARY KEY,
            study_id TEXT NOT NULL REFERENCES studies(id) ON DELETE CASCADE,
            subject_id TEXT REFERENCES subjects(id) ON DELETE SET NULL,
            event_type TEXT NOT NULL,
            actor TEXT NOT NULL,
            created_at TEXT NOT NULL,
            details_json TEXT NOT NULL DEFAULT '{}'
        );
        CREATE INDEX idx_subjects_study_code ON subjects(study_id, subject_code);
        CREATE INDEX idx_subjects_study_group ON subjects(study_id, group_name);
        CREATE INDEX idx_audit_events_study_time ON audit_events(study_id, created_at DESC);
        """
    )
    connection.execute(
        "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
        (STUDY_SCHEMA_VERSION, _utc_now()),
    )
    connection.execute(f"PRAGMA user_version = {STUDY_SCHEMA_VERSION}")


def _resolve_study_root(path: Path) -> Path:
    resolved = path.expanduser().resolve()
    if resolved.is_dir():
        return resolved
    if resolved.is_file() and resolved.name in {STUDY_DATABASE_NAME, STUDY_MANIFEST_NAME}:
        return resolved.parent
    raise InvalidStudyError(
        "Select a study directory, project.json, or project.sqlite file."
    )


def _write_manifest(root: Path, *, study_id: str, identifier: str, name: str) -> None:
    payload = {
        "format": STUDY_MANIFEST_FORMAT,
        "schema_version": STUDY_SCHEMA_VERSION,
        "study_id": study_id,
        "study_identifier": identifier,
        "study_name": name,
        "database": STUDY_DATABASE_NAME,
    }
    temporary = root / f"{STUDY_MANIFEST_NAME}.tmp"
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    temporary.replace(root / STUDY_MANIFEST_NAME)


def _read_manifest(root: Path) -> dict[str, Any]:
    path = root / STUDY_MANIFEST_NAME
    if not path.is_file():
        raise InvalidStudyError(f"The study manifest is missing: {path}")
    try:
        manifest = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise InvalidStudyError(f"The study manifest could not be read: {exc}") from exc
    if manifest.get("format") != STUDY_MANIFEST_FORMAT:
        raise InvalidStudyError("The selected folder is not a LYS BBB study.")
    if manifest.get("schema_version") != STUDY_SCHEMA_VERSION:
        raise UnsupportedStudyVersionError(
            f"The study manifest uses schema version {manifest.get('schema_version')}; "
            f"this application requires version {STUDY_SCHEMA_VERSION}."
        )
    if manifest.get("database") != STUDY_DATABASE_NAME or not manifest.get("study_id"):
        raise InvalidStudyError("The study manifest is incomplete.")
    return manifest


def _single_study(connection: sqlite3.Connection) -> sqlite3.Row:
    row = connection.execute(
        "SELECT id, blinding_state FROM studies"
    ).fetchone()
    if row is None:
        raise InvalidStudyError("The study database has no study record.")
    return row


def _subject_from_row(row: sqlite3.Row) -> SubjectRecord:
    return SubjectRecord(
        id=row["id"],
        subject_code=row["subject_code"],
        group_name=row["group_name"],
        metadata=json.loads(row["metadata_json"]),
        expected_t1=bool(row["expected_t1"]),
        expected_t2=bool(row["expected_t2"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _insert_audit(
    connection: sqlite3.Connection,
    *,
    study_id: str,
    event_type: str,
    actor: str,
    details: dict[str, Any],
    subject_id: str | None = None,
    created_at: str | None = None,
) -> None:
    connection.execute(
        """
        INSERT INTO audit_events(
            id, study_id, subject_id, event_type, actor, created_at, details_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            str(uuid4()),
            study_id,
            subject_id,
            event_type,
            actor,
            created_at or _utc_now(),
            json.dumps(details, sort_keys=True),
        ),
    )


def _touch_study(connection: sqlite3.Connection, study_id: str, timestamp: str) -> None:
    connection.execute(
        "UPDATE studies SET updated_at = ? WHERE id = ?",
        (timestamp, study_id),
    )


def _ensure_group(connection: sqlite3.Connection, study_id: str, group_name: str) -> None:
    next_order = connection.execute(
        "SELECT COALESCE(MAX(sort_order), -1) + 1 FROM study_groups WHERE study_id = ?",
        (study_id,),
    ).fetchone()[0]
    connection.execute(
        """
        INSERT OR IGNORE INTO study_groups(study_id, name, sort_order)
        VALUES (?, ?, ?)
        """,
        (study_id, group_name, next_order),
    )
