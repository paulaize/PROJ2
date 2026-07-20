"""Shared SQLite primitives for desktop study repositories."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4


class StudyStateError(RuntimeError):
    """Base error for persistent study state."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def connect(database_path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(database_path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def normalize_required(value: str, field_name: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise StudyStateError(f"{field_name} cannot be empty.")
    return normalized


def single_study(connection: sqlite3.Connection) -> sqlite3.Row:
    row = connection.execute("SELECT id, blinding_state FROM studies").fetchone()
    if row is None:
        raise StudyStateError("The study database has no study record.")
    return row


def insert_audit(
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
            created_at or utc_now(),
            json.dumps(details, sort_keys=True),
        ),
    )


def touch_study(connection: sqlite3.Connection, study_id: str, timestamp: str) -> None:
    connection.execute(
        "UPDATE studies SET updated_at = ? WHERE id = ?",
        (timestamp, study_id),
    )
