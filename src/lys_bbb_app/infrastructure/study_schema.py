"""Ordered SQLite schema creation and migration for desktop study roots."""

from __future__ import annotations

import sqlite3

from lys_bbb_app.infrastructure.atlas_mapping_repository import create_atlas_schema


def create_schema(
    connection: sqlite3.Connection,
    *,
    schema_version: int,
    applied_at: str,
) -> None:
    if schema_version != 11:
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
                    'APPROVED', 'OUTDATED'
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
            reviewer TEXT NOT NULL CHECK (length(trim(reviewer)) > 0),
            study_blinding_state TEXT NOT NULL CHECK (
                study_blinding_state IN ('BLINDED', 'UNBLINDED')
            ),
            created_at TEXT NOT NULL
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
        CREATE TABLE IF NOT EXISTS t1_brain_mask_releases (
            id TEXT PRIMARY KEY,
            study_id TEXT NOT NULL REFERENCES studies(id) ON DELETE CASCADE,
            root_path TEXT NOT NULL,
            active INTEGER NOT NULL CHECK (active IN (0, 1)),
            source_commit TEXT NOT NULL,
            weights_sha256 TEXT NOT NULL,
            manifest_sha256 TEXT NOT NULL,
            test_time_augmentation INTEGER NOT NULL CHECK (
                test_time_augmentation IN (0, 1)
            ),
            method_version TEXT NOT NULL,
            method_spec_sha256 TEXT NOT NULL,
            metadata_json TEXT NOT NULL DEFAULT '{}',
            validated_at TEXT NOT NULL,
            validated_by TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS t1_brain_mask_jobs (
            id TEXT PRIMARY KEY,
            study_id TEXT NOT NULL REFERENCES studies(id) ON DELETE CASCADE,
            state TEXT NOT NULL CHECK (
                state IN ('QUEUED', 'RUNNING', 'SUCCEEDED', 'FAILED', 'INTERRUPTED')
            ),
            stage TEXT,
            progress_current INTEGER,
            progress_total INTEGER,
            release_id TEXT NOT NULL REFERENCES t1_brain_mask_releases(id),
            subject_ids_json TEXT NOT NULL DEFAULT '[]',
            submitted_at TEXT NOT NULL,
            started_at TEXT,
            finished_at TEXT,
            error_message TEXT,
            output_path TEXT,
            metadata_json TEXT NOT NULL DEFAULT '{}'
        );
        CREATE TABLE IF NOT EXISTS t1_brain_mask_artifacts (
            id TEXT PRIMARY KEY,
            study_id TEXT NOT NULL REFERENCES studies(id) ON DELETE CASCADE,
            subject_id TEXT NOT NULL REFERENCES subjects(id) ON DELETE CASCADE,
            origin TEXT NOT NULL CHECK (origin IN ('AUTOMATIC', 'CORRECTED')),
            state TEXT NOT NULL CHECK (
                state IN (
                    'DRAFT_REVIEW_REQUIRED', 'CORRECTED_REVIEW_REQUIRED',
                    'APPROVED', 'OUTDATED'
                )
            ),
            version INTEGER NOT NULL CHECK (version > 0),
            active INTEGER NOT NULL CHECK (active IN (0, 1)),
            mask_path TEXT NOT NULL,
            mask_sha256 TEXT NOT NULL,
            raw_mask_path TEXT,
            raw_mask_sha256 TEXT,
            qc_preview_path TEXT,
            source_scan_input_id TEXT NOT NULL REFERENCES scan_inputs(id),
            release_id TEXT NOT NULL REFERENCES t1_brain_mask_releases(id),
            job_id TEXT NOT NULL REFERENCES t1_brain_mask_jobs(id),
            foreground_voxels INTEGER NOT NULL CHECK (foreground_voxels > 0),
            volume_mm3 REAL NOT NULL CHECK (volume_mm3 > 0),
            device TEXT NOT NULL,
            regularity_warnings_json TEXT NOT NULL DEFAULT '[]',
            metadata_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            created_by TEXT NOT NULL,
            superseded_by TEXT REFERENCES t1_brain_mask_artifacts(id),
            UNIQUE(subject_id, version)
        );
        CREATE TABLE IF NOT EXISTS t1_brain_mask_reviews (
            id TEXT PRIMARY KEY,
            study_id TEXT NOT NULL REFERENCES studies(id) ON DELETE CASCADE,
            subject_id TEXT NOT NULL REFERENCES subjects(id) ON DELETE CASCADE,
            artifact_id TEXT NOT NULL UNIQUE
                REFERENCES t1_brain_mask_artifacts(id) ON DELETE CASCADE,
            reviewer TEXT NOT NULL CHECK (length(trim(reviewer)) > 0),
            study_blinding_state TEXT NOT NULL CHECK (
                study_blinding_state IN ('BLINDED', 'UNBLINDED')
            ),
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS t1_registration_methods (
            id TEXT PRIMARY KEY,
            study_id TEXT NOT NULL REFERENCES studies(id) ON DELETE CASCADE,
            active INTEGER NOT NULL CHECK (active IN (0, 1)),
            method_version TEXT NOT NULL,
            method_spec_sha256 TEXT NOT NULL,
            config_json TEXT NOT NULL DEFAULT '{}',
            registered_at TEXT NOT NULL,
            registered_by TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS t1_registration_jobs (
            id TEXT PRIMARY KEY,
            study_id TEXT NOT NULL REFERENCES studies(id) ON DELETE CASCADE,
            state TEXT NOT NULL CHECK (
                state IN ('QUEUED', 'RUNNING', 'SUCCEEDED', 'FAILED', 'INTERRUPTED')
            ),
            stage TEXT,
            progress_current INTEGER,
            progress_total INTEGER,
            method_id TEXT NOT NULL REFERENCES t1_registration_methods(id),
            subject_ids_json TEXT NOT NULL DEFAULT '[]',
            submitted_at TEXT NOT NULL,
            started_at TEXT,
            finished_at TEXT,
            error_message TEXT,
            output_path TEXT,
            metadata_json TEXT NOT NULL DEFAULT '{}'
        );
        CREATE TABLE IF NOT EXISTS t1_registration_artifacts (
            id TEXT PRIMARY KEY,
            study_id TEXT NOT NULL REFERENCES studies(id) ON DELETE CASCADE,
            subject_id TEXT NOT NULL REFERENCES subjects(id) ON DELETE CASCADE,
            state TEXT NOT NULL CHECK (
                state IN ('REVIEW_REQUIRED', 'APPROVED', 'OUTDATED')
            ),
            version INTEGER NOT NULL CHECK (version > 0),
            active INTEGER NOT NULL CHECK (active IN (0, 1)),
            registered_post_path TEXT NOT NULL,
            registered_post_sha256 TEXT NOT NULL,
            transform_path TEXT NOT NULL,
            transform_sha256 TEXT NOT NULL,
            qc_preview_path TEXT NOT NULL,
            qc_preview_sha256 TEXT NOT NULL,
            source_pre_scan_input_id TEXT NOT NULL REFERENCES scan_inputs(id),
            source_post_scan_input_id TEXT NOT NULL REFERENCES scan_inputs(id),
            source_brain_mask_artifact_id TEXT NOT NULL
                REFERENCES t1_brain_mask_artifacts(id),
            method_id TEXT NOT NULL REFERENCES t1_registration_methods(id),
            job_id TEXT NOT NULL REFERENCES t1_registration_jobs(id),
            before_xcorr REAL,
            after_xcorr REAL NOT NULL,
            registration_metric REAL NOT NULL,
            optimizer_stop TEXT NOT NULL,
            metadata_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            created_by TEXT NOT NULL,
            superseded_by TEXT REFERENCES t1_registration_artifacts(id),
            UNIQUE(subject_id, version)
        );
        CREATE TABLE IF NOT EXISTS t1_registration_reviews (
            id TEXT PRIMARY KEY,
            study_id TEXT NOT NULL REFERENCES studies(id) ON DELETE CASCADE,
            subject_id TEXT NOT NULL REFERENCES subjects(id) ON DELETE CASCADE,
            artifact_id TEXT NOT NULL UNIQUE
                REFERENCES t1_registration_artifacts(id) ON DELETE CASCADE,
            reviewer TEXT NOT NULL CHECK (length(trim(reviewer)) > 0),
            study_blinding_state TEXT NOT NULL CHECK (
                study_blinding_state IN ('BLINDED', 'UNBLINDED')
            ),
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS t1_enhancement_methods (
            id TEXT PRIMARY KEY,
            study_id TEXT NOT NULL REFERENCES studies(id) ON DELETE CASCADE,
            active INTEGER NOT NULL CHECK (active IN (0, 1)),
            method_version TEXT NOT NULL,
            method_spec_sha256 TEXT NOT NULL,
            scientific_status TEXT NOT NULL CHECK (
                scientific_status IN ('PROVISIONAL', 'APPROVED', 'RETIRED')
            ),
            config_json TEXT NOT NULL DEFAULT '{}',
            registered_at TEXT NOT NULL,
            registered_by TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS t1_enhancement_jobs (
            id TEXT PRIMARY KEY,
            study_id TEXT NOT NULL REFERENCES studies(id) ON DELETE CASCADE,
            state TEXT NOT NULL CHECK (
                state IN ('QUEUED', 'RUNNING', 'SUCCEEDED', 'FAILED', 'INTERRUPTED')
            ),
            stage TEXT,
            progress_current INTEGER,
            progress_total INTEGER,
            method_id TEXT NOT NULL REFERENCES t1_enhancement_methods(id),
            subject_ids_json TEXT NOT NULL DEFAULT '[]',
            submitted_at TEXT NOT NULL,
            started_at TEXT,
            finished_at TEXT,
            error_message TEXT,
            output_path TEXT,
            metadata_json TEXT NOT NULL DEFAULT '{}'
        );
        CREATE TABLE IF NOT EXISTS t1_enhancement_results (
            id TEXT PRIMARY KEY,
            study_id TEXT NOT NULL REFERENCES studies(id) ON DELETE CASCADE,
            subject_id TEXT NOT NULL REFERENCES subjects(id) ON DELETE CASCADE,
            version INTEGER NOT NULL CHECK (version > 0),
            state TEXT NOT NULL CHECK (state IN ('PROVISIONAL', 'OUTDATED')),
            active INTEGER NOT NULL CHECK (active IN (0, 1)),
            percent_enhancement_map TEXT NOT NULL,
            percent_enhancement_sha256 TEXT NOT NULL,
            summary_csv TEXT NOT NULL,
            summary_sha256 TEXT NOT NULL,
            qc_preview_path TEXT NOT NULL,
            qc_preview_sha256 TEXT NOT NULL,
            metadata_path TEXT NOT NULL,
            metadata_sha256 TEXT NOT NULL,
            source_registration_artifact_id TEXT NOT NULL
                REFERENCES t1_registration_artifacts(id),
            source_brain_mask_artifact_id TEXT NOT NULL
                REFERENCES t1_brain_mask_artifacts(id),
            source_pre_scan_input_id TEXT NOT NULL REFERENCES scan_inputs(id),
            method_id TEXT NOT NULL REFERENCES t1_enhancement_methods(id),
            job_id TEXT NOT NULL REFERENCES t1_enhancement_jobs(id),
            metrics_json TEXT NOT NULL DEFAULT '[]',
            metadata_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            created_by TEXT NOT NULL,
            outdated_at TEXT,
            outdated_reason TEXT,
            superseded_by TEXT REFERENCES t1_enhancement_results(id),
            UNIQUE(subject_id, version)
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
        CREATE UNIQUE INDEX IF NOT EXISTS idx_t1_brain_mask_releases_active
            ON t1_brain_mask_releases(study_id) WHERE active = 1;
        CREATE INDEX IF NOT EXISTS idx_t1_brain_mask_jobs_state
            ON t1_brain_mask_jobs(study_id, state);
        CREATE INDEX IF NOT EXISTS idx_t1_brain_mask_artifacts_subject
            ON t1_brain_mask_artifacts(subject_id, version DESC);
        CREATE INDEX IF NOT EXISTS idx_t1_brain_mask_artifacts_state
            ON t1_brain_mask_artifacts(study_id, state);
        CREATE UNIQUE INDEX IF NOT EXISTS idx_t1_brain_mask_artifacts_active
            ON t1_brain_mask_artifacts(subject_id) WHERE active = 1;
        CREATE INDEX IF NOT EXISTS idx_t1_brain_mask_reviews_subject_time
            ON t1_brain_mask_reviews(subject_id, created_at DESC);
        CREATE UNIQUE INDEX IF NOT EXISTS idx_t1_registration_methods_active
            ON t1_registration_methods(study_id) WHERE active = 1;
        CREATE INDEX IF NOT EXISTS idx_t1_registration_jobs_state
            ON t1_registration_jobs(study_id, state);
        CREATE INDEX IF NOT EXISTS idx_t1_registration_artifacts_subject
            ON t1_registration_artifacts(subject_id, version DESC);
        CREATE UNIQUE INDEX IF NOT EXISTS idx_t1_registration_artifacts_active
            ON t1_registration_artifacts(subject_id) WHERE active = 1;
        CREATE INDEX IF NOT EXISTS idx_t1_registration_reviews_subject_time
            ON t1_registration_reviews(subject_id, created_at DESC);
        CREATE UNIQUE INDEX IF NOT EXISTS idx_t1_enhancement_methods_active
            ON t1_enhancement_methods(study_id) WHERE active = 1;
        CREATE INDEX IF NOT EXISTS idx_t1_enhancement_jobs_state
            ON t1_enhancement_jobs(study_id, state);
        CREATE INDEX IF NOT EXISTS idx_t1_enhancement_results_subject
            ON t1_enhancement_results(subject_id, version DESC);
        CREATE UNIQUE INDEX IF NOT EXISTS idx_t1_enhancement_results_active
            ON t1_enhancement_results(subject_id) WHERE active = 1;
        CREATE INDEX idx_audit_events_study_time ON audit_events(study_id, created_at DESC);
        """
    )
    create_atlas_schema(connection)
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
                        'APPROVED', 'OUTDATED'
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
                reviewer TEXT NOT NULL CHECK (length(trim(reviewer)) > 0),
                study_blinding_state TEXT NOT NULL CHECK (
                    study_blinding_state IN ('BLINDED', 'UNBLINDED')
                ),
                created_at TEXT NOT NULL
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
        version = 8
        connection.execute(
            "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
            (version, applied_at),
        )
        connection.execute(f"PRAGMA user_version = {version}")
    if version == 7:
        connection.executescript(
            """
            UPDATE artifacts
            SET state = 'OUTDATED', active = 0
            WHERE state = 'REJECTED';

            CREATE TABLE reviews_v8 (
                id TEXT PRIMARY KEY,
                study_id TEXT NOT NULL REFERENCES studies(id) ON DELETE CASCADE,
                subject_id TEXT NOT NULL REFERENCES subjects(id) ON DELETE CASCADE,
                artifact_id TEXT NOT NULL UNIQUE REFERENCES artifacts(id) ON DELETE CASCADE,
                reviewer TEXT NOT NULL CHECK (length(trim(reviewer)) > 0),
                study_blinding_state TEXT NOT NULL CHECK (
                    study_blinding_state IN ('BLINDED', 'UNBLINDED')
                ),
                created_at TEXT NOT NULL
            );
            INSERT INTO reviews_v8(
                id, study_id, subject_id, artifact_id, reviewer,
                study_blinding_state, created_at
            )
            SELECT
                id, study_id, subject_id, artifact_id, reviewer,
                study_blinding_state, created_at
            FROM reviews
            WHERE decision = 'APPROVED';
            DROP TABLE reviews;
            ALTER TABLE reviews_v8 RENAME TO reviews;
            CREATE INDEX idx_reviews_subject_time
                ON reviews(subject_id, created_at DESC);

            UPDATE audit_events
            SET details_json = json_remove(details_json, '$.issue_code', '$.notes')
            WHERE json_valid(details_json);
            """
        )
        version = 8
        connection.execute(
            "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
            (version, applied_at),
        )
        connection.execute(f"PRAGMA user_version = {version}")
    if version == 8:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS t1_brain_mask_releases (
                id TEXT PRIMARY KEY,
                study_id TEXT NOT NULL REFERENCES studies(id) ON DELETE CASCADE,
                root_path TEXT NOT NULL,
                active INTEGER NOT NULL CHECK (active IN (0, 1)),
                source_commit TEXT NOT NULL,
                weights_sha256 TEXT NOT NULL,
                manifest_sha256 TEXT NOT NULL,
                test_time_augmentation INTEGER NOT NULL CHECK (
                    test_time_augmentation IN (0, 1)
                ),
                method_version TEXT NOT NULL,
                method_spec_sha256 TEXT NOT NULL,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                validated_at TEXT NOT NULL,
                validated_by TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS t1_brain_mask_jobs (
                id TEXT PRIMARY KEY,
                study_id TEXT NOT NULL REFERENCES studies(id) ON DELETE CASCADE,
                state TEXT NOT NULL CHECK (
                    state IN ('QUEUED', 'RUNNING', 'SUCCEEDED', 'FAILED', 'INTERRUPTED')
                ),
                stage TEXT,
                progress_current INTEGER,
                progress_total INTEGER,
                release_id TEXT NOT NULL REFERENCES t1_brain_mask_releases(id),
                subject_ids_json TEXT NOT NULL DEFAULT '[]',
                submitted_at TEXT NOT NULL,
                started_at TEXT,
                finished_at TEXT,
                error_message TEXT,
                output_path TEXT,
                metadata_json TEXT NOT NULL DEFAULT '{}'
            );
            CREATE TABLE IF NOT EXISTS t1_brain_mask_artifacts (
                id TEXT PRIMARY KEY,
                study_id TEXT NOT NULL REFERENCES studies(id) ON DELETE CASCADE,
                subject_id TEXT NOT NULL REFERENCES subjects(id) ON DELETE CASCADE,
                origin TEXT NOT NULL CHECK (origin IN ('AUTOMATIC', 'CORRECTED')),
                state TEXT NOT NULL CHECK (
                    state IN (
                        'DRAFT_REVIEW_REQUIRED', 'CORRECTED_REVIEW_REQUIRED',
                        'APPROVED', 'OUTDATED'
                    )
                ),
                version INTEGER NOT NULL CHECK (version > 0),
                active INTEGER NOT NULL CHECK (active IN (0, 1)),
                mask_path TEXT NOT NULL,
                mask_sha256 TEXT NOT NULL,
                raw_mask_path TEXT,
                raw_mask_sha256 TEXT,
                qc_preview_path TEXT,
                source_scan_input_id TEXT NOT NULL REFERENCES scan_inputs(id),
                release_id TEXT NOT NULL REFERENCES t1_brain_mask_releases(id),
                job_id TEXT NOT NULL REFERENCES t1_brain_mask_jobs(id),
                foreground_voxels INTEGER NOT NULL CHECK (foreground_voxels > 0),
                volume_mm3 REAL NOT NULL CHECK (volume_mm3 > 0),
                device TEXT NOT NULL,
                regularity_warnings_json TEXT NOT NULL DEFAULT '[]',
                metadata_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                created_by TEXT NOT NULL,
                superseded_by TEXT REFERENCES t1_brain_mask_artifacts(id),
                UNIQUE(subject_id, version)
            );
            CREATE TABLE IF NOT EXISTS t1_brain_mask_reviews (
                id TEXT PRIMARY KEY,
                study_id TEXT NOT NULL REFERENCES studies(id) ON DELETE CASCADE,
                subject_id TEXT NOT NULL REFERENCES subjects(id) ON DELETE CASCADE,
                artifact_id TEXT NOT NULL UNIQUE
                    REFERENCES t1_brain_mask_artifacts(id) ON DELETE CASCADE,
                reviewer TEXT NOT NULL CHECK (length(trim(reviewer)) > 0),
                study_blinding_state TEXT NOT NULL CHECK (
                    study_blinding_state IN ('BLINDED', 'UNBLINDED')
                ),
                created_at TEXT NOT NULL
            );
            CREATE UNIQUE INDEX IF NOT EXISTS idx_t1_brain_mask_releases_active
                ON t1_brain_mask_releases(study_id) WHERE active = 1;
            CREATE INDEX IF NOT EXISTS idx_t1_brain_mask_jobs_state
                ON t1_brain_mask_jobs(study_id, state);
            CREATE INDEX IF NOT EXISTS idx_t1_brain_mask_artifacts_subject
                ON t1_brain_mask_artifacts(subject_id, version DESC);
            CREATE INDEX IF NOT EXISTS idx_t1_brain_mask_artifacts_state
                ON t1_brain_mask_artifacts(study_id, state);
            CREATE UNIQUE INDEX IF NOT EXISTS idx_t1_brain_mask_artifacts_active
                ON t1_brain_mask_artifacts(subject_id) WHERE active = 1;
            CREATE INDEX IF NOT EXISTS idx_t1_brain_mask_reviews_subject_time
                ON t1_brain_mask_reviews(subject_id, created_at DESC);
            """
        )
        version = 9
        connection.execute(
            "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
            (version, applied_at),
        )
        connection.execute(f"PRAGMA user_version = {version}")
    if version == 9:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS t1_registration_methods (
                id TEXT PRIMARY KEY,
                study_id TEXT NOT NULL REFERENCES studies(id) ON DELETE CASCADE,
                active INTEGER NOT NULL CHECK (active IN (0, 1)),
                method_version TEXT NOT NULL,
                method_spec_sha256 TEXT NOT NULL,
                config_json TEXT NOT NULL DEFAULT '{}',
                registered_at TEXT NOT NULL,
                registered_by TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS t1_registration_jobs (
                id TEXT PRIMARY KEY,
                study_id TEXT NOT NULL REFERENCES studies(id) ON DELETE CASCADE,
                state TEXT NOT NULL CHECK (
                    state IN ('QUEUED', 'RUNNING', 'SUCCEEDED', 'FAILED', 'INTERRUPTED')
                ),
                stage TEXT,
                progress_current INTEGER,
                progress_total INTEGER,
                method_id TEXT NOT NULL REFERENCES t1_registration_methods(id),
                subject_ids_json TEXT NOT NULL DEFAULT '[]',
                submitted_at TEXT NOT NULL,
                started_at TEXT,
                finished_at TEXT,
                error_message TEXT,
                output_path TEXT,
                metadata_json TEXT NOT NULL DEFAULT '{}'
            );
            CREATE TABLE IF NOT EXISTS t1_registration_artifacts (
                id TEXT PRIMARY KEY,
                study_id TEXT NOT NULL REFERENCES studies(id) ON DELETE CASCADE,
                subject_id TEXT NOT NULL REFERENCES subjects(id) ON DELETE CASCADE,
                state TEXT NOT NULL CHECK (
                    state IN ('REVIEW_REQUIRED', 'APPROVED', 'OUTDATED')
                ),
                version INTEGER NOT NULL CHECK (version > 0),
                active INTEGER NOT NULL CHECK (active IN (0, 1)),
                registered_post_path TEXT NOT NULL,
                registered_post_sha256 TEXT NOT NULL,
                transform_path TEXT NOT NULL,
                transform_sha256 TEXT NOT NULL,
                qc_preview_path TEXT NOT NULL,
                qc_preview_sha256 TEXT NOT NULL,
                source_pre_scan_input_id TEXT NOT NULL REFERENCES scan_inputs(id),
                source_post_scan_input_id TEXT NOT NULL REFERENCES scan_inputs(id),
                source_brain_mask_artifact_id TEXT NOT NULL
                    REFERENCES t1_brain_mask_artifacts(id),
                method_id TEXT NOT NULL REFERENCES t1_registration_methods(id),
                job_id TEXT NOT NULL REFERENCES t1_registration_jobs(id),
                before_xcorr REAL,
                after_xcorr REAL NOT NULL,
                registration_metric REAL NOT NULL,
                optimizer_stop TEXT NOT NULL,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                created_by TEXT NOT NULL,
                superseded_by TEXT REFERENCES t1_registration_artifacts(id),
                UNIQUE(subject_id, version)
            );
            CREATE TABLE IF NOT EXISTS t1_registration_reviews (
                id TEXT PRIMARY KEY,
                study_id TEXT NOT NULL REFERENCES studies(id) ON DELETE CASCADE,
                subject_id TEXT NOT NULL REFERENCES subjects(id) ON DELETE CASCADE,
                artifact_id TEXT NOT NULL UNIQUE
                    REFERENCES t1_registration_artifacts(id) ON DELETE CASCADE,
                reviewer TEXT NOT NULL CHECK (length(trim(reviewer)) > 0),
                study_blinding_state TEXT NOT NULL CHECK (
                    study_blinding_state IN ('BLINDED', 'UNBLINDED')
                ),
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS t1_enhancement_methods (
                id TEXT PRIMARY KEY,
                study_id TEXT NOT NULL REFERENCES studies(id) ON DELETE CASCADE,
                active INTEGER NOT NULL CHECK (active IN (0, 1)),
                method_version TEXT NOT NULL,
                method_spec_sha256 TEXT NOT NULL,
                scientific_status TEXT NOT NULL CHECK (
                    scientific_status IN ('PROVISIONAL', 'APPROVED', 'RETIRED')
                ),
                config_json TEXT NOT NULL DEFAULT '{}',
                registered_at TEXT NOT NULL,
                registered_by TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS t1_enhancement_jobs (
                id TEXT PRIMARY KEY,
                study_id TEXT NOT NULL REFERENCES studies(id) ON DELETE CASCADE,
                state TEXT NOT NULL CHECK (
                    state IN ('QUEUED', 'RUNNING', 'SUCCEEDED', 'FAILED', 'INTERRUPTED')
                ),
                stage TEXT,
                progress_current INTEGER,
                progress_total INTEGER,
                method_id TEXT NOT NULL REFERENCES t1_enhancement_methods(id),
                subject_ids_json TEXT NOT NULL DEFAULT '[]',
                submitted_at TEXT NOT NULL,
                started_at TEXT,
                finished_at TEXT,
                error_message TEXT,
                output_path TEXT,
                metadata_json TEXT NOT NULL DEFAULT '{}'
            );
            CREATE TABLE IF NOT EXISTS t1_enhancement_results (
                id TEXT PRIMARY KEY,
                study_id TEXT NOT NULL REFERENCES studies(id) ON DELETE CASCADE,
                subject_id TEXT NOT NULL REFERENCES subjects(id) ON DELETE CASCADE,
                version INTEGER NOT NULL CHECK (version > 0),
                state TEXT NOT NULL CHECK (state IN ('PROVISIONAL', 'OUTDATED')),
                active INTEGER NOT NULL CHECK (active IN (0, 1)),
                percent_enhancement_map TEXT NOT NULL,
                percent_enhancement_sha256 TEXT NOT NULL,
                summary_csv TEXT NOT NULL,
                summary_sha256 TEXT NOT NULL,
                qc_preview_path TEXT NOT NULL,
                qc_preview_sha256 TEXT NOT NULL,
                metadata_path TEXT NOT NULL,
                metadata_sha256 TEXT NOT NULL,
                source_registration_artifact_id TEXT NOT NULL
                    REFERENCES t1_registration_artifacts(id),
                source_brain_mask_artifact_id TEXT NOT NULL
                    REFERENCES t1_brain_mask_artifacts(id),
                source_pre_scan_input_id TEXT NOT NULL REFERENCES scan_inputs(id),
                method_id TEXT NOT NULL REFERENCES t1_enhancement_methods(id),
                job_id TEXT NOT NULL REFERENCES t1_enhancement_jobs(id),
                metrics_json TEXT NOT NULL DEFAULT '[]',
                metadata_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                created_by TEXT NOT NULL,
                outdated_at TEXT,
                outdated_reason TEXT,
                superseded_by TEXT REFERENCES t1_enhancement_results(id),
                UNIQUE(subject_id, version)
            );
            CREATE UNIQUE INDEX IF NOT EXISTS idx_t1_registration_methods_active
                ON t1_registration_methods(study_id) WHERE active = 1;
            CREATE INDEX IF NOT EXISTS idx_t1_registration_jobs_state
                ON t1_registration_jobs(study_id, state);
            CREATE INDEX IF NOT EXISTS idx_t1_registration_artifacts_subject
                ON t1_registration_artifacts(subject_id, version DESC);
            CREATE UNIQUE INDEX IF NOT EXISTS idx_t1_registration_artifacts_active
                ON t1_registration_artifacts(subject_id) WHERE active = 1;
            CREATE INDEX IF NOT EXISTS idx_t1_registration_reviews_subject_time
                ON t1_registration_reviews(subject_id, created_at DESC);
            CREATE UNIQUE INDEX IF NOT EXISTS idx_t1_enhancement_methods_active
                ON t1_enhancement_methods(study_id) WHERE active = 1;
            CREATE INDEX IF NOT EXISTS idx_t1_enhancement_jobs_state
                ON t1_enhancement_jobs(study_id, state);
            CREATE INDEX IF NOT EXISTS idx_t1_enhancement_results_subject
                ON t1_enhancement_results(subject_id, version DESC);
            CREATE UNIQUE INDEX IF NOT EXISTS idx_t1_enhancement_results_active
                ON t1_enhancement_results(subject_id) WHERE active = 1;
            """
        )
        version = 10
        connection.execute(
            "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
            (version, applied_at),
        )
        connection.execute(f"PRAGMA user_version = {version}")
    if version == 10:
        create_atlas_schema(connection)
        version = 11
        connection.execute(
            "INSERT OR REPLACE INTO schema_migrations(version, applied_at) VALUES (?, ?)",
            (version, applied_at),
        )
        connection.execute(f"PRAGMA user_version = {version}")
    if version != target_version:
        raise ValueError(
            f"No migration path exists from schema {from_version} to {target_version}."
        )
