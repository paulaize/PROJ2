"""Build and validate study metadata used for side-aware quantification."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any

from lys_bbb.flash_cohort import parse_case_id, timepoint_sort_key
from lys_bbb.mask_workflow import read_csv_rows, write_csv


STUDY_METADATA_FIELDS = [
    "case_id",
    "animal_id",
    "timepoint",
    "include",
    "group",
    "ipsilateral_side",
    "lesion_mask_path",
    "review_status",
    "review_notes",
    "notes",
]


VALID_INCLUDE = {"", "yes", "no"}
VALID_SIDES = {"", "left", "right", "low-x", "high-x"}
VALID_REVIEW_STATUS = {"", "pass", "fail", "include", "exclude", "review"}


def normalize_include(value: Any) -> str:
    text = str(value or "").strip().lower()
    if text in {"1", "true", "t", "yes", "y", "include", "included"}:
        return "yes"
    if text in {"0", "false", "f", "no", "n", "exclude", "excluded"}:
        return "no"
    return text


def normalize_side(value: Any) -> str:
    return str(value or "").strip().lower().replace("_", "-")


def normalize_review_status(value: Any) -> str:
    text = str(value or "").strip().lower()
    if text in {"passed", "included"}:
        return "pass"
    if text in {"failed", "excluded"}:
        return "fail"
    return text


def case_sort_key(case_id: str) -> tuple[str, tuple[int, str], str]:
    parts = parse_case_id(case_id)
    if parts is None:
        return case_id, (10_000, ""), case_id
    return parts.animal_id, timepoint_sort_key(parts.timepoint), parts.case_id


def rows_by_case(rows: list[dict[str, str]]) -> dict[str, dict[str, str]]:
    return {row["case_id"]: row for row in rows if row.get("case_id")}


def derive_animal_defaults(previous_rows: list[dict[str, str]]) -> dict[str, dict[str, str]]:
    defaults: dict[str, dict[str, str]] = {}
    for row in previous_rows:
        animal_id = row.get("animal_id", "")
        if not animal_id:
            continue
        animal_defaults = defaults.setdefault(animal_id, {})
        if row.get("group") and not animal_defaults.get("group"):
            animal_defaults["group"] = row["group"]
        side = normalize_side(row.get("ipsilateral_side") or row.get("lesion_side") or row.get("stroke_side"))
        if side and not animal_defaults.get("ipsilateral_side"):
            animal_defaults["ipsilateral_side"] = side
    return defaults


def source_rows_from_analysis_manifest(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    source: list[dict[str, str]] = []
    for row in rows:
        case_id = row.get("case_id", "")
        if not case_id:
            continue
        parts = parse_case_id(case_id)
        source.append({
            "case_id": case_id,
            "animal_id": row.get("animal_id") or (parts.animal_id if parts else ""),
            "timepoint": row.get("timepoint") or (parts.timepoint if parts else ""),
        })
    return sorted(source, key=lambda row: case_sort_key(row["case_id"]))


def source_rows_from_input_root(input_root: Path) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for session_dir in sorted(path for path in input_root.iterdir() if path.is_dir()):
        parts = parse_case_id(session_dir.name)
        if parts is None:
            continue
        if not (session_dir / "pre_coronal.nii.gz").exists() or not (session_dir / "post_coronal.nii.gz").exists():
            continue
        rows.append({
            "case_id": parts.case_id,
            "animal_id": parts.animal_id,
            "timepoint": parts.timepoint,
        })
    return sorted(rows, key=lambda row: case_sort_key(row["case_id"]))


def build_study_metadata_rows(
    source_rows: list[dict[str, str]],
    *,
    previous_rows: list[dict[str, str]] | None = None,
    propagate_animal_fields: bool = True,
) -> list[dict[str, str]]:
    previous_rows = previous_rows or []
    previous_by_case = rows_by_case(previous_rows)
    animal_defaults = derive_animal_defaults(previous_rows) if propagate_animal_fields else {}
    rows: list[dict[str, str]] = []
    for source in source_rows:
        case_id = source["case_id"]
        animal_id = source.get("animal_id", "")
        prev = previous_by_case.get(case_id, {})
        defaults = animal_defaults.get(animal_id, {})
        row = {
            "case_id": case_id,
            "animal_id": animal_id,
            "timepoint": source.get("timepoint", ""),
            "include": normalize_include(prev.get("include", "")),
            "group": prev.get("group") or defaults.get("group", ""),
            "ipsilateral_side": normalize_side(prev.get("ipsilateral_side") or prev.get("stroke_side") or defaults.get("ipsilateral_side", "")),
            "lesion_mask_path": prev.get("lesion_mask_path") or prev.get("lesion_mask") or "",
            "review_status": normalize_review_status(prev.get("review_status", "")),
            "review_notes": prev.get("review_notes", ""),
            "notes": prev.get("notes", ""),
        }
        rows.append(row)
    return rows


def duplicate_case_ids(rows: list[dict[str, str]]) -> list[str]:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for row in rows:
        case_id = row.get("case_id", "")
        if not case_id:
            continue
        if case_id in seen:
            duplicates.add(case_id)
        seen.add(case_id)
    return sorted(duplicates)


def duplicate_timepoints(rows: list[dict[str, str]]) -> list[str]:
    seen: set[tuple[str, str]] = set()
    duplicates: set[str] = set()
    for row in rows:
        key = (row.get("animal_id", ""), row.get("timepoint", ""))
        if not all(key):
            continue
        if key in seen:
            duplicates.add(f"{key[0]}_{key[1]}")
        seen.add(key)
    return sorted(duplicates)


def validate_study_metadata_rows(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []
    for case_id in duplicate_case_ids(rows):
        issues.append({"severity": "error", "case_id": case_id, "field": "case_id", "message": "duplicate case_id"})
    for animal_timepoint in duplicate_timepoints(rows):
        issues.append({
            "severity": "warning",
            "case_id": animal_timepoint,
            "field": "timepoint",
            "message": "duplicate animal/timepoint; D7-D1 deltas require unique D1 and D7 rows",
        })
    for row in rows:
        case_id = row.get("case_id", "")
        include = normalize_include(row.get("include", ""))
        side = normalize_side(row.get("ipsilateral_side", ""))
        review_status = normalize_review_status(row.get("review_status", ""))
        if include not in VALID_INCLUDE:
            issues.append({"severity": "error", "case_id": case_id, "field": "include", "message": f"invalid include value: {row.get('include', '')}"})
        if side not in VALID_SIDES:
            issues.append({"severity": "error", "case_id": case_id, "field": "ipsilateral_side", "message": f"invalid side: {row.get('ipsilateral_side', '')}"})
        if review_status not in VALID_REVIEW_STATUS:
            issues.append({"severity": "error", "case_id": case_id, "field": "review_status", "message": f"invalid review_status: {row.get('review_status', '')}"})
    return issues


def write_issues(path: Path, issues: list[dict[str, str]]) -> dict[str, int]:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = ["severity", "case_id", "field", "message"]
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(issues)
    summary = {
        "n_issues": len(issues),
        "n_errors": sum(1 for issue in issues if issue["severity"] == "error"),
        "n_warnings": sum(1 for issue in issues if issue["severity"] == "warning"),
    }
    return summary


def write_summary(path: Path, rows: list[dict[str, str]], issues: list[dict[str, str]]) -> dict[str, Any]:
    summary = {
        "n_rows": len(rows),
        "n_with_group": sum(1 for row in rows if row.get("group")),
        "n_with_ipsilateral_side": sum(1 for row in rows if row.get("ipsilateral_side")),
        "n_with_lesion_mask": sum(1 for row in rows if row.get("lesion_mask_path")),
        "n_explicit_include": sum(1 for row in rows if row.get("include")),
        "n_issues": len(issues),
        "n_errors": sum(1 for issue in issues if issue["severity"] == "error"),
        "n_warnings": sum(1 for issue in issues if issue["severity"] == "warning"),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(summary, indent=2) + "\n")
    return summary


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build or refresh the study metadata CSV for group, side, lesion, and review fields.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--input-root", type=Path, default=Path("output/all_mice"))
    parser.add_argument("--analysis-manifest", type=Path, default=None)
    parser.add_argument("-o", "--output", type=Path, default=Path("derivatives/manifests/study_metadata.csv"))
    parser.add_argument("--previous", type=Path, default=None)
    parser.add_argument("--issues", type=Path, default=Path("reports/qc/study_metadata_issues.csv"))
    parser.add_argument("--summary", type=Path, default=Path("reports/qc/study_metadata_summary.json"))
    parser.add_argument("--no-propagate-animal-fields", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.analysis_manifest is not None:
        source_rows = source_rows_from_analysis_manifest(read_csv_rows(args.analysis_manifest))
    else:
        source_rows = source_rows_from_input_root(args.input_root)
    previous_path = args.previous or (args.output if args.output.exists() else None)
    previous_rows = read_csv_rows(previous_path) if previous_path else []
    rows = build_study_metadata_rows(
        source_rows,
        previous_rows=previous_rows,
        propagate_animal_fields=not args.no_propagate_animal_fields,
    )
    issues = validate_study_metadata_rows(rows)
    write_csv(args.output, rows, STUDY_METADATA_FIELDS)
    issue_summary = write_issues(args.issues, issues)
    summary = write_summary(args.summary, rows, issues)
    print(f"rows: {summary['n_rows']}")
    print(f"with ipsilateral side: {summary['n_with_ipsilateral_side']}")
    print(f"issues: {issue_summary['n_issues']} ({issue_summary['n_errors']} errors, {issue_summary['n_warnings']} warnings)")
    print(f"metadata: {args.output}")
    print(f"issues csv: {args.issues}")
    print(f"summary: {args.summary}")
    return 1 if issue_summary["n_errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
