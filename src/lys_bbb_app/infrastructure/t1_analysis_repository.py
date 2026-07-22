"""SQLite persistence for reviewed T1 registration and provisional enhancement."""

from __future__ import annotations

import json
import math
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any, Protocol
from uuid import uuid4

from lys_bbb_app.domain.errors import StudyStateError
from lys_bbb_app.domain.t1_analysis import (
    T1EnhancementJobRecord,
    T1EnhancementMethodRecord,
    T1EnhancementResultDraft,
    T1EnhancementResultRecord,
    T1EnhancementResultState,
    T1RegistrationApprovalRecord,
    T1RegistrationArtifactDraft,
    T1RegistrationArtifactRecord,
    T1RegistrationJobRecord,
    T1RegistrationMethodRecord,
    T1RegistrationState,
)
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


def _relative(repository: StudyDatabaseContext, path: Path) -> str:
    try:
        return path.resolve().relative_to(repository.root_path.resolve()).as_posix()
    except ValueError as exc:
        raise StudyStateError("T1 analysis outputs must remain inside the study root.") from exc


def _finite_or_none(value: float) -> float | None:
    return value if math.isfinite(value) else None


def register_registration_method(
    repository: StudyDatabaseContext,
    *,
    method_version: str,
    method_spec_sha256: str,
    config: dict[str, Any],
    actor: str,
) -> str:
    normalized_actor = normalize_required(actor, "Actor")
    now = utc_now()
    try:
        with closing(connect(repository.database_path)) as connection:
            with connection:
                study = single_study(connection)
                existing = connection.execute(
                    """
                    SELECT id FROM t1_registration_methods
                    WHERE study_id = ? AND method_version = ? AND method_spec_sha256 = ?
                    """,
                    (study["id"], method_version, method_spec_sha256),
                ).fetchone()
                method_id = existing["id"] if existing is not None else str(uuid4())
                connection.execute(
                    "UPDATE t1_registration_methods SET active = 0 WHERE study_id = ?",
                    (study["id"],),
                )
                connection.execute(
                    """
                    INSERT INTO t1_registration_methods(
                        id, study_id, active, method_version, method_spec_sha256,
                        config_json, registered_at, registered_by
                    ) VALUES (?, ?, 1, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        active = 1, registered_at = excluded.registered_at,
                        registered_by = excluded.registered_by
                    """,
                    (
                        method_id,
                        study["id"],
                        method_version,
                        method_spec_sha256,
                        json.dumps(config, sort_keys=True),
                        now,
                        normalized_actor,
                    ),
                )
                touch_study(connection, study["id"], now)
                insert_audit(
                    connection,
                    study_id=study["id"],
                    event_type="T1_REGISTRATION_METHOD_REGISTERED",
                    actor=normalized_actor,
                    details={
                        "method_id": method_id,
                        "method_version": method_version,
                        "method_spec_sha256": method_spec_sha256,
                    },
                    created_at=now,
                )
    except sqlite3.Error as exc:
        raise StudyStateError(f"Could not register the T1 registration method: {exc}") from exc
    return method_id


def create_registration_job(
    repository: StudyDatabaseContext,
    subject_ids: tuple[str, ...],
    *,
    method_id: str,
    actor: str,
) -> str:
    normalized_actor = normalize_required(actor, "Actor")
    job_id = str(uuid4())
    now = utc_now()
    try:
        with closing(connect(repository.database_path)) as connection:
            with connection:
                study = single_study(connection)
                active = connection.execute(
                    """
                    SELECT id FROM t1_registration_methods
                    WHERE id = ? AND study_id = ? AND active = 1
                    """,
                    (method_id, study["id"]),
                ).fetchone()
                if active is None:
                    raise StudyStateError("The selected T1 registration method is not active.")
                connection.execute(
                    """
                    INSERT INTO t1_registration_jobs(
                        id, study_id, state, stage, progress_current, progress_total,
                        method_id, subject_ids_json, submitted_at, metadata_json
                    ) VALUES (?, ?, ?, 'queued', 0, ?, ?, ?, ?, ?)
                    """,
                    (
                        job_id,
                        study["id"],
                        ProcessingJobState.QUEUED.value,
                        len(subject_ids),
                        method_id,
                        json.dumps(subject_ids),
                        now,
                        json.dumps({"submitted_by": normalized_actor}, sort_keys=True),
                    ),
                )
                insert_audit(
                    connection,
                    study_id=study["id"],
                    event_type="T1_REGISTRATION_SUBMITTED",
                    actor=normalized_actor,
                    details={"job_id": job_id, "subject_ids": list(subject_ids)},
                    created_at=now,
                )
    except StudyStateError:
        raise
    except sqlite3.Error as exc:
        raise StudyStateError(f"Could not create the T1 registration job: {exc}") from exc
    return job_id


def start_registration_job(repository: StudyDatabaseContext, job_id: str) -> None:
    _start_job(repository, "t1_registration_jobs", job_id, "preparing_registration")


def update_registration_job(
    repository: StudyDatabaseContext,
    job_id: str,
    current: int,
    total: int,
    stage: str,
) -> None:
    _update_job(repository, "t1_registration_jobs", job_id, current, total, stage)


def fail_registration_job(
    repository: StudyDatabaseContext,
    job_id: str,
    error: str,
    *,
    actor: str,
) -> None:
    _fail_job(
        repository,
        "t1_registration_jobs",
        job_id,
        error,
        actor=actor,
        event_type="T1_REGISTRATION_FAILED",
    )


def complete_registration_job(
    repository: StudyDatabaseContext,
    job_id: str,
    drafts: tuple[T1RegistrationArtifactDraft, ...],
    *,
    method_id: str,
    output_path: Path,
    actor: str,
) -> None:
    normalized_actor = normalize_required(actor, "Actor")
    relative_output = _relative(repository, output_path)
    now = utc_now()
    try:
        with closing(connect(repository.database_path)) as connection:
            with connection:
                study = single_study(connection)
                job = connection.execute(
                    """
                    SELECT state, method_id FROM t1_registration_jobs
                    WHERE id = ? AND study_id = ?
                    """,
                    (job_id, study["id"]),
                ).fetchone()
                if (
                    job is None
                    or job["state"] != ProcessingJobState.RUNNING.value
                    or job["method_id"] != method_id
                ):
                    raise StudyStateError("The T1 registration job is not running.")
                for draft in drafts:
                    _assert_registration_dependencies(connection, draft)
                    artifact_id = str(uuid4())
                    previous = connection.execute(
                        """
                        SELECT id FROM t1_registration_artifacts
                        WHERE subject_id = ? AND active = 1
                        """,
                        (draft.subject_id,),
                    ).fetchone()
                    if previous is not None:
                        connection.execute(
                            """
                            UPDATE t1_registration_artifacts
                            SET active = 0, state = ? WHERE id = ?
                            """,
                            (T1RegistrationState.OUTDATED.value, previous["id"]),
                        )
                    invalidate_enhancement_results(
                        connection,
                        subject_id=draft.subject_id,
                        reason="A new T1 registration artifact was created.",
                        changed_at=now,
                    )
                    version = int(
                        connection.execute(
                            """
                            SELECT COALESCE(MAX(version), 0) + 1
                            FROM t1_registration_artifacts WHERE subject_id = ?
                            """,
                            (draft.subject_id,),
                        ).fetchone()[0]
                    )
                    connection.execute(
                        """
                        INSERT INTO t1_registration_artifacts(
                            id, study_id, subject_id, state, version, active,
                            registered_post_path, registered_post_sha256,
                            transform_path, transform_sha256, qc_preview_path,
                            qc_preview_sha256, source_pre_scan_input_id,
                            source_post_scan_input_id, source_brain_mask_artifact_id,
                            method_id, job_id, before_xcorr, after_xcorr,
                            registration_metric, optimizer_stop, metadata_json,
                            created_at, created_by
                        ) VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                                  ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            artifact_id,
                            study["id"],
                            draft.subject_id,
                            T1RegistrationState.REVIEW_REQUIRED.value,
                            version,
                            _relative(repository, draft.registered_post_path),
                            draft.registered_post_sha256,
                            _relative(repository, draft.transform_path),
                            draft.transform_sha256,
                            _relative(repository, draft.qc_preview_path),
                            draft.qc_preview_sha256,
                            draft.source_pre_scan_input_id,
                            draft.source_post_scan_input_id,
                            draft.source_brain_mask_artifact_id,
                            method_id,
                            job_id,
                            _finite_or_none(draft.before_xcorr),
                            draft.after_xcorr,
                            draft.registration_metric,
                            draft.optimizer_stop,
                            json.dumps(draft.metadata, sort_keys=True),
                            now,
                            normalized_actor,
                        ),
                    )
                    if previous is not None:
                        connection.execute(
                            """
                            UPDATE t1_registration_artifacts SET superseded_by = ?
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
                        event_type="T1_REGISTRATION_ARTIFACT_CREATED",
                        actor=normalized_actor,
                        details={
                            "artifact_id": artifact_id,
                            "version": version,
                            "job_id": job_id,
                            "method_id": method_id,
                            "source_pre_scan_input_id": draft.source_pre_scan_input_id,
                            "source_post_scan_input_id": draft.source_post_scan_input_id,
                            "source_brain_mask_artifact_id": (
                                draft.source_brain_mask_artifact_id
                            ),
                            "human_review_required": True,
                        },
                        created_at=now,
                    )
                connection.execute(
                    """
                    UPDATE t1_registration_jobs
                    SET state = ?, stage = 'artifacts_created',
                        progress_current = progress_total, finished_at = ?,
                        output_path = ?, error_message = NULL
                    WHERE id = ?
                    """,
                    (
                        ProcessingJobState.SUCCEEDED.value,
                        now,
                        relative_output,
                        job_id,
                    ),
                )
                touch_study(connection, study["id"], now)
    except StudyStateError:
        raise
    except sqlite3.Error as exc:
        raise StudyStateError(f"Could not commit T1 registration outputs: {exc}") from exc


def record_registration_approval(
    repository: StudyDatabaseContext,
    artifact_id: str,
    *,
    reviewer: str,
) -> None:
    normalized_reviewer = normalize_required(reviewer, "Reviewer")
    now = utc_now()
    approval_id = str(uuid4())
    try:
        with closing(connect(repository.database_path)) as connection:
            with connection:
                study = single_study(connection)
                artifact = connection.execute(
                    """
                    SELECT a.*, s.archived_at
                    FROM t1_registration_artifacts AS a
                    JOIN subjects AS s ON s.id = a.subject_id
                    WHERE a.id = ?
                    """,
                    (artifact_id,),
                ).fetchone()
                if artifact is None:
                    raise StudyStateError("The selected T1 registration is unavailable.")
                if artifact["archived_at"] is not None:
                    raise StudyStateError("Restore the subject before review.")
                if (
                    not artifact["active"]
                    or artifact["state"] != T1RegistrationState.REVIEW_REQUIRED.value
                ):
                    raise StudyStateError(
                        "Only the active T1 registration awaiting review can be approved."
                    )
                _assert_current_registration_row_dependencies(connection, artifact)
                connection.execute(
                    """
                    INSERT INTO t1_registration_reviews(
                        id, study_id, subject_id, artifact_id, reviewer,
                        study_blinding_state, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        approval_id,
                        study["id"],
                        artifact["subject_id"],
                        artifact_id,
                        normalized_reviewer,
                        study["blinding_state"],
                        now,
                    ),
                )
                connection.execute(
                    "UPDATE t1_registration_artifacts SET state = ? WHERE id = ?",
                    (T1RegistrationState.APPROVED.value, artifact_id),
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
                    event_type="T1_REGISTRATION_APPROVED",
                    actor=normalized_reviewer,
                    details={
                        "artifact_id": artifact_id,
                        "approval_id": approval_id,
                        "registered_post_sha256": artifact["registered_post_sha256"],
                        "transform_sha256": artifact["transform_sha256"],
                        "study_blinding_state": study["blinding_state"],
                    },
                    created_at=now,
                )
    except StudyStateError:
        raise
    except sqlite3.Error as exc:
        raise StudyStateError(f"Could not approve the T1 registration: {exc}") from exc


def register_enhancement_method(
    repository: StudyDatabaseContext,
    *,
    method_version: str,
    method_spec_sha256: str,
    config: dict[str, Any],
    actor: str,
) -> str:
    normalized_actor = normalize_required(actor, "Actor")
    now = utc_now()
    try:
        with closing(connect(repository.database_path)) as connection:
            with connection:
                study = single_study(connection)
                existing = connection.execute(
                    """
                    SELECT id FROM t1_enhancement_methods
                    WHERE study_id = ? AND method_version = ? AND method_spec_sha256 = ?
                    """,
                    (study["id"], method_version, method_spec_sha256),
                ).fetchone()
                method_id = existing["id"] if existing is not None else str(uuid4())
                connection.execute(
                    "UPDATE t1_enhancement_methods SET active = 0 WHERE study_id = ?",
                    (study["id"],),
                )
                connection.execute(
                    """
                    INSERT INTO t1_enhancement_methods(
                        id, study_id, active, method_version, method_spec_sha256,
                        scientific_status, config_json, registered_at, registered_by
                    ) VALUES (?, ?, 1, ?, ?, 'PROVISIONAL', ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        active = 1, registered_at = excluded.registered_at,
                        registered_by = excluded.registered_by
                    """,
                    (
                        method_id,
                        study["id"],
                        method_version,
                        method_spec_sha256,
                        json.dumps(config, sort_keys=True),
                        now,
                        normalized_actor,
                    ),
                )
                invalidated = connection.execute(
                    """
                    UPDATE t1_enhancement_results
                    SET active = 0, state = 'OUTDATED', outdated_at = ?,
                        outdated_reason = 'The active T1 enhancement method changed.'
                    WHERE study_id = ? AND active = 1 AND method_id != ?
                    """,
                    (now, study["id"], method_id),
                ).rowcount
                touch_study(connection, study["id"], now)
                insert_audit(
                    connection,
                    study_id=study["id"],
                    event_type="T1_ENHANCEMENT_METHOD_REGISTERED",
                    actor=normalized_actor,
                    details={
                        "method_id": method_id,
                        "method_version": method_version,
                        "method_spec_sha256": method_spec_sha256,
                        "scientific_status": "PROVISIONAL",
                        "results_invalidated": invalidated,
                    },
                    created_at=now,
                )
    except sqlite3.Error as exc:
        raise StudyStateError(f"Could not register the T1 enhancement method: {exc}") from exc
    return method_id


def create_enhancement_job(
    repository: StudyDatabaseContext,
    subject_ids: tuple[str, ...],
    *,
    method_id: str,
    actor: str,
) -> str:
    return _create_analysis_job(
        repository,
        "t1_enhancement_jobs",
        "t1_enhancement_methods",
        subject_ids,
        method_id=method_id,
        actor=actor,
        event_type="T1_ENHANCEMENT_SUBMITTED",
    )


def start_enhancement_job(repository: StudyDatabaseContext, job_id: str) -> None:
    _start_job(repository, "t1_enhancement_jobs", job_id, "preparing_enhancement")


def update_enhancement_job(
    repository: StudyDatabaseContext,
    job_id: str,
    current: int,
    total: int,
    stage: str,
) -> None:
    _update_job(repository, "t1_enhancement_jobs", job_id, current, total, stage)


def fail_enhancement_job(
    repository: StudyDatabaseContext,
    job_id: str,
    error: str,
    *,
    actor: str,
) -> None:
    _fail_job(
        repository,
        "t1_enhancement_jobs",
        job_id,
        error,
        actor=actor,
        event_type="T1_ENHANCEMENT_FAILED",
    )


def complete_enhancement_job(
    repository: StudyDatabaseContext,
    job_id: str,
    drafts: tuple[T1EnhancementResultDraft, ...],
    *,
    method_id: str,
    output_path: Path,
    actor: str,
) -> None:
    normalized_actor = normalize_required(actor, "Actor")
    relative_output = _relative(repository, output_path)
    now = utc_now()
    try:
        with closing(connect(repository.database_path)) as connection:
            with connection:
                study = single_study(connection)
                job = connection.execute(
                    """
                    SELECT state, method_id FROM t1_enhancement_jobs
                    WHERE id = ? AND study_id = ?
                    """,
                    (job_id, study["id"]),
                ).fetchone()
                if (
                    job is None
                    or job["state"] != ProcessingJobState.RUNNING.value
                    or job["method_id"] != method_id
                ):
                    raise StudyStateError("The T1 enhancement job is not running.")
                for draft in drafts:
                    _assert_enhancement_dependencies(connection, draft)
                    result_id = str(uuid4())
                    previous = connection.execute(
                        """
                        SELECT id FROM t1_enhancement_results
                        WHERE subject_id = ? AND active = 1
                        """,
                        (draft.subject_id,),
                    ).fetchone()
                    if previous is not None:
                        connection.execute(
                            """
                            UPDATE t1_enhancement_results
                            SET active = 0, state = 'OUTDATED', outdated_at = ?,
                                outdated_reason = 'A new provisional result was created.'
                            WHERE id = ?
                            """,
                            (now, previous["id"]),
                        )
                    version = int(
                        connection.execute(
                            """
                            SELECT COALESCE(MAX(version), 0) + 1
                            FROM t1_enhancement_results WHERE subject_id = ?
                            """,
                            (draft.subject_id,),
                        ).fetchone()[0]
                    )
                    connection.execute(
                        """
                        INSERT INTO t1_enhancement_results(
                            id, study_id, subject_id, version, state, active,
                            percent_enhancement_map, percent_enhancement_sha256,
                            summary_csv, summary_sha256, qc_preview_path,
                            qc_preview_sha256, metadata_path, metadata_sha256,
                            source_registration_artifact_id,
                            source_brain_mask_artifact_id, source_pre_scan_input_id,
                            method_id, job_id, metrics_json, metadata_json,
                            created_at, created_by
                        ) VALUES (?, ?, ?, ?, 'PROVISIONAL', 1, ?, ?, ?, ?, ?, ?, ?, ?,
                                  ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            result_id,
                            study["id"],
                            draft.subject_id,
                            version,
                            _relative(repository, draft.percent_enhancement_map),
                            draft.percent_enhancement_sha256,
                            _relative(repository, draft.summary_csv),
                            draft.summary_sha256,
                            _relative(repository, draft.qc_preview_path),
                            draft.qc_preview_sha256,
                            _relative(repository, draft.metadata_path),
                            draft.metadata_sha256,
                            draft.source_registration_artifact_id,
                            draft.source_brain_mask_artifact_id,
                            draft.source_pre_scan_input_id,
                            method_id,
                            job_id,
                            json.dumps(draft.metrics, sort_keys=True),
                            json.dumps(draft.metadata, sort_keys=True),
                            now,
                            normalized_actor,
                        ),
                    )
                    if previous is not None:
                        connection.execute(
                            """
                            UPDATE t1_enhancement_results SET superseded_by = ?
                            WHERE id = ?
                            """,
                            (result_id, previous["id"]),
                        )
                    connection.execute(
                        "UPDATE subjects SET updated_at = ? WHERE id = ?",
                        (now, draft.subject_id),
                    )
                    insert_audit(
                        connection,
                        study_id=study["id"],
                        subject_id=draft.subject_id,
                        event_type="T1_PROVISIONAL_ENHANCEMENT_CREATED",
                        actor=normalized_actor,
                        details={
                            "result_id": result_id,
                            "version": version,
                            "method_id": method_id,
                            "source_registration_artifact_id": (
                                draft.source_registration_artifact_id
                            ),
                            "source_brain_mask_artifact_id": (
                                draft.source_brain_mask_artifact_id
                            ),
                            "scientific_status": "PROVISIONAL",
                            "registration_recomputed": False,
                        },
                        created_at=now,
                    )
                connection.execute(
                    """
                    UPDATE t1_enhancement_jobs
                    SET state = ?, stage = 'provisional_results_created',
                        progress_current = progress_total, finished_at = ?,
                        output_path = ?, error_message = NULL
                    WHERE id = ?
                    """,
                    (
                        ProcessingJobState.SUCCEEDED.value,
                        now,
                        relative_output,
                        job_id,
                    ),
                )
                touch_study(connection, study["id"], now)
    except StudyStateError:
        raise
    except sqlite3.Error as exc:
        raise StudyStateError(f"Could not commit T1 enhancement results: {exc}") from exc


def invalidate_t1_analysis(
    connection: sqlite3.Connection,
    *,
    subject_id: str,
    reason: str,
    changed_at: str,
    invalidate_registration: bool,
) -> tuple[int, int]:
    registrations = 0
    if invalidate_registration:
        registrations = connection.execute(
            """
            UPDATE t1_registration_artifacts
            SET active = 0, state = 'OUTDATED'
            WHERE subject_id = ? AND active = 1
            """,
            (subject_id,),
        ).rowcount
    results = invalidate_enhancement_results(
        connection,
        subject_id=subject_id,
        reason=reason,
        changed_at=changed_at,
    )
    return registrations, results


def invalidate_enhancement_results(
    connection: sqlite3.Connection,
    *,
    subject_id: str,
    reason: str,
    changed_at: str,
) -> int:
    return int(
        connection.execute(
            """
            UPDATE t1_enhancement_results
            SET active = 0, state = 'OUTDATED', outdated_at = ?, outdated_reason = ?
            WHERE subject_id = ? AND active = 1
            """,
            (changed_at, reason, subject_id),
        ).rowcount
    )


def interrupt_running_jobs(repository: StudyDatabaseContext) -> int:
    now = utc_now()
    count = 0
    try:
        with closing(connect(repository.database_path)) as connection:
            with connection:
                for table in ("t1_registration_jobs", "t1_enhancement_jobs"):
                    count += connection.execute(
                        f"""
                        UPDATE {table}
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
    except sqlite3.Error as exc:
        raise StudyStateError(f"Could not recover interrupted T1 jobs: {exc}") from exc
    return int(count)


def registration_method_from_row(row: sqlite3.Row) -> T1RegistrationMethodRecord:
    return T1RegistrationMethodRecord(
        id=row["id"],
        active=bool(row["active"]),
        method_version=row["method_version"],
        method_spec_sha256=row["method_spec_sha256"],
        config=json.loads(row["config_json"]),
        registered_at=row["registered_at"],
        registered_by=row["registered_by"],
    )


def registration_job_from_row(
    row: sqlite3.Row,
    root_path: Path,
) -> T1RegistrationJobRecord:
    return T1RegistrationJobRecord(
        id=row["id"],
        state=ProcessingJobState(row["state"]),
        stage=row["stage"],
        progress_current=row["progress_current"],
        progress_total=row["progress_total"],
        method_id=row["method_id"],
        subject_ids=tuple(json.loads(row["subject_ids_json"])),
        submitted_at=row["submitted_at"],
        started_at=row["started_at"],
        finished_at=row["finished_at"],
        error_message=row["error_message"],
        output_path=root_path / row["output_path"] if row["output_path"] else None,
        metadata=json.loads(row["metadata_json"]),
    )


def registration_artifact_from_row(
    row: sqlite3.Row,
    root_path: Path,
) -> T1RegistrationArtifactRecord:
    return T1RegistrationArtifactRecord(
        id=row["id"],
        subject_id=row["subject_id"],
        state=T1RegistrationState(row["state"]),
        version=int(row["version"]),
        active=bool(row["active"]),
        registered_post_path=root_path / row["registered_post_path"],
        registered_post_sha256=row["registered_post_sha256"],
        transform_path=root_path / row["transform_path"],
        transform_sha256=row["transform_sha256"],
        qc_preview_path=root_path / row["qc_preview_path"],
        qc_preview_sha256=row["qc_preview_sha256"],
        source_pre_scan_input_id=row["source_pre_scan_input_id"],
        source_post_scan_input_id=row["source_post_scan_input_id"],
        source_brain_mask_artifact_id=row["source_brain_mask_artifact_id"],
        method_id=row["method_id"],
        job_id=row["job_id"],
        before_xcorr=(
            float(row["before_xcorr"])
            if row["before_xcorr"] is not None
            else float("nan")
        ),
        after_xcorr=float(row["after_xcorr"]),
        registration_metric=float(row["registration_metric"]),
        optimizer_stop=row["optimizer_stop"],
        created_at=row["created_at"],
        created_by=row["created_by"],
        superseded_by=row["superseded_by"],
        metadata=json.loads(row["metadata_json"]),
    )


def registration_approval_from_row(row: sqlite3.Row) -> T1RegistrationApprovalRecord:
    return T1RegistrationApprovalRecord(
        id=row["id"],
        subject_id=row["subject_id"],
        artifact_id=row["artifact_id"],
        reviewer=row["reviewer"],
        study_blinding_state=row["study_blinding_state"],
        created_at=row["created_at"],
    )


def enhancement_method_from_row(row: sqlite3.Row) -> T1EnhancementMethodRecord:
    return T1EnhancementMethodRecord(
        id=row["id"],
        active=bool(row["active"]),
        method_version=row["method_version"],
        method_spec_sha256=row["method_spec_sha256"],
        scientific_status=row["scientific_status"],
        config=json.loads(row["config_json"]),
        registered_at=row["registered_at"],
        registered_by=row["registered_by"],
    )


def enhancement_job_from_row(
    row: sqlite3.Row,
    root_path: Path,
) -> T1EnhancementJobRecord:
    return T1EnhancementJobRecord(
        id=row["id"],
        state=ProcessingJobState(row["state"]),
        stage=row["stage"],
        progress_current=row["progress_current"],
        progress_total=row["progress_total"],
        method_id=row["method_id"],
        subject_ids=tuple(json.loads(row["subject_ids_json"])),
        submitted_at=row["submitted_at"],
        started_at=row["started_at"],
        finished_at=row["finished_at"],
        error_message=row["error_message"],
        output_path=root_path / row["output_path"] if row["output_path"] else None,
        metadata=json.loads(row["metadata_json"]),
    )


def enhancement_result_from_row(
    row: sqlite3.Row,
    root_path: Path,
) -> T1EnhancementResultRecord:
    return T1EnhancementResultRecord(
        id=row["id"],
        subject_id=row["subject_id"],
        version=int(row["version"]),
        state=T1EnhancementResultState(row["state"]),
        active=bool(row["active"]),
        percent_enhancement_map=root_path / row["percent_enhancement_map"],
        percent_enhancement_sha256=row["percent_enhancement_sha256"],
        summary_csv=root_path / row["summary_csv"],
        summary_sha256=row["summary_sha256"],
        qc_preview_path=root_path / row["qc_preview_path"],
        qc_preview_sha256=row["qc_preview_sha256"],
        metadata_path=root_path / row["metadata_path"],
        metadata_sha256=row["metadata_sha256"],
        source_registration_artifact_id=row["source_registration_artifact_id"],
        source_brain_mask_artifact_id=row["source_brain_mask_artifact_id"],
        source_pre_scan_input_id=row["source_pre_scan_input_id"],
        method_id=row["method_id"],
        job_id=row["job_id"],
        metrics=tuple(json.loads(row["metrics_json"])),
        metadata=json.loads(row["metadata_json"]),
        created_at=row["created_at"],
        created_by=row["created_by"],
        outdated_at=row["outdated_at"],
        outdated_reason=row["outdated_reason"],
        superseded_by=row["superseded_by"],
    )


def _assert_registration_dependencies(
    connection: sqlite3.Connection,
    draft: T1RegistrationArtifactDraft,
) -> None:
    pre = connection.execute(
        """
        SELECT id FROM scan_inputs
        WHERE id = ? AND subject_id = ? AND role = 'T1_PRE' AND active = 1
          AND state = 'CONVERTED' AND validation_state = 'VALID'
        """,
        (draft.source_pre_scan_input_id, draft.subject_id),
    ).fetchone()
    post = connection.execute(
        """
        SELECT id FROM scan_inputs
        WHERE id = ? AND subject_id = ? AND role = 'T1_POST' AND active = 1
          AND state = 'CONVERTED' AND validation_state = 'VALID'
        """,
        (draft.source_post_scan_input_id, draft.subject_id),
    ).fetchone()
    mask = connection.execute(
        """
        SELECT a.id FROM t1_brain_mask_artifacts AS a
        JOIN t1_brain_mask_reviews AS r ON r.artifact_id = a.id
        WHERE a.id = ? AND a.subject_id = ? AND a.active = 1 AND a.state = 'APPROVED'
        """,
        (draft.source_brain_mask_artifact_id, draft.subject_id),
    ).fetchone()
    if pre is None or post is None or mask is None:
        raise StudyStateError(
            "T1 registration requires the current validated pre/post inputs and "
            "the exact approved brain mask."
        )


def _assert_current_registration_row_dependencies(
    connection: sqlite3.Connection,
    artifact: sqlite3.Row,
) -> None:
    draft = T1RegistrationArtifactDraft(
        subject_id=artifact["subject_id"],
        registered_post_path=Path("unused"),
        registered_post_sha256=artifact["registered_post_sha256"],
        transform_path=Path("unused"),
        transform_sha256=artifact["transform_sha256"],
        qc_preview_path=Path("unused"),
        qc_preview_sha256=artifact["qc_preview_sha256"],
        source_pre_scan_input_id=artifact["source_pre_scan_input_id"],
        source_post_scan_input_id=artifact["source_post_scan_input_id"],
        source_brain_mask_artifact_id=artifact["source_brain_mask_artifact_id"],
        before_xcorr=float("nan"),
        after_xcorr=float(artifact["after_xcorr"]),
        registration_metric=float(artifact["registration_metric"]),
        optimizer_stop=artifact["optimizer_stop"],
        metadata={},
    )
    _assert_registration_dependencies(connection, draft)


def _assert_enhancement_dependencies(
    connection: sqlite3.Connection,
    draft: T1EnhancementResultDraft,
) -> None:
    registration = connection.execute(
        """
        SELECT a.id FROM t1_registration_artifacts AS a
        JOIN t1_registration_reviews AS r ON r.artifact_id = a.id
        WHERE a.id = ? AND a.subject_id = ? AND a.active = 1 AND a.state = 'APPROVED'
          AND a.source_brain_mask_artifact_id = ?
          AND a.source_pre_scan_input_id = ?
        """,
        (
            draft.source_registration_artifact_id,
            draft.subject_id,
            draft.source_brain_mask_artifact_id,
            draft.source_pre_scan_input_id,
        ),
    ).fetchone()
    mask = connection.execute(
        """
        SELECT a.id FROM t1_brain_mask_artifacts AS a
        JOIN t1_brain_mask_reviews AS r ON r.artifact_id = a.id
        WHERE a.id = ? AND a.subject_id = ? AND a.active = 1 AND a.state = 'APPROVED'
        """,
        (draft.source_brain_mask_artifact_id, draft.subject_id),
    ).fetchone()
    if registration is None or mask is None:
        raise StudyStateError(
            "T1 enhancement requires the exact approved registration and brain mask."
        )


def _create_analysis_job(
    repository: StudyDatabaseContext,
    job_table: str,
    method_table: str,
    subject_ids: tuple[str, ...],
    *,
    method_id: str,
    actor: str,
    event_type: str,
) -> str:
    normalized_actor = normalize_required(actor, "Actor")
    job_id = str(uuid4())
    now = utc_now()
    try:
        with closing(connect(repository.database_path)) as connection:
            with connection:
                study = single_study(connection)
                method = connection.execute(
                    f"SELECT id FROM {method_table} WHERE id = ? AND active = 1",
                    (method_id,),
                ).fetchone()
                if method is None:
                    raise StudyStateError("The selected T1 method is not active.")
                connection.execute(
                    f"""
                    INSERT INTO {job_table}(
                        id, study_id, state, stage, progress_current, progress_total,
                        method_id, subject_ids_json, submitted_at, metadata_json
                    ) VALUES (?, ?, ?, 'queued', 0, ?, ?, ?, ?, ?)
                    """,
                    (
                        job_id,
                        study["id"],
                        ProcessingJobState.QUEUED.value,
                        len(subject_ids),
                        method_id,
                        json.dumps(subject_ids),
                        now,
                        json.dumps({"submitted_by": normalized_actor}, sort_keys=True),
                    ),
                )
                insert_audit(
                    connection,
                    study_id=study["id"],
                    event_type=event_type,
                    actor=normalized_actor,
                    details={"job_id": job_id, "subject_ids": list(subject_ids)},
                    created_at=now,
                )
    except StudyStateError:
        raise
    except sqlite3.Error as exc:
        raise StudyStateError(f"Could not create the T1 analysis job: {exc}") from exc
    return job_id


def _start_job(
    repository: StudyDatabaseContext,
    table: str,
    job_id: str,
    stage: str,
) -> None:
    now = utc_now()
    try:
        with closing(connect(repository.database_path)) as connection:
            with connection:
                changed = connection.execute(
                    f"""
                    UPDATE {table} SET state = ?, stage = ?, started_at = ?
                    WHERE id = ? AND state = ?
                    """,
                    (
                        ProcessingJobState.RUNNING.value,
                        stage,
                        now,
                        job_id,
                        ProcessingJobState.QUEUED.value,
                    ),
                ).rowcount
                if changed != 1:
                    raise StudyStateError("The T1 analysis job cannot be started.")
    except StudyStateError:
        raise
    except sqlite3.Error as exc:
        raise StudyStateError(f"Could not start the T1 analysis job: {exc}") from exc


def _update_job(
    repository: StudyDatabaseContext,
    table: str,
    job_id: str,
    current: int,
    total: int,
    stage: str,
) -> None:
    try:
        with closing(connect(repository.database_path)) as connection:
            with connection:
                connection.execute(
                    f"""
                    UPDATE {table}
                    SET stage = ?, progress_current = ?, progress_total = ?
                    WHERE id = ? AND state = ?
                    """,
                    (stage, current, total, job_id, ProcessingJobState.RUNNING.value),
                )
    except sqlite3.Error as exc:
        raise StudyStateError(f"Could not update T1 analysis progress: {exc}") from exc


def _fail_job(
    repository: StudyDatabaseContext,
    table: str,
    job_id: str,
    error: str,
    *,
    actor: str,
    event_type: str,
) -> None:
    message = normalize_required(error, "T1 analysis error")
    now = utc_now()
    try:
        with closing(connect(repository.database_path)) as connection:
            with connection:
                study = single_study(connection)
                connection.execute(
                    f"""
                    UPDATE {table}
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
                    event_type=event_type,
                    actor=normalize_required(actor, "Actor"),
                    details={"job_id": job_id, "error": message},
                    created_at=now,
                )
    except sqlite3.Error as exc:
        raise StudyStateError(f"Could not record T1 analysis failure: {exc}") from exc
