"""Persistence operations for subject-owned, versioned MRI inputs."""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Protocol
from uuid import uuid4

from lys_bbb_app.domain.scan_import import (
    ImportConfidence,
    OrientationPolicy,
    ScanConversionResult,
    ScanImportAssignment,
    ScanImportState,
    ScanInputRecord,
    ScanRole,
    SourceFormat,
)
from lys_bbb_app.domain.errors import StudyStateError
from lys_bbb_app.infrastructure.database_support import (
    connect as _connect,
    insert_audit as _insert_audit,
    normalize_required as _normalize_required,
    single_study as _single_study,
    touch_study as _touch_study,
    utc_now as _utc_now,
)


class StudyDatabaseContext(Protocol):
    root_path: Path
    database_path: Path


def stage_scan_imports(
    repository: StudyDatabaseContext,
    assignments: tuple[ScanImportAssignment, ...],
    *,
    actor: str,
) -> tuple[ScanInputRecord, ...]:
    """Persist confirmed subject/role assignments before conversion starts."""

    normalized_actor = _normalize_required(actor, "Actor")
    _validate_assignments(assignments)
    now = _utc_now()
    inserted_ids: list[str] = []
    try:
        with closing(_connect(repository.database_path)) as connection:
            with connection:
                study = _single_study(connection)
                subjects = {
                    row["subject_code"].casefold(): row
                    for row in connection.execute(
                        """
                        SELECT id, subject_code, expected_t1, expected_t2, archived_at
                        FROM subjects WHERE study_id = ?
                        """,
                        (study["id"],),
                    ).fetchall()
                }
                by_subject: dict[str, list[ScanImportAssignment]] = {}
                for assignment in assignments:
                    by_subject.setdefault(
                        assignment.subject_code.strip().casefold(), []
                    ).append(assignment)

                created_subjects = 0
                for folded_code, subject_assignments in by_subject.items():
                    expected_t1 = any(
                        item.role in {ScanRole.T1_PRE, ScanRole.T1_POST}
                        for item in subject_assignments
                    )
                    expected_t2 = any(
                        item.role is ScanRole.T2 for item in subject_assignments
                    )
                    existing = subjects.get(folded_code)
                    if existing is not None and existing["archived_at"] is not None:
                        raise StudyStateError(
                            f"Subject {existing['subject_code']} was removed from this study. "
                            "Restore it before importing new scans with that subject ID."
                        )
                    if existing is None:
                        subject_id = str(uuid4())
                        subject_code = subject_assignments[0].subject_code.strip()
                        connection.execute(
                            """
                            INSERT INTO subjects(
                                id, study_id, subject_code, group_name, metadata_json,
                                expected_t1, expected_t2, created_at, updated_at
                            ) VALUES (?, ?, ?, NULL, '{}', ?, ?, ?, ?)
                            """,
                            (
                                subject_id,
                                study["id"],
                                subject_code,
                                int(expected_t1),
                                int(expected_t2),
                                now,
                                now,
                            ),
                        )
                        subjects[folded_code] = {
                            "id": subject_id,
                            "subject_code": subject_code,
                            "expected_t1": int(expected_t1),
                            "expected_t2": int(expected_t2),
                            "archived_at": None,
                        }
                        created_subjects += 1
                        _insert_audit(
                            connection,
                            study_id=study["id"],
                            subject_id=subject_id,
                            event_type="SUBJECT_DISCOVERED",
                            actor=normalized_actor,
                            details={
                                "subject_code": subject_code,
                                "expected_t1": expected_t1,
                                "expected_t2": expected_t2,
                            },
                            created_at=now,
                        )
                    else:
                        connection.execute(
                            """
                            UPDATE subjects
                            SET expected_t1 = ?, expected_t2 = ?, updated_at = ?
                            WHERE id = ?
                            """,
                            (
                                int(bool(existing["expected_t1"]) or expected_t1),
                                int(bool(existing["expected_t2"]) or expected_t2),
                                now,
                                existing["id"],
                            ),
                        )

                for assignment in assignments:
                    subject = subjects[assignment.subject_code.strip().casefold()]
                    record_id = _insert_assignment(
                        connection,
                        study_id=study["id"],
                        subject=subject,
                        assignment=assignment,
                        actor=normalized_actor,
                        timestamp=now,
                    )
                    inserted_ids.append(record_id)
                _touch_study(connection, study["id"], now)
                _insert_audit(
                    connection,
                    study_id=study["id"],
                    event_type="MRI_IMPORT_CONFIRMED",
                    actor=normalized_actor,
                    details={
                        "assignments": len(assignments),
                        "subjects_created": created_subjects,
                    },
                    created_at=now,
                )
            return tuple(
                scan_input_from_row(row, repository.root_path)
                for row in connection.execute(
                    f"""
                    SELECT si.*, s.subject_code
                    FROM scan_inputs AS si
                    JOIN subjects AS s ON s.id = si.subject_id
                    WHERE si.id IN ({','.join('?' for _ in inserted_ids)})
                    ORDER BY s.subject_code COLLATE NOCASE, si.role
                    """,
                    inserted_ids,
                ).fetchall()
            )
    except StudyStateError:
        raise
    except sqlite3.IntegrityError as exc:
        raise StudyStateError(
            f"The MRI assignments conflict with study state: {exc}"
        ) from exc
    except sqlite3.Error as exc:
        raise StudyStateError(f"Could not save the MRI import plan: {exc}") from exc


def mark_scan_import_converting(
    repository: StudyDatabaseContext,
    record_id: str,
) -> None:
    _update_scan_import_state(repository, record_id, ScanImportState.CONVERTING)


def complete_scan_import(
    repository: StudyDatabaseContext,
    record_id: str,
    result: ScanConversionResult,
    *,
    actor: str,
) -> None:
    normalized_actor = _normalize_required(actor, "Actor")
    try:
        relative_output = result.output_path.resolve().relative_to(
            repository.root_path.resolve()
        )
    except ValueError as exc:
        raise StudyStateError(
            "Converted MRI outputs must remain inside the study root."
        ) from exc
    now = _utc_now()
    try:
        with closing(_connect(repository.database_path)) as connection:
            with connection:
                study = _single_study(connection)
                row = connection.execute(
                    "SELECT subject_id, role, version FROM scan_inputs WHERE id = ?",
                    (record_id,),
                ).fetchone()
                if row is None:
                    raise StudyStateError(f"Unknown scan import record: {record_id}")
                connection.execute(
                    """
                    UPDATE scan_inputs
                    SET state = ?, output_path = ?, output_sha256 = ?,
                        source_sha256 = ?, output_shape_json = ?,
                        output_spacing_json = ?, output_axis_codes_json = ?,
                        error_message = NULL, updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        ScanImportState.CONVERTED.value,
                        relative_output.as_posix(),
                        result.output_sha256,
                        result.source_sha256,
                        json.dumps(result.shape),
                        json.dumps(result.spacing_mm),
                        json.dumps(result.axis_codes),
                        now,
                        record_id,
                    ),
                )
                previous = connection.execute(
                    """
                    SELECT id FROM scan_inputs
                    WHERE subject_id = ? AND role = ? AND active = 1 AND id != ?
                    """,
                    (row["subject_id"], row["role"], record_id),
                ).fetchone()
                if previous is not None:
                    connection.execute(
                        """
                        UPDATE scan_inputs
                        SET active = 0, state = ?, superseded_by = ?, updated_at = ?
                        WHERE id = ?
                        """,
                        (
                            ScanImportState.SUPERSEDED.value,
                            record_id,
                            now,
                            previous["id"],
                        ),
                    )
                connection.execute(
                    "UPDATE scan_inputs SET active = 1 WHERE id = ?",
                    (record_id,),
                )
                _touch_study(connection, study["id"], now)
                _insert_audit(
                    connection,
                    study_id=study["id"],
                    subject_id=row["subject_id"],
                    event_type="MRI_INPUT_CONVERTED",
                    actor=normalized_actor,
                    details={
                        "role": row["role"],
                        "version": row["version"],
                        "output_path": relative_output.as_posix(),
                        "output_sha256": result.output_sha256,
                    },
                    created_at=now,
                )
    except StudyStateError:
        raise
    except sqlite3.Error as exc:
        raise StudyStateError(
            f"Could not record the converted MRI input: {exc}"
        ) from exc


def fail_scan_import(
    repository: StudyDatabaseContext,
    record_id: str,
    error: str,
    *,
    actor: str,
) -> None:
    normalized_actor = _normalize_required(actor, "Actor")
    message = _normalize_required(error, "Conversion error")
    now = _utc_now()
    try:
        with closing(_connect(repository.database_path)) as connection:
            with connection:
                study = _single_study(connection)
                row = connection.execute(
                    "SELECT subject_id, role, version FROM scan_inputs WHERE id = ?",
                    (record_id,),
                ).fetchone()
                if row is None:
                    raise StudyStateError(f"Unknown scan import record: {record_id}")
                connection.execute(
                    """
                    UPDATE scan_inputs SET state = ?, error_message = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (ScanImportState.FAILED.value, message, now, record_id),
                )
                _touch_study(connection, study["id"], now)
                _insert_audit(
                    connection,
                    study_id=study["id"],
                    subject_id=row["subject_id"],
                    event_type="MRI_INPUT_CONVERSION_FAILED",
                    actor=normalized_actor,
                    details={
                        "role": row["role"],
                        "version": row["version"],
                        "error": message,
                    },
                    created_at=now,
                )
    except StudyStateError:
        raise
    except sqlite3.Error as exc:
        raise StudyStateError(
            f"Could not record the MRI import failure: {exc}"
        ) from exc


def scan_input_from_row(row: sqlite3.Row, root_path: Path) -> ScanInputRecord:
    output_path = row["output_path"]
    return ScanInputRecord(
        id=row["id"],
        proposal_id=row["proposal_id"],
        subject_id=row["subject_id"],
        subject_code=row["subject_code"],
        role=ScanRole(row["role"]),
        version=int(row["version"]),
        active=bool(row["active"]),
        state=ScanImportState(row["state"]),
        source_path=Path(row["source_path"]),
        source_format=SourceFormat(row["source_format"]),
        session_id=row["session_id"],
        scan_id=row["scan_id"],
        protocol=row["protocol"],
        method=row["method"],
        acquisition_orientation=row["acquisition_orientation"],
        confidence=ImportConfidence(row["confidence"]),
        orientation_policy=OrientationPolicy(row["orientation_policy"]),
        flip_axes=tuple(int(value) for value in json.loads(row["flip_axes_json"])),
        output_path=(root_path / output_path if output_path else None),
        output_sha256=row["output_sha256"],
        source_sha256=row["source_sha256"],
        output_shape=tuple(int(value) for value in json.loads(row["output_shape_json"])),
        output_spacing_mm=tuple(
            float(value) for value in json.loads(row["output_spacing_json"])
        ),
        output_axis_codes=tuple(
            str(value) for value in json.loads(row["output_axis_codes_json"])
        ),
        error_message=row["error_message"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _validate_assignments(assignments: tuple[ScanImportAssignment, ...]) -> None:
    if not assignments:
        raise StudyStateError("Select at least one MRI scan to import.")
    keys: set[tuple[str, ScanRole]] = set()
    for assignment in assignments:
        subject_code = _normalize_required(assignment.subject_code, "Subject ID")
        if assignment.role is ScanRole.IGNORE:
            raise StudyStateError("Ignored scans cannot be staged for import.")
        key = (subject_code.casefold(), assignment.role)
        if key in keys:
            raise StudyStateError(
                f"Subject {subject_code} has more than one {assignment.role.value} "
                "assignment. Keep one or edit the subject/role proposal."
            )
        keys.add(key)
        if assignment.source_format is SourceFormat.BRUKER and assignment.scan_id is None:
            raise StudyStateError("A Bruker assignment requires a scan number.")
        if not assignment.source_path.exists():
            raise StudyStateError(
                f"The selected MRI source is unavailable: {assignment.source_path}"
            )


def _insert_assignment(
    connection: sqlite3.Connection,
    *,
    study_id: str,
    subject: sqlite3.Row | dict[str, object],
    assignment: ScanImportAssignment,
    actor: str,
    timestamp: str,
) -> str:
    record_id = str(uuid4())
    previous = connection.execute(
        """
        SELECT id FROM scan_inputs
        WHERE subject_id = ? AND role = ? AND active = 1
        """,
        (subject["id"], assignment.role.value),
    ).fetchone()
    version = int(
        connection.execute(
            """
            SELECT COALESCE(MAX(version), 0) + 1 FROM scan_inputs
            WHERE subject_id = ? AND role = ?
            """,
            (subject["id"], assignment.role.value),
        ).fetchone()[0]
    )
    connection.execute(
        """
        INSERT INTO scan_inputs(
            id, proposal_id, study_id, subject_id, role, version,
            active, state, source_path, source_format, session_id,
            scan_id, protocol, method, acquisition_orientation,
            confidence, orientation_policy, flip_axes_json,
            created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            record_id,
            assignment.proposal_id,
            study_id,
            subject["id"],
            assignment.role.value,
            version,
            int(previous is None),
            ScanImportState.QUEUED.value,
            str(assignment.source_path.expanduser().resolve()),
            assignment.source_format.value,
            assignment.session_id,
            assignment.scan_id,
            assignment.protocol,
            assignment.method,
            assignment.acquisition_orientation,
            assignment.confidence.value,
            assignment.orientation_policy.value,
            json.dumps(sorted(set(assignment.flip_axes))),
            timestamp,
            timestamp,
        ),
    )
    _insert_audit(
        connection,
        study_id=study_id,
        subject_id=str(subject["id"]),
        event_type="MRI_INPUT_ASSIGNED",
        actor=actor,
        details={
            "role": assignment.role.value,
            "version": version,
            "source_format": assignment.source_format.value,
            "source_path": str(assignment.source_path.resolve()),
            "session_id": assignment.session_id,
            "scan_id": assignment.scan_id,
            "confidence": assignment.confidence.value,
            "orientation_policy": assignment.orientation_policy.value,
            "flip_axes": sorted(set(assignment.flip_axes)),
            "predecessor_input_id": previous["id"] if previous is not None else None,
        },
        created_at=timestamp,
    )
    return record_id


def _update_scan_import_state(
    repository: StudyDatabaseContext,
    record_id: str,
    state: ScanImportState,
) -> None:
    try:
        with closing(_connect(repository.database_path)) as connection:
            with connection:
                cursor = connection.execute(
                    """
                    UPDATE scan_inputs SET state = ?, updated_at = ?
                    WHERE id = ? AND state = ?
                    """,
                    (
                        state.value,
                        _utc_now(),
                        record_id,
                        ScanImportState.QUEUED.value,
                    ),
                )
                if cursor.rowcount != 1:
                    raise StudyStateError(
                        f"Unknown queued scan import record: {record_id}"
                    )
    except StudyStateError:
        raise
    except sqlite3.Error as exc:
        raise StudyStateError(f"Could not update the MRI import state: {exc}") from exc
