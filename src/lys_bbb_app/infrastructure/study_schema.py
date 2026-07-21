"""Ordered SQLite schema creation and migration for desktop study roots."""

from __future__ import annotations

import sqlite3


def create_schema(
    connection: sqlite3.Connection,
    *,
    schema_version: int,
    applied_at: str,
) -> None:
    if schema_version != 7:
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
            archived_at TEXT,
            archived_by TEXT,
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
            validation_state TEXT NOT NULL DEFAULT 'NOT_RUN' CHECK (
                validation_state IN ('NOT_RUN', 'VALID', 'INVALID')
            ),
            validation_issues_json TEXT NOT NULL DEFAULT '[]',
            validated_at TEXT,
            validated_by TEXT,
            superseded_by TEXT REFERENCES scan_inputs(id),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(subject_id, role, version)
        );
        CREATE TABLE model_releases (
            id TEXT PRIMARY KEY,
            study_id TEXT NOT NULL REFERENCES studies(id) ON DELETE CASCADE,
            name TEXT NOT NULL,
            version TEXT NOT NULL,
            root_path TEXT NOT NULL,
            active INTEGER NOT NULL CHECK (active IN (0, 1)),
            architecture TEXT NOT NULL,
            threshold REAL NOT NULL,
            expected_spacing_json TEXT NOT NULL,
            model_sha256_json TEXT NOT NULL,
            manifest_sha256 TEXT NOT NULL,
            frozen_spec_sha256 TEXT NOT NULL,
            threshold_sha256 TEXT NOT NULL,
            project_git_commit TEXT NOT NULL,
            ratlesnetv2_git_commit TEXT NOT NULL,
            metadata_json TEXT NOT NULL DEFAULT '{}',
            validated_at TEXT NOT NULL,
            validated_by TEXT NOT NULL
        );
        CREATE TABLE jobs (
            id TEXT PRIMARY KEY,
            study_id TEXT NOT NULL REFERENCES studies(id) ON DELETE CASCADE,
            job_type TEXT NOT NULL,
            state TEXT NOT NULL CHECK (
                state IN ('QUEUED', 'RUNNING', 'SUCCEEDED', 'FAILED', 'INTERRUPTED')
            ),
            stage TEXT,
            progress_current INTEGER,
            progress_total INTEGER,
            model_release_id TEXT REFERENCES model_releases(id),
            subject_ids_json TEXT NOT NULL DEFAULT '[]',
            submitted_at TEXT NOT NULL,
            started_at TEXT,
            finished_at TEXT,
            error_message TEXT,
            output_path TEXT,
            metadata_json TEXT NOT NULL DEFAULT '{}'
        );
        CREATE TABLE artifacts (
            id TEXT PRIMARY KEY,
            study_id TEXT NOT NULL REFERENCES studies(id) ON DELETE CASCADE,
            subject_id TEXT NOT NULL REFERENCES subjects(id) ON DELETE CASCADE,
            artifact_type TEXT NOT NULL,
            state TEXT NOT NULL CHECK (
                state IN (
                    'DRAFT_REVIEW_REQUIRED', 'CORRECTED_REVIEW_REQUIRED',
                    'APPROVED', 'REJECTED', 'OUTDATED'
                )
            ),
            version INTEGER NOT NULL CHECK (version > 0),
            active INTEGER NOT NULL CHECK (active IN (0, 1)),
            path TEXT NOT NULL,
            file_hash TEXT NOT NULL,
            source_scan_input_id TEXT NOT NULL REFERENCES scan_inputs(id),
            model_release_id TEXT NOT NULL REFERENCES model_releases(id),
            job_id TEXT NOT NULL REFERENCES jobs(id),
            metadata_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            created_by TEXT NOT NULL,
            superseded_by TEXT REFERENCES artifacts(id),
            UNIQUE(subject_id, artifact_type, version)
        );
        CREATE TABLE reviews (
            id TEXT PRIMARY KEY,
            study_id TEXT NOT NULL REFERENCES studies(id) ON DELETE CASCADE,
            subject_id TEXT NOT NULL REFERENCES subjects(id) ON DELETE CASCADE,
            artifact_id TEXT NOT NULL UNIQUE REFERENCES artifacts(id) ON DELETE CASCADE,
            decision TEXT NOT NULL CHECK (decision IN ('APPROVED', 'REJECTED')),
            reviewer TEXT NOT NULL CHECK (length(trim(reviewer)) > 0),
            study_blinding_state TEXT NOT NULL CHECK (
                study_blinding_state IN ('BLINDED', 'UNBLINDED')
            ),
            issue_code TEXT,
            notes TEXT,
            created_at TEXT NOT NULL,
            CHECK (decision != 'REJECTED' OR (
                issue_code IS NOT NULL AND length(trim(issue_code)) > 0
                AND notes IS NOT NULL AND length(trim(notes)) > 0
            ))
        );
        CREATE TABLE results (
            id TEXT PRIMARY KEY,
            study_id TEXT NOT NULL REFERENCES studies(id) ON DELETE CASCADE,
            subject_id TEXT NOT NULL REFERENCES subjects(id) ON DELETE CASCADE,
            result_type TEXT NOT NULL,
            version INTEGER NOT NULL CHECK (version > 0),
            state TEXT NOT NULL CHECK (state IN ('APPROVED', 'OUTDATED')),
            active INTEGER NOT NULL CHECK (active IN (0, 1)),
            value REAL NOT NULL CHECK (value >= 0),
            unit TEXT NOT NULL,
            lesion_voxel_count INTEGER CHECK (lesion_voxel_count >= 0),
            method_version TEXT NOT NULL,
            source_artifact_id TEXT NOT NULL REFERENCES artifacts(id),
            source_scan_input_id TEXT NOT NULL REFERENCES scan_inputs(id),
            model_release_id TEXT NOT NULL REFERENCES model_releases(id),
            mask_sha256 TEXT NOT NULL,
            reviewer TEXT NOT NULL,
            metadata_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            approved_at TEXT NOT NULL,
            outdated_at TEXT,
            outdated_reason TEXT,
            superseded_by TEXT REFERENCES results(id),
            UNIQUE(subject_id, result_type, version)
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
        CREATE INDEX idx_subjects_study_archived ON subjects(study_id, archived_at);
        CREATE INDEX idx_scan_inputs_subject_role ON scan_inputs(subject_id, role, version DESC);
        CREATE INDEX idx_scan_inputs_state ON scan_inputs(study_id, state);
        CREATE UNIQUE INDEX idx_scan_inputs_active_role
            ON scan_inputs(subject_id, role) WHERE active = 1;
        CREATE UNIQUE INDEX idx_model_releases_active
            ON model_releases(study_id) WHERE active = 1;
        CREATE INDEX idx_jobs_state ON jobs(study_id, state);
        CREATE INDEX idx_artifacts_subject_type
            ON artifacts(subject_id, artifact_type, version DESC);
        CREATE INDEX idx_artifacts_state ON artifacts(study_id, state);
        CREATE UNIQUE INDEX idx_artifacts_active_type
            ON artifacts(subject_id, artifact_type) WHERE active = 1;
        CREATE INDEX idx_reviews_subject_time
            ON reviews(subject_id, created_at DESC);
        CREATE INDEX idx_results_subject_type
            ON results(subject_id, result_type, version DESC);
        CREATE INDEX idx_results_state ON results(study_id, state);
        CREATE UNIQUE INDEX idx_results_active_type
            ON results(subject_id, result_type) WHERE active = 1;
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
    if version == 3:
        connection.executescript(
            """
            ALTER TABLE subjects ADD COLUMN archived_at TEXT;
            ALTER TABLE subjects ADD COLUMN archived_by TEXT;
            CREATE INDEX idx_subjects_study_archived
                ON subjects(study_id, archived_at);
            """
        )
        version = 4
        connection.execute(
            "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
            (version, applied_at),
        )
        connection.execute(f"PRAGMA user_version = {version}")
    if version == 4:
        connection.executescript(
            """
            ALTER TABLE scan_inputs ADD COLUMN validation_state TEXT NOT NULL
                DEFAULT 'NOT_RUN' CHECK (
                    validation_state IN ('NOT_RUN', 'VALID', 'INVALID')
                );
            ALTER TABLE scan_inputs ADD COLUMN validation_issues_json TEXT NOT NULL
                DEFAULT '[]';
            ALTER TABLE scan_inputs ADD COLUMN validated_at TEXT;
            ALTER TABLE scan_inputs ADD COLUMN validated_by TEXT;
            """
        )
        version = 5
        connection.execute(
            "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
            (version, applied_at),
        )
        connection.execute(f"PRAGMA user_version = {version}")
    if version == 5:
        connection.executescript(
            """
            CREATE TABLE model_releases (
                id TEXT PRIMARY KEY,
                study_id TEXT NOT NULL REFERENCES studies(id) ON DELETE CASCADE,
                name TEXT NOT NULL,
                version TEXT NOT NULL,
                root_path TEXT NOT NULL,
                active INTEGER NOT NULL CHECK (active IN (0, 1)),
                architecture TEXT NOT NULL,
                threshold REAL NOT NULL,
                expected_spacing_json TEXT NOT NULL,
                model_sha256_json TEXT NOT NULL,
                manifest_sha256 TEXT NOT NULL,
                frozen_spec_sha256 TEXT NOT NULL,
                threshold_sha256 TEXT NOT NULL,
                project_git_commit TEXT NOT NULL,
                ratlesnetv2_git_commit TEXT NOT NULL,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                validated_at TEXT NOT NULL,
                validated_by TEXT NOT NULL
            );
            CREATE TABLE jobs (
                id TEXT PRIMARY KEY,
                study_id TEXT NOT NULL REFERENCES studies(id) ON DELETE CASCADE,
                job_type TEXT NOT NULL,
                state TEXT NOT NULL CHECK (
                    state IN ('QUEUED', 'RUNNING', 'SUCCEEDED', 'FAILED', 'INTERRUPTED')
                ),
                stage TEXT,
                progress_current INTEGER,
                progress_total INTEGER,
                model_release_id TEXT REFERENCES model_releases(id),
                subject_ids_json TEXT NOT NULL DEFAULT '[]',
                submitted_at TEXT NOT NULL,
                started_at TEXT,
                finished_at TEXT,
                error_message TEXT,
                output_path TEXT,
                metadata_json TEXT NOT NULL DEFAULT '{}'
            );
            CREATE TABLE artifacts (
                id TEXT PRIMARY KEY,
                study_id TEXT NOT NULL REFERENCES studies(id) ON DELETE CASCADE,
                subject_id TEXT NOT NULL REFERENCES subjects(id) ON DELETE CASCADE,
                artifact_type TEXT NOT NULL,
                state TEXT NOT NULL CHECK (
                    state IN ('DRAFT_REVIEW_REQUIRED', 'OUTDATED')
                ),
                version INTEGER NOT NULL CHECK (version > 0),
                active INTEGER NOT NULL CHECK (active IN (0, 1)),
                path TEXT NOT NULL,
                file_hash TEXT NOT NULL,
                source_scan_input_id TEXT NOT NULL REFERENCES scan_inputs(id),
                model_release_id TEXT NOT NULL REFERENCES model_releases(id),
                job_id TEXT NOT NULL REFERENCES jobs(id),
                metadata_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                created_by TEXT NOT NULL,
                superseded_by TEXT REFERENCES artifacts(id),
                UNIQUE(subject_id, artifact_type, version)
            );
            CREATE UNIQUE INDEX idx_model_releases_active
                ON model_releases(study_id) WHERE active = 1;
            CREATE INDEX idx_jobs_state ON jobs(study_id, state);
            CREATE INDEX idx_artifacts_subject_type
                ON artifacts(subject_id, artifact_type, version DESC);
            CREATE INDEX idx_artifacts_state ON artifacts(study_id, state);
            CREATE UNIQUE INDEX idx_artifacts_active_type
                ON artifacts(subject_id, artifact_type) WHERE active = 1;
            """
        )
        version = 6
        connection.execute(
            "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
            (version, applied_at),
        )
        connection.execute(f"PRAGMA user_version = {version}")
    if version == 6:
        connection.executescript(
            """
            ALTER TABLE artifacts RENAME TO artifacts_v6;
            CREATE TABLE artifacts (
                id TEXT PRIMARY KEY,
                study_id TEXT NOT NULL REFERENCES studies(id) ON DELETE CASCADE,
                subject_id TEXT NOT NULL REFERENCES subjects(id) ON DELETE CASCADE,
                artifact_type TEXT NOT NULL,
                state TEXT NOT NULL CHECK (
                    state IN (
                        'DRAFT_REVIEW_REQUIRED', 'CORRECTED_REVIEW_REQUIRED',
                        'APPROVED', 'REJECTED', 'OUTDATED'
                    )
                ),
                version INTEGER NOT NULL CHECK (version > 0),
                active INTEGER NOT NULL CHECK (active IN (0, 1)),
                path TEXT NOT NULL,
                file_hash TEXT NOT NULL,
                source_scan_input_id TEXT NOT NULL REFERENCES scan_inputs(id),
                model_release_id TEXT NOT NULL REFERENCES model_releases(id),
                job_id TEXT NOT NULL REFERENCES jobs(id),
                metadata_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                created_by TEXT NOT NULL,
                superseded_by TEXT REFERENCES artifacts(id),
                UNIQUE(subject_id, artifact_type, version)
            );
            INSERT INTO artifacts(
                id, study_id, subject_id, artifact_type, state, version, active,
                path, file_hash, source_scan_input_id, model_release_id, job_id,
                metadata_json, created_at, created_by, superseded_by
            )
            SELECT
                id, study_id, subject_id, artifact_type, state, version, active,
                path, file_hash, source_scan_input_id, model_release_id, job_id,
                metadata_json, created_at, created_by, superseded_by
            FROM artifacts_v6;
            UPDATE artifacts
            SET artifact_type = 'T2_LESION_MASK'
            WHERE artifact_type = 'T2_LESION_MASK_DRAFT';
            DROP TABLE artifacts_v6;
            CREATE INDEX idx_artifacts_subject_type
                ON artifacts(subject_id, artifact_type, version DESC);
            CREATE INDEX idx_artifacts_state ON artifacts(study_id, state);
            CREATE UNIQUE INDEX idx_artifacts_active_type
                ON artifacts(subject_id, artifact_type) WHERE active = 1;
            CREATE TABLE reviews (
                id TEXT PRIMARY KEY,
                study_id TEXT NOT NULL REFERENCES studies(id) ON DELETE CASCADE,
                subject_id TEXT NOT NULL REFERENCES subjects(id) ON DELETE CASCADE,
                artifact_id TEXT NOT NULL UNIQUE REFERENCES artifacts(id) ON DELETE CASCADE,
                decision TEXT NOT NULL CHECK (decision IN ('APPROVED', 'REJECTED')),
                reviewer TEXT NOT NULL CHECK (length(trim(reviewer)) > 0),
                study_blinding_state TEXT NOT NULL CHECK (
                    study_blinding_state IN ('BLINDED', 'UNBLINDED')
                ),
                issue_code TEXT,
                notes TEXT,
                created_at TEXT NOT NULL,
                CHECK (decision != 'REJECTED' OR (
                    issue_code IS NOT NULL AND length(trim(issue_code)) > 0
                    AND notes IS NOT NULL AND length(trim(notes)) > 0
                ))
            );
            CREATE TABLE results (
                id TEXT PRIMARY KEY,
                study_id TEXT NOT NULL REFERENCES studies(id) ON DELETE CASCADE,
                subject_id TEXT NOT NULL REFERENCES subjects(id) ON DELETE CASCADE,
                result_type TEXT NOT NULL,
                version INTEGER NOT NULL CHECK (version > 0),
                state TEXT NOT NULL CHECK (state IN ('APPROVED', 'OUTDATED')),
                active INTEGER NOT NULL CHECK (active IN (0, 1)),
                value REAL NOT NULL CHECK (value >= 0),
                unit TEXT NOT NULL,
                lesion_voxel_count INTEGER CHECK (lesion_voxel_count >= 0),
                method_version TEXT NOT NULL,
                source_artifact_id TEXT NOT NULL REFERENCES artifacts(id),
                source_scan_input_id TEXT NOT NULL REFERENCES scan_inputs(id),
                model_release_id TEXT NOT NULL REFERENCES model_releases(id),
                mask_sha256 TEXT NOT NULL,
                reviewer TEXT NOT NULL,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                approved_at TEXT NOT NULL,
                outdated_at TEXT,
                outdated_reason TEXT,
                superseded_by TEXT REFERENCES results(id),
                UNIQUE(subject_id, result_type, version)
            );
            CREATE INDEX idx_reviews_subject_time
                ON reviews(subject_id, created_at DESC);
            CREATE INDEX idx_results_subject_type
                ON results(subject_id, result_type, version DESC);
            CREATE INDEX idx_results_state ON results(study_id, state);
            CREATE UNIQUE INDEX idx_results_active_type
                ON results(subject_id, result_type) WHERE active = 1;
            """
        )
        version = 7
        connection.execute(
            "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
            (version, applied_at),
        )
        connection.execute(f"PRAGMA user_version = {version}")
    if version != target_version:
        raise ValueError(
            f"No migration path exists from schema {from_version} to {target_version}."
        )
