"""SQLite persistence for immutable T2 mask reviews and approved lesion results."""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Protocol
from uuid import uuid4

from lys_bbb.t2_review import T2MaskMeasurement
from lys_bbb_app.domain.errors import StudyStateError
from lys_bbb_app.domain.t2_lesion import (
    ArtifactState,
    ResultState,
    ReviewDecision,
    T2CorrectedArtifactDraft,
    T2LesionResultRecord,
    T2ReviewDecisionRecord,
    T2_LESION_MASK_ARTIFACT_TYPE,
    T2_LESION_VOLUME_RESULT_TYPE,
    T2_NATIVE_VOLUME_METHOD_VERSION,
)
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


def create_corrected_t2_artifact(
    repository: StudyDatabaseContext,
    draft: T2CorrectedArtifactDraft,
    *,
    actor: str,
) -> str:
    """Register one validated correction as a new immutable artifact version."""

    reviewer = normalize_required(actor, "Actor")
    now = utc_now()
    relative_mask = _relative_to_root(repository, draft.mask_path)
    relative_qc = (
        _relative_to_root(repository, draft.qc_preview_path)
        if draft.qc_preview_path is not None
        else None
    )
    artifact_id = str(uuid4())
    try:
        with closing(connect(repository.database_path)) as connection:
            with connection:
                study = single_study(connection)
                source = connection.execute(
                    """
                    SELECT * FROM artifacts
                    WHERE id = ? AND subject_id = ? AND artifact_type = ?
                    """,
                    (
                        draft.source_artifact_id,
                        draft.subject_id,
                        T2_LESION_MASK_ARTIFACT_TYPE,
                    ),
                ).fetchone()
                if source is None:
                    raise StudyStateError(
                        "The source T2 lesion artifact is unavailable."
                    )
                if not source["active"] or source["state"] not in {
                    ArtifactState.DRAFT_REVIEW_REQUIRED.value,
                    ArtifactState.CORRECTED_REVIEW_REQUIRED.value,
                    ArtifactState.APPROVED.value,
                }:
                    raise StudyStateError(
                        "Start the correction from the current T2 lesion mask."
                    )
                current = connection.execute(
                    """
                    SELECT id FROM artifacts
                    WHERE subject_id = ? AND artifact_type = ? AND active = 1
                    """,
                    (draft.subject_id, T2_LESION_MASK_ARTIFACT_TYPE),
                ).fetchone()
                if current is not None and current["id"] != source["id"]:
                    raise StudyStateError(
                        "A newer T2 lesion artifact is already active for this subject."
                    )

                version = int(
                    connection.execute(
                        """
                        SELECT COALESCE(MAX(version), 0) + 1 FROM artifacts
                        WHERE subject_id = ? AND artifact_type = ?
                        """,
                        (draft.subject_id, T2_LESION_MASK_ARTIFACT_TYPE),
                    ).fetchone()[0]
                )
                if current is not None:
                    connection.execute(
                        """
                        UPDATE artifacts SET active = 0, state = ?
                        WHERE id = ?
                        """,
                        (ArtifactState.OUTDATED.value, source["id"]),
                    )

                source_metadata = json.loads(source["metadata_json"])
                metadata = dict(source_metadata)
                metadata.update(draft.metadata)
                metadata.update(
                    {
                        "origin": "CORRECTED",
                        "source_artifact_id": source["id"],
                        "imported_from": str(draft.imported_from),
                        "qc_preview_path": (
                            relative_qc.as_posix() if relative_qc is not None else None
                        ),
                        "lesion_voxel_count": draft.lesion_voxel_count,
                        "provisional_volume_mm3": draft.provisional_volume_mm3,
                        "automatic_prediction": False,
                        "human_review_required": True,
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
                        T2_LESION_MASK_ARTIFACT_TYPE,
                        ArtifactState.CORRECTED_REVIEW_REQUIRED.value,
                        version,
                        relative_mask.as_posix(),
                        draft.mask_sha256,
                        source["source_scan_input_id"],
                        source["model_release_id"],
                        source["job_id"],
                        json.dumps(metadata, sort_keys=True),
                        now,
                        reviewer,
                    ),
                )
                connection.execute(
                    "UPDATE artifacts SET superseded_by = ? WHERE id = ?",
                    (artifact_id, source["id"]),
                )
                invalidated = invalidate_t2_results(
                    connection,
                    subject_id=draft.subject_id,
                    reason="A corrected T2 lesion mask was imported.",
                    changed_at=now,
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
                    event_type="T2_CORRECTED_LESION_MASK_IMPORTED",
                    actor=reviewer,
                    details={
                        "artifact_id": artifact_id,
                        "source_artifact_id": source["id"],
                        "version": version,
                        "mask_sha256": draft.mask_sha256,
                        "lesion_voxel_count": draft.lesion_voxel_count,
                        "provisional_volume_mm3": draft.provisional_volume_mm3,
                        "results_invalidated": invalidated,
                        "human_review_required": True,
                    },
                    created_at=now,
                )
    except StudyStateError:
        raise
    except (json.JSONDecodeError, sqlite3.Error) as exc:
        raise StudyStateError(
            f"Could not register the corrected T2 lesion mask: {exc}"
        ) from exc
    return artifact_id


def record_t2_review(
    repository: StudyDatabaseContext,
    artifact_id: str,
    decision: ReviewDecision,
    *,
    reviewer: str,
    issue_code: str | None = None,
    notes: str | None = None,
    measurement: T2MaskMeasurement | None = None,
) -> None:
    """Record one immutable decision and create an official result on approval."""

    normalized_reviewer = normalize_required(reviewer, "Reviewer")
    normalized_notes = _normalize_optional(notes)
    normalized_issue = _normalize_optional(issue_code)
    if decision is ReviewDecision.REJECTED and (
        normalized_issue is None or normalized_notes is None
    ):
        raise StudyStateError("Rejecting a T2 lesion mask requires an issue and notes.")
    if decision is ReviewDecision.APPROVED and measurement is None:
        raise StudyStateError("An approved T2 lesion mask requires a validated measurement.")

    now = utc_now()
    review_id = str(uuid4())
    try:
        with closing(connect(repository.database_path)) as connection:
            with connection:
                study = single_study(connection)
                artifact = connection.execute(
                    """
                    SELECT a.*, s.archived_at
                    FROM artifacts AS a
                    JOIN subjects AS s ON s.id = a.subject_id
                    WHERE a.id = ? AND a.artifact_type = ?
                    """,
                    (artifact_id, T2_LESION_MASK_ARTIFACT_TYPE),
                ).fetchone()
                if artifact is None:
                    raise StudyStateError("The selected T2 lesion artifact is unavailable.")
                if artifact["archived_at"] is not None:
                    raise StudyStateError("Restore the subject before reviewing its mask.")
                if not artifact["active"] or artifact["state"] not in {
                    ArtifactState.DRAFT_REVIEW_REQUIRED.value,
                    ArtifactState.CORRECTED_REVIEW_REQUIRED.value,
                }:
                    raise StudyStateError(
                        "Only the active T2 lesion mask awaiting review can be decided."
                    )
                existing_review = connection.execute(
                    "SELECT id FROM reviews WHERE artifact_id = ?",
                    (artifact_id,),
                ).fetchone()
                if existing_review is not None:
                    raise StudyStateError(
                        "This exact T2 lesion artifact already has a review decision."
                    )
                if measurement is not None and measurement.mask_sha256 != artifact["file_hash"]:
                    raise StudyStateError(
                        "The validated lesion mask does not match the registered artifact."
                    )

                connection.execute(
                    """
                    INSERT INTO reviews(
                        id, study_id, subject_id, artifact_id, decision, reviewer,
                        study_blinding_state, issue_code, notes, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        review_id,
                        study["id"],
                        artifact["subject_id"],
                        artifact_id,
                        decision.value,
                        normalized_reviewer,
                        study["blinding_state"],
                        normalized_issue,
                        normalized_notes,
                        now,
                    ),
                )

                result_id: str | None = None
                if decision is ReviewDecision.REJECTED:
                    connection.execute(
                        "UPDATE artifacts SET state = ?, active = 0 WHERE id = ?",
                        (ArtifactState.REJECTED.value, artifact_id),
                    )
                else:
                    assert measurement is not None
                    connection.execute(
                        "UPDATE artifacts SET state = ? WHERE id = ?",
                        (ArtifactState.APPROVED.value, artifact_id),
                    )
                    result_id = _create_approved_result(
                        connection,
                        study_id=study["id"],
                        artifact=artifact,
                        measurement=measurement,
                        reviewer=normalized_reviewer,
                        timestamp=now,
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
                    event_type=f"T2_LESION_MASK_{decision.value}",
                    actor=normalized_reviewer,
                    details={
                        "artifact_id": artifact_id,
                        "review_id": review_id,
                        "decision": decision.value,
                        "issue_code": normalized_issue,
                        "notes": normalized_notes,
                        "study_blinding_state": study["blinding_state"],
                        "result_id": result_id,
                    },
                    created_at=now,
                )
    except StudyStateError:
        raise
    except sqlite3.IntegrityError as exc:
        raise StudyStateError(
            "This exact T2 lesion artifact already has a review decision."
        ) from exc
    except sqlite3.Error as exc:
        raise StudyStateError(f"Could not record the T2 mask review: {exc}") from exc


def invalidate_t2_results(
    connection: sqlite3.Connection,
    *,
    reason: str,
    changed_at: str,
    subject_id: str | None = None,
    study_id: str | None = None,
    excluding_release_id: str | None = None,
) -> int:
    """Mark matching active T2 results outdated inside an existing transaction."""

    clauses = ["result_type = ?", "active = 1"]
    parameters: list[object] = [T2_LESION_VOLUME_RESULT_TYPE]
    if subject_id is not None:
        clauses.append("subject_id = ?")
        parameters.append(subject_id)
    if study_id is not None:
        clauses.append("study_id = ?")
        parameters.append(study_id)
    if excluding_release_id is not None:
        clauses.append("model_release_id != ?")
        parameters.append(excluding_release_id)
    parameters = [
        ResultState.OUTDATED.value,
        changed_at,
        normalize_required(reason, "Invalidation reason"),
        *parameters,
    ]
    cursor = connection.execute(
        f"""
        UPDATE results
        SET state = ?, active = 0, outdated_at = ?, outdated_reason = ?
        WHERE {' AND '.join(clauses)}
        """,
        parameters,
    )
    return int(cursor.rowcount)


def review_from_row(row: sqlite3.Row) -> T2ReviewDecisionRecord:
    return T2ReviewDecisionRecord(
        id=row["id"],
        subject_id=row["subject_id"],
        artifact_id=row["artifact_id"],
        decision=ReviewDecision(row["decision"]),
        reviewer=row["reviewer"],
        study_blinding_state=row["study_blinding_state"],
        issue_code=row["issue_code"],
        notes=row["notes"],
        created_at=row["created_at"],
    )


def result_from_row(row: sqlite3.Row) -> T2LesionResultRecord:
    return T2LesionResultRecord(
        id=row["id"],
        subject_id=row["subject_id"],
        version=int(row["version"]),
        state=ResultState(row["state"]),
        active=bool(row["active"]),
        lesion_voxel_count=int(row["lesion_voxel_count"]),
        lesion_volume_mm3=float(row["value"]),
        unit=row["unit"],
        method_version=row["method_version"],
        source_artifact_id=row["source_artifact_id"],
        source_scan_input_id=row["source_scan_input_id"],
        model_release_id=row["model_release_id"],
        mask_sha256=row["mask_sha256"],
        reviewer=row["reviewer"],
        created_at=row["created_at"],
        approved_at=row["approved_at"],
        outdated_at=row["outdated_at"],
        outdated_reason=row["outdated_reason"],
        superseded_by=row["superseded_by"],
        metadata=json.loads(row["metadata_json"]),
    )


def _create_approved_result(
    connection: sqlite3.Connection,
    *,
    study_id: str,
    artifact: sqlite3.Row,
    measurement: T2MaskMeasurement,
    reviewer: str,
    timestamp: str,
) -> str:
    previous = connection.execute(
        """
        SELECT id FROM results
        WHERE subject_id = ? AND result_type = ?
        ORDER BY version DESC
        LIMIT 1
        """,
        (artifact["subject_id"], T2_LESION_VOLUME_RESULT_TYPE),
    ).fetchone()
    invalidate_t2_results(
        connection,
        subject_id=artifact["subject_id"],
        reason="A newer T2 lesion mask was approved.",
        changed_at=timestamp,
    )
    version = int(
        connection.execute(
            """
            SELECT COALESCE(MAX(version), 0) + 1 FROM results
            WHERE subject_id = ? AND result_type = ?
            """,
            (artifact["subject_id"], T2_LESION_VOLUME_RESULT_TYPE),
        ).fetchone()[0]
    )
    result_id = str(uuid4())
    metadata = {
        "shape": list(measurement.shape),
        "spacing_mm": list(measurement.spacing_mm),
        "axis_codes": list(measurement.axis_codes),
        "formula": "lesion_voxel_count * product(native_t2_spacing_mm)",
        "native_space": True,
        "warnings": [],
    }
    connection.execute(
        """
        INSERT INTO results(
            id, study_id, subject_id, result_type, version, state, active,
            value, unit, lesion_voxel_count, method_version, source_artifact_id,
            source_scan_input_id, model_release_id, mask_sha256, reviewer,
            metadata_json, created_at, approved_at
        ) VALUES (?, ?, ?, ?, ?, ?, 1, ?, 'mm3', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            result_id,
            study_id,
            artifact["subject_id"],
            T2_LESION_VOLUME_RESULT_TYPE,
            version,
            ResultState.APPROVED.value,
            measurement.lesion_volume_mm3,
            measurement.lesion_voxel_count,
            T2_NATIVE_VOLUME_METHOD_VERSION,
            artifact["id"],
            artifact["source_scan_input_id"],
            artifact["model_release_id"],
            measurement.mask_sha256,
            reviewer,
            json.dumps(metadata, sort_keys=True),
            timestamp,
            timestamp,
        ),
    )
    if previous is not None:
        connection.execute(
            "UPDATE results SET superseded_by = ? WHERE id = ?",
            (result_id, previous["id"]),
        )
    insert_audit(
        connection,
        study_id=study_id,
        subject_id=artifact["subject_id"],
        event_type="T2_LESION_RESULT_APPROVED",
        actor=reviewer,
        details={
            "result_id": result_id,
            "result_version": version,
            "artifact_id": artifact["id"],
            "mask_sha256": measurement.mask_sha256,
            "lesion_voxel_count": measurement.lesion_voxel_count,
            "lesion_volume_mm3": measurement.lesion_volume_mm3,
            "unit": "mm3",
            "method_version": T2_NATIVE_VOLUME_METHOD_VERSION,
        },
        created_at=timestamp,
    )
    return result_id


def _normalize_optional(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


def _relative_to_root(repository: StudyDatabaseContext, path: Path) -> Path:
    try:
        return Path(path).resolve().relative_to(repository.root_path.resolve())
    except ValueError as exc:
        raise StudyStateError(
            "Corrected T2 lesion artifacts must remain inside the study root."
        ) from exc
