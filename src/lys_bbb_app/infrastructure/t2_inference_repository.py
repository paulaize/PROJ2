"""SQLite persistence for frozen T2 releases, jobs, and draft lesion artifacts."""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Protocol
from uuid import uuid4

from lys_bbb.t2_model_release import FrozenT2ModelRelease
from lys_bbb_app.domain.errors import StudyStateError
from lys_bbb_app.domain.t2_lesion import (
    ArtifactState,
    ProcessingJobRecord,
    ProcessingJobState,
    T2ArtifactDraft,
    T2LesionArtifactRecord,
    T2ModelReleaseRecord,
    T2_LESION_MASK_ARTIFACT_TYPE,
)
from lys_bbb_app.infrastructure.database_support import (
    connect,
    insert_audit,
    normalize_required,
    single_study,
    touch_study,
    utc_now,
)
from lys_bbb_app.infrastructure.t2_review_repository import invalidate_t2_results
from lys_bbb_app.infrastructure.atlas_mapping_repository import (
    invalidate_atlas_for_lesion_change,
)


ARTIFACT_TYPE = T2_LESION_MASK_ARTIFACT_TYPE


class StudyDatabaseContext(Protocol):
    root_path: Path
    database_path: Path


def register_t2_model_release(
    repository: StudyDatabaseContext,
    release: FrozenT2ModelRelease,
    *,
    actor: str,
) -> None:
    reviewer = normalize_required(actor, "Actor")
    now = utc_now()
    try:
        with closing(connect(repository.database_path)) as connection:
            with connection:
                study = single_study(connection)
                existing = connection.execute(
                    "SELECT manifest_sha256, frozen_spec_sha256 FROM model_releases WHERE id = ?",
                    (release.id,),
                ).fetchone()
                if existing is not None and (
                    existing["manifest_sha256"] != release.manifest_sha256
                    or existing["frozen_spec_sha256"] != release.frozen_spec_sha256
                ):
                    raise StudyStateError(
                        "A different model package is already registered with this release ID."
                    )
                connection.execute(
                    "UPDATE model_releases SET active = 0 WHERE study_id = ?",
                    (study["id"],),
                )
                connection.execute(
                    """
                    INSERT INTO model_releases(
                        id, study_id, name, version, root_path, active, architecture,
                        threshold, expected_spacing_json, model_sha256_json,
                        manifest_sha256, frozen_spec_sha256, threshold_sha256,
                        project_git_commit, ratlesnetv2_git_commit, metadata_json,
                        validated_at, validated_by
                    ) VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        root_path = excluded.root_path,
                        active = 1,
                        validated_at = excluded.validated_at,
                        validated_by = excluded.validated_by
                    """,
                    (
                        release.id,
                        study["id"],
                        release.name,
                        release.version,
                        str(release.root_path),
                        "RatLesNetV2",
                        release.threshold,
                        json.dumps(release.expected_spacing_mm),
                        json.dumps(release.model_sha256),
                        release.manifest_sha256,
                        release.frozen_spec_sha256,
                        release.threshold_sha256,
                        release.project_git_commit,
                        release.ratlesnetv2_git_commit,
                        json.dumps(release.metadata, sort_keys=True),
                        now,
                        reviewer,
                    ),
                )
                invalidated = invalidate_t2_results(
                    connection,
                    study_id=study["id"],
                    excluding_release_id=release.id,
                    reason="The active frozen T2 model release changed.",
                    changed_at=now,
                )
                touch_study(connection, study["id"], now)
                insert_audit(
                    connection,
                    study_id=study["id"],
                    event_type="T2_MODEL_RELEASE_VALIDATED",
                    actor=reviewer,
                    details={
                        "release_id": release.id,
                        "version": release.version,
                        "root_path": str(release.root_path),
                        "threshold": release.threshold,
                        "model_sha256": list(release.model_sha256),
                        "results_invalidated": invalidated,
                    },
                    created_at=now,
                )
    except StudyStateError:
        raise
    except sqlite3.Error as exc:
        raise StudyStateError(
            f"Could not register the T2 model release: {exc}"
        ) from exc


def create_t2_inference_job(
    repository: StudyDatabaseContext,
    subject_ids: tuple[str, ...],
    *,
    release_id: str,
    actor: str,
) -> str:
    reviewer = normalize_required(actor, "Actor")
    job_id = str(uuid4())
    now = utc_now()
    try:
        with closing(connect(repository.database_path)) as connection:
            with connection:
                study = single_study(connection)
                release = connection.execute(
                    "SELECT id FROM model_releases WHERE id = ? AND active = 1",
                    (release_id,),
                ).fetchone()
                if release is None:
                    raise StudyStateError(
                        "The selected T2 model release is not active."
                    )
                connection.execute(
                    """
                    INSERT INTO jobs(
                        id, study_id, job_type, state, stage, progress_current,
                        progress_total, model_release_id, subject_ids_json, submitted_at,
                        metadata_json
                    ) VALUES (?, ?, 'T2_LESION_INFERENCE', ?, 'queued', 0, ?, ?, ?, ?, ?)
                    """,
                    (
                        job_id,
                        study["id"],
                        ProcessingJobState.QUEUED.value,
                        len(subject_ids),
                        release_id,
                        json.dumps(subject_ids),
                        now,
                        json.dumps({"submitted_by": reviewer}, sort_keys=True),
                    ),
                )
                insert_audit(
                    connection,
                    study_id=study["id"],
                    event_type="T2_INFERENCE_SUBMITTED",
                    actor=reviewer,
                    details={
                        "job_id": job_id,
                        "release_id": release_id,
                        "subject_ids": list(subject_ids),
                    },
                    created_at=now,
                )
    except StudyStateError:
        raise
    except sqlite3.Error as exc:
        raise StudyStateError(f"Could not create the T2 inference job: {exc}") from exc
    return job_id


def start_job(repository: StudyDatabaseContext, job_id: str) -> None:
    _transition_job(
        repository,
        job_id,
        from_state=ProcessingJobState.QUEUED,
        to_state=ProcessingJobState.RUNNING,
        stage="preparing_inputs",
    )


def update_job_progress(
    repository: StudyDatabaseContext,
    job_id: str,
    current: int,
    total: int,
    stage: str,
) -> None:
    try:
        with closing(connect(repository.database_path)) as connection:
            with connection:
                connection.execute(
                    """
                    UPDATE jobs SET stage = ?, progress_current = ?, progress_total = ?
                    WHERE id = ? AND state = ?
                    """,
                    (stage, current, total, job_id, ProcessingJobState.RUNNING.value),
                )
    except sqlite3.Error as exc:
        raise StudyStateError(f"Could not update T2 inference progress: {exc}") from exc


def fail_job(
    repository: StudyDatabaseContext,
    job_id: str,
    error: str,
    *,
    actor: str,
) -> None:
    message = normalize_required(error, "T2 inference error")
    now = utc_now()
    try:
        with closing(connect(repository.database_path)) as connection:
            with connection:
                study = single_study(connection)
                connection.execute(
                    """
                    UPDATE jobs SET state = ?, stage = 'failed', finished_at = ?,
                                    error_message = ?
                    WHERE id = ? AND state IN (?, ?)
                    """,
                    (
                        ProcessingJobState.FAILED.value,
                        now,
                        message,
                        job_id,
                        ProcessingJobState.QUEUED.value,
                        ProcessingJobState.RUNNING.value,
                    ),
                )
                insert_audit(
                    connection,
                    study_id=study["id"],
                    event_type="T2_INFERENCE_FAILED",
                    actor=normalize_required(actor, "Actor"),
                    details={"job_id": job_id, "error": message},
                    created_at=now,
                )
    except sqlite3.Error as exc:
        raise StudyStateError(f"Could not record T2 inference failure: {exc}") from exc


def complete_job(
    repository: StudyDatabaseContext,
    job_id: str,
    drafts: tuple[T2ArtifactDraft, ...],
    *,
    release_id: str,
    output_path: Path,
    actor: str,
) -> None:
    reviewer = normalize_required(actor, "Actor")
    now = utc_now()
    relative_output = _relative_to_root(repository, output_path)
    try:
        with closing(connect(repository.database_path)) as connection:
            with connection:
                study = single_study(connection)
                job = connection.execute(
                    "SELECT state FROM jobs WHERE id = ? AND study_id = ?",
                    (job_id, study["id"]),
                ).fetchone()
                if job is None or job["state"] != ProcessingJobState.RUNNING.value:
                    raise StudyStateError("The T2 inference job is not running.")
                for draft in drafts:
                    artifact_id = str(uuid4())
                    previous = connection.execute(
                        """
                        SELECT id FROM artifacts
                        WHERE subject_id = ? AND artifact_type = ? AND active = 1
                        """,
                        (draft.subject_id, ARTIFACT_TYPE),
                    ).fetchone()
                    if previous is not None:
                        connection.execute(
                            """
                            UPDATE artifacts SET active = 0, state = ? WHERE id = ?
                            """,
                            (ArtifactState.OUTDATED.value, previous["id"]),
                        )
                    version = int(
                        connection.execute(
                            """
                            SELECT COALESCE(MAX(version), 0) + 1 FROM artifacts
                            WHERE subject_id = ? AND artifact_type = ?
                            """,
                            (draft.subject_id, ARTIFACT_TYPE),
                        ).fetchone()[0]
                    )
                    metadata = dict(draft.metadata)
                    metadata.update(
                        {
                            "origin": "AUTOMATIC",
                            "probability_path": _relative_to_root(
                                repository, draft.probability_path
                            ).as_posix(),
                            "probability_sha256": draft.probability_sha256,
                            "qc_preview_path": (
                                _relative_to_root(
                                    repository, draft.qc_preview_path
                                ).as_posix()
                                if draft.qc_preview_path is not None
                                else None
                            ),
                            "lesion_voxel_count": draft.lesion_voxel_count,
                            "provisional_volume_mm3": draft.provisional_volume_mm3,
                            "threshold": draft.threshold,
                            "device": draft.device,
                        }
                    )
                    connection.execute(
                        """
                        INSERT INTO artifacts(
                            id, study_id, subject_id, artifact_type, state, version,
                            active, path, file_hash, source_scan_input_id,
                            model_release_id, job_id, metadata_json, created_at, created_by
                        ) VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            artifact_id,
                            study["id"],
                            draft.subject_id,
                            ARTIFACT_TYPE,
                            ArtifactState.DRAFT_REVIEW_REQUIRED.value,
                            version,
                            _relative_to_root(repository, draft.mask_path).as_posix(),
                            draft.mask_sha256,
                            draft.source_scan_input_id,
                            release_id,
                            job_id,
                            json.dumps(metadata, sort_keys=True),
                            now,
                            reviewer,
                        ),
                    )
                    if previous is not None:
                        connection.execute(
                            "UPDATE artifacts SET superseded_by = ? WHERE id = ?",
                            (artifact_id, previous["id"]),
                        )
                    invalidated_results = invalidate_t2_results(
                        connection,
                        subject_id=draft.subject_id,
                        reason="A new automatic T2 lesion mask was generated.",
                        changed_at=now,
                    )
                    invalidated_atlas = invalidate_atlas_for_lesion_change(
                        connection,
                        subject_id=draft.subject_id,
                        lesion_artifact_id=previous["id"] if previous is not None else None,
                        reason="A new automatic T2 lesion mask was generated.",
                        changed_at=now,
                    )
                    connection.execute(
                        "UPDATE subjects SET updated_at = ? WHERE id = ?",
                        (now, draft.subject_id),
                    )
                    insert_audit(
                        connection,
                        study_id=study["id"],
                        subject_id=draft.subject_id,
                        event_type="T2_DRAFT_LESION_MASK_CREATED",
                        actor=reviewer,
                        details={
                            "artifact_id": artifact_id,
                            "version": version,
                            "job_id": job_id,
                            "release_id": release_id,
                            "source_scan_input_id": draft.source_scan_input_id,
                            "mask_sha256": draft.mask_sha256,
                            "human_review_required": True,
                            "results_invalidated": invalidated_results,
                            "atlas_mapping_invalidated": invalidated_atlas,
                        },
                        created_at=now,
                    )
                connection.execute(
                    """
                    UPDATE jobs SET state = ?, stage = 'drafts_created',
                                    progress_current = progress_total,
                                    finished_at = ?, output_path = ?, error_message = NULL
                    WHERE id = ?
                    """,
                    (
                        ProcessingJobState.SUCCEEDED.value,
                        now,
                        relative_output.as_posix(),
                        job_id,
                    ),
                )
                touch_study(connection, study["id"], now)
                insert_audit(
                    connection,
                    study_id=study["id"],
                    event_type="T2_INFERENCE_COMPLETED",
                    actor=reviewer,
                    details={
                        "job_id": job_id,
                        "release_id": release_id,
                        "draft_artifacts": len(drafts),
                        "output_path": relative_output.as_posix(),
                    },
                    created_at=now,
                )
    except StudyStateError:
        raise
    except sqlite3.Error as exc:
        raise StudyStateError(f"Could not commit T2 inference outputs: {exc}") from exc


def interrupt_running_jobs(repository: StudyDatabaseContext) -> int:
    now = utc_now()
    try:
        with closing(connect(repository.database_path)) as connection:
            with connection:
                cursor = connection.execute(
                    """
                    UPDATE jobs SET state = ?, stage = 'interrupted', finished_at = ?,
                                    error_message = 'Application closed before job completion.'
                    WHERE state = ?
                    """,
                    (
                        ProcessingJobState.INTERRUPTED.value,
                        now,
                        ProcessingJobState.RUNNING.value,
                    ),
                )
                return int(cursor.rowcount)
    except sqlite3.Error as exc:
        raise StudyStateError(f"Could not recover interrupted jobs: {exc}") from exc


def model_release_from_row(row: sqlite3.Row) -> T2ModelReleaseRecord:
    return T2ModelReleaseRecord(
        id=row["id"],
        name=row["name"],
        version=row["version"],
        root_path=Path(row["root_path"]),
        active=bool(row["active"]),
        architecture=row["architecture"],
        threshold=float(row["threshold"]),
        expected_spacing_mm=tuple(json.loads(row["expected_spacing_json"])),
        model_sha256=tuple(json.loads(row["model_sha256_json"])),
        manifest_sha256=row["manifest_sha256"],
        frozen_spec_sha256=row["frozen_spec_sha256"],
        threshold_sha256=row["threshold_sha256"],
        project_git_commit=row["project_git_commit"],
        ratlesnetv2_git_commit=row["ratlesnetv2_git_commit"],
        metadata=json.loads(row["metadata_json"]),
        validated_at=row["validated_at"],
        validated_by=row["validated_by"],
    )


def job_from_row(row: sqlite3.Row, root_path: Path) -> ProcessingJobRecord:
    output_path = row["output_path"]
    return ProcessingJobRecord(
        id=row["id"],
        job_type=row["job_type"],
        state=ProcessingJobState(row["state"]),
        stage=row["stage"],
        progress_current=row["progress_current"],
        progress_total=row["progress_total"],
        model_release_id=row["model_release_id"],
        subject_ids=tuple(json.loads(row["subject_ids_json"])),
        submitted_at=row["submitted_at"],
        started_at=row["started_at"],
        finished_at=row["finished_at"],
        error_message=row["error_message"],
        output_path=root_path / output_path if output_path else None,
        metadata=json.loads(row["metadata_json"]),
    )


def artifact_from_row(row: sqlite3.Row, root_path: Path) -> T2LesionArtifactRecord:
    metadata = json.loads(row["metadata_json"])
    qc_path = metadata.get("qc_preview_path")
    return T2LesionArtifactRecord(
        id=row["id"],
        subject_id=row["subject_id"],
        artifact_type=row["artifact_type"],
        origin=str(metadata.get("origin", "AUTOMATIC")),
        state=ArtifactState(row["state"]),
        version=int(row["version"]),
        active=bool(row["active"]),
        mask_path=root_path / row["path"],
        mask_sha256=row["file_hash"],
        probability_path=root_path / metadata["probability_path"],
        probability_sha256=metadata["probability_sha256"],
        qc_preview_path=root_path / qc_path if qc_path else None,
        source_scan_input_id=row["source_scan_input_id"],
        model_release_id=row["model_release_id"],
        job_id=row["job_id"],
        lesion_voxel_count=int(metadata["lesion_voxel_count"]),
        provisional_volume_mm3=float(metadata["provisional_volume_mm3"]),
        threshold=float(metadata["threshold"]),
        device=str(metadata["device"]),
        created_at=row["created_at"],
        created_by=row["created_by"],
        superseded_by=row["superseded_by"],
        metadata=metadata,
    )


def _transition_job(
    repository: StudyDatabaseContext,
    job_id: str,
    *,
    from_state: ProcessingJobState,
    to_state: ProcessingJobState,
    stage: str,
) -> None:
    now = utc_now()
    try:
        with closing(connect(repository.database_path)) as connection:
            with connection:
                cursor = connection.execute(
                    """
                    UPDATE jobs SET state = ?, stage = ?, started_at = ?
                    WHERE id = ? AND state = ?
                    """,
                    (to_state.value, stage, now, job_id, from_state.value),
                )
                if cursor.rowcount != 1:
                    raise StudyStateError("The T2 inference job cannot be started.")
    except StudyStateError:
        raise
    except sqlite3.Error as exc:
        raise StudyStateError(f"Could not start T2 inference: {exc}") from exc


def _relative_to_root(repository: StudyDatabaseContext, path: Path) -> Path:
    try:
        return Path(path).resolve().relative_to(repository.root_path.resolve())
    except ValueError as exc:
        raise StudyStateError(
            "T2 inference outputs must remain inside the study root."
        ) from exc
