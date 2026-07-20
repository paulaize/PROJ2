"""Ordered SQLite schema creation and migration for desktop study roots."""

from __future__ import annotations

import sqlite3


def create_schema(
    connection: sqlite3.Connection,
    *,
    schema_version: int,
    applied_at: str,
) -> None:
    if schema_version != 3:
        raise ValueError(f"Unsupported schema creation target: {schema_version}")
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
            kind TEXT NOT NULL CHECK (kind IN ('mri', 't1', 't2')),
            path TEXT NOT NULL CHECK (length(trim(path)) > 0),
            selected_at TEXT NOT NULL,
            PRIMARY KEY(study_id, kind)
        );
        CREATE TABLE scan_inputs (
            id TEXT PRIMARY KEY,
            proposal_id TEXT NOT NULL,
            study_id TEXT NOT NULL REFERENCES studies(id) ON DELETE CASCADE,
            subject_id TEXT NOT NULL REFERENCES subjects(id) ON DELETE CASCADE,
            role TEXT NOT NULL CHECK (role IN ('T1_PRE', 'T1_POST', 'T2')),
            version INTEGER NOT NULL CHECK (version > 0),
            active INTEGER NOT NULL CHECK (active IN (0, 1)),
            state TEXT NOT NULL CHECK (
                state IN ('QUEUED', 'CONVERTING', 'CONVERTED', 'FAILED', 'SUPERSEDED')
            ),
            source_path TEXT NOT NULL,
            source_format TEXT NOT NULL CHECK (source_format IN ('BRUKER', 'NIFTI')),
            session_id TEXT NOT NULL,
            scan_id INTEGER,
            protocol TEXT NOT NULL DEFAULT '',
            method TEXT NOT NULL DEFAULT '',
            acquisition_orientation TEXT NOT NULL DEFAULT '',
            confidence TEXT NOT NULL CHECK (confidence IN ('HIGH', 'MEDIUM', 'LOW')),
            orientation_policy TEXT NOT NULL CHECK (
                orientation_policy IN ('NATIVE', 'T1_CORONAL')
            ),
            flip_axes_json TEXT NOT NULL DEFAULT '[]',
            output_path TEXT,
            output_sha256 TEXT,
            source_sha256 TEXT,
            output_shape_json TEXT NOT NULL DEFAULT '[]',
            output_spacing_json TEXT NOT NULL DEFAULT '[]',
            output_axis_codes_json TEXT NOT NULL DEFAULT '[]',
            error_message TEXT,
            superseded_by TEXT REFERENCES scan_inputs(id),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(subject_id, role, version)
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
        CREATE INDEX idx_scan_inputs_subject_role ON scan_inputs(subject_id, role, version DESC);
        CREATE INDEX idx_scan_inputs_state ON scan_inputs(study_id, state);
        CREATE UNIQUE INDEX idx_scan_inputs_active_role
            ON scan_inputs(subject_id, role) WHERE active = 1;
        CREATE INDEX idx_audit_events_study_time ON audit_events(study_id, created_at DESC);
        """
    )
    connection.execute(
        "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
        (schema_version, applied_at),
    )
    connection.execute(f"PRAGMA user_version = {schema_version}")


def migrate_schema(
    connection: sqlite3.Connection,
    from_version: int,
    *,
    target_version: int,
    applied_at: str,
) -> None:
    version = from_version
    if version == 2:
        connection.executescript(
            """
            ALTER TABLE input_folders RENAME TO input_folders_v2;
            CREATE TABLE input_folders (
                study_id TEXT NOT NULL REFERENCES studies(id) ON DELETE CASCADE,
                kind TEXT NOT NULL CHECK (kind IN ('mri', 't1', 't2')),
                path TEXT NOT NULL CHECK (length(trim(path)) > 0),
                selected_at TEXT NOT NULL,
                PRIMARY KEY(study_id, kind)
            );
            INSERT INTO input_folders(study_id, kind, path, selected_at)
                SELECT study_id, kind, path, selected_at FROM input_folders_v2;
            DROP TABLE input_folders_v2;
            CREATE TABLE scan_inputs (
                id TEXT PRIMARY KEY,
                proposal_id TEXT NOT NULL,
                study_id TEXT NOT NULL REFERENCES studies(id) ON DELETE CASCADE,
                subject_id TEXT NOT NULL REFERENCES subjects(id) ON DELETE CASCADE,
                role TEXT NOT NULL CHECK (role IN ('T1_PRE', 'T1_POST', 'T2')),
                version INTEGER NOT NULL CHECK (version > 0),
                active INTEGER NOT NULL CHECK (active IN (0, 1)),
                state TEXT NOT NULL CHECK (
                    state IN ('QUEUED', 'CONVERTING', 'CONVERTED', 'FAILED', 'SUPERSEDED')
                ),
                source_path TEXT NOT NULL,
                source_format TEXT NOT NULL CHECK (source_format IN ('BRUKER', 'NIFTI')),
                session_id TEXT NOT NULL,
                scan_id INTEGER,
                protocol TEXT NOT NULL DEFAULT '',
                method TEXT NOT NULL DEFAULT '',
                acquisition_orientation TEXT NOT NULL DEFAULT '',
                confidence TEXT NOT NULL CHECK (confidence IN ('HIGH', 'MEDIUM', 'LOW')),
                orientation_policy TEXT NOT NULL CHECK (
                    orientation_policy IN ('NATIVE', 'T1_CORONAL')
                ),
                flip_axes_json TEXT NOT NULL DEFAULT '[]',
                output_path TEXT,
                output_sha256 TEXT,
                source_sha256 TEXT,
                output_shape_json TEXT NOT NULL DEFAULT '[]',
                output_spacing_json TEXT NOT NULL DEFAULT '[]',
                output_axis_codes_json TEXT NOT NULL DEFAULT '[]',
                error_message TEXT,
                superseded_by TEXT REFERENCES scan_inputs(id),
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(subject_id, role, version)
            );
            CREATE INDEX idx_scan_inputs_subject_role
                ON scan_inputs(subject_id, role, version DESC);
            CREATE INDEX idx_scan_inputs_state ON scan_inputs(study_id, state);
            CREATE UNIQUE INDEX idx_scan_inputs_active_role
                ON scan_inputs(subject_id, role) WHERE active = 1;
            """
        )
        version = 3
        connection.execute(
            "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
            (version, applied_at),
        )
        connection.execute(f"PRAGMA user_version = {version}")
    if version != target_version:
        raise ValueError(
            f"No migration path exists from schema {from_version} to {target_version}."
        )
