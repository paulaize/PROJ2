"""Persistence operations for explicit managed-input validation outcomes."""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Protocol

from lys_bbb_app.domain.errors import StudyStateError
from lys_bbb_app.domain.scan_import import InputValidationOutcome, ScanImportState
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


def record_input_validations(
    repository: StudyDatabaseContext,
    subject_id: str,
    outcomes: tuple[InputValidationOutcome, ...],
    *,
    actor: str,
) -> None:
    """Store current validation decisions and one auditable summary atomically."""

    normalized_actor = _normalize_required(actor, "Actor")
    if not outcomes:
        raise StudyStateError("No converted MRI inputs are available to validate.")
    outcome_ids = {outcome.scan_input_id for outcome in outcomes}
    if len(outcome_ids) != len(outcomes):
        raise StudyStateError("Each MRI input can have only one validation outcome.")
    now = _utc_now()
    try:
        with closing(_connect(repository.database_path)) as connection:
            with connection:
                study = _single_study(connection)
                records = connection.execute(
                    f"""
                    SELECT id FROM scan_inputs
                    WHERE subject_id = ? AND active = 1 AND state = ?
                      AND id IN ({','.join('?' for _ in outcomes)})
                    """,
                    (
                        subject_id,
                        ScanImportState.CONVERTED.value,
                        *outcome_ids,
                    ),
                ).fetchall()
                found_ids = {row["id"] for row in records}
                if found_ids != outcome_ids:
                    raise StudyStateError(
                        "Input validation can update only active converted MRI inputs."
                    )
                for outcome in outcomes:
                    issues = [
                        {
                            "code": issue.code,
                            "severity": issue.severity,
                            "user_message": issue.user_message,
                            "technical_detail": issue.technical_detail,
                        }
                        for issue in outcome.issues
                    ]
                    connection.execute(
                        """
                        UPDATE scan_inputs
                        SET validation_state = ?, validation_issues_json = ?,
                            validated_at = ?, validated_by = ?, updated_at = ?
                        WHERE id = ?
                        """,
                        (
                            outcome.state.value,
                            json.dumps(issues, sort_keys=True),
                            now,
                            normalized_actor,
                            now,
                            outcome.scan_input_id,
                        ),
                    )
                connection.execute(
                    "UPDATE subjects SET updated_at = ? WHERE id = ?",
                    (now, subject_id),
                )
                _touch_study(connection, study["id"], now)
                _insert_audit(
                    connection,
                    study_id=study["id"],
                    subject_id=subject_id,
                    event_type="MRI_INPUTS_VALIDATED",
                    actor=normalized_actor,
                    details={
                        "inputs": len(outcomes),
                        "valid": sum(
                            outcome.state.value == "VALID" for outcome in outcomes
                        ),
                        "invalid": sum(
                            outcome.state.value == "INVALID" for outcome in outcomes
                        ),
                        "issue_codes": sorted(
                            {
                                issue.code
                                for outcome in outcomes
                                for issue in outcome.issues
                            }
                        ),
                    },
                    created_at=now,
                )
    except StudyStateError:
        raise
    except sqlite3.Error as exc:
        raise StudyStateError(
            f"Could not save the MRI input validation: {exc}"
        ) from exc
