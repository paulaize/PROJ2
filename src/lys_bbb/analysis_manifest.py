"""Build the analysis manifest that gates cohort quantification."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path
from typing import Any

from lys_bbb.mask_workflow import as_bool, as_float, as_int, read_csv_rows, write_csv


ANALYSIS_MANIFEST_FIELDS = [
    "case_id",
    "animal_id",
    "timepoint",
    "include",
    "qc_gate",
    "pre_path",
    "post_path",
    "brain_mask_path",
    "lesion_mask_path",
    "ipsilateral_side",
    "group",
    "brain_mask_source",
    "brain_mask_status",
    "brain_mask_qc_png",
    "manual_status",
    "registration_status",
    "manual_mask_qc_png",
    "registration_qc_png",
    "registration_after_xcorr",
    "manual_mbe_dice",
    "qc_notes",
    "review_status",
    "review_notes",
    "outputs_are",
    "analysis_mode",
]


PRESERVED_FIELDS = {
    "include",
    "lesion_mask_path",
    "lesion_mask",
    "ipsilateral_side",
    "lesion_side",
    "stroke_side",
    "group",
    "review_status",
    "review_notes",
}


def row_by_case(rows: list[dict[str, str]]) -> dict[str, dict[str, str]]:
    return {row["case_id"]: row for row in rows if row.get("case_id")}


def selected_brain_mask_path(row: dict[str, Any]) -> str:
    return str(row.get("brain_mask_path") or row.get("manual_mask_path") or "")


def selected_brain_mask_grid_ok(row: dict[str, Any]) -> Any:
    return row.get("brain_mask_grid_ok") if "brain_mask_grid_ok" in row else row.get("manual_mask_grid_ok")


def selected_brain_mask_components(row: dict[str, Any]) -> Any:
    return row.get("brain_mask_components") if "brain_mask_components" in row else row.get("manual_mask_components")


def selected_brain_mask_status(row: dict[str, Any]) -> str:
    return str(row.get("brain_mask_status") or "")


def selected_brain_mask_qc_png(row: dict[str, Any]) -> str:
    return str(row.get("brain_mask_qc_png") or row.get("manual_mask_qc_png") or "")


def selected_brain_mask_source(row: dict[str, Any]) -> str:
    if row.get("brain_mask_source"):
        return str(row["brain_mask_source"])
    if row.get("manual_mask_path"):
        return "manual"
    return ""


def is_testing_source(row: dict[str, Any]) -> bool:
    source = selected_brain_mask_source(row).lower()
    return "test" in source or source in {"debug", "development"}


def manual_mask_done(row: dict[str, Any]) -> bool:
    if "brain_mask_status" in row and row.get("brain_mask_source") and row.get("brain_mask_source") != "manual":
        return True
    return as_bool(row.get("manual_mask_done_name"))


def brain_mask_gate(row: dict[str, Any]) -> tuple[str, str, str]:
    if not as_bool(row.get("pre_exists")) or not as_bool(row.get("post_exists")):
        return "missing_conversion", "missing_conversion", "missing pre/post converted image"
    if not selected_brain_mask_path(row):
        return "missing_brain_mask", "needs_manual_mask", "missing corrected brain mask"
    if not as_bool(selected_brain_mask_grid_ok(row)):
        return "mask_grid_error", "needs_correction", "manual mask grid does not match pre image"
    if is_testing_source(row):
        return "testing_mask_source", "needs_review", "brain mask source is marked as testing/non-final"

    generic_status = selected_brain_mask_status(row)
    if generic_status and generic_status != "ready_candidate":
        return generic_status, generic_status, str(row.get("brain_mask_notes") or row.get("qc_notes") or "")

    notes: list[str] = []
    status = "ready_candidate"
    if not manual_mask_done(row):
        notes.append("manual mask is not marked done")
        status = "needs_review"
    dice = as_float(row.get("manual_mbe_dice"))
    if dice is not None and dice >= 0.999:
        notes.append("manual mask appears unchanged from MouseBrainExtractor")
        status = "needs_review"
    components = as_int(selected_brain_mask_components(row))
    if components is not None and components > 1:
        notes.append("manual mask has multiple connected components")
        status = "needs_review"
    if status != "ready_candidate":
        return "mask_needs_review", status, "; ".join(notes)
    return "mask_ready", status, ""


def manual_gate(row: dict[str, Any]) -> tuple[str, str, str]:
    """Backward-compatible name for older tests and callers."""
    return brain_mask_gate(row)


def registration_gate(row: dict[str, Any]) -> tuple[str, str]:
    if not row.get("registration_qc_png"):
        return "missing_registration_qc", "missing registration QC"
    if row.get("registration_source_match") not in {True, "True", "true", "1", 1}:
        return "registration_source_mismatch", "registration QC source paths differ from audited pre/post paths"
    return "registration_ready", ""


def gate_qc_row(
    row: dict[str, Any],
    *,
    allow_review_masks_for_testing: bool = False,
) -> tuple[bool, str, str, str, str]:
    manual_status, manual_review, manual_notes = brain_mask_gate(row)
    registration_status, registration_notes = registration_gate(row)
    notes = unique_notes(manual_notes, registration_notes, row.get("qc_notes", ""))
    if manual_status == "missing_conversion":
        return False, "missing_conversion", manual_review, notes, "standard"
    testing_statuses = {"needs_review", "mask_needs_review", "testing_mask_source"}
    if manual_status in testing_statuses and allow_review_masks_for_testing:
        if registration_status == "registration_ready":
            return True, "testing_review_mask", manual_review, notes, "testing_nonfinal_masks"
        return False, registration_status, manual_review, notes, "testing_nonfinal_masks"
    if manual_status != "mask_ready":
        return False, manual_status, manual_review, notes, "standard"
    if registration_status != "registration_ready":
        return False, registration_status, manual_review, notes, "standard"
    return True, "ready_for_provisional_quantification", manual_review, notes, "standard"


def unique_notes(*values: Any) -> str:
    notes: list[str] = []
    seen: set[str] = set()
    for value in values:
        for part in str(value or "").split(";"):
            note = part.strip()
            if note and note not in seen:
                seen.add(note)
                notes.append(note)
    return "; ".join(notes)


def merge_preserved_values(row: dict[str, Any], previous: dict[str, str] | None) -> dict[str, Any]:
    if not previous:
        return row
    for field in PRESERVED_FIELDS:
        if previous.get(field):
            if field in {"lesion_mask", "lesion_side", "stroke_side"}:
                continue
            row[field] = previous[field]
    if not row.get("lesion_mask_path"):
        row["lesion_mask_path"] = previous.get("lesion_mask_path") or previous.get("lesion_mask") or ""
    if not row.get("ipsilateral_side"):
        row["ipsilateral_side"] = (
            previous.get("ipsilateral_side")
            or previous.get("lesion_side")
            or previous.get("stroke_side")
            or ""
        )
    return row


def apply_review_gate(row: dict[str, Any]) -> dict[str, Any]:
    review = str(row.get("review_status", "")).strip().lower()
    allowed_gates = {"ready_for_provisional_quantification", "testing_review_mask"}
    if row["qc_gate"] not in allowed_gates:
        row["include"] = "no"
    elif review in {"fail", "failed", "exclude", "excluded", "no"}:
        row["include"] = "no"
        row["qc_gate"] = "excluded_by_review"
    elif review in {"pass", "passed", "include", "included", "yes"}:
        row["include"] = "yes"
    return row


def build_analysis_manifest_rows(
    qc_rows: list[dict[str, Any]],
    *,
    previous_rows: list[dict[str, str]] | None = None,
    auto_include_ready: bool = True,
    allow_review_masks_for_testing: bool = False,
) -> list[dict[str, Any]]:
    previous_by_case = row_by_case(previous_rows or [])
    rows: list[dict[str, Any]] = []
    for qc_row in qc_rows:
        case_id = qc_row.get("case_id", "")
        is_ready, qc_gate, manual_status, notes, analysis_mode = gate_qc_row(
            qc_row,
            allow_review_masks_for_testing=allow_review_masks_for_testing,
        )
        registration_status, _registration_notes = registration_gate(qc_row)
        row: dict[str, Any] = {
            "case_id": case_id,
            "animal_id": qc_row.get("animal_id", ""),
            "timepoint": qc_row.get("timepoint", ""),
            "include": "yes" if is_ready and auto_include_ready else "no",
            "qc_gate": qc_gate,
            "pre_path": qc_row.get("pre_path", ""),
            "post_path": qc_row.get("post_path", ""),
            "brain_mask_path": selected_brain_mask_path(qc_row) if is_ready else "",
            "lesion_mask_path": "",
            "ipsilateral_side": "",
            "group": "",
            "brain_mask_source": selected_brain_mask_source(qc_row),
            "brain_mask_status": selected_brain_mask_status(qc_row) or manual_status,
            "brain_mask_qc_png": selected_brain_mask_qc_png(qc_row),
            "manual_status": manual_status,
            "registration_status": registration_status,
            "manual_mask_qc_png": qc_row.get("manual_mask_qc_png", ""),
            "registration_qc_png": qc_row.get("registration_qc_png", ""),
            "registration_after_xcorr": qc_row.get("registration_after_xcorr", ""),
            "manual_mbe_dice": qc_row.get("manual_mbe_dice", ""),
            "qc_notes": notes,
            "review_status": "",
            "review_notes": "",
            "outputs_are": (
                "semi-quantitative T1-weighted gadolinium enhancement, "
                "not T1, Ktrans, Ki, ve, vp, or absolute permeability"
            ),
            "analysis_mode": analysis_mode,
        }
        row = merge_preserved_values(row, previous_by_case.get(case_id))
        row = apply_review_gate(row)
        rows.append(row)
    return sorted(rows, key=lambda item: (item["animal_id"], item["timepoint"], item["case_id"]))


def write_summary(path: Path, rows: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        gate = str(row.get("qc_gate", ""))
        counts[gate] = counts.get(gate, 0) + 1
    counts["included"] = sum(1 for row in rows if str(row.get("include", "")).lower() in {"yes", "true", "1"})
    counts["total"] = len(rows)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["metric", "count"])
        writer.writeheader()
        for key, value in sorted(counts.items()):
            writer.writerow({"metric": key, "count": value})
    return counts


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build a cohort analysis manifest from the QC manifest.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--qc-manifest", type=Path, default=Path("reports/qc/qc_manifest.csv"))
    parser.add_argument("-o", "--output", type=Path, default=Path("derivatives/manifests/analysis_manifest.csv"))
    parser.add_argument(
        "--previous-manifest",
        type=Path,
        default=None,
        help="optional manifest whose editable group/side/lesion/review fields should be preserved",
    )
    parser.add_argument(
        "--no-auto-include-ready",
        action="store_true",
        help="write include=no even for cases that pass automated mask and registration gates",
    )
    parser.add_argument(
        "--allow-review-masks-for-testing",
        action="store_true",
        help="include review-level grid-valid masks for non-final test quantification",
    )
    parser.add_argument("--summary", type=Path, default=Path("reports/qc/analysis_manifest_summary.csv"))
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    qc_rows = read_csv_rows(args.qc_manifest)
    previous_path = args.previous_manifest or (args.output if args.output.exists() else None)
    previous_rows = read_csv_rows(previous_path) if previous_path else []
    rows = build_analysis_manifest_rows(
        qc_rows,
        previous_rows=previous_rows,
        auto_include_ready=not args.no_auto_include_ready,
        allow_review_masks_for_testing=args.allow_review_masks_for_testing,
    )
    write_csv(args.output, rows, ANALYSIS_MANIFEST_FIELDS)
    counts = write_summary(args.summary, rows)
    print(f"manifest rows: {len(rows)}")
    print(f"included: {counts['included']}")
    print(f"manifest: {args.output}")
    print(f"summary: {args.summary}")
    for gate, count in sorted((key, value) for key, value in counts.items() if key not in {'included', 'total'}):
        print(f"{gate}: {count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
