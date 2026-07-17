#!/usr/bin/env python
"""Open Colab brain masks beside their T1s in ITK-SNAP and record preferences."""

from __future__ import annotations

import argparse
import csv
import subprocess
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from lys_bbb.brain_extraction_review import (  # noqa: E402
    MODEL_LABELS,
    MODEL_ORDER,
    find_itksnap,
    group_predictions,
    itksnap_command,
    locate_results_root,
    read_predictions,
    upsert_case_review,
    validate_prediction,
    write_overall_decision,
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Validate one or more downloaded Colab result archives, then open one "
            "ITK-SNAP window per model for each T1 case."
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "results",
        type=Path,
        nargs="+",
        help="Downloaded result .zip or extracted directory (one or more)",
    )
    parser.add_argument(
        "--review-dir",
        type=Path,
        default=None,
        help="Directory for combined review decisions; useful with multiple archives",
    )
    parser.add_argument("--viewer", type=Path, default=None, help="ITK-SNAP executable")
    parser.add_argument("--case", action="append", default=[], help="Review only this case (repeatable)")
    parser.add_argument("--model", action="append", default=[], help="Review only this model ID (repeatable)")
    parser.add_argument("--start-at", default=None, help="Start at this case in sorted order")
    parser.add_argument("--limit", type=int, default=None, help="Maximum number of cases to review")
    parser.add_argument("--dry-run", action="store_true", help="Validate and print commands without opening ITK-SNAP")
    parser.add_argument("--allow-invalid", action="store_true", help="Open predictions even when grid validation fails")
    parser.add_argument("--no-wait", action="store_true", help="Ask for a choice without waiting for ITK-SNAP windows to close")
    parser.add_argument("--no-record", action="store_true", help="Do not ask for or save model preferences")
    return parser.parse_args(argv)


def existing_vote_counts(review_csv: Path) -> Counter[str]:
    counts: Counter[str] = Counter()
    if not review_csv.is_file():
        return counts
    with review_csv.open(newline="") as stream:
        for row in csv.DictReader(stream):
            if row.get("preferred_model"):
                counts[row["preferred_model"]] += 1
    return counts


def choose_prediction(case_id: str, predictions: list, review_csv: Path) -> bool:
    print(f"\n{case_id}: close the ITK-SNAP windows after comparing the boundaries.")
    for index, prediction in enumerate(predictions, start=1):
        print(f"  {index}. {prediction.model_id}: {MODEL_LABELS.get(prediction.model_id, prediction.model_id)}")
    while True:
        answer = input("Preferred mask number, s=skip, or q=stop: ").strip().lower()
        if answer == "q":
            return False
        if answer in {"s", ""}:
            upsert_case_review(review_csv, case_id=case_id, preferred_model="")
            return True
        if answer.isdigit() and 1 <= int(answer) <= len(predictions):
            selected = predictions[int(answer) - 1]
            upsert_case_review(
                review_csv,
                case_id=case_id,
                preferred_model=selected.model_id,
            )
            return True
        print("Please enter one of the displayed numbers, s, or q.")


def choose_overall(results_root: Path, predictions: list, vote_counts: Counter[str]) -> None:
    available = {prediction.model_id for prediction in predictions}
    model_ids = [model_id for model_id in MODEL_ORDER if model_id in available]
    model_ids.extend(sorted(available - set(model_ids)))
    if not model_ids:
        return
    print("\nCase-level preference summary:")
    for index, model_id in enumerate(model_ids, start=1):
        print(f"  {index}. {model_id}: {vote_counts[model_id]} case(s)")
    while True:
        answer = input("Overall preferred model number, or s=leave undecided: ").strip().lower()
        if answer in {"s", ""}:
            return
        if answer.isdigit() and 1 <= int(answer) <= len(model_ids):
            selected = model_ids[int(answer) - 1]
            output = results_root / "benchmark_decision.json"
            write_overall_decision(output, selected, dict(vote_counts))
            print(f"Saved provisional decision: {output}")
            return
        print("Please enter one of the displayed numbers or s.")


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    results_roots = [locate_results_root(path) for path in args.results]
    predictions = [
        prediction
        for results_root in results_roots
        for prediction in read_predictions(results_root)
    ]
    seen: set[tuple[str, str]] = set()
    duplicates: set[tuple[str, str]] = set()
    for prediction in predictions:
        key = (prediction.case_id, prediction.model_id)
        if key in seen:
            duplicates.add(key)
        seen.add(key)
    if duplicates:
        details = ", ".join(
            f"{case_id} / {model_id}" for case_id, model_id in sorted(duplicates)
        )
        raise ValueError(f"duplicate predictions across result archives: {details}")
    if args.case:
        predictions = [item for item in predictions if item.case_id in set(args.case)]
    if args.model:
        predictions = [item for item in predictions if item.model_id in set(args.model)]
    if not predictions:
        raise ValueError("no successful predictions match the requested filters")

    invalid: dict[tuple[str, str], list[str]] = {}
    for prediction in predictions:
        errors = validate_prediction(prediction)
        if errors:
            invalid[(prediction.case_id, prediction.model_id)] = errors
    if invalid:
        print("Validation problems:")
        for (case_id, model_id), errors in invalid.items():
            print(f"  {case_id} / {model_id}: {'; '.join(errors)}")
        if not args.allow_invalid:
            predictions = [
                item for item in predictions
                if (item.case_id, item.model_id) not in invalid
            ]
    if not predictions:
        raise ValueError("no valid predictions remain to review")

    grouped = group_predictions(predictions)
    case_ids = sorted(grouped)
    if args.start_at:
        if args.start_at not in case_ids:
            raise ValueError(f"--start-at case is unavailable: {args.start_at}")
        case_ids = case_ids[case_ids.index(args.start_at):]
    if args.limit is not None:
        if args.limit <= 0:
            raise ValueError("--limit must be positive")
        case_ids = case_ids[:args.limit]

    viewer = Path("itksnap") if args.dry_run and args.viewer is None else find_itksnap(args.viewer)
    if args.review_dir is not None:
        review_root = args.review_dir.expanduser().resolve()
    elif len(results_roots) == 1:
        review_root = results_roots[0]
    else:
        review_root = args.results[0].expanduser().resolve().parent / "t1_brain_extraction_combined_review"
    if not args.dry_run and not args.no_record:
        review_root.mkdir(parents=True, exist_ok=True)

    for results_root in results_roots:
        print(f"Results: {results_root}")
    print(f"Review decisions: {review_root}")
    print(f"Cases: {len(case_ids)}  predictions: {sum(len(grouped[key]) for key in case_ids)}")
    review_csv = review_root / "model_review.csv"
    reviewed_predictions = []
    for case_id in case_ids:
        case_predictions = grouped[case_id]
        reviewed_predictions.extend(case_predictions)
        processes = []
        print(f"\nOpening {case_id} ({len(case_predictions)} model windows)")
        for prediction in case_predictions:
            command = itksnap_command(viewer, prediction)
            print("  " + " ".join(command))
            if not args.dry_run:
                processes.append(subprocess.Popen(command))
        if args.dry_run:
            continue
        if not args.no_wait:
            for process in processes:
                process.wait()
        if not args.no_record and not choose_prediction(case_id, case_predictions, review_csv):
            break

    if args.dry_run:
        print("\nDry run complete: every displayed command pairs one T1 with one model mask.")
        return 0
    if not args.no_record:
        vote_counts = existing_vote_counts(review_csv)
        choose_overall(review_root, reviewed_predictions, vote_counts)
        print(f"Case-level selections: {review_csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
