"""Versioned SQLite repository for canonical desktop study roots."""

from __future__ import annotations

import json
import re
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any
from uuid import uuid4

from lys_bbb_app.domain.scan_import import (
    ScanConversionResult,
    ScanImportAssignment,
    ScanInputRecord,
)
from lys_bbb_app.domain.errors import StudyStateError
from lys_bbb_app.domain.study import (
    AuditEventRecord,
    BlindingState,
    CreateStudyRequest,
    CreateSubjectRequest,
    StudySnapshot,
    SubjectRecord,
)
from lys_bbb_app.infrastructure.database_support import (
    connect as _connect,
    insert_audit as _insert_audit,
    normalize_required as _normalize_required,
    single_study as _single_study,
    touch_study as _touch_study,
    utc_now as _utc_now,
)
from lys_bbb_app.infrastructure.scan_input_repository import (
    complete_scan_import as _complete_scan_import,
    fail_scan_import as _fail_scan_import,
    mark_scan_import_converting as _mark_scan_import_converting,
    scan_input_from_row as _scan_input_from_row,
    stage_scan_imports as _stage_scan_imports,
)
from lys_bbb_app.infrastructure.study_schema import (
    create_schema as _create_study_schema,
    migrate_schema as _migrate_study_schema,
)


STUDY_SCHEMA_VERSION = 4
STUDY_APPLICATION_ID = 0x4C595342  # "LYSB"
STUDY_MANIFEST_FORMAT = "lys-bbb-study"
STUDY_DATABASE_NAME = "project.sqlite"
STUDY_MANIFEST_NAME = "project.json"
STUDY_DIRECTORIES = ("imports", "work", "outputs", "reports", "exports", "logs")


class StudyAlreadyExistsError(StudyStateError):
    """Raised when study creation could overwrite an existing path."""


class InvalidStudyError(StudyStateError):
    """Raised when a path does not contain a valid LYS BBB study."""


class UnsupportedStudyVersionError(StudyStateError):
    """Raised when a study uses a newer or unsupported schema."""


class DuplicateSubjectError(StudyStateError):
    """Raised when a subject code is already present in the study."""


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
                if version > STUDY_SCHEMA_VERSION or version < 2:
                    raise UnsupportedStudyVersionError(
                        f"This study uses schema version {version}; this application "
                        f"supports versions 2 through {STUDY_SCHEMA_VERSION}."
                    )
                if version < STUDY_SCHEMA_VERSION:
                    _migrate_schema(connection, version)
                    connection.commit()
                row = connection.execute("SELECT id FROM studies").fetchone()
                if row is None or row["id"] != manifest["study_id"]:
                    raise InvalidStudyError(
                        "The project manifest and database identify different studies."
                    )
        except StudyStateError:
            raise
        except sqlite3.Error as exc:
            raise InvalidStudyError(f"The study database could not be read: {exc}") from exc

        if manifest.get("schema_version") != STUDY_SCHEMA_VERSION:
            with closing(_connect(database_path)) as connection:
                study = connection.execute(
                    "SELECT id, identifier, name FROM studies"
                ).fetchone()
            _write_manifest(
                root,
                study_id=study["id"],
                identifier=study["identifier"],
                name=study["name"],
            )

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
                        WHERE study_id = ? AND archived_at IS NULL
                        ORDER BY subject_code COLLATE NOCASE
                        """,
                        (study["id"],),
                    ).fetchall()
                )
                archived_subjects = tuple(
                    _subject_from_row(row)
                    for row in connection.execute(
                        """
                        SELECT id, subject_code, group_name, metadata_json,
                               expected_t1, expected_t2, created_at, updated_at
                        FROM subjects
                        WHERE study_id = ? AND archived_at IS NOT NULL
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
                scan_inputs = tuple(
                    _scan_input_from_row(row, self.root_path)
                    for row in connection.execute(
                        """
                        SELECT si.*, s.subject_code
                        FROM scan_inputs AS si
                        JOIN subjects AS s ON s.id = si.subject_id
                        WHERE si.study_id = ? AND s.archived_at IS NULL
                        ORDER BY s.subject_code COLLATE NOCASE, si.role, si.version DESC
                        """,
                        (study["id"],),
                    ).fetchall()
                )
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
            scan_inputs=scan_inputs,
            group_definitions=groups,
            archived_subjects=archived_subjects,
            mri_input_folder=folders.get("mri"),
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

    def rename_subject(
        self,
        subject_id: str,
        subject_code: str,
        *,
        actor: str,
    ) -> StudySnapshot:
        """Change the visible subject code while preserving its stable database ID."""

        normalized_subject_id = _normalize_required(subject_id, "Subject ID")
        normalized_code = _normalize_required(subject_code, "Subject name")
        normalized_actor = _normalize_required(actor, "Actor")
        now = _utc_now()
        try:
            with closing(_connect(self.database_path)) as connection:
                with connection:
                    study = _single_study(connection)
                    subject = connection.execute(
                        """
                        SELECT id, subject_code FROM subjects
                        WHERE id = ? AND study_id = ? AND archived_at IS NULL
                        """,
                        (normalized_subject_id, study["id"]),
                    ).fetchone()
                    if subject is None:
                        raise StudyStateError("The selected subject is not active.")
                    duplicate = connection.execute(
                        """
                        SELECT id FROM subjects
                        WHERE study_id = ? AND subject_code = ? COLLATE NOCASE AND id != ?
                        """,
                        (study["id"], normalized_code, normalized_subject_id),
                    ).fetchone()
                    if duplicate is not None:
                        raise DuplicateSubjectError(
                            f"Subject name already exists in this study: {normalized_code}"
                        )
                    if subject["subject_code"] == normalized_code:
                        return self.snapshot()
                    connection.execute(
                        """
                        UPDATE subjects SET subject_code = ?, updated_at = ?
                        WHERE id = ?
                        """,
                        (normalized_code, now, normalized_subject_id),
                    )
                    _touch_study(connection, study["id"], now)
                    _insert_audit(
                        connection,
                        study_id=study["id"],
                        subject_id=normalized_subject_id,
                        event_type="SUBJECT_RENAMED",
                        actor=normalized_actor,
                        details={
                            "previous_subject_code": subject["subject_code"],
                            "subject_code": normalized_code,
                            "managed_files_moved": False,
                        },
                        created_at=now,
                    )
        except StudyStateError:
            raise
        except sqlite3.Error as exc:
            raise StudyStateError(f"Could not rename the subject: {exc}") from exc
        return self.snapshot()

    def archive_subject(self, subject_id: str, *, actor: str) -> StudySnapshot:
        """Hide a subject while preserving its inputs, outputs, and audit history."""

        normalized_subject_id = _normalize_required(subject_id, "Subject ID")
        normalized_actor = _normalize_required(actor, "Actor")
        now = _utc_now()
        try:
            with closing(_connect(self.database_path)) as connection:
                with connection:
                    study = _single_study(connection)
                    subject = connection.execute(
                        """
                        SELECT id, subject_code, archived_at FROM subjects
                        WHERE id = ? AND study_id = ?
                        """,
                        (normalized_subject_id, study["id"]),
                    ).fetchone()
                    if subject is None:
                        raise StudyStateError("The selected subject does not exist.")
                    if subject["archived_at"] is not None:
                        raise StudyStateError("The selected subject is already removed.")
                    running = connection.execute(
                        """
                        SELECT COUNT(*) FROM scan_inputs
                        WHERE subject_id = ? AND state IN ('QUEUED', 'CONVERTING')
                        """,
                        (normalized_subject_id,),
                    ).fetchone()[0]
                    if running:
                        raise StudyStateError(
                            "Wait for the subject's MRI import to finish before removing it."
                        )
                    retained_inputs = connection.execute(
                        "SELECT COUNT(*) FROM scan_inputs WHERE subject_id = ?",
                        (normalized_subject_id,),
                    ).fetchone()[0]
                    connection.execute(
                        """
                        UPDATE subjects
                        SET archived_at = ?, archived_by = ?, updated_at = ?
                        WHERE id = ?
                        """,
                        (now, normalized_actor, now, normalized_subject_id),
                    )
                    _touch_study(connection, study["id"], now)
                    _insert_audit(
                        connection,
                        study_id=study["id"],
                        subject_id=normalized_subject_id,
                        event_type="SUBJECT_REMOVED",
                        actor=normalized_actor,
                        details={
                            "subject_code": subject["subject_code"],
                            "retained_scan_inputs": retained_inputs,
                            "source_data_modified": False,
                        },
                        created_at=now,
                    )
        except StudyStateError:
            raise
        except sqlite3.Error as exc:
            raise StudyStateError(f"Could not remove the subject: {exc}") from exc
        return self.snapshot()

    def restore_subject(self, subject_id: str, *, actor: str) -> StudySnapshot:
        """Return an archived subject and its retained inputs to active worklists."""

        normalized_subject_id = _normalize_required(subject_id, "Subject ID")
        normalized_actor = _normalize_required(actor, "Actor")
        now = _utc_now()
        try:
            with closing(_connect(self.database_path)) as connection:
                with connection:
                    study = _single_study(connection)
                    subject = connection.execute(
                        """
                        SELECT id, subject_code, archived_at FROM subjects
                        WHERE id = ? AND study_id = ?
                        """,
                        (normalized_subject_id, study["id"]),
                    ).fetchone()
                    if subject is None:
                        raise StudyStateError("The selected subject does not exist.")
                    if subject["archived_at"] is None:
                        raise StudyStateError("The selected subject is already active.")
                    connection.execute(
                        """
                        UPDATE subjects
                        SET archived_at = NULL, archived_by = NULL, updated_at = ?
                        WHERE id = ?
                        """,
                        (now, normalized_subject_id),
                    )
                    _touch_study(connection, study["id"], now)
                    _insert_audit(
                        connection,
                        study_id=study["id"],
                        subject_id=normalized_subject_id,
                        event_type="SUBJECT_RESTORED",
                        actor=normalized_actor,
                        details={"subject_code": subject["subject_code"]},
                        created_at=now,
                    )
        except StudyStateError:
            raise
        except sqlite3.Error as exc:
            raise StudyStateError(f"Could not restore the subject: {exc}") from exc
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
        if kind not in {"mri", "t1", "t2"}:
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

    def stage_scan_imports(
        self,
        assignments: tuple[ScanImportAssignment, ...],
        *,
        actor: str,
    ) -> tuple[ScanInputRecord, ...]:
        return _stage_scan_imports(self, assignments, actor=actor)

    def mark_scan_import_converting(self, record_id: str) -> None:
        _mark_scan_import_converting(self, record_id)

    def complete_scan_import(
        self,
        record_id: str,
        result: ScanConversionResult,
        *,
        actor: str,
    ) -> None:
        _complete_scan_import(self, record_id, result, actor=actor)

    def fail_scan_import(self, record_id: str, error: str, *, actor: str) -> None:
        _fail_scan_import(self, record_id, error, actor=actor)

    def record_audit_event(
        self,
        event_type: str,
        *,
        actor: str,
        details: dict[str, Any] | None = None,
        subject_id: str | None = None,
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
                        subject_id=subject_id,
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
    _create_study_schema(
        connection,
        schema_version=STUDY_SCHEMA_VERSION,
        applied_at=_utc_now(),
    )


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
    version = manifest.get("schema_version")
    if not isinstance(version, int) or version > STUDY_SCHEMA_VERSION or version < 2:
        raise UnsupportedStudyVersionError(
            f"The study manifest uses schema version {version}; this application "
            f"supports versions 2 through {STUDY_SCHEMA_VERSION}."
        )
    if manifest.get("database") != STUDY_DATABASE_NAME or not manifest.get("study_id"):
        raise InvalidStudyError("The study manifest is incomplete.")
    return manifest


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


def _migrate_schema(connection: sqlite3.Connection, from_version: int) -> None:
    try:
        _migrate_study_schema(
            connection,
            from_version,
            target_version=STUDY_SCHEMA_VERSION,
            applied_at=_utc_now(),
        )
    except ValueError as exc:
        raise UnsupportedStudyVersionError(str(exc)) from exc


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
