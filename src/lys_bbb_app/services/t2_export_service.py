"""Approved-only T2 result export without Qt dependencies."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

from lys_bbb_app.domain.errors import StudyStateError
from lys_bbb_app.domain.study import StudySnapshot
from lys_bbb_app.domain.t2_lesion import ResultState


@dataclass(frozen=True)
class ApprovedT2Export:
    path: Path
    row_count: int
    blinded: bool


def export_approved_t2_results(
    study: StudySnapshot,
    destination: Path | str,
) -> ApprovedT2Export:
    """Write active approved T2 lesion results; provisional values are excluded."""

    output = Path(destination).expanduser().resolve()
    if output.exists():
        raise StudyStateError(f"The export already exists and will not be overwritten: {output}")
    if not output.parent.is_dir():
        raise StudyStateError(f"The export directory does not exist: {output.parent}")

    subjects = {subject.id: subject for subject in study.subjects}
    rows = [
        result
        for result in study.results
        if result.active
        and result.state is ResultState.APPROVED
        and result.subject_id in subjects
    ]
    rows.sort(key=lambda result: subjects[result.subject_id].subject_code.casefold())
    if not rows:
        raise StudyStateError("This study has no active approved T2 lesion results to export.")

    fieldnames = ["subject_id"]
    if not study.is_blinded:
        fieldnames.append("group")
    fieldnames.extend(
        (
            "result_type",
            "result_version",
            "result_state",
            "lesion_voxel_count",
            "lesion_volume_mm3",
            "unit",
            "method_version",
            "approved_mask_artifact_id",
            "approved_mask_sha256",
            "source_scan_input_id",
            "model_release_id",
            "reviewer",
            "approved_at",
            "warnings",
        )
    )
    created = False
    try:
        with output.open("x", encoding="utf-8", newline="") as handle:
            created = True
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            for result in rows:
                subject = subjects[result.subject_id]
                row = {
                    "subject_id": subject.subject_code,
                    "result_type": "T2 lesion volume",
                    "result_version": result.version,
                    "result_state": result.state.value,
                    "lesion_voxel_count": result.lesion_voxel_count,
                    "lesion_volume_mm3": f"{result.lesion_volume_mm3:.9g}",
                    "unit": result.unit,
                    "method_version": result.method_version,
                    "approved_mask_artifact_id": result.source_artifact_id,
                    "approved_mask_sha256": result.mask_sha256,
                    "source_scan_input_id": result.source_scan_input_id,
                    "model_release_id": result.model_release_id,
                    "reviewer": result.reviewer,
                    "approved_at": result.approved_at,
                    "warnings": "; ".join(
                        str(warning)
                        for warning in result.metadata.get("warnings", [])
                    ),
                }
                if not study.is_blinded:
                    row["group"] = subject.group_name or ""
                writer.writerow(row)
    except (OSError, TypeError, csv.Error) as exc:
        if created:
            output.unlink(missing_ok=True)
        raise StudyStateError(f"Could not write the approved T2 results CSV: {exc}") from exc
    return ApprovedT2Export(output, len(rows), study.is_blinded)
