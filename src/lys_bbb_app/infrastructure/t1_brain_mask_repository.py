"""SQLite persistence for T1 brain-mask releases, runs, artifacts, and approvals."""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any, Protocol
from uuid import uuid4

from lys_bbb.t1_brain_mask_release import FrozenT1BrainMaskRelease
from lys_bbb.t1_brain_mask_review import T1BrainMaskMeasurement
from lys_bbb_app.domain.errors import StudyStateError
from lys_bbb_app.domain.t1_brain_mask import (
    T1_BRAIN_MASK_METHOD_VERSION,
    T1BrainMaskApprovalRecord,
    T1BrainMaskArtifactDraft,
    T1BrainMaskArtifactRecord,
    T1BrainMaskJobRecord,
    T1BrainMaskReleaseRecord,
    T1CorrectedBrainMaskDraft,
)
from lys_bbb_app.domain.t2_lesion import ArtifactState, ProcessingJobState
from lys_bbb_app.infrastructure.database_support import (
    connect,
    insert_audit,
    normalize_required,
    single_study,
    touch_study,
    utc_now,
)
from lys_bbb_app.infrastructure.t1_analysis_repository import invalidate_t1_analysis


class StudyDatabaseContext(Protocol):
    root_path: Path
    database_path: Path


def register_t1_brain_mask_release(
    repository: StudyDatabaseContext,
    release: FrozenT1BrainMaskRelease,
    *,
    manifest_sha256: str,
    method_spec_sha256: str,
    method_metadata: dict[str, Any],
    actor: str,
) -> None:
    """Activate one checksum-validated RS2/M-seam method release."""

    reviewer = normalize_required(actor, "Actor")
    now = utc_now()
    try:
        with closing(connect(repository.database_path)) as connection:
            with connection:
                study = single_study(connection)
                existing = connection.execute(
                    """
                    SELECT source_commit, weights_sha256, manifest_sha256,
                           method_spec_sha256
                    FROM t1_brain_mask_releases WHERE id = ?
                    """,
                    (release.id,),
                ).fetchone()
                declared = (
                    release.source_commit,
                    release.weights_sha256,
                    manifest_sha256,
                    method_spec_sha256,
                )
                if existing is not None and tuple(existing) != declared:
                    raise StudyStateError(
                        "A different T1 brain-mask method is already registered with "
                        "this release ID."
                    )
                connection.execute(
                    "UPDATE t1_brain_mask_releases SET active = 0 WHERE study_id = ?",
                    (study["id"],),
                )
                connection.execute(
                    """
                    INSERT INTO t1_brain_mask_releases(
                        id, study_id, root_path, active, source_commit, weights_sha256,
                        manifest_sha256, test_time_augmentation, method_version,
                        method_spec_sha256, metadata_json, validated_at, validated_by
                    ) VALUES (?, ?, ?, 1, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        root_path = excluded.root_path,
                        active = 1,
                        validated_at = excluded.validated_at,
                        validated_by = excluded.validated_by
                    """,
                    (
                        release.id,
                        study["id"],
                        str(release.root_path),
                        release.source_commit,
                        release.weights_sha256,
                        manifest_sha256,
                        int(release.test_time_augmentation),
                        T1_BRAIN_MASK_METHOD_VERSION,
                        method_spec_sha256,
                        json.dumps(method_metadata, sort_keys=True),
                        now,
                        reviewer,
                    ),
                )
                touch_study(connection, study["id"], now)
                insert_audit(
                    connection,
                    study_id=study["id"],
                    event_type="T1_BRAIN_MASK_RELEASE_VALIDATED",
                    actor=reviewer,
                    details={
                        "release_id": release.id,
                        "root_path": str(release.root_path),
                        "source_commit": release.source_commit,
                        "weights_sha256": release.weights_sha256,
                        "manifest_sha256": manifest_sha256,
                        "method_version": T1_BRAIN_MASK_METHOD_VERSION,
                        "method_spec_sha256": method_spec_sha256,
                        "test_time_augmentation": release.test_time_augmentation,
                    },
                    created_at=now,
                )
    except StudyStateError:
        raise
    except sqlite3.Error as exc:
        raise StudyStateError(
            f"Could not register the T1 brain-mask release: {exc}"
        ) from exc


def create_t1_brain_mask_job(
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
                    """
                    SELECT id FROM t1_brain_mask_releases
                    WHERE id = ? AND study_id = ? AND active = 1
                    """,
                    (release_id, study["id"]),
                ).fetchone()
                if release is None:
                    raise StudyStateError(
                        "The selected T1 brain-mask release is not active."
                    )
                connection.execute(
                    """
                    INSERT INTO t1_brain_mask_jobs(
                        id, study_id, state, stage, progress_current, progress_total,
                        release_id, subject_ids_json, submitted_at, metadata_json
                    ) VALUES (?, ?, ?, 'queued', 0, ?, ?, ?, ?, ?)
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
                    event_type="T1_BRAIN_MASK_GENERATION_SUBMITTED",
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
        raise StudyStateError(
            f"Could not create the T1 brain-mask job: {exc}"
        ) from exc
    return job_id


def start_t1_brain_mask_job(repository: StudyDatabaseContext, job_id: str) -> None:
    now = utc_now()
    try:
        with closing(connect(repository.database_path)) as connection:
            with connection:
                changed = connection.execute(
                    """
                    UPDATE t1_brain_mask_jobs
                    SET state = ?, stage = 'preparing_inputs', started_at = ?
                    WHERE id = ? AND state = ?
                    """,
                    (
                        ProcessingJobState.RUNNING.value,
                        now,
                        job_id,
                        ProcessingJobState.QUEUED.value,
                    ),
                ).rowcount
                if changed != 1:
                    raise StudyStateError(
                        "The T1 brain-mask generation job cannot be started."
                    )
    except StudyStateError:
        raise
    except sqlite3.Error as exc:
        raise StudyStateError(
            f"Could not start T1 brain-mask generation: {exc}"
        ) from exc


def update_t1_brain_mask_job(
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
                    UPDATE t1_brain_mask_jobs
                    SET stage = ?, progress_current = ?, progress_total = ?
                    WHERE id = ? AND state = ?
                    """,
                    (stage, current, total, job_id, ProcessingJobState.RUNNING.value),
                )
    except sqlite3.Error as exc:
        raise StudyStateError(
            f"Could not update T1 brain-mask generation progress: {exc}"
        ) from exc


def fail_t1_brain_mask_job(
    repository: StudyDatabaseContext,
    job_id: str,
    error: str,
    *,
    actor: str,
) -> None:
    message = normalize_required(error, "T1 brain-mask generation error")
    now = utc_now()
    try:
        with closing(connect(repository.database_path)) as connection:
            with connection:
                study = single_study(connection)
                connection.execute(
                    """
                    UPDATE t1_brain_mask_jobs
                    SET state = ?, stage = 'failed', finished_at = ?, error_message = ?
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
                    event_type="T1_BRAIN_MASK_GENERATION_FAILED",
                    actor=normalize_required(actor, "Actor"),
                    details={"job_id": job_id, "error": message},
                    created_at=now,
                )
    except sqlite3.Error as exc:
        raise StudyStateError(
            f"Could not record T1 brain-mask generation failure: {exc}"
        ) from exc


def complete_t1_brain_mask_job(
    repository: StudyDatabaseContext,
    job_id: str,
    drafts: tuple[T1BrainMaskArtifactDraft, ...],
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
                    """
                    SELECT state, release_id FROM t1_brain_mask_jobs
                    WHERE id = ? AND study_id = ?
                    """,
                    (job_id, study["id"]),
                ).fetchone()
                if (
                    job is None
                    or job["state"] != ProcessingJobState.RUNNING.value
                    or job["release_id"] != release_id
                ):
                    raise StudyStateError(
                        "The T1 brain-mask generation job is not running."
                    )
                for draft in drafts:
                    artifact_id = str(uuid4())
                    previous = connection.execute(
                        """
                        SELECT id FROM t1_brain_mask_artifacts
                        WHERE subject_id = ? AND active = 1
                        """,
                        (draft.subject_id,),
                    ).fetchone()
                    if previous is not None:
                        connection.execute(
                            """
                            UPDATE t1_brain_mask_artifacts
                            SET active = 0, state = ? WHERE id = ?
                            """,
                            (ArtifactState.OUTDATED.value, previous["id"]),
                        )
                    invalidate_t1_analysis(
                        connection,
                        subject_id=draft.subject_id,
                        reason="The active approved T1 brain mask changed.",
                        changed_at=now,
                        invalidate_registration=True,
                    )
                    version = int(
                        connection.execute(
                            """
                            SELECT COALESCE(MAX(version), 0) + 1
                            FROM t1_brain_mask_artifacts WHERE subject_id = ?
                            """,
                            (draft.subject_id,),
                        ).fetchone()[0]
                    )
                    connection.execute(
                        """
                        INSERT INTO t1_brain_mask_artifacts(
                            id, study_id, subject_id, origin, state, version, active,
                            mask_path, mask_sha256, raw_mask_path, raw_mask_sha256,
                            qc_preview_path, source_scan_input_id, release_id, job_id,
                            foreground_voxels, volume_mm3, device,
                            regularity_warnings_json, metadata_json, created_at, created_by
                        ) VALUES (?, ?, ?, 'AUTOMATIC', ?, ?, 1, ?, ?, ?, ?, ?, ?, ?, ?,
                                  ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            artifact_id,
                            study["id"],
                            draft.subject_id,
                            ArtifactState.DRAFT_REVIEW_REQUIRED.value,
                            version,
                            _relative_to_root(repository, draft.mask_path).as_posix(),
                            draft.mask_sha256,
                            _relative_to_root(repository, draft.raw_mask_path).as_posix(),
                            draft.raw_mask_sha256,
                            (
                                _relative_to_root(
                                    repository, draft.qc_preview_path
                                ).as_posix()
                                if draft.qc_preview_path is not None
                                else None
                            ),
                            draft.source_scan_input_id,
                            release_id,
                            job_id,
                            draft.foreground_voxels,
                            draft.volume_mm3,
                            draft.device,
                            json.dumps(draft.regularity_warnings),
                            json.dumps(draft.metadata, sort_keys=True),
                            now,
                            reviewer,
                        ),
                    )
                    if previous is not None:
                        connection.execute(
                            """
                            UPDATE t1_brain_mask_artifacts SET superseded_by = ?
                            WHERE id = ?
                            """,
                            (artifact_id, previous["id"]),
                        )
                    connection.execute(
                        "UPDATE subjects SET updated_at = ? WHERE id = ?",
                        (now, draft.subject_id),
                    )
                    insert_audit(
                        connection,
                        study_id=study["id"],
                        subject_id=draft.subject_id,
                        event_type="T1_DRAFT_BRAIN_MASK_CREATED",
                        actor=reviewer,
                        details={
                            "artifact_id": artifact_id,
                            "version": version,
                            "job_id": job_id,
                            "release_id": release_id,
                            "source_scan_input_id": draft.source_scan_input_id,
                            "mask_sha256": draft.mask_sha256,
                            "human_review_required": True,
                        },
                        created_at=now,
                    )
                connection.execute(
                    """
                    UPDATE t1_brain_mask_jobs
                    SET state = ?, stage = 'drafts_created',
                        progress_current = progress_total, finished_at = ?,
                        output_path = ?, error_message = NULL
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
                    event_type="T1_BRAIN_MASK_GENERATION_COMPLETED",
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
        raise StudyStateError(
            f"Could not commit T1 brain-mask outputs: {exc}"
        ) from exc


def create_corrected_t1_brain_mask_artifact(
    repository: StudyDatabaseContext,
    draft: T1CorrectedBrainMaskDraft,
    *,
    actor: str,
) -> str:
    reviewer = normalize_required(actor, "Actor")
    now = utc_now()
    artifact_id = str(uuid4())
    try:
        with closing(connect(repository.database_path)) as connection:
            with connection:
                study = single_study(connection)
                source = connection.execute(
                    """
                    SELECT * FROM t1_brain_mask_artifacts
                    WHERE id = ? AND subject_id = ?
                    """,
                    (draft.source_artifact_id, draft.subject_id),
                ).fetchone()
                if source is None:
                    raise StudyStateError(
                        "The source T1 brain-mask artifact is unavailable."
                    )
                if not source["active"] or source["state"] not in {
                    ArtifactState.DRAFT_REVIEW_REQUIRED.value,
                    ArtifactState.CORRECTED_REVIEW_REQUIRED.value,
                    ArtifactState.APPROVED.value,
                }:
                    raise StudyStateError(
                        "Start the correction from the current T1 brain mask."
                    )
                version = int(
                    connection.execute(
                        """
                        SELECT COALESCE(MAX(version), 0) + 1
                        FROM t1_brain_mask_artifacts WHERE subject_id = ?
                        """,
                        (draft.subject_id,),
                    ).fetchone()[0]
                )
                metadata = json.loads(source["metadata_json"])
                metadata.update(draft.metadata)
                metadata.update(
                    {
                        "origin": "CORRECTED",
                        "source_artifact_id": source["id"],
                        "imported_from": str(draft.imported_from),
                        "automatic_prediction": False,
                        "human_review_required": True,
                    }
                )
                connection.execute(
                    """
                    UPDATE t1_brain_mask_artifacts
                    SET active = 0, state = ? WHERE id = ?
                    """,
                    (ArtifactState.OUTDATED.value, source["id"]),
                )
                invalidate_t1_analysis(
                    connection,
                    subject_id=draft.subject_id,
                    reason="The active approved T1 brain mask changed.",
                    changed_at=now,
                    invalidate_registration=True,
                )
                connection.execute(
                    """
                    INSERT INTO t1_brain_mask_artifacts(
                        id, study_id, subject_id, origin, state, version, active,
                        mask_path, mask_sha256, raw_mask_path, raw_mask_sha256,
                        qc_preview_path, source_scan_input_id, release_id, job_id,
                        foreground_voxels, volume_mm3, device,
                        regularity_warnings_json, metadata_json, created_at, created_by
                    ) VALUES (?, ?, ?, 'CORRECTED', ?, ?, 1, ?, ?, ?, ?, ?, ?, ?, ?,
                              ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        artifact_id,
                        study["id"],
                        draft.subject_id,
                        ArtifactState.CORRECTED_REVIEW_REQUIRED.value,
                        version,
                        _relative_to_root(repository, draft.mask_path).as_posix(),
                        draft.mask_sha256,
                        source["raw_mask_path"],
                        source["raw_mask_sha256"],
                        (
                            _relative_to_root(repository, draft.qc_preview_path).as_posix()
                            if draft.qc_preview_path is not None
                            else None
                        ),
                        source["source_scan_input_id"],
                        source["release_id"],
                        source["job_id"],
                        draft.foreground_voxels,
                        draft.volume_mm3,
                        "human",
                        "[]",
                        json.dumps(metadata, sort_keys=True),
                        now,
                        reviewer,
                    ),
                )
                connection.execute(
                    "UPDATE t1_brain_mask_artifacts SET superseded_by = ? WHERE id = ?",
                    (artifact_id, source["id"]),
                )
                connection.execute(
                    "UPDATE subjects SET updated_at = ? WHERE id = ?",
                    (now, draft.subject_id),
                )
                touch_study(connection, study["id"], now)
                insert_audit(
                    connection,
                    study_id=study["id"],
                    subject_id=draft.subject_id,
                    event_type="T1_CORRECTED_BRAIN_MASK_IMPORTED",
                    actor=reviewer,
                    details={
                        "artifact_id": artifact_id,
                        "source_artifact_id": source["id"],
                        "version": version,
                        "mask_sha256": draft.mask_sha256,
                        "human_review_required": True,
                    },
                    created_at=now,
                )
    except StudyStateError:
        raise
    except (json.JSONDecodeError, sqlite3.Error) as exc:
        raise StudyStateError(
            f"Could not register the corrected T1 brain mask: {exc}"
        ) from exc
    return artifact_id


def record_t1_brain_mask_approval(
    repository: StudyDatabaseContext,
    artifact_id: str,
    *,
    reviewer: str,
    measurement: T1BrainMaskMeasurement,
) -> None:
    normalized_reviewer = normalize_required(reviewer, "Reviewer")
    now = utc_now()
    review_id = str(uuid4())
    try:
        with closing(connect(repository.database_path)) as connection:
            with connection:
                study = single_study(connection)
                artifact = connection.execute(
                    """
                    SELECT a.*, s.archived_at
                    FROM t1_brain_mask_artifacts AS a
                    JOIN subjects AS s ON s.id = a.subject_id
                    WHERE a.id = ?
                    """,
                    (artifact_id,),
                ).fetchone()
                if artifact is None:
                    raise StudyStateError(
                        "The selected T1 brain-mask artifact is unavailable."
                    )
                if artifact["archived_at"] is not None:
                    raise StudyStateError("Restore the subject before reviewing its mask.")
                if not artifact["active"] or artifact["state"] not in {
                    ArtifactState.DRAFT_REVIEW_REQUIRED.value,
                    ArtifactState.CORRECTED_REVIEW_REQUIRED.value,
                }:
                    raise StudyStateError(
                        "Only the active T1 brain mask awaiting review can be approved."
                    )
                if connection.execute(
                    "SELECT id FROM t1_brain_mask_reviews WHERE artifact_id = ?",
                    (artifact_id,),
                ).fetchone() is not None:
                    raise StudyStateError(
                        "This exact T1 brain-mask artifact is already approved."
                    )
                if measurement.mask_sha256 != artifact["mask_sha256"]:
                    raise StudyStateError(
                        "The validated T1 brain mask does not match the registered artifact."
                    )
                connection.execute(
                    """
                    INSERT INTO t1_brain_mask_reviews(
                        id, study_id, subject_id, artifact_id, reviewer,
                        study_blinding_state, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        review_id,
                        study["id"],
                        artifact["subject_id"],
                        artifact_id,
                        normalized_reviewer,
                        study["blinding_state"],
                        now,
                    ),
                )
                connection.execute(
                    "UPDATE t1_brain_mask_artifacts SET state = ? WHERE id = ?",
                    (ArtifactState.APPROVED.value, artifact_id),
                )
                connection.execute(
                    "UPDATE subjects SET updated_at = ? WHERE id = ?",
                    (now, artifact["subject_id"]),
                )
                touch_study(connection, study["id"], now)
                insert_audit(
                    connection,
                    study_id=study["id"],
                    subject_id=artifact["subject_id"],
                    event_type="T1_BRAIN_MASK_APPROVED",
                    actor=normalized_reviewer,
                    details={
                        "artifact_id": artifact_id,
                        "review_id": review_id,
                        "mask_sha256": measurement.mask_sha256,
                        "foreground_voxels": measurement.foreground_voxels,
                        "volume_mm3": measurement.volume_mm3,
                        "study_blinding_state": study["blinding_state"],
                    },
                    created_at=now,
                )
    except StudyStateError:
        raise
    except sqlite3.Error as exc:
        raise StudyStateError(
            f"Could not approve the T1 brain mask: {exc}"
        ) from exc


def interrupt_running_t1_brain_mask_jobs(repository: StudyDatabaseContext) -> int:
    now = utc_now()
    try:
        with closing(connect(repository.database_path)) as connection:
            with connection:
                return int(
                    connection.execute(
                        """
                        UPDATE t1_brain_mask_jobs
                        SET state = ?, stage = 'interrupted', finished_at = ?,
                            error_message = 'Application closed before job completion.'
                        WHERE state = ?
                        """,
                        (
                            ProcessingJobState.INTERRUPTED.value,
                            now,
                            ProcessingJobState.RUNNING.value,
                        ),
                    ).rowcount
                )
    except sqlite3.Error as exc:
        raise StudyStateError(
            f"Could not recover interrupted T1 brain-mask jobs: {exc}"
        ) from exc


def release_from_row(row: sqlite3.Row) -> T1BrainMaskReleaseRecord:
    return T1BrainMaskReleaseRecord(
        id=row["id"],
        root_path=Path(row["root_path"]),
        active=bool(row["active"]),
        source_commit=row["source_commit"],
        weights_sha256=row["weights_sha256"],
        manifest_sha256=row["manifest_sha256"],
        test_time_augmentation=bool(row["test_time_augmentation"]),
        method_version=row["method_version"],
        method_spec_sha256=row["method_spec_sha256"],
        metadata=json.loads(row["metadata_json"]),
        validated_at=row["validated_at"],
        validated_by=row["validated_by"],
    )


def job_from_row(row: sqlite3.Row, root_path: Path) -> T1BrainMaskJobRecord:
    output_path = row["output_path"]
    return T1BrainMaskJobRecord(
        id=row["id"],
        state=ProcessingJobState(row["state"]),
        stage=row["stage"],
        progress_current=row["progress_current"],
        progress_total=row["progress_total"],
        release_id=row["release_id"],
        subject_ids=tuple(json.loads(row["subject_ids_json"])),
        submitted_at=row["submitted_at"],
        started_at=row["started_at"],
        finished_at=row["finished_at"],
        error_message=row["error_message"],
        output_path=root_path / output_path if output_path else None,
        metadata=json.loads(row["metadata_json"]),
    )


def artifact_from_row(row: sqlite3.Row, root_path: Path) -> T1BrainMaskArtifactRecord:
    raw_path = row["raw_mask_path"]
    qc_path = row["qc_preview_path"]
    return T1BrainMaskArtifactRecord(
        id=row["id"],
        subject_id=row["subject_id"],
        origin=row["origin"],
        state=ArtifactState(row["state"]),
        version=int(row["version"]),
        active=bool(row["active"]),
        mask_path=root_path / row["mask_path"],
        mask_sha256=row["mask_sha256"],
        raw_mask_path=root_path / raw_path if raw_path else None,
        raw_mask_sha256=row["raw_mask_sha256"],
        qc_preview_path=root_path / qc_path if qc_path else None,
        source_scan_input_id=row["source_scan_input_id"],
        release_id=row["release_id"],
        job_id=row["job_id"],
        foreground_voxels=int(row["foreground_voxels"]),
        volume_mm3=float(row["volume_mm3"]),
        device=row["device"],
        regularity_warnings=tuple(json.loads(row["regularity_warnings_json"])),
        created_at=row["created_at"],
        created_by=row["created_by"],
        superseded_by=row["superseded_by"],
        metadata=json.loads(row["metadata_json"]),
    )


def approval_from_row(row: sqlite3.Row) -> T1BrainMaskApprovalRecord:
    return T1BrainMaskApprovalRecord(
        id=row["id"],
        subject_id=row["subject_id"],
        artifact_id=row["artifact_id"],
        reviewer=row["reviewer"],
        study_blinding_state=row["study_blinding_state"],
        created_at=row["created_at"],
    )


def _relative_to_root(repository: StudyDatabaseContext, path: Path) -> Path:
    try:
        return Path(path).resolve().relative_to(repository.root_path.resolve())
    except ValueError as exc:
        raise StudyStateError(
            "T1 brain-mask outputs must remain inside the study root."
        ) from exc
