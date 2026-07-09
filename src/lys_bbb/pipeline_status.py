"""Summarize current V1 pipeline readiness from generated manifests."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any

from lys_bbb.mask_workflow import as_float, read_csv_rows


def count_by(rows: list[dict[str, Any]], field: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        key = str(row.get(field, "") or "blank")
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text())


def read_csv_if_exists(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    return read_csv_rows(path)


def summarize_registration(rows: list[dict[str, str]], *, worst_n: int = 5) -> dict[str, Any]:
    scored: list[tuple[float, str]] = []
    improved = 0
    for row in rows:
        after = as_float(row.get("after_xcorr"))
        before = as_float(row.get("before_xcorr"))
        if after is not None:
            scored.append((after, row.get("case_id", "")))
        if after is not None and before is not None and after > before:
            improved += 1
    scored.sort()
    values = [value for value, _case_id in scored]
    summary: dict[str, Any] = {
        "n_registration_qc": len(rows),
        "n_improved": improved,
        "worst_cases": [{"case_id": case_id, "after_xcorr": value} for value, case_id in scored[:worst_n]],
    }
    if values:
        mid = len(values) // 2
        summary.update({
            "min_after_xcorr": values[0],
            "median_after_xcorr": values[mid] if len(values) % 2 else (values[mid - 1] + values[mid]) / 2,
            "max_after_xcorr": values[-1],
        })
    return summary


def build_status(
    *,
    qc_summary: dict[str, Any],
    manual_worklist_rows: list[dict[str, str]],
    analysis_manifest_rows: list[dict[str, str]],
    nnunet_manifest_rows: list[dict[str, str]],
    registration_rows: list[dict[str, str]],
) -> dict[str, Any]:
    analysis_gate_counts = count_by(analysis_manifest_rows, "qc_gate")
    manual_status_counts = count_by(manual_worklist_rows, "manual_status")
    nnunet_split_counts = count_by(nnunet_manifest_rows, "split")
    included = sum(
        1
        for row in analysis_manifest_rows
        if str(row.get("include", "")).strip().lower() in {"yes", "true", "1"}
    )
    n_train = nnunet_split_counts.get("train", 0)
    blockers: list[str] = []
    if analysis_gate_counts.get("missing_conversion", 0):
        blockers.append("Resolve missing converted pre/post sessions.")
    if analysis_gate_counts.get("missing_brain_mask", 0):
        blockers.append("Create corrected T1 pre-space brain masks.")
    if analysis_gate_counts.get("mask_needs_review", 0):
        blockers.append("Review or fix existing manual masks before using them.")
    if included == 0:
        blockers.append("No sessions are currently included for final-style cohort quantification.")
    if n_train < 8:
        blockers.append("nnU-Net brain-mask training set is below the 8-12 corrected-mask starting target.")

    next_commands = [
        "conda run -n lys-bbb python scripts/qc/build_qc_manifest.py --input-root output/all_mice --registration-summary reports/qc/registration_all_mice/registration_qc_summary.csv",
        "conda run -n lys-bbb python scripts/masks/build_manual_mask_workflow.py",
        "conda run -n lys-bbb python scripts/qc/build_analysis_manifest.py",
        "conda run -n lys-bbb python scripts/qc/build_project_status.py",
    ]
    if included:
        next_commands.append(
            "conda run -n lys-bbb python scripts/quantification/quantify_flash_cohort.py output/all_mice --roi-manifest derivatives/manifests/analysis_manifest.csv -o derivatives/flash_v1_cohort"
        )
    else:
        next_commands.append(
            "conda run -n lys-bbb python scripts/quantification/quantify_flash_cohort.py output/all_mice --roi-manifest derivatives/manifests/analysis_manifest.csv -o derivatives/flash_v1_cohort --dry-run"
        )
    if n_train >= 8:
        next_commands.append(
            "conda run -n lys-bbb python scripts/masks/prepare_nnunet_brain_extraction.py --manifest derivatives/brain_seg/nnunet_manifest.csv --nnunet-raw derivatives/brain_seg/nnUNet_raw --dry-run"
        )

    return {
        "qc_summary": qc_summary,
        "manual_status_counts": manual_status_counts,
        "analysis_gate_counts": analysis_gate_counts,
        "analysis_included": included,
        "nnunet_split_counts": nnunet_split_counts,
        "registration": summarize_registration(registration_rows),
        "blockers": blockers,
        "next_commands": next_commands,
    }


def bullets(values: list[str]) -> str:
    if not values:
        return "- None\n"
    return "".join(f"- {value}\n" for value in values)


def counts_table(counts: dict[str, int]) -> str:
    if not counts:
        return "| Status | Count |\n| --- | ---: |\n| missing | 0 |\n"
    lines = ["| Status | Count |", "| --- | ---: |"]
    lines.extend(f"| {key} | {value} |" for key, value in counts.items())
    return "\n".join(lines) + "\n"


def format_float(value: Any) -> str:
    if isinstance(value, float):
        return f"{value:.4f}"
    return str(value)


def write_markdown(path: Path, status: dict[str, Any]) -> None:
    registration = status.get("registration", {})
    worst = registration.get("worst_cases", [])
    worst_lines = "\n".join(
        f"- {case['case_id']}: after_xcorr {format_float(case['after_xcorr'])}" for case in worst
    ) or "- None"
    next_commands = "\n\n".join(f"```bash\n{command}\n```" for command in status["next_commands"])
    text = f"""# V1 Pipeline Status

This report is generated from the current QC and manifest files. It is a
technical readiness summary, not a biological result.

## Current Gates

Included for manifest-gated quantification: **{status['analysis_included']}**

### Analysis Manifest

{counts_table(status['analysis_gate_counts'])}
### Manual Mask Worklist

{counts_table(status['manual_status_counts'])}
### nnU-Net Manifest

{counts_table(status['nnunet_split_counts'])}
## Registration QC

- QC rows: {registration.get('n_registration_qc', 0)}
- Improved after registration: {registration.get('n_improved', 0)}
- after_xcorr min/median/max: {format_float(registration.get('min_after_xcorr', ''))} / {format_float(registration.get('median_after_xcorr', ''))} / {format_float(registration.get('max_after_xcorr', ''))}

Worst cases by after-registration correlation:

{worst_lines}

## Blockers

{bullets(status['blockers'])}
## Next Commands

{next_commands}
"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build a compact V1 pipeline readiness report.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--qc-summary", type=Path, default=Path("reports/qc/qc_summary.json"))
    parser.add_argument("--manual-worklist", type=Path, default=Path("reports/qc/manual_mask_worklist.csv"))
    parser.add_argument("--analysis-manifest", type=Path, default=Path("derivatives/manifests/analysis_manifest.csv"))
    parser.add_argument("--nnunet-manifest", type=Path, default=Path("derivatives/brain_seg/nnunet_manifest.csv"))
    parser.add_argument(
        "--registration-summary",
        type=Path,
        default=Path("reports/qc/registration_all_mice/registration_qc_summary.csv"),
    )
    parser.add_argument("-o", "--output", type=Path, default=Path("reports/qc/project_status.md"))
    parser.add_argument("--json-output", type=Path, default=Path("reports/qc/project_status.json"))
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    status = build_status(
        qc_summary=read_json(args.qc_summary),
        manual_worklist_rows=read_csv_if_exists(args.manual_worklist),
        analysis_manifest_rows=read_csv_if_exists(args.analysis_manifest),
        nnunet_manifest_rows=read_csv_if_exists(args.nnunet_manifest),
        registration_rows=read_csv_if_exists(args.registration_summary),
    )
    write_markdown(args.output, status)
    args.json_output.parent.mkdir(parents=True, exist_ok=True)
    args.json_output.write_text(json.dumps(status, indent=2) + "\n")
    print(f"included: {status['analysis_included']}")
    print(f"blockers: {len(status['blockers'])}")
    print(f"status report: {args.output}")
    print(f"status json: {args.json_output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
