"""SQLite persistence for immutable atlas mapping artifacts and approvals."""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any, Protocol
from uuid import uuid4

from lys_bbb.atlas_registration import AtlasToT1Output
from lys_bbb.atlas_release import MajorRegionScheme, ValidatedAtlasRelease
from lys_bbb.atlas_mapping import AtlasCompositeOutput, MajorRegionLesionResult
from lys_bbb.hashing import sha256_file
from lys_bbb.t1_t2_registration import T1ToT2Output
from lys_bbb_app.domain.atlas_mapping import (
    AtlasInT2CompositeRecord,
    AtlasMappingJobRecord,
    AtlasMappingState,
    AtlasReleaseRecord,
    AtlasReviewState,
    AtlasToT1ArtifactRecord,
    MajorRegionLesionResultRecord,
    MajorRegionSchemeRecord,
    T1ToT2ArtifactRecord,
    T2RegistrationSupportMaskRecord,
)
from lys_bbb_app.domain.errors import StudyStateError
from lys_bbb_app.domain.t2_lesion import ProcessingJobState
from lys_bbb_app.infrastructure.database_support import (
    connect,
    insert_audit,
    normalize_required,
    single_study,
    touch_study,
    utc_now,
)


class StudyDatabaseContext(Protocol):
    root_path: Path
    database_path: Path


def create_atlas_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS atlas_releases (
            id TEXT PRIMARY KEY,
            study_id TEXT NOT NULL REFERENCES studies(id) ON DELETE CASCADE,
            active INTEGER NOT NULL CHECK (active IN (0, 1)),
            release_version TEXT NOT NULL,
            aidamri_revision TEXT NOT NULL,
            template_path TEXT NOT NULL,
            template_sha256 TEXT NOT NULL,
            labels_path TEXT NOT NULL,
            labels_sha256 TEXT NOT NULL,
            source_lookup_path TEXT NOT NULL,
            source_lookup_sha256 TEXT NOT NULL,
            template_mask_path TEXT NOT NULL,
            template_mask_sha256 TEXT NOT NULL,
            geometry_json TEXT NOT NULL,
            registered_at TEXT NOT NULL,
            registered_by TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS major_region_schemes (
            id TEXT PRIMARY KEY,
            study_id TEXT NOT NULL REFERENCES studies(id) ON DELETE CASCADE,
            active INTEGER NOT NULL CHECK (active IN (0, 1)),
            state TEXT NOT NULL CHECK (
                state IN ('DRAFT_REVIEW_REQUIRED', 'APPROVED', 'OUTDATED')
            ),
            mapping_version TEXT NOT NULL,
            mapping_path TEXT NOT NULL,
            mapping_sha256 TEXT NOT NULL,
            source_label_count INTEGER NOT NULL CHECK (source_label_count > 0),
            major_region_count INTEGER NOT NULL CHECK (major_region_count > 0),
            registered_at TEXT NOT NULL,
            registered_by TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS major_region_scheme_reviews (
            id TEXT PRIMARY KEY,
            study_id TEXT NOT NULL REFERENCES studies(id) ON DELETE CASCADE,
            scheme_id TEXT NOT NULL UNIQUE
                REFERENCES major_region_schemes(id) ON DELETE CASCADE,
            mapping_sha256 TEXT NOT NULL,
            reviewer TEXT NOT NULL CHECK (length(trim(reviewer)) > 0),
            study_blinding_state TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS t2_registration_support_masks (
            id TEXT PRIMARY KEY,
            study_id TEXT NOT NULL REFERENCES studies(id) ON DELETE CASCADE,
            subject_id TEXT NOT NULL REFERENCES subjects(id) ON DELETE CASCADE,
            active INTEGER NOT NULL CHECK (active IN (0, 1)),
            state TEXT NOT NULL CHECK (
                state IN ('DRAFT_REVIEW_REQUIRED', 'APPROVED', 'OUTDATED')
            ),
            version INTEGER NOT NULL CHECK (version > 0),
            mask_path TEXT NOT NULL,
            mask_sha256 TEXT NOT NULL,
            source_t2_scan_input_id TEXT NOT NULL REFERENCES scan_inputs(id),
            created_at TEXT NOT NULL,
            created_by TEXT NOT NULL,
            superseded_by TEXT REFERENCES t2_registration_support_masks(id),
            UNIQUE(subject_id, version)
        );
        CREATE TABLE IF NOT EXISTS t2_registration_support_mask_reviews (
            id TEXT PRIMARY KEY,
            study_id TEXT NOT NULL REFERENCES studies(id) ON DELETE CASCADE,
            subject_id TEXT NOT NULL REFERENCES subjects(id) ON DELETE CASCADE,
            artifact_id TEXT NOT NULL UNIQUE
                REFERENCES t2_registration_support_masks(id) ON DELETE CASCADE,
            mask_sha256 TEXT NOT NULL,
            reviewer TEXT NOT NULL CHECK (length(trim(reviewer)) > 0),
            study_blinding_state TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS atlas_to_t1_methods (
            id TEXT PRIMARY KEY,
            study_id TEXT NOT NULL REFERENCES studies(id) ON DELETE CASCADE,
            active INTEGER NOT NULL CHECK (active IN (0, 1)),
            method_version TEXT NOT NULL,
            method_spec_sha256 TEXT NOT NULL,
            config_json TEXT NOT NULL,
            registered_at TEXT NOT NULL,
            registered_by TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS atlas_to_t1_jobs (
            id TEXT PRIMARY KEY,
            study_id TEXT NOT NULL REFERENCES studies(id) ON DELETE CASCADE,
            subject_id TEXT NOT NULL REFERENCES subjects(id) ON DELETE CASCADE,
            state TEXT NOT NULL CHECK (
                state IN ('QUEUED', 'RUNNING', 'SUCCEEDED', 'FAILED', 'INTERRUPTED')
            ),
            stage TEXT NOT NULL,
            progress_current INTEGER,
            progress_total INTEGER,
            method_id TEXT NOT NULL REFERENCES atlas_to_t1_methods(id),
            submitted_at TEXT NOT NULL,
            started_at TEXT,
            finished_at TEXT,
            error_message TEXT,
            output_path TEXT,
            metadata_json TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS atlas_to_t1_artifacts (
            id TEXT PRIMARY KEY,
            study_id TEXT NOT NULL REFERENCES studies(id) ON DELETE CASCADE,
            subject_id TEXT NOT NULL REFERENCES subjects(id) ON DELETE CASCADE,
            active INTEGER NOT NULL CHECK (active IN (0, 1)),
            state TEXT NOT NULL CHECK (
                state IN ('DRAFT_REVIEW_REQUIRED', 'APPROVED', 'OUTDATED')
            ),
            candidate TEXT NOT NULL CHECK (candidate IN ('rigid', 'affine', 'syn')),
            transform_path TEXT NOT NULL,
            transform_sha256 TEXT NOT NULL,
            warped_intensity_path TEXT NOT NULL,
            warped_intensity_sha256 TEXT NOT NULL,
            warped_support_path TEXT NOT NULL,
            warped_support_sha256 TEXT NOT NULL,
            qc_path TEXT NOT NULL,
            qc_sha256 TEXT NOT NULL,
            metadata_path TEXT NOT NULL,
            metadata_sha256 TEXT NOT NULL,
            source_pre_scan_input_id TEXT NOT NULL REFERENCES scan_inputs(id),
            source_t1_mask_artifact_id TEXT NOT NULL REFERENCES t1_brain_mask_artifacts(id),
            atlas_release_id TEXT NOT NULL REFERENCES atlas_releases(id),
            method_id TEXT NOT NULL REFERENCES atlas_to_t1_methods(id),
            job_id TEXT NOT NULL REFERENCES atlas_to_t1_jobs(id),
            created_at TEXT NOT NULL,
            created_by TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS atlas_to_t1_reviews (
            id TEXT PRIMARY KEY,
            study_id TEXT NOT NULL REFERENCES studies(id) ON DELETE CASCADE,
            subject_id TEXT NOT NULL REFERENCES subjects(id) ON DELETE CASCADE,
            artifact_id TEXT NOT NULL UNIQUE
                REFERENCES atlas_to_t1_artifacts(id) ON DELETE CASCADE,
            transform_sha256 TEXT NOT NULL,
            warped_intensity_sha256 TEXT NOT NULL,
            warped_support_sha256 TEXT NOT NULL,
            qc_sha256 TEXT NOT NULL,
            metadata_sha256 TEXT NOT NULL,
            reviewer TEXT NOT NULL CHECK (length(trim(reviewer)) > 0),
            study_blinding_state TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS t1_to_t2_methods (
            id TEXT PRIMARY KEY,
            study_id TEXT NOT NULL REFERENCES studies(id) ON DELETE CASCADE,
            active INTEGER NOT NULL CHECK (active IN (0, 1)),
            method_version TEXT NOT NULL,
            method_spec_sha256 TEXT NOT NULL,
            config_json TEXT NOT NULL,
            registered_at TEXT NOT NULL,
            registered_by TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS t1_to_t2_jobs (
            id TEXT PRIMARY KEY,
            study_id TEXT NOT NULL REFERENCES studies(id) ON DELETE CASCADE,
            subject_id TEXT NOT NULL REFERENCES subjects(id) ON DELETE CASCADE,
            state TEXT NOT NULL CHECK (
                state IN ('QUEUED', 'RUNNING', 'SUCCEEDED', 'FAILED', 'INTERRUPTED')
            ),
            stage TEXT NOT NULL,
            progress_current INTEGER,
            progress_total INTEGER,
            method_id TEXT NOT NULL REFERENCES t1_to_t2_methods(id),
            submitted_at TEXT NOT NULL,
            started_at TEXT,
            finished_at TEXT,
            error_message TEXT,
            output_path TEXT,
            metadata_json TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS t1_to_t2_artifacts (
            id TEXT PRIMARY KEY,
            study_id TEXT NOT NULL REFERENCES studies(id) ON DELETE CASCADE,
            subject_id TEXT NOT NULL REFERENCES subjects(id) ON DELETE CASCADE,
            active INTEGER NOT NULL CHECK (active IN (0, 1)),
            state TEXT NOT NULL CHECK (
                state IN ('DRAFT_REVIEW_REQUIRED', 'APPROVED', 'OUTDATED')
            ),
            transform_path TEXT NOT NULL,
            transform_sha256 TEXT NOT NULL,
            transformed_t1_path TEXT NOT NULL,
            transformed_t1_sha256 TEXT NOT NULL,
            transformed_t1_mask_path TEXT NOT NULL,
            transformed_t1_mask_sha256 TEXT NOT NULL,
            qc_montage_path TEXT NOT NULL,
            qc_montage_sha256 TEXT NOT NULL,
            qc_manifest_path TEXT NOT NULL,
            qc_manifest_sha256 TEXT NOT NULL,
            qc_slice_paths_json TEXT NOT NULL,
            metadata_path TEXT NOT NULL,
            metadata_sha256 TEXT NOT NULL,
            source_pre_scan_input_id TEXT NOT NULL REFERENCES scan_inputs(id),
            source_t2_scan_input_id TEXT NOT NULL REFERENCES scan_inputs(id),
            source_t1_mask_artifact_id TEXT NOT NULL REFERENCES t1_brain_mask_artifacts(id),
            source_t2_support_mask_id TEXT NOT NULL
                REFERENCES t2_registration_support_masks(id),
            lesion_exclusion_artifact_id TEXT REFERENCES artifacts(id),
            lesion_exclusion_sha256 TEXT,
            method_id TEXT NOT NULL REFERENCES t1_to_t2_methods(id),
            job_id TEXT NOT NULL REFERENCES t1_to_t2_jobs(id),
            created_at TEXT NOT NULL,
            created_by TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS t1_to_t2_reviews (
            id TEXT PRIMARY KEY,
            study_id TEXT NOT NULL REFERENCES studies(id) ON DELETE CASCADE,
            subject_id TEXT NOT NULL REFERENCES subjects(id) ON DELETE CASCADE,
            artifact_id TEXT NOT NULL UNIQUE
                REFERENCES t1_to_t2_artifacts(id) ON DELETE CASCADE,
            transform_sha256 TEXT NOT NULL,
            transformed_t1_sha256 TEXT NOT NULL,
            transformed_t1_mask_sha256 TEXT NOT NULL,
            qc_montage_sha256 TEXT NOT NULL,
            qc_manifest_sha256 TEXT NOT NULL,
            metadata_sha256 TEXT NOT NULL,
            reviewer TEXT NOT NULL CHECK (length(trim(reviewer)) > 0),
            study_blinding_state TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS atlas_t2_composites (
            id TEXT PRIMARY KEY,
            study_id TEXT NOT NULL REFERENCES studies(id) ON DELETE CASCADE,
            subject_id TEXT NOT NULL REFERENCES subjects(id) ON DELETE CASCADE,
            active INTEGER NOT NULL CHECK (active IN (0, 1)),
            state TEXT NOT NULL CHECK (
                state IN ('DRAFT_REVIEW_REQUIRED', 'APPROVED', 'OUTDATED')
            ),
            labels_path TEXT NOT NULL,
            labels_sha256 TEXT NOT NULL,
            support_path TEXT NOT NULL,
            support_sha256 TEXT NOT NULL,
            qc_montage_path TEXT NOT NULL,
            qc_montage_sha256 TEXT NOT NULL,
            qc_manifest_path TEXT NOT NULL,
            qc_manifest_sha256 TEXT NOT NULL,
            qc_slice_paths_json TEXT NOT NULL,
            metadata_path TEXT NOT NULL,
            metadata_sha256 TEXT NOT NULL,
            source_atlas_to_t1_artifact_id TEXT NOT NULL
                REFERENCES atlas_to_t1_artifacts(id),
            source_t1_to_t2_artifact_id TEXT NOT NULL REFERENCES t1_to_t2_artifacts(id),
            atlas_release_id TEXT NOT NULL REFERENCES atlas_releases(id),
            major_region_scheme_id TEXT NOT NULL REFERENCES major_region_schemes(id),
            source_t2_scan_input_id TEXT NOT NULL REFERENCES scan_inputs(id),
            created_at TEXT NOT NULL,
            created_by TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS atlas_t2_composite_reviews (
            id TEXT PRIMARY KEY,
            study_id TEXT NOT NULL REFERENCES studies(id) ON DELETE CASCADE,
            subject_id TEXT NOT NULL REFERENCES subjects(id) ON DELETE CASCADE,
            artifact_id TEXT NOT NULL UNIQUE REFERENCES atlas_t2_composites(id),
            labels_sha256 TEXT NOT NULL,
            support_sha256 TEXT NOT NULL,
            qc_montage_sha256 TEXT NOT NULL,
            qc_manifest_sha256 TEXT NOT NULL,
            metadata_sha256 TEXT NOT NULL,
            reviewer TEXT NOT NULL CHECK (length(trim(reviewer)) > 0),
            study_blinding_state TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS major_region_lesion_results (
            id TEXT PRIMARY KEY,
            study_id TEXT NOT NULL REFERENCES studies(id) ON DELETE CASCADE,
            subject_id TEXT NOT NULL REFERENCES subjects(id) ON DELETE CASCADE,
            active INTEGER NOT NULL CHECK (active IN (0, 1)),
            state TEXT NOT NULL CHECK (state IN ('APPROVED', 'OUTDATED')),
            result_csv_path TEXT NOT NULL,
            result_csv_sha256 TEXT NOT NULL,
            metadata_path TEXT NOT NULL,
            metadata_sha256 TEXT NOT NULL,
            lesion_voxel_count INTEGER NOT NULL CHECK (lesion_voxel_count >= 0),
            lesion_volume_mm3 REAL NOT NULL CHECK (lesion_volume_mm3 >= 0),
            mapped_lesion_voxels INTEGER NOT NULL CHECK (mapped_lesion_voxels >= 0),
            unmapped_lesion_voxels INTEGER NOT NULL CHECK (unmapped_lesion_voxels >= 0),
            outside_atlas_support_lesion_voxels INTEGER NOT NULL CHECK (
                outside_atlas_support_lesion_voxels >= 0
            ),
            boundary_lesion_voxels INTEGER NOT NULL CHECK (boundary_lesion_voxels >= 0),
            sensitivity_status TEXT NOT NULL,
            source_composite_artifact_id TEXT NOT NULL REFERENCES atlas_t2_composites(id),
            source_lesion_artifact_id TEXT NOT NULL REFERENCES artifacts(id),
            source_lesion_sha256 TEXT NOT NULL,
            major_region_scheme_id TEXT NOT NULL REFERENCES major_region_schemes(id),
            created_at TEXT NOT NULL,
            created_by TEXT NOT NULL
        );
        CREATE UNIQUE INDEX IF NOT EXISTS idx_atlas_releases_active
            ON atlas_releases(study_id) WHERE active = 1;
        CREATE UNIQUE INDEX IF NOT EXISTS idx_major_region_schemes_active
            ON major_region_schemes(study_id) WHERE active = 1;
        CREATE UNIQUE INDEX IF NOT EXISTS idx_t2_support_active
            ON t2_registration_support_masks(subject_id) WHERE active = 1;
        CREATE UNIQUE INDEX IF NOT EXISTS idx_atlas_to_t1_methods_active
            ON atlas_to_t1_methods(study_id) WHERE active = 1;
        CREATE INDEX IF NOT EXISTS idx_atlas_to_t1_jobs_state
            ON atlas_to_t1_jobs(study_id, state);
        CREATE INDEX IF NOT EXISTS idx_atlas_to_t1_artifacts_subject
            ON atlas_to_t1_artifacts(subject_id, created_at DESC);
        CREATE UNIQUE INDEX IF NOT EXISTS idx_atlas_to_t1_selected_active
            ON atlas_to_t1_artifacts(subject_id) WHERE active = 1;
        CREATE UNIQUE INDEX IF NOT EXISTS idx_t1_to_t2_methods_active
            ON t1_to_t2_methods(study_id) WHERE active = 1;
        CREATE INDEX IF NOT EXISTS idx_t1_to_t2_jobs_state
            ON t1_to_t2_jobs(study_id, state);
        CREATE UNIQUE INDEX IF NOT EXISTS idx_t1_to_t2_active
            ON t1_to_t2_artifacts(subject_id) WHERE active = 1;
        CREATE UNIQUE INDEX IF NOT EXISTS idx_atlas_t2_composites_active
            ON atlas_t2_composites(subject_id) WHERE active = 1;
        CREATE UNIQUE INDEX IF NOT EXISTS idx_major_region_results_active
            ON major_region_lesion_results(subject_id) WHERE active = 1;
        """
    )


class AtlasMappingRepository:
    def __init__(self, context: StudyDatabaseContext):
        self.root_path = context.root_path
        self.database_path = context.database_path

    def register_release(
        self, release: ValidatedAtlasRelease, *, actor: str
    ) -> str:
        actor = normalize_required(actor, "Actor")
        release_id = str(uuid4())
        now = utc_now()
        geometry = {
            "shape": release.template_geometry.shape,
            "spacing_mm": release.template_geometry.spacing_mm,
            "affine": release.template_geometry.affine,
            "orientation": release.template_geometry.orientation,
            "qform_code": release.template_geometry.qform_code,
            "sform_code": release.template_geometry.sform_code,
            "qform": release.template_geometry.qform,
            "sform": release.template_geometry.sform,
            "physical_bounds_mm": release.template_geometry.physical_bounds_mm,
            "physical_extent_mm": release.template_geometry.physical_extent_mm,
            "handedness": release.template_geometry.handedness,
        }
        with closing(connect(self.database_path)) as connection, connection:
            study = single_study(connection)
            previous = connection.execute(
                "SELECT id FROM atlas_releases WHERE study_id = ? AND active = 1",
                (study["id"],),
            ).fetchone()
            connection.execute(
                "UPDATE atlas_releases SET active = 0 WHERE study_id = ? AND active = 1",
                (study["id"],),
            )
            connection.execute(
                """
                INSERT INTO atlas_releases(
                    id, study_id, active, release_version, aidamri_revision,
                    template_path, template_sha256, labels_path, labels_sha256,
                    source_lookup_path, source_lookup_sha256, template_mask_path,
                    template_mask_sha256, geometry_json, registered_at, registered_by
                ) VALUES (?, ?, 1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    release_id,
                    study["id"],
                    release.spec.release_version,
                    release.spec.revision,
                    str(release.spec.template_path),
                    release.spec.template_sha256,
                    str(release.spec.labels_path),
                    release.spec.labels_sha256,
                    str(release.spec.source_lookup_path),
                    release.spec.source_lookup_sha256,
                    str(release.spec.template_mask_path),
                    release.template_mask_sha256,
                    json.dumps(geometry, sort_keys=True),
                    now,
                    actor,
                ),
            )
            if previous is not None:
                self._invalidate_all_subjects(
                    connection, "Atlas release changed", now, invalidate_atlas_to_t1=True
                )
            insert_audit(
                connection,
                study_id=study["id"],
                event_type="ATLAS_RELEASE_REGISTERED",
                actor=actor,
                details={"release_id": release_id, "checksums_reverified": True},
                created_at=now,
            )
            touch_study(connection, study["id"], now)
        return release_id

    def register_scheme(self, scheme: MajorRegionScheme, *, actor: str) -> str:
        actor = normalize_required(actor, "Actor")
        scheme_id = str(uuid4())
        now = utc_now()
        region_count = len({row.major_region_id for row in scheme.rows})
        with closing(connect(self.database_path)) as connection, connection:
            study = single_study(connection)
            connection.execute(
                "UPDATE major_region_schemes SET active = 0, state = 'OUTDATED' "
                "WHERE study_id = ? AND active = 1",
                (study["id"],),
            )
            connection.execute(
                """
                INSERT INTO major_region_schemes(
                    id, study_id, active, state, mapping_version, mapping_path,
                    mapping_sha256, source_label_count, major_region_count,
                    registered_at, registered_by
                ) VALUES (?, ?, 1, 'DRAFT_REVIEW_REQUIRED', ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    scheme_id,
                    study["id"],
                    scheme.mapping_version,
                    str(scheme.path.resolve()),
                    scheme.sha256,
                    len(scheme.rows),
                    region_count,
                    now,
                    actor,
                ),
            )
            self._invalidate_all_subjects(
                connection, "Major-region scheme changed", now, invalidate_atlas_to_t1=False
            )
            insert_audit(
                connection,
                study_id=study["id"],
                event_type="MAJOR_REGION_SCHEME_DRAFT_REGISTERED",
                actor=actor,
                details={"scheme_id": scheme_id, "mapping_sha256": scheme.sha256},
                created_at=now,
            )
            touch_study(connection, study["id"], now)
        return scheme_id

    def approve_scheme(self, scheme_id: str, *, reviewer: str) -> None:
        reviewer = normalize_required(reviewer, "Reviewer identity")
        now = utc_now()
        with closing(connect(self.database_path)) as connection, connection:
            study = single_study(connection)
            row = connection.execute(
                "SELECT * FROM major_region_schemes WHERE id = ? AND active = 1",
                (scheme_id,),
            ).fetchone()
            if row is None or row["state"] != "DRAFT_REVIEW_REQUIRED":
                raise StudyStateError("The active draft major-region scheme is unavailable.")
            _verify(Path(row["mapping_path"]), row["mapping_sha256"], "mapping")
            connection.execute(
                "INSERT INTO major_region_scheme_reviews VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    str(uuid4()), study["id"], scheme_id, row["mapping_sha256"], reviewer,
                    study["blinding_state"], now,
                ),
            )
            connection.execute(
                "UPDATE major_region_schemes SET state = 'APPROVED' WHERE id = ?",
                (scheme_id,),
            )
            insert_audit(
                connection,
                study_id=study["id"],
                event_type="MAJOR_REGION_SCHEME_APPROVED",
                actor=reviewer,
                details={"scheme_id": scheme_id, "mapping_sha256": row["mapping_sha256"]},
                created_at=now,
            )

    def create_t2_support_mask(
        self,
        *,
        subject_id: str,
        source_t2_scan_input_id: str,
        mask_path: Path,
        mask_sha256: str,
        actor: str,
    ) -> str:
        actor = normalize_required(actor, "Actor")
        _verify(mask_path, mask_sha256, "T2 registration-support mask")
        artifact_id = str(uuid4())
        now = utc_now()
        with closing(connect(self.database_path)) as connection, connection:
            study = single_study(connection)
            source = connection.execute(
                """
                SELECT id FROM scan_inputs WHERE id = ? AND subject_id = ? AND role = 'T2'
                  AND active = 1 AND state = 'CONVERTED' AND validation_state = 'VALID'
                """,
                (source_t2_scan_input_id, subject_id),
            ).fetchone()
            if source is None:
                raise StudyStateError("A current validated native T2 is required.")
            previous = connection.execute(
                "SELECT id, version FROM t2_registration_support_masks "
                "WHERE subject_id = ? AND active = 1",
                (subject_id,),
            ).fetchone()
            version = int(previous["version"]) + 1 if previous else 1
            connection.execute(
                "UPDATE t2_registration_support_masks SET active = 0, state = 'OUTDATED', "
                "superseded_by = ? WHERE subject_id = ? AND active = 1",
                (artifact_id, subject_id),
            )
            connection.execute(
                """
                INSERT INTO t2_registration_support_masks(
                    id, study_id, subject_id, active, state, version, mask_path,
                    mask_sha256, source_t2_scan_input_id, created_at, created_by
                ) VALUES (?, ?, ?, 1, 'DRAFT_REVIEW_REQUIRED', ?, ?, ?, ?, ?, ?)
                """,
                (
                    artifact_id, study["id"], subject_id, version,
                    _relative(self.root_path, mask_path), mask_sha256,
                    source_t2_scan_input_id, now, actor,
                ),
            )
            self._invalidate_subject(
                connection, subject_id, "T2 support mask changed", now, False
            )
            insert_audit(
                connection,
                study_id=study["id"],
                subject_id=subject_id,
                event_type="ATLAS_T2_SUPPORT_MASK_DRAFT_CREATED",
                actor=actor,
                details={
                    "artifact_id": artifact_id,
                    "mask_sha256": mask_sha256,
                    "source_t2_scan_input_id": source_t2_scan_input_id,
                },
                created_at=now,
            )
            touch_study(connection, study["id"], now)
        return artifact_id

    def approve_t2_support_mask(self, artifact_id: str, *, reviewer: str) -> None:
        reviewer = normalize_required(reviewer, "Reviewer identity")
        now = utc_now()
        with closing(connect(self.database_path)) as connection, connection:
            study = single_study(connection)
            row = connection.execute(
                "SELECT * FROM t2_registration_support_masks WHERE id = ? AND active = 1",
                (artifact_id,),
            ).fetchone()
            if row is None or row["state"] != "DRAFT_REVIEW_REQUIRED":
                raise StudyStateError("The current draft T2 support mask is unavailable.")
            _verify(self.root_path / row["mask_path"], row["mask_sha256"], "T2 mask")
            connection.execute(
                "INSERT INTO t2_registration_support_mask_reviews VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    str(uuid4()), study["id"], row["subject_id"], artifact_id,
                    row["mask_sha256"], reviewer, study["blinding_state"], now,
                ),
            )
            connection.execute(
                "UPDATE t2_registration_support_masks SET state = 'APPROVED' WHERE id = ?",
                (artifact_id,),
            )
            insert_audit(
                connection,
                study_id=study["id"],
                subject_id=row["subject_id"],
                event_type="ATLAS_T2_SUPPORT_MASK_APPROVED",
                actor=reviewer,
                details={"artifact_id": artifact_id, "mask_sha256": row["mask_sha256"]},
                created_at=now,
            )
            touch_study(connection, study["id"], now)

    def register_method(
        self,
        kind: str,
        *,
        method_version: str,
        method_spec_sha256: str,
        config: dict[str, Any],
        actor: str,
    ) -> str:
        table = _method_table(kind)
        method_id = str(uuid4())
        now = utc_now()
        with closing(connect(self.database_path)) as connection, connection:
            study = single_study(connection)
            existing = connection.execute(
                f"SELECT id FROM {table} WHERE study_id = ? AND method_spec_sha256 = ?",
                (study["id"], method_spec_sha256),
            ).fetchone()
            if existing:
                connection.execute(
                    f"UPDATE {table} SET active = CASE WHEN id = ? THEN 1 ELSE 0 END "
                    "WHERE study_id = ?",
                    (existing["id"], study["id"]),
                )
                return str(existing["id"])
            connection.execute(
                f"UPDATE {table} SET active = 0 WHERE study_id = ?", (study["id"],)
            )
            connection.execute(
                f"INSERT INTO {table} VALUES (?, ?, 1, ?, ?, ?, ?, ?)",
                (
                    method_id, study["id"], method_version, method_spec_sha256,
                    json.dumps(config, sort_keys=True), now,
                    normalize_required(actor, "Actor"),
                ),
            )
        return method_id

    def create_job(
        self, kind: str, *, subject_id: str, method_id: str, actor: str
    ) -> str:
        table = _job_table(kind)
        job_id = str(uuid4())
        now = utc_now()
        with closing(connect(self.database_path)) as connection, connection:
            study = single_study(connection)
            connection.execute(
                f"""
                INSERT INTO {table}(
                    id, study_id, subject_id, state, stage, progress_current,
                    progress_total, method_id, submitted_at, metadata_json
                ) VALUES (?, ?, ?, 'QUEUED', 'queued', 0, 1, ?, ?, ?)
                """,
                (
                    job_id, study["id"], subject_id, method_id, now,
                    json.dumps({"submitted_by": normalize_required(actor, "Actor")}),
                ),
            )
        return job_id

    def start_job(self, kind: str, job_id: str, *, total: int) -> None:
        table = _job_table(kind)
        with closing(connect(self.database_path)) as connection, connection:
            changed = connection.execute(
                f"UPDATE {table} SET state = 'RUNNING', stage = 'starting', "
                "progress_total = ?, started_at = ? WHERE id = ? AND state = 'QUEUED'",
                (total, utc_now(), job_id),
            ).rowcount
            if changed != 1:
                raise StudyStateError("The atlas mapping job cannot be started.")

    def update_job(self, kind: str, job_id: str, current: int, total: int, stage: str) -> None:
        table = _job_table(kind)
        with closing(connect(self.database_path)) as connection, connection:
            connection.execute(
                f"UPDATE {table} SET stage = ?, progress_current = ?, progress_total = ? "
                "WHERE id = ? AND state = 'RUNNING'",
                (stage, current, total, job_id),
            )

    def fail_job(self, kind: str, job_id: str, error: str) -> None:
        table = _job_table(kind)
        with closing(connect(self.database_path)) as connection, connection:
            connection.execute(
                f"UPDATE {table} SET state = 'FAILED', stage = 'failed', finished_at = ?, "
                "error_message = ? WHERE id = ? AND state IN ('QUEUED', 'RUNNING')",
                (utc_now(), normalize_required(error, "Error"), job_id),
            )

    def complete_atlas_to_t1(
        self,
        *,
        job_id: str,
        subject_id: str,
        method_id: str,
        source_pre_scan_input_id: str,
        source_t1_mask_artifact_id: str,
        atlas_release_id: str,
        output: AtlasToT1Output,
        qc_by_candidate: dict[str, Path],
        actor: str,
    ) -> tuple[str, ...]:
        now = utc_now()
        ids: list[str] = []
        with closing(connect(self.database_path)) as connection, connection:
            study = single_study(connection)
            _verify(output.metadata_path, output.metadata_sha256, "atlas metadata")
            for candidate in output.candidates:
                qc = qc_by_candidate[candidate.candidate]
                _verify(candidate.transform_path, candidate.transform_sha256, "transform")
                _verify(
                    candidate.warped_intensity_path,
                    candidate.warped_intensity_sha256,
                    "warped atlas intensity",
                )
                _verify(
                    candidate.warped_support_path,
                    candidate.warped_support_sha256,
                    "warped atlas support",
                )
                if not qc.is_file():
                    raise StudyStateError(f"Atlas candidate QC is unavailable: {qc}")
                artifact_id = str(uuid4())
                ids.append(artifact_id)
                connection.execute(
                    """
                    INSERT INTO atlas_to_t1_artifacts(
                        id, study_id, subject_id, active, state, candidate,
                        transform_path, transform_sha256, warped_intensity_path,
                        warped_intensity_sha256, warped_support_path,
                        warped_support_sha256, qc_path, qc_sha256, metadata_path,
                        metadata_sha256, source_pre_scan_input_id,
                        source_t1_mask_artifact_id, atlas_release_id, method_id,
                        job_id, created_at, created_by
                    ) VALUES (?, ?, ?, 0, 'DRAFT_REVIEW_REQUIRED', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        artifact_id, study["id"], subject_id, candidate.candidate,
                        _relative(self.root_path, candidate.transform_path),
                        candidate.transform_sha256,
                        _relative(self.root_path, candidate.warped_intensity_path),
                        candidate.warped_intensity_sha256,
                        _relative(self.root_path, candidate.warped_support_path),
                        candidate.warped_support_sha256,
                        _relative(self.root_path, qc), sha256_file(qc),
                        _relative(self.root_path, output.metadata_path),
                        output.metadata_sha256, source_pre_scan_input_id,
                        source_t1_mask_artifact_id, atlas_release_id, method_id,
                        job_id, now, normalize_required(actor, "Actor"),
                    ),
                )
            connection.execute(
                "UPDATE atlas_to_t1_jobs SET state = 'SUCCEEDED', stage = 'review_required', "
                "progress_current = progress_total, finished_at = ?, output_path = ? WHERE id = ?",
                (now, _relative(self.root_path, output.metadata_path.parent), job_id),
            )
        return tuple(ids)

    def approve_atlas_to_t1(self, artifact_id: str, *, reviewer: str) -> None:
        reviewer = normalize_required(reviewer, "Reviewer identity")
        now = utc_now()
        with closing(connect(self.database_path)) as connection, connection:
            study = single_study(connection)
            row = connection.execute(
                "SELECT * FROM atlas_to_t1_artifacts WHERE id = ?",
                (artifact_id,),
            ).fetchone()
            if row is None or row["state"] != "DRAFT_REVIEW_REQUIRED":
                raise StudyStateError("The atlas-to-T1 candidate is unavailable for review.")
            for column, label in (
                ("transform", "transform"), ("warped_intensity", "warped atlas"),
                ("warped_support", "warped atlas support"),
                ("qc", "QC"), ("metadata", "metadata"),
            ):
                _verify(
                    self.root_path / row[f"{column}_path"], row[f"{column}_sha256"], label
                )
            connection.execute(
                "UPDATE atlas_to_t1_artifacts SET active = 0, state = 'OUTDATED' "
                "WHERE subject_id = ? AND active = 1",
                (row["subject_id"],),
            )
            connection.execute(
                "UPDATE atlas_to_t1_artifacts SET active = 1, state = 'APPROVED' WHERE id = ?",
                (artifact_id,),
            )
            connection.execute(
                """
                INSERT INTO atlas_to_t1_reviews VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(uuid4()), study["id"], row["subject_id"], artifact_id,
                    row["transform_sha256"], row["warped_intensity_sha256"],
                    row["warped_support_sha256"], row["qc_sha256"],
                    row["metadata_sha256"], reviewer,
                    study["blinding_state"], now,
                ),
            )
            self._invalidate_subject(
                connection, row["subject_id"], "Atlas-to-T1 candidate changed", now, False
            )
            insert_audit(
                connection,
                study_id=study["id"],
                subject_id=row["subject_id"],
                event_type="ATLAS_TO_T1_CANDIDATE_APPROVED",
                actor=reviewer,
                details={
                    "artifact_id": artifact_id,
                    "candidate": row["candidate"],
                    "transform_sha256": row["transform_sha256"],
                    "metadata_sha256": row["metadata_sha256"],
                },
                created_at=now,
            )
            touch_study(connection, study["id"], now)

    def complete_t1_to_t2(
        self,
        *,
        job_id: str,
        subject_id: str,
        method_id: str,
        source_pre_scan_input_id: str,
        source_t2_scan_input_id: str,
        source_t1_mask_artifact_id: str,
        source_t2_support_mask_id: str,
        lesion_exclusion_artifact_id: str | None,
        output: T1ToT2Output,
        qc_montage_path: Path,
        qc_manifest_path: Path,
        qc_slice_paths: tuple[Path, ...],
        actor: str,
    ) -> str:
        artifact_id = str(uuid4())
        now = utc_now()
        with closing(connect(self.database_path)) as connection, connection:
            study = single_study(connection)
            for path, digest, label in (
                (output.transform_path, output.transform_sha256, "T1-to-T2 transform"),
                (
                    output.transformed_t1_path,
                    output.transformed_t1_sha256,
                    "transformed pre-T1",
                ),
                (
                    output.transformed_t1_brain_mask_path,
                    output.transformed_t1_brain_mask_sha256,
                    "transformed pre-T1 mask",
                ),
                (output.metadata_path, output.metadata_sha256, "T1-to-T2 metadata"),
            ):
                _verify(path, digest, label)
            _require_qc_files(qc_montage_path, qc_manifest_path, qc_slice_paths)
            connection.execute(
                "UPDATE t1_to_t2_artifacts SET active = 0, state = 'OUTDATED' "
                "WHERE subject_id = ? AND active = 1",
                (subject_id,),
            )
            connection.execute(
                """
                INSERT INTO t1_to_t2_artifacts(
                    id, study_id, subject_id, active, state, transform_path,
                    transform_sha256, transformed_t1_path, transformed_t1_sha256,
                    transformed_t1_mask_path, transformed_t1_mask_sha256,
                    qc_montage_path, qc_montage_sha256, qc_manifest_path,
                    qc_manifest_sha256, qc_slice_paths_json, metadata_path,
                    metadata_sha256, source_pre_scan_input_id,
                    source_t2_scan_input_id, source_t1_mask_artifact_id,
                    source_t2_support_mask_id, lesion_exclusion_artifact_id,
                    lesion_exclusion_sha256, method_id, job_id, created_at, created_by
                ) VALUES (?, ?, ?, 1, 'DRAFT_REVIEW_REQUIRED', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    artifact_id, study["id"], subject_id,
                    _relative(self.root_path, output.transform_path), output.transform_sha256,
                    _relative(self.root_path, output.transformed_t1_path),
                    output.transformed_t1_sha256,
                    _relative(self.root_path, output.transformed_t1_brain_mask_path),
                    output.transformed_t1_brain_mask_sha256,
                    _relative(self.root_path, qc_montage_path), sha256_file(qc_montage_path),
                    _relative(self.root_path, qc_manifest_path), sha256_file(qc_manifest_path),
                    json.dumps([_relative(self.root_path, path) for path in qc_slice_paths]),
                    _relative(self.root_path, output.metadata_path),
                    output.metadata_sha256,
                    source_pre_scan_input_id, source_t2_scan_input_id,
                    source_t1_mask_artifact_id, source_t2_support_mask_id,
                    lesion_exclusion_artifact_id,
                    output.input_sha256.get("lesion_exclusion_mask"), method_id, job_id,
                    now, normalize_required(actor, "Actor"),
                ),
            )
            connection.execute(
                "UPDATE t1_to_t2_jobs SET state = 'SUCCEEDED', stage = 'review_required', "
                "progress_current = progress_total, finished_at = ?, output_path = ? WHERE id = ?",
                (now, _relative(self.root_path, output.metadata_path.parent), job_id),
            )
            self._outdate_composite_and_results(connection, subject_id, now, "New T1-to-T2 mapping")
        return artifact_id

    def approve_t1_to_t2(self, artifact_id: str, *, reviewer: str) -> None:
        self._approve_artifact(
            table="t1_to_t2_artifacts",
            review_table="t1_to_t2_reviews",
            artifact_id=artifact_id,
            hashes=(
                "transform",
                "transformed_t1",
                "transformed_t1_mask",
                "qc_montage",
                "qc_manifest",
                "metadata",
            ),
            reviewer=reviewer,
        )

    def complete_composite(
        self,
        *,
        subject_id: str,
        source_atlas_to_t1_artifact_id: str,
        source_t1_to_t2_artifact_id: str,
        atlas_release_id: str,
        major_region_scheme_id: str,
        source_t2_scan_input_id: str,
        output: AtlasCompositeOutput,
        qc_montage_path: Path,
        qc_manifest_path: Path,
        qc_slice_paths: tuple[Path, ...],
        actor: str,
    ) -> str:
        artifact_id = str(uuid4())
        now = utc_now()
        with closing(connect(self.database_path)) as connection, connection:
            study = single_study(connection)
            for path, digest, label in (
                (
                    output.labels_in_native_t2_path,
                    output.labels_in_native_t2_sha256,
                    "major labels in native T2",
                ),
                (
                    output.atlas_support_in_native_t2_path,
                    output.atlas_support_in_native_t2_sha256,
                    "atlas support in native T2",
                ),
                (output.metadata_path, output.metadata_sha256, "composite metadata"),
            ):
                _verify(path, digest, label)
            _require_qc_files(qc_montage_path, qc_manifest_path, qc_slice_paths)
            required = connection.execute(
                """
                SELECT a.id FROM atlas_to_t1_artifacts a
                JOIN atlas_to_t1_reviews r ON r.artifact_id = a.id
                JOIN t1_to_t2_artifacts t ON t.id = ? AND t.state = 'APPROVED'
                JOIN t1_to_t2_reviews tr ON tr.artifact_id = t.id
                JOIN major_region_schemes s ON s.id = ? AND s.state = 'APPROVED'
                WHERE a.id = ? AND a.state = 'APPROVED'
                """,
                (
                    source_t1_to_t2_artifact_id, major_region_scheme_id,
                    source_atlas_to_t1_artifact_id,
                ),
            ).fetchone()
            if required is None:
                raise StudyStateError("Composite labels require every approved dependency.")
            connection.execute(
                "UPDATE atlas_t2_composites SET active = 0, state = 'OUTDATED' "
                "WHERE subject_id = ? AND active = 1",
                (subject_id,),
            )
            connection.execute(
                """
                INSERT INTO atlas_t2_composites(
                    id, study_id, subject_id, active, state, labels_path, labels_sha256,
                    support_path, support_sha256, qc_montage_path, qc_montage_sha256,
                    qc_manifest_path, qc_manifest_sha256, qc_slice_paths_json,
                    metadata_path, metadata_sha256,
                    source_atlas_to_t1_artifact_id, source_t1_to_t2_artifact_id,
                    atlas_release_id, major_region_scheme_id, source_t2_scan_input_id,
                    created_at, created_by
                ) VALUES (?, ?, ?, 1, 'DRAFT_REVIEW_REQUIRED', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    artifact_id, study["id"], subject_id,
                    _relative(self.root_path, output.labels_in_native_t2_path),
                    output.labels_in_native_t2_sha256,
                    _relative(self.root_path, output.atlas_support_in_native_t2_path),
                    output.atlas_support_in_native_t2_sha256,
                    _relative(self.root_path, qc_montage_path), sha256_file(qc_montage_path),
                    _relative(self.root_path, qc_manifest_path), sha256_file(qc_manifest_path),
                    json.dumps([_relative(self.root_path, path) for path in qc_slice_paths]),
                    _relative(self.root_path, output.metadata_path),
                    output.metadata_sha256,
                    source_atlas_to_t1_artifact_id, source_t1_to_t2_artifact_id,
                    atlas_release_id, major_region_scheme_id, source_t2_scan_input_id,
                    now, normalize_required(actor, "Actor"),
                ),
            )
            self._outdate_results(connection, subject_id, now, "New composite labels")
        return artifact_id

    def approve_composite(self, artifact_id: str, *, reviewer: str) -> None:
        self._approve_artifact(
            table="atlas_t2_composites",
            review_table="atlas_t2_composite_reviews",
            artifact_id=artifact_id,
            hashes=("labels", "support", "qc_montage", "qc_manifest", "metadata"),
            reviewer=reviewer,
        )

    def record_result(
        self,
        *,
        subject_id: str,
        source_composite_artifact_id: str,
        source_lesion_artifact_id: str,
        major_region_scheme_id: str,
        result: MajorRegionLesionResult,
        actor: str,
    ) -> str:
        result_id = str(uuid4())
        now = utc_now()
        with closing(connect(self.database_path)) as connection, connection:
            study = single_study(connection)
            ready = connection.execute(
                """
                SELECT c.id, l.path lesion_path, l.file_hash lesion_sha256
                FROM atlas_t2_composites c
                JOIN atlas_t2_composite_reviews cr ON cr.artifact_id = c.id
                JOIN artifacts l ON l.id = ? AND l.active = 1 AND l.state = 'APPROVED'
                JOIN reviews lr ON lr.artifact_id = l.id
                JOIN major_region_schemes s ON s.id = ? AND s.state = 'APPROVED'
                WHERE c.id = ? AND c.active = 1 AND c.state = 'APPROVED'
                """,
                (source_lesion_artifact_id, major_region_scheme_id, source_composite_artifact_id),
            ).fetchone()
            if ready is None:
                raise StudyStateError("Regional result dependencies are not approved.")
            _verify(result.result_csv_path, result.result_csv_sha256, "regional CSV")
            _verify(result.metadata_path, result.metadata_sha256, "regional metadata")
            if result.lesion_sha256 != ready["lesion_sha256"]:
                raise StudyStateError(
                    "The regional result is not bound to the approved lesion checksum."
                )
            _verify(
                self.root_path / ready["lesion_path"],
                ready["lesion_sha256"],
                "approved native lesion",
            )
            self._outdate_results(connection, subject_id, now, "New regional result")
            connection.execute(
                """
                INSERT INTO major_region_lesion_results(
                    id, study_id, subject_id, active, state, result_csv_path,
                    result_csv_sha256, metadata_path, metadata_sha256,
                    lesion_voxel_count, lesion_volume_mm3, mapped_lesion_voxels,
                    unmapped_lesion_voxels, outside_atlas_support_lesion_voxels,
                    boundary_lesion_voxels,
                    sensitivity_status, source_composite_artifact_id,
                    source_lesion_artifact_id, source_lesion_sha256,
                    major_region_scheme_id, created_at, created_by
                ) VALUES (?, ?, ?, 1, 'APPROVED', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    result_id, study["id"], subject_id,
                    _relative(self.root_path, result.result_csv_path), result.result_csv_sha256,
                    _relative(self.root_path, result.metadata_path), result.metadata_sha256,
                    result.lesion_voxel_count, result.lesion_volume_mm3,
                    result.mapped_lesion_voxels, result.unmapped_lesion_voxels,
                    result.outside_atlas_support_lesion_voxels,
                    result.boundary_lesion_voxels, result.sensitivity_status,
                    source_composite_artifact_id, source_lesion_artifact_id,
                    result.lesion_sha256, major_region_scheme_id, now,
                    normalize_required(actor, "Actor"),
                ),
            )
            normalized_actor = normalize_required(actor, "Actor")
            insert_audit(
                connection,
                study_id=study["id"],
                subject_id=subject_id,
                event_type="MAJOR_REGION_LESION_RESULT_CREATED",
                actor=normalized_actor,
                details={
                    "result_id": result_id,
                    "source_composite_artifact_id": source_composite_artifact_id,
                    "source_lesion_artifact_id": source_lesion_artifact_id,
                    "result_csv_sha256": result.result_csv_sha256,
                    "metadata_sha256": result.metadata_sha256,
                },
                created_at=now,
            )
            touch_study(connection, study["id"], now)
        return result_id

    def state(self, subject_id: str) -> AtlasMappingState:
        with closing(connect(self.database_path)) as connection:
            release_row = connection.execute(
                "SELECT * FROM atlas_releases WHERE active = 1"
            ).fetchone()
            scheme_row = connection.execute(
                """
                SELECT s.*, r.reviewer, r.created_at reviewed_at
                FROM major_region_schemes s
                LEFT JOIN major_region_scheme_reviews r ON r.scheme_id = s.id
                WHERE s.active = 1
                """
            ).fetchone()
            support_row = connection.execute(
                """
                SELECT m.*, r.reviewer, r.created_at reviewed_at
                FROM t2_registration_support_masks m
                LEFT JOIN t2_registration_support_mask_reviews r ON r.artifact_id = m.id
                WHERE m.subject_id = ? AND m.active = 1
                """,
                (subject_id,),
            ).fetchone()
            atlas_rows = connection.execute(
                """
                SELECT a.*, r.reviewer, r.created_at reviewed_at,
                       CASE WHEN r.id IS NULL THEN 0 ELSE 1 END selected_by_review
                FROM atlas_to_t1_artifacts a
                LEFT JOIN atlas_to_t1_reviews r ON r.artifact_id = a.id
                WHERE a.subject_id = ? ORDER BY a.created_at DESC, a.candidate
                """,
                (subject_id,),
            ).fetchall()
            t1_t2_row = connection.execute(
                """
                SELECT a.*, r.reviewer, r.created_at reviewed_at
                FROM t1_to_t2_artifacts a
                LEFT JOIN t1_to_t2_reviews r ON r.artifact_id = a.id
                WHERE a.subject_id = ? AND a.active = 1
                """,
                (subject_id,),
            ).fetchone()
            composite_row = connection.execute(
                """
                SELECT a.*, r.reviewer, r.created_at reviewed_at
                FROM atlas_t2_composites a
                LEFT JOIN atlas_t2_composite_reviews r ON r.artifact_id = a.id
                WHERE a.subject_id = ? AND a.active = 1
                """,
                (subject_id,),
            ).fetchone()
            result_row = connection.execute(
                "SELECT * FROM major_region_lesion_results WHERE subject_id = ? AND active = 1",
                (subject_id,),
            ).fetchone()
            job_rows = []
            for kind, table in (
                ("atlas_to_t1", "atlas_to_t1_jobs"),
                ("t1_to_t2", "t1_to_t2_jobs"),
            ):
                rows = connection.execute(
                    f"SELECT *, '{kind}' kind FROM {table} WHERE subject_id = ?",
                    (subject_id,),
                ).fetchall()
                job_rows.extend(rows)
        candidates = tuple(_atlas_artifact(row, self.root_path) for row in atlas_rows)
        return AtlasMappingState(
            release=_release(release_row) if release_row else None,
            scheme=_scheme(scheme_row) if scheme_row else None,
            t2_support_mask=_support_mask(support_row, self.root_path) if support_row else None,
            atlas_to_t1_candidates=candidates,
            selected_atlas_to_t1=next((item for item in candidates if item.active), None),
            t1_to_t2=_t1_t2(t1_t2_row, self.root_path) if t1_t2_row else None,
            composite=_composite(composite_row, self.root_path) if composite_row else None,
            result=_result(result_row, self.root_path) if result_row else None,
            jobs=tuple(_job(row, self.root_path) for row in job_rows),
        )

    def invalidate_for_input_change(
        self, subject_id: str, *, role: str, reason: str, changed_at: str
    ) -> None:
        with closing(connect(self.database_path)) as connection, connection:
            invalidate_atlas_for_input_change(
                connection,
                subject_id=subject_id,
                role=role,
                reason=reason,
                changed_at=changed_at,
            )

    def invalidate_for_lesion_change(
        self, subject_id: str, *, lesion_artifact_id: str, reason: str, changed_at: str
    ) -> None:
        with closing(connect(self.database_path)) as connection, connection:
            invalidate_atlas_for_lesion_change(
                connection,
                subject_id=subject_id,
                lesion_artifact_id=lesion_artifact_id,
                reason=reason,
                changed_at=changed_at,
            )

    def interrupt_running_jobs(self) -> int:
        count = 0
        now = utc_now()
        with closing(connect(self.database_path)) as connection, connection:
            for table in ("atlas_to_t1_jobs", "t1_to_t2_jobs"):
                count += connection.execute(
                    f"UPDATE {table} SET state = 'INTERRUPTED', stage = 'interrupted', "
                    "finished_at = ?, error_message = 'Application closed before job completion.' "
                    "WHERE state = 'RUNNING'",
                    (now,),
                ).rowcount
        return int(count)

    def _approve_artifact(
        self,
        *,
        table: str,
        review_table: str,
        artifact_id: str,
        hashes: tuple[str, ...],
        reviewer: str,
    ) -> None:
        reviewer = normalize_required(reviewer, "Reviewer identity")
        now = utc_now()
        with closing(connect(self.database_path)) as connection, connection:
            study = single_study(connection)
            row = connection.execute(
                f"SELECT * FROM {table} WHERE id = ? AND active = 1", (artifact_id,)
            ).fetchone()
            if row is None or row["state"] != "DRAFT_REVIEW_REQUIRED":
                raise StudyStateError("The current draft artifact is unavailable for review.")
            for prefix in hashes:
                _verify(
                    self.root_path / row[f"{prefix}_path"],
                    row[f"{prefix}_sha256"],
                    prefix,
                )
            if "qc_manifest" in hashes:
                _verify_qc_slices(self.root_path, row)
            hash_columns = ", ".join(f"{prefix}_sha256" for prefix in hashes)
            placeholders = ", ".join("?" for _ in hashes)
            connection.execute(
                f"INSERT INTO {review_table}(id, study_id, subject_id, artifact_id, "
                f"{hash_columns}, reviewer, study_blinding_state, created_at) "
                f"VALUES (?, ?, ?, ?, {placeholders}, ?, ?, ?)",
                (
                    str(uuid4()),
                    study["id"],
                    row["subject_id"],
                    artifact_id,
                    *(row[f"{prefix}_sha256"] for prefix in hashes),
                    reviewer,
                    study["blinding_state"],
                    now,
                ),
            )
            connection.execute(
                f"UPDATE {table} SET state = 'APPROVED' WHERE id = ?", (artifact_id,)
            )
            event_type = {
                "t1_to_t2_artifacts": "ATLAS_T1_TO_T2_REGISTRATION_APPROVED",
                "atlas_t2_composites": "ATLAS_T2_COMPOSITE_APPROVED",
            }[table]
            insert_audit(
                connection,
                study_id=study["id"],
                subject_id=row["subject_id"],
                event_type=event_type,
                actor=reviewer,
                details={
                    "artifact_id": artifact_id,
                    "approved_hashes": {
                        prefix: row[f"{prefix}_sha256"] for prefix in hashes
                    },
                },
                created_at=now,
            )
            touch_study(connection, study["id"], now)

    def _invalidate_all_subjects(
        self,
        connection: sqlite3.Connection,
        reason: str,
        changed_at: str,
        invalidate_atlas_to_t1: bool,
    ) -> None:
        rows = connection.execute("SELECT id FROM subjects").fetchall()
        for row in rows:
            self._invalidate_subject(
                connection, row["id"], reason, changed_at, invalidate_atlas_to_t1
            )

    def _invalidate_subject(
        self,
        connection: sqlite3.Connection,
        subject_id: str,
        reason: str,
        changed_at: str,
        invalidate_atlas_to_t1: bool,
    ) -> None:
        if invalidate_atlas_to_t1:
            connection.execute(
                "UPDATE atlas_to_t1_artifacts SET active = 0, state = 'OUTDATED' "
                "WHERE subject_id = ? AND state != 'OUTDATED'",
                (subject_id,),
            )
        connection.execute(
            "UPDATE t1_to_t2_artifacts SET active = 0, state = 'OUTDATED' "
            "WHERE subject_id = ? AND state != 'OUTDATED'",
            (subject_id,),
        )
        self._outdate_composite_and_results(
            connection, subject_id, changed_at, reason
        )

    def _outdate_composite_and_results(
        self,
        connection: sqlite3.Connection,
        subject_id: str,
        changed_at: str,
        reason: str,
    ) -> None:
        connection.execute(
            "UPDATE atlas_t2_composites SET active = 0, state = 'OUTDATED' "
            "WHERE subject_id = ? AND state != 'OUTDATED'",
            (subject_id,),
        )
        self._outdate_results(connection, subject_id, changed_at, reason)

    def _outdate_results(
        self,
        connection: sqlite3.Connection,
        subject_id: str,
        changed_at: str,
        reason: str,
    ) -> None:
        connection.execute(
            "UPDATE major_region_lesion_results SET active = 0, state = 'OUTDATED' "
            "WHERE subject_id = ? AND state != 'OUTDATED'",
            (subject_id,),
        )
        _ = (changed_at, reason)


def invalidate_atlas_for_input_change(
    connection: sqlite3.Connection,
    *,
    subject_id: str,
    role: str,
    reason: str,
    changed_at: str,
) -> dict[str, int]:
    """Invalidate atlas dependencies within the caller's existing transaction."""

    counts = {
        "atlas_to_t1": 0,
        "t1_to_t2": 0,
        "t2_support_masks": 0,
        "composites": 0,
        "results": 0,
    }
    if role == "T1_POST":
        return counts
    if role == "T1_PRE":
        counts["atlas_to_t1"] = connection.execute(
            "UPDATE atlas_to_t1_artifacts SET active = 0, state = 'OUTDATED' "
            "WHERE subject_id = ? AND state != 'OUTDATED'",
            (subject_id,),
        ).rowcount
    elif role == "T2":
        counts["t2_support_masks"] = connection.execute(
            "UPDATE t2_registration_support_masks "
            "SET active = 0, state = 'OUTDATED' "
            "WHERE subject_id = ? AND state != 'OUTDATED'",
            (subject_id,),
        ).rowcount
    else:
        return counts
    counts["t1_to_t2"] = connection.execute(
        "UPDATE t1_to_t2_artifacts SET active = 0, state = 'OUTDATED' "
        "WHERE subject_id = ? AND state != 'OUTDATED'",
        (subject_id,),
    ).rowcount
    counts["composites"] = connection.execute(
        "UPDATE atlas_t2_composites SET active = 0, state = 'OUTDATED' "
        "WHERE subject_id = ? AND state != 'OUTDATED'",
        (subject_id,),
    ).rowcount
    counts["results"] = connection.execute(
        "UPDATE major_region_lesion_results SET active = 0, state = 'OUTDATED' "
        "WHERE subject_id = ? AND state != 'OUTDATED'",
        (subject_id,),
    ).rowcount
    _ = (reason, changed_at)
    return {key: int(value) for key, value in counts.items()}


def invalidate_atlas_for_t1_mask_change(
    connection: sqlite3.Connection,
    *,
    subject_id: str,
    reason: str,
    changed_at: str,
) -> dict[str, int]:
    return invalidate_atlas_for_input_change(
        connection,
        subject_id=subject_id,
        role="T1_PRE",
        reason=reason,
        changed_at=changed_at,
    )


def invalidate_atlas_for_lesion_change(
    connection: sqlite3.Connection,
    *,
    subject_id: str,
    lesion_artifact_id: str | None,
    reason: str,
    changed_at: str,
) -> dict[str, int]:
    """Always outdate overlap; also outdate mappings bound to this metric mask."""

    results = connection.execute(
        "UPDATE major_region_lesion_results SET active = 0, state = 'OUTDATED' "
        "WHERE subject_id = ? AND state != 'OUTDATED'",
        (subject_id,),
    ).rowcount
    t1_to_t2 = 0
    composites = 0
    if lesion_artifact_id is not None:
        t1_to_t2 = connection.execute(
            "UPDATE t1_to_t2_artifacts SET active = 0, state = 'OUTDATED' "
            "WHERE subject_id = ? AND active = 1 "
            "AND lesion_exclusion_artifact_id = ?",
            (subject_id, lesion_artifact_id),
        ).rowcount
        if t1_to_t2:
            composites = connection.execute(
                "UPDATE atlas_t2_composites SET active = 0, state = 'OUTDATED' "
                "WHERE subject_id = ? AND state != 'OUTDATED'",
                (subject_id,),
            ).rowcount
    _ = (reason, changed_at)
    return {
        "t1_to_t2": int(t1_to_t2),
        "composites": int(composites),
        "results": int(results),
    }


def _method_table(kind: str) -> str:
    if kind not in {"atlas_to_t1", "t1_to_t2"}:
        raise ValueError(f"Unsupported atlas method kind: {kind}")
    return f"{kind}_methods"


def _job_table(kind: str) -> str:
    if kind not in {"atlas_to_t1", "t1_to_t2"}:
        raise ValueError(f"Unsupported atlas job kind: {kind}")
    return f"{kind}_jobs"


def _relative(root: Path, path: Path) -> str:
    resolved = path.resolve()
    try:
        return str(resolved.relative_to(root.resolve()))
    except ValueError as exc:
        raise StudyStateError(f"Artifact is outside the study root: {resolved}") from exc


def _verify(path: Path, expected: str, label: str) -> None:
    if not path.is_file():
        raise StudyStateError(f"The immutable {label} file is unavailable: {path}")
    observed = sha256_file(path)
    if observed != expected:
        raise StudyStateError(
            f"The immutable {label} checksum changed: expected {expected}, got {observed}"
        )


def _require_qc_files(
    montage_path: Path,
    manifest_path: Path,
    slice_paths: tuple[Path, ...],
) -> None:
    if not montage_path.is_file() or not manifest_path.is_file() or not slice_paths:
        raise StudyStateError("The complete all-slice QC bundle is unavailable.")
    try:
        manifest = json.loads(manifest_path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise StudyStateError("The all-slice QC manifest is invalid.") from exc
    declared = manifest.get("slice_sha256")
    if not isinstance(declared, dict):
        raise StudyStateError("The QC manifest does not bind every rendered slice.")
    if set(declared) != {path.name for path in slice_paths}:
        raise StudyStateError("The QC manifest slice set does not match the artifact.")
    for path in slice_paths:
        _verify(path, str(declared[path.name]), f"QC slice {path.name}")


def _verify_qc_slices(root: Path, row: sqlite3.Row) -> None:
    _require_qc_files(
        root / row["qc_montage_path"],
        root / row["qc_manifest_path"],
        tuple(root / value for value in json.loads(row["qc_slice_paths_json"])),
    )


def _release(row: sqlite3.Row) -> AtlasReleaseRecord:
    return AtlasReleaseRecord(
        id=row["id"], active=bool(row["active"]), release_version=row["release_version"],
        aidamri_revision=row["aidamri_revision"], template_path=Path(row["template_path"]),
        template_sha256=row["template_sha256"], labels_path=Path(row["labels_path"]),
        labels_sha256=row["labels_sha256"],
        source_lookup_path=Path(row["source_lookup_path"]),
        source_lookup_sha256=row["source_lookup_sha256"],
        template_mask_path=Path(row["template_mask_path"]),
        template_mask_sha256=row["template_mask_sha256"],
        geometry=json.loads(row["geometry_json"]), registered_at=row["registered_at"],
        registered_by=row["registered_by"],
    )


def _scheme(row: sqlite3.Row) -> MajorRegionSchemeRecord:
    return MajorRegionSchemeRecord(
        id=row["id"], active=bool(row["active"]), state=AtlasReviewState(row["state"]),
        mapping_version=row["mapping_version"], mapping_path=Path(row["mapping_path"]),
        mapping_sha256=row["mapping_sha256"], source_label_count=row["source_label_count"],
        major_region_count=row["major_region_count"], registered_at=row["registered_at"],
        registered_by=row["registered_by"], reviewer=row["reviewer"],
        reviewed_at=row["reviewed_at"],
    )


def _support_mask(row: sqlite3.Row, root: Path) -> T2RegistrationSupportMaskRecord:
    return T2RegistrationSupportMaskRecord(
        id=row["id"], subject_id=row["subject_id"], active=bool(row["active"]),
        state=AtlasReviewState(row["state"]), version=row["version"],
        mask_path=root / row["mask_path"], mask_sha256=row["mask_sha256"],
        source_t2_scan_input_id=row["source_t2_scan_input_id"],
        created_at=row["created_at"], created_by=row["created_by"],
        reviewer=row["reviewer"], reviewed_at=row["reviewed_at"],
    )


def _atlas_artifact(row: sqlite3.Row, root: Path) -> AtlasToT1ArtifactRecord:
    return AtlasToT1ArtifactRecord(
        id=row["id"], subject_id=row["subject_id"], active=bool(row["active"]),
        state=AtlasReviewState(row["state"]), candidate=row["candidate"],
        transform_path=root / row["transform_path"], transform_sha256=row["transform_sha256"],
        warped_intensity_path=root / row["warped_intensity_path"],
        warped_intensity_sha256=row["warped_intensity_sha256"],
        warped_support_path=root / row["warped_support_path"],
        warped_support_sha256=row["warped_support_sha256"],
        qc_path=root / row["qc_path"], qc_sha256=row["qc_sha256"],
        metadata_path=root / row["metadata_path"], metadata_sha256=row["metadata_sha256"],
        source_pre_scan_input_id=row["source_pre_scan_input_id"],
        source_t1_mask_artifact_id=row["source_t1_mask_artifact_id"],
        atlas_release_id=row["atlas_release_id"], method_id=row["method_id"],
        job_id=row["job_id"], created_at=row["created_at"],
        selected_by_review=bool(row["selected_by_review"]), reviewer=row["reviewer"],
        reviewed_at=row["reviewed_at"],
    )


def _t1_t2(row: sqlite3.Row, root: Path) -> T1ToT2ArtifactRecord:
    return T1ToT2ArtifactRecord(
        id=row["id"], subject_id=row["subject_id"], active=bool(row["active"]),
        state=AtlasReviewState(row["state"]), transform_path=root / row["transform_path"],
        transform_sha256=row["transform_sha256"],
        transformed_t1_path=root / row["transformed_t1_path"],
        transformed_t1_sha256=row["transformed_t1_sha256"],
        transformed_t1_mask_path=root / row["transformed_t1_mask_path"],
        transformed_t1_mask_sha256=row["transformed_t1_mask_sha256"],
        qc_montage_path=root / row["qc_montage_path"],
        qc_montage_sha256=row["qc_montage_sha256"],
        qc_manifest_path=root / row["qc_manifest_path"],
        qc_manifest_sha256=row["qc_manifest_sha256"],
        qc_slice_paths=tuple(root / value for value in json.loads(row["qc_slice_paths_json"])),
        metadata_path=root / row["metadata_path"],
        metadata_sha256=row["metadata_sha256"],
        source_pre_scan_input_id=row["source_pre_scan_input_id"],
        source_t2_scan_input_id=row["source_t2_scan_input_id"],
        source_t1_mask_artifact_id=row["source_t1_mask_artifact_id"],
        source_t2_support_mask_id=row["source_t2_support_mask_id"],
        lesion_exclusion_artifact_id=row["lesion_exclusion_artifact_id"],
        lesion_exclusion_sha256=row["lesion_exclusion_sha256"], method_id=row["method_id"],
        job_id=row["job_id"], created_at=row["created_at"], reviewer=row["reviewer"],
        reviewed_at=row["reviewed_at"],
    )


def _composite(row: sqlite3.Row, root: Path) -> AtlasInT2CompositeRecord:
    return AtlasInT2CompositeRecord(
        id=row["id"], subject_id=row["subject_id"], active=bool(row["active"]),
        state=AtlasReviewState(row["state"]), labels_path=root / row["labels_path"],
        labels_sha256=row["labels_sha256"], support_path=root / row["support_path"],
        support_sha256=row["support_sha256"], qc_montage_path=root / row["qc_montage_path"],
        qc_montage_sha256=row["qc_montage_sha256"],
        qc_manifest_path=root / row["qc_manifest_path"],
        qc_manifest_sha256=row["qc_manifest_sha256"],
        qc_slice_paths=tuple(root / value for value in json.loads(row["qc_slice_paths_json"])),
        metadata_path=root / row["metadata_path"],
        metadata_sha256=row["metadata_sha256"],
        source_atlas_to_t1_artifact_id=row["source_atlas_to_t1_artifact_id"],
        source_t1_to_t2_artifact_id=row["source_t1_to_t2_artifact_id"],
        atlas_release_id=row["atlas_release_id"],
        major_region_scheme_id=row["major_region_scheme_id"],
        source_t2_scan_input_id=row["source_t2_scan_input_id"], created_at=row["created_at"],
        reviewer=row["reviewer"], reviewed_at=row["reviewed_at"],
    )


def _result(row: sqlite3.Row, root: Path) -> MajorRegionLesionResultRecord:
    return MajorRegionLesionResultRecord(
        id=row["id"], subject_id=row["subject_id"], active=bool(row["active"]),
        state=AtlasReviewState(row["state"]), result_csv_path=root / row["result_csv_path"],
        result_csv_sha256=row["result_csv_sha256"], metadata_path=root / row["metadata_path"],
        metadata_sha256=row["metadata_sha256"], lesion_voxel_count=row["lesion_voxel_count"],
        lesion_volume_mm3=row["lesion_volume_mm3"],
        mapped_lesion_voxels=row["mapped_lesion_voxels"],
        unmapped_lesion_voxels=row["unmapped_lesion_voxels"],
        outside_atlas_support_lesion_voxels=row[
            "outside_atlas_support_lesion_voxels"
        ],
        boundary_lesion_voxels=row["boundary_lesion_voxels"],
        sensitivity_status=row["sensitivity_status"],
        source_composite_artifact_id=row["source_composite_artifact_id"],
        source_lesion_artifact_id=row["source_lesion_artifact_id"],
        source_lesion_sha256=row["source_lesion_sha256"],
        major_region_scheme_id=row["major_region_scheme_id"], created_at=row["created_at"],
    )


def _job(row: sqlite3.Row, root: Path) -> AtlasMappingJobRecord:
    return AtlasMappingJobRecord(
        id=row["id"], subject_id=row["subject_id"], state=ProcessingJobState(row["state"]),
        stage=row["stage"], progress_current=row["progress_current"],
        progress_total=row["progress_total"], method_id=row["method_id"],
        submitted_at=row["submitted_at"], started_at=row["started_at"],
        finished_at=row["finished_at"], error_message=row["error_message"],
        output_path=root / row["output_path"] if row["output_path"] else None,
        metadata={**json.loads(row["metadata_json"]), "kind": row["kind"]},
    )
