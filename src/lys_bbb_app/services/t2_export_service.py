"""Approved-only T2 result export without Qt dependencies."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import nibabel as nib
import numpy as np
import xlsxwriter
from xlsxwriter.exceptions import XlsxWriterException

from lys_bbb.t2_review import validate_and_measure_t2_mask

from lys_bbb_app.domain.errors import StudyStateError
from lys_bbb_app.domain.study import StudySnapshot
from lys_bbb_app.domain.t2_lesion import ResultState


@dataclass(frozen=True)
class ApprovedT2Export:
    path: Path
    row_count: int
    blinded: bool


@dataclass(frozen=True)
class ApprovedT2ExcelExport(ApprovedT2Export):
    detailed: bool
    slice_row_count: int


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

    subjects, rows = _approved_results(study)

    fieldnames = _summary_fieldnames(study)
    created = False
    try:
        with output.open("x", encoding="utf-8", newline="") as handle:
            created = True
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            for result in rows:
                subject = subjects[result.subject_id]
                row = _summary_row(subject, result)
                row["lesion_volume_mm3"] = f"{result.lesion_volume_mm3:.9g}"
                if not study.is_blinded:
                    row["group"] = subject.group_name or ""
                writer.writerow(row)
    except (OSError, TypeError, csv.Error) as exc:
        if created:
            output.unlink(missing_ok=True)
        raise StudyStateError(f"Could not write the approved T2 results CSV: {exc}") from exc
    return ApprovedT2Export(output, len(rows), study.is_blinded)


def export_approved_t2_results_excel(
    study: StudySnapshot,
    destination: Path | str,
    *,
    detailed: bool = False,
) -> ApprovedT2ExcelExport:
    """Write approved result summaries and optional native-mask per-slice details."""

    output = Path(destination).expanduser().resolve()
    if output.exists():
        raise StudyStateError(
            f"The export already exists and will not be overwritten: {output}"
        )
    if not output.parent.is_dir():
        raise StudyStateError(f"The export directory does not exist: {output.parent}")

    subjects, results = _approved_results(study)
    slice_rows: list[dict[str, Any]] = []
    if detailed:
        try:
            for result in results:
                slice_rows.extend(
                    _per_slice_rows(study, subjects[result.subject_id], result)
                )
        except (FileNotFoundError, OSError, TypeError, ValueError) as exc:
            raise StudyStateError(
                f"Could not prepare the approved T2 per-slice measurements: {exc}"
            ) from exc

    workbook: xlsxwriter.Workbook | None = None
    try:
        workbook = xlsxwriter.Workbook(output)
        formats = _workbook_formats(workbook)
        _write_summary_sheet(
            workbook,
            formats,
            study,
            subjects,
            results,
            slice_rows,
            detailed=detailed,
        )
        if detailed:
            _write_slice_sheet(workbook, formats, study, slice_rows)
            _write_data_dictionary_sheet(workbook, formats)
        workbook.close()
        workbook = None
    except (FileNotFoundError, OSError, TypeError, ValueError, XlsxWriterException) as exc:
        if workbook is not None:
            try:
                workbook.close()
            except Exception:  # pragma: no cover - best-effort cleanup after writer failure
                pass
        output.unlink(missing_ok=True)
        raise StudyStateError(f"Could not write the approved T2 Excel export: {exc}") from exc
    return ApprovedT2ExcelExport(
        output,
        len(results),
        study.is_blinded,
        detailed,
        len(slice_rows),
    )


def _approved_results(study: StudySnapshot):
    subjects = {subject.id: subject for subject in study.subjects}
    results = [
        result
        for result in study.results
        if result.active
        and result.state is ResultState.APPROVED
        and result.subject_id in subjects
    ]
    results.sort(key=lambda result: subjects[result.subject_id].subject_code.casefold())
    if not results:
        raise StudyStateError(
            "This study has no active approved T2 lesion results to export."
        )
    return subjects, results


def _summary_fieldnames(study: StudySnapshot) -> list[str]:
    fieldnames = ["subject_id", "animal_identifier", "time_identifier"]
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
    return fieldnames


def _summary_row(subject, result) -> dict[str, Any]:
    return {
        "subject_id": subject.subject_code,
        "animal_identifier": subject.animal_identifier or "",
        "time_identifier": subject.time_identifier or "",
        "result_type": "T2 lesion volume",
        "result_version": result.version,
        "result_state": result.state.value,
        "lesion_voxel_count": result.lesion_voxel_count,
        "lesion_volume_mm3": result.lesion_volume_mm3,
        "unit": result.unit,
        "method_version": result.method_version,
        "approved_mask_artifact_id": result.source_artifact_id,
        "approved_mask_sha256": result.mask_sha256,
        "source_scan_input_id": result.source_scan_input_id,
        "model_release_id": result.model_release_id,
        "reviewer": result.reviewer,
        "approved_at": result.approved_at,
        "warnings": "; ".join(
            str(warning) for warning in result.metadata.get("warnings", [])
        ),
    }


def _per_slice_rows(study: StudySnapshot, subject, result) -> list[dict[str, Any]]:
    artifact = next(
        (item for item in study.artifacts if item.id == result.source_artifact_id),
        None,
    )
    source = next(
        (item for item in study.scan_inputs if item.id == result.source_scan_input_id),
        None,
    )
    if artifact is None or source is None or source.output_path is None:
        raise ValueError(
            f"Approved model resources are incomplete for subject {subject.subject_code}."
        )
    measurement = validate_and_measure_t2_mask(
        artifact.mask_path,
        source.output_path,
        expected_mask_sha256=result.mask_sha256,
    )
    if measurement.lesion_voxel_count != result.lesion_voxel_count:
        raise ValueError(
            f"Approved lesion voxel count no longer reconciles for {subject.subject_code}."
        )

    image = nib.load(str(artifact.mask_path))
    mask = np.asarray(image.dataobj) == 1
    affine = np.asarray(image.affine, dtype=np.float64)
    voxel_volume_mm3 = float(abs(np.linalg.det(affine[:3, :3])))
    in_plane_area_mm2 = float(
        np.linalg.norm(np.cross(affine[:3, 0], affine[:3, 1]))
    )
    normal = np.cross(affine[:3, 0], affine[:3, 1])
    normal /= np.linalg.norm(normal)
    axis_codes = tuple(str(code) for code in nib.aff2axcodes(affine))
    center_i = (mask.shape[0] - 1) / 2
    center_j = (mask.shape[1] - 1) / 2
    rows: list[dict[str, Any]] = []
    for index in range(mask.shape[2]):
        lesion_voxels = int(np.count_nonzero(mask[:, :, index]))
        center_world = affine @ np.array([center_i, center_j, index, 1.0])
        row = {
            "subject_id": subject.subject_code,
            "animal_identifier": subject.animal_identifier or "",
            "time_identifier": subject.time_identifier or "",
            "slice_number": index + 1,
            "storage_index": index,
            "slice_axis": 2,
            "slice_axis_code": axis_codes[2],
            "slice_position_mm": float(np.dot(center_world[:3], normal)),
            "slice_center_x_mm": float(center_world[0]),
            "slice_center_y_mm": float(center_world[1]),
            "slice_center_z_mm": float(center_world[2]),
            "lesion_voxel_count": lesion_voxels,
            "lesion_area_mm2": lesion_voxels * in_plane_area_mm2,
            "lesion_volume_mm3": lesion_voxels * voxel_volume_mm3,
            "voxel_volume_mm3": voxel_volume_mm3,
            "approved_mask_artifact_id": result.source_artifact_id,
            "approved_mask_sha256": result.mask_sha256,
            "source_scan_input_id": result.source_scan_input_id,
        }
        if not study.is_blinded:
            row["group"] = subject.group_name or ""
        rows.append(row)
    total = sum(float(row["lesion_volume_mm3"]) for row in rows)
    if not np.isclose(total, result.lesion_volume_mm3, rtol=0, atol=1e-9):
        raise ValueError(
            f"Per-slice lesion volume does not reconcile for {subject.subject_code}."
        )
    return rows


def _workbook_formats(workbook: xlsxwriter.Workbook) -> dict[str, Any]:
    return {
        "title": workbook.add_format(
            {"bold": True, "font_size": 16, "font_color": "#FFFFFF", "bg_color": "#315B6D"}
        ),
        "subtitle": workbook.add_format(
            {"font_color": "#425B66", "bg_color": "#E9F1F4", "text_wrap": True}
        ),
        "header": workbook.add_format(
            {"bold": True, "font_color": "#FFFFFF", "bg_color": "#477B8E", "border": 1, "border_color": "#D5E1E5"}
        ),
        "text": workbook.add_format({"border": 1, "border_color": "#E3E9EC"}),
        "integer": workbook.add_format(
            {"num_format": "0", "border": 1, "border_color": "#E3E9EC"}
        ),
        "decimal": workbook.add_format(
            {"num_format": "0.000000", "border": 1, "border_color": "#E3E9EC"}
        ),
    }


def _write_summary_sheet(
    workbook,
    formats,
    study,
    subjects,
    results,
    slice_rows,
    *,
    detailed: bool,
) -> None:
    worksheet = workbook.add_worksheet("Summary")
    worksheet.hide_gridlines(2)
    worksheet.freeze_panes(3, 0)
    fieldnames = _summary_fieldnames(study)
    if detailed:
        fieldnames.extend(("per_slice_volume_sum_mm3", "volume_difference_mm3"))
    worksheet.merge_range(0, 0, 0, 5, "Approved T2 lesion results", formats["title"])
    worksheet.set_row(0, 24, formats["title"])
    subtitle = (
        "Approved results only. Detailed per-slice measurements are calculated from "
        "the immutable approved native-space binary lesion mask."
        if detailed
        else "Approved results only. Draft masks and provisional values are excluded."
    )
    worksheet.merge_range(1, 0, 1, 8, subtitle, formats["subtitle"])
    for column, name in enumerate(fieldnames):
        worksheet.write(2, column, name, formats["header"])
    slice_totals: dict[str, float] = {}
    for row in slice_rows:
        slice_totals[row["subject_id"]] = slice_totals.get(row["subject_id"], 0.0) + float(
            row["lesion_volume_mm3"]
        )
    for row_index, result in enumerate(results, start=3):
        subject = subjects[result.subject_id]
        row = _summary_row(subject, result)
        if not study.is_blinded:
            row["group"] = subject.group_name or ""
        if detailed:
            row["per_slice_volume_sum_mm3"] = slice_totals[subject.subject_code]
            row["volume_difference_mm3"] = (
                slice_totals[subject.subject_code] - result.lesion_volume_mm3
            )
        _write_data_row(worksheet, row_index, fieldnames, row, formats)
    worksheet.autofilter(2, 0, 2 + len(results), len(fieldnames) - 1)
    _set_column_widths(worksheet, fieldnames)


def _write_slice_sheet(workbook, formats, study, rows) -> None:
    worksheet = workbook.add_worksheet("Per-slice lesions")
    worksheet.hide_gridlines(2)
    worksheet.freeze_panes(3, 0)
    worksheet.merge_range(
        0,
        0,
        0,
        5,
        "Per-slice approved lesion measurements",
        formats["title"],
    )
    worksheet.set_row(0, 24, formats["title"])
    worksheet.merge_range(
        1,
        0,
        1,
        8,
        "One row per native T2 storage slice, including zero-lesion slices. Slice "
        "volume totals reconcile with the Summary sheet.",
        formats["subtitle"],
    )
    fieldnames = ["subject_id", "animal_identifier", "time_identifier"]
    if not study.is_blinded:
        fieldnames.append("group")
    fieldnames.extend(
        (
            "slice_number",
            "storage_index",
            "slice_axis",
            "slice_axis_code",
            "slice_position_mm",
            "slice_center_x_mm",
            "slice_center_y_mm",
            "slice_center_z_mm",
            "lesion_voxel_count",
            "lesion_area_mm2",
            "lesion_volume_mm3",
            "voxel_volume_mm3",
            "approved_mask_artifact_id",
            "approved_mask_sha256",
            "source_scan_input_id",
        )
    )
    for column, name in enumerate(fieldnames):
        worksheet.write(2, column, name, formats["header"])
    for row_index, row in enumerate(rows, start=3):
        _write_data_row(worksheet, row_index, fieldnames, row, formats)
    worksheet.autofilter(2, 0, 2 + len(rows), len(fieldnames) - 1)
    _set_column_widths(worksheet, fieldnames)


def _write_data_dictionary_sheet(workbook, formats) -> None:
    worksheet = workbook.add_worksheet("Data dictionary")
    worksheet.hide_gridlines(2)
    worksheet.freeze_panes(2, 0)
    worksheet.merge_range(
        0,
        0,
        0,
        2,
        "Detailed export data dictionary",
        formats["title"],
    )
    worksheet.set_row(0, 24, formats["title"])
    headers = ("field", "definition", "unit")
    for column, header in enumerate(headers):
        worksheet.write(1, column, header, formats["header"])
    definitions = (
        ("slice_number", "Human-readable one-based native T2 storage slice number.", ""),
        ("storage_index", "Zero-based NIfTI storage index along axis 2.", ""),
        ("slice_axis_code", "Positive anatomical direction of NIfTI storage axis 2.", ""),
        (
            "slice_position_mm",
            "Signed physical position of the slice center projected onto its normal.",
            "mm",
        ),
        ("slice_center_x_mm", "World-space X coordinate of the slice center.", "mm"),
        ("slice_center_y_mm", "World-space Y coordinate of the slice center.", "mm"),
        ("slice_center_z_mm", "World-space Z coordinate of the slice center.", "mm"),
        ("lesion_voxel_count", "Approved lesion-mask foreground voxels in this slice.", "voxels"),
        ("lesion_area_mm2", "Foreground voxels multiplied by native in-plane voxel area.", "mm²"),
        ("lesion_volume_mm3", "Foreground voxels multiplied by native voxel volume.", "mm³"),
        ("voxel_volume_mm3", "Absolute determinant of the native mask affine.", "mm³"),
    )
    for row_index, values in enumerate(definitions, start=2):
        for column, value in enumerate(values):
            worksheet.write(row_index, column, value, formats["text"])
    worksheet.set_column(0, 0, 25)
    worksheet.set_column(1, 1, 72)
    worksheet.set_column(2, 2, 12)


def _write_data_row(worksheet, row_index, fieldnames, row, formats) -> None:
    integer_fields = {
        "result_version",
        "lesion_voxel_count",
        "slice_number",
        "storage_index",
        "slice_axis",
    }
    decimal_fields = {
        name for name in fieldnames if name.endswith(("_mm", "_mm2", "_mm3"))
    }
    for column, name in enumerate(fieldnames):
        value = row.get(name, "")
        cell_format = (
            formats["integer"]
            if name in integer_fields
            else formats["decimal"]
            if name in decimal_fields
            else formats["text"]
        )
        worksheet.write(row_index, column, value, cell_format)


def _set_column_widths(worksheet, fieldnames) -> None:
    for column, name in enumerate(fieldnames):
        width = min(38, max(11, len(name) + 2))
        if name.endswith(("_sha256", "_artifact_id", "_input_id")):
            width = 24
        worksheet.set_column(column, column, width)
