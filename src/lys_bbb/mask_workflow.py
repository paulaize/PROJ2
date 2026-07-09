"""Manual T1 brain-mask review and nnU-Net dataset preparation helpers."""

from __future__ import annotations

import argparse
import csv
import html
import json
import os
import shutil
from pathlib import Path
from typing import Any

import nibabel as nib
import numpy as np


WORKLIST_FIELDS = [
    "case_id",
    "animal_id",
    "timepoint",
    "mask_priority",
    "manual_status",
    "manual_action",
    "converted",
    "pre_image",
    "post_image",
    "current_manual_mask",
    "suggested_manual_mask",
    "final_done_mask",
    "mbe_prelabel",
    "manual_mask_qc_png",
    "mbe_mask_qc_png",
    "registration_qc_png",
    "registration_after_xcorr",
    "manual_mbe_dice",
    "qc_status",
    "qc_notes",
    "registration_review",
    "mask_review",
    "include_for_quantification",
    "include_for_nnunet",
    "review_notes",
]


NNUNET_MANIFEST_FIELDS = [
    "case_id",
    "image",
    "mask",
    "split",
    "manual_status",
    "qc_status",
    "notes",
]


NNUNET_PREP_FIELDS = [
    "case_id",
    "split",
    "status",
    "image",
    "mask",
    "output_image",
    "output_label",
    "message",
]


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "t", "yes", "y"}


def as_int(value: Any) -> int | None:
    try:
        if value == "" or value is None:
            return None
        return int(float(value))
    except (TypeError, ValueError):
        return None


def as_float(value: Any) -> float | None:
    try:
        if value == "" or value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def manual_status_and_action(row: dict[str, Any]) -> tuple[str, str, str]:
    pre_exists = as_bool(row.get("pre_exists"))
    post_exists = as_bool(row.get("post_exists"))
    manual_mask = row.get("manual_mask_path") or ""
    mbe_mask = row.get("mbe_mask_path") or ""

    if not (pre_exists and post_exists):
        return "P0", "missing_conversion", "fix conversion before manual masking"
    if not manual_mask:
        if mbe_mask:
            return "P1", "needs_manual_mask", "copy/correct MouseBrainExtractor pre-label"
        return "P1", "needs_prelabel_or_manual_mask", "create a mask from scratch or add a pre-label"
    if not as_bool(row.get("manual_mask_grid_ok")):
        return "P1", "mask_grid_error", "resave mask on the exact pre-image grid"

    actions: list[str] = []
    if not as_bool(row.get("manual_mask_done_name")):
        actions.append("review correction and mark final as *_done.nii.gz")
    dice = as_float(row.get("manual_mbe_dice"))
    if dice is not None and dice >= 0.999:
        actions.append("correct unchanged MouseBrainExtractor pre-label")
    components = as_int(row.get("manual_mask_components"))
    if components is not None and components > 1:
        actions.append("remove disconnected non-brain components")

    if actions:
        return "P2", "needs_correction_or_review", "; ".join(actions)
    return "P3", "ready_candidate", "ready for final visual QC"


def build_manual_worklist_rows(
    qc_rows: list[dict[str, Any]],
    *,
    manual_dir: Path,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in qc_rows:
        case_id = row.get("case_id", "")
        priority, manual_status, action = manual_status_and_action(row)
        converted = as_bool(row.get("pre_exists")) and as_bool(row.get("post_exists"))
        registration_ok = bool(row.get("registration_qc_png")) and as_bool(row.get("registration_source_match"))
        ready_mask = manual_status == "ready_candidate"
        rows.append({
            "case_id": case_id,
            "animal_id": row.get("animal_id", ""),
            "timepoint": row.get("timepoint", ""),
            "mask_priority": priority,
            "manual_status": manual_status,
            "manual_action": action,
            "converted": "yes" if converted else "no",
            "pre_image": row.get("pre_path", ""),
            "post_image": row.get("post_path", ""),
            "current_manual_mask": row.get("manual_mask_path", ""),
            "suggested_manual_mask": str(manual_dir / f"{case_id}_pre_manual_mask.nii.gz") if case_id else "",
            "final_done_mask": str(manual_dir / f"{case_id}_pre_manual_mask_done.nii.gz") if case_id else "",
            "mbe_prelabel": row.get("mbe_mask_path", ""),
            "manual_mask_qc_png": row.get("manual_mask_qc_png", ""),
            "mbe_mask_qc_png": row.get("mbe_mask_qc_png", ""),
            "registration_qc_png": row.get("registration_qc_png", ""),
            "registration_after_xcorr": row.get("registration_after_xcorr", ""),
            "manual_mbe_dice": row.get("manual_mbe_dice", ""),
            "qc_status": row.get("qc_status", ""),
            "qc_notes": row.get("qc_notes", ""),
            "registration_review": "",
            "mask_review": "",
            "include_for_quantification": "yes" if ready_mask and registration_ok else "no",
            "include_for_nnunet": "yes" if ready_mask else "no",
            "review_notes": "",
        })
    return sorted(
        rows,
        key=lambda item: (
            {"P1": 0, "P2": 1, "P3": 2, "P0": 3}.get(str(item["mask_priority"]), 9),
            item["animal_id"],
            item["timepoint"],
            item["case_id"],
        ),
    )


def build_nnunet_manifest_rows(
    qc_rows: list[dict[str, Any]],
    *,
    include_review_labels: bool = False,
    include_unlabeled: bool = True,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in qc_rows:
        case_id = row.get("case_id", "")
        pre_path = row.get("pre_path", "")
        if not pre_path or not as_bool(row.get("pre_exists")):
            continue
        priority, manual_status, action = manual_status_and_action(row)
        manual_mask = row.get("manual_mask_path", "")
        usable_label = bool(manual_mask) and as_bool(row.get("manual_mask_grid_ok"))
        if usable_label and not include_review_labels:
            usable_label = as_bool(row.get("manual_mask_done_name")) and manual_status == "ready_candidate"
        if usable_label:
            rows.append({
                "case_id": case_id,
                "image": pre_path,
                "mask": manual_mask,
                "split": "train",
                "manual_status": manual_status,
                "qc_status": row.get("qc_status", ""),
                "notes": action,
            })
        elif include_unlabeled:
            rows.append({
                "case_id": case_id,
                "image": pre_path,
                "mask": "",
                "split": "test",
                "manual_status": manual_status,
                "qc_status": row.get("qc_status", ""),
                "notes": action,
            })
    return sorted(rows, key=lambda item: (item["split"] != "train", item["case_id"]))


def absolute_for_link(path_text: str, *, cwd: Path) -> Path:
    path = Path(path_text)
    if path.is_absolute():
        return path
    return (cwd / path).resolve()


def relative_href(path_text: str, *, base_dir: Path, cwd: Path) -> str:
    target = absolute_for_link(path_text, cwd=cwd)
    return os.path.relpath(target, base_dir.resolve())


def link_html(path_text: str, *, base_dir: Path, cwd: Path, label: str | None = None) -> str:
    if not path_text:
        return '<span class="muted">missing</span>'
    href = html.escape(relative_href(path_text, base_dir=base_dir, cwd=cwd))
    text = html.escape(label or Path(path_text).name)
    return f'<a href="{href}">{text}</a>'


def thumb_html(path_text: str, *, base_dir: Path, cwd: Path, label: str) -> str:
    if not path_text:
        return '<span class="muted">missing</span>'
    href = html.escape(relative_href(path_text, base_dir=base_dir, cwd=cwd))
    alt = html.escape(label)
    return f'<a href="{href}"><img class="thumb" src="{href}" alt="{alt}"></a>'


def write_manual_dashboard(path: Path, rows: list[dict[str, Any]], *, cwd: Path | None = None) -> None:
    cwd = (cwd or Path.cwd()).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    base_dir = path.parent
    status_counts: dict[str, int] = {}
    for row in rows:
        status = str(row.get("manual_status", ""))
        status_counts[status] = status_counts.get(status, 0) + 1

    summary_items = "\n".join(
        f"<div><strong>{html.escape(status)}</strong><span>{count}</span></div>"
        for status, count in sorted(status_counts.items())
    )
    table_rows = []
    for row in rows:
        status_class = html.escape(str(row["manual_status"]).replace("_", "-"))
        table_rows.append(
            "<tr>"
            f'<td class="status {status_class}">{html.escape(str(row["mask_priority"]))}<br>'
            f'{html.escape(str(row["manual_status"]))}</td>'
            f"<td><strong>{html.escape(str(row['case_id']))}</strong><br>"
            f"{html.escape(str(row['animal_id']))} {html.escape(str(row['timepoint']))}</td>"
            f"<td>{html.escape(str(row['manual_action']))}<br>"
            f'<span class="muted">{html.escape(str(row.get("qc_notes", "")))}</span></td>'
            f"<td>{link_html(str(row.get('pre_image', '')), base_dir=base_dir, cwd=cwd, label='pre')}</td>"
            f"<td>{link_html(str(row.get('current_manual_mask', '')), base_dir=base_dir, cwd=cwd, label='manual')}</td>"
            f"<td>{link_html(str(row.get('mbe_prelabel', '')), base_dir=base_dir, cwd=cwd, label='MBE')}</td>"
            f"<td>{thumb_html(str(row.get('manual_mask_qc_png', '')), base_dir=base_dir, cwd=cwd, label='manual mask QC')}</td>"
            f"<td>{thumb_html(str(row.get('mbe_mask_qc_png', '')), base_dir=base_dir, cwd=cwd, label='MBE mask QC')}</td>"
            f"<td>{thumb_html(str(row.get('registration_qc_png', '')), base_dir=base_dir, cwd=cwd, label='registration QC')}<br>"
            f'<span class="muted">xcorr {html.escape(str(row.get("registration_after_xcorr", "")))}</span></td>'
            f"<td>{html.escape(str(row.get('include_for_quantification', '')))}</td>"
            f"<td>{html.escape(str(row.get('include_for_nnunet', '')))}</td>"
            "</tr>"
        )
    body_rows = "\n".join(table_rows)
    html_text = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>T1 Brain Mask Manual Review</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; margin: 24px; color: #1f2933; }}
    h1 {{ font-size: 24px; margin: 0 0 8px; }}
    p {{ max-width: 980px; line-height: 1.45; }}
    .summary {{ display: flex; flex-wrap: wrap; gap: 12px; margin: 18px 0; }}
    .summary div {{ border: 1px solid #d8dee9; border-radius: 6px; padding: 10px 12px; min-width: 170px; background: #f8fafc; }}
    .summary strong {{ display: block; font-size: 13px; color: #485465; }}
    .summary span {{ font-size: 24px; }}
    table {{ border-collapse: collapse; width: 100%; table-layout: fixed; }}
    th, td {{ border: 1px solid #d8dee9; padding: 8px; vertical-align: top; font-size: 12px; overflow-wrap: anywhere; }}
    th {{ background: #eef2f6; text-align: left; position: sticky; top: 0; z-index: 1; }}
    .muted {{ color: #667085; font-size: 11px; }}
    .thumb {{ width: 156px; height: auto; border: 1px solid #cbd5e1; background: #ffffff; }}
    .status {{ font-weight: 600; }}
    .needs-manual-mask, .needs-prelabel-or-manual-mask, .mask-grid-error {{ background: #fff1f2; }}
    .needs-correction-or-review {{ background: #fff7ed; }}
    .ready-candidate {{ background: #ecfdf3; }}
    .missing-conversion {{ background: #f1f5f9; }}
  </style>
</head>
<body>
  <h1>T1 Brain Mask Manual Review</h1>
  <p>
    Review the manual mask and registration thumbnails before accepting a case.
    MouseBrainExtractor outputs are pre-labels only; corrected masks should stay
    on the native pre-contrast T1 grid.
  </p>
  <div class="summary">
    {summary_items}
  </div>
  <table>
    <thead>
      <tr>
        <th>Priority / Status</th>
        <th>Case</th>
        <th>Action</th>
        <th>Pre Image</th>
        <th>Manual Mask</th>
        <th>Pre-label</th>
        <th>Manual QC</th>
        <th>Pre-label QC</th>
        <th>Registration QC</th>
        <th>Quant</th>
        <th>nnU-Net</th>
      </tr>
    </thead>
    <tbody>
      {body_rows}
    </tbody>
  </table>
</body>
</html>
"""
    path.write_text(html_text)


def validate_same_grid(image_path: Path, mask_path: Path) -> tuple[nib.Nifti1Image, nib.Nifti1Image]:
    image = nib.load(str(image_path))
    mask = nib.load(str(mask_path))
    if image.shape != mask.shape:
        raise ValueError(f"shape mismatch: image {image.shape}, mask {mask.shape}")
    if not np.allclose(image.affine, mask.affine, atol=1e-3):
        raise ValueError("affine mismatch between image and mask")
    return image, mask


def dataset_dir(nnunet_raw: Path, dataset_id: int, dataset_name: str) -> Path:
    return nnunet_raw / f"Dataset{dataset_id:03d}_{dataset_name}"


def write_dataset_json(path: Path, *, num_training: int) -> None:
    path.write_text(json.dumps({
        "channel_names": {"0": "T1"},
        "labels": {"background": 0, "brain": 1},
        "numTraining": num_training,
        "file_ending": ".nii.gz",
    }, indent=2) + "\n")


def prepare_nnunet_dataset(
    manifest_rows: list[dict[str, Any]],
    *,
    nnunet_raw: Path,
    dataset_id: int = 501,
    dataset_name: str = "MouseBrainMask",
    dry_run: bool = False,
    overwrite: bool = False,
) -> list[dict[str, Any]]:
    root = dataset_dir(nnunet_raw, dataset_id, dataset_name)
    images_tr = root / "imagesTr"
    labels_tr = root / "labelsTr"
    images_ts = root / "imagesTs"
    if not dry_run:
        for folder in (images_tr, labels_tr, images_ts):
            folder.mkdir(parents=True, exist_ok=True)

    records: list[dict[str, Any]] = []
    n_train = 0
    for row in manifest_rows:
        case_id = row.get("case_id", "")
        split = str(row.get("split", "")).strip().lower()
        image_path = Path(str(row.get("image", ""))).expanduser()
        mask_text = str(row.get("mask", "")).strip()
        mask_path = Path(mask_text).expanduser() if mask_text else None
        out_image = images_tr / f"{case_id}_0000.nii.gz" if split == "train" else images_ts / f"{case_id}_0000.nii.gz"
        out_label = labels_tr / f"{case_id}.nii.gz" if split == "train" else None
        status = "ready"
        message = ""
        try:
            if split not in {"train", "test"}:
                raise ValueError(f"unsupported split: {split}")
            if not image_path.exists():
                raise FileNotFoundError(f"missing image: {image_path}")
            nib.load(str(image_path))
            if split == "train":
                if mask_path is None:
                    raise ValueError("training row is missing a mask")
                if not mask_path.exists():
                    raise FileNotFoundError(f"missing mask: {mask_path}")
                image, mask_img = validate_same_grid(image_path, mask_path)
                n_train += 1
                if not dry_run:
                    if overwrite or not out_image.exists():
                        shutil.copy2(image_path, out_image)
                    mask_data = (mask_img.get_fdata(dtype=np.float32) > 0).astype(np.uint8)
                    label_img = nib.Nifti1Image(mask_data, image.affine, image.header.copy())
                    label_img.set_data_dtype(np.uint8)
                    if overwrite or not out_label.exists():
                        nib.save(label_img, str(out_label))
            else:
                if not dry_run and (overwrite or not out_image.exists()):
                    shutil.copy2(image_path, out_image)
        except Exception as exc:
            status = "failed"
            message = str(exc)
        records.append({
            "case_id": case_id,
            "split": split,
            "status": status,
            "image": str(image_path),
            "mask": str(mask_path or ""),
            "output_image": str(out_image),
            "output_label": str(out_label or ""),
            "message": message,
        })

    if not dry_run:
        write_dataset_json(root / "dataset.json", num_training=n_train)
    return records


def parse_build_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build manual T1 brain-mask worklist, dashboard, and nnU-Net manifest.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--qc-manifest", type=Path, default=Path("reports/qc/qc_manifest.csv"))
    parser.add_argument("--out-dir", type=Path, default=Path("reports/qc"))
    parser.add_argument("--manual-dir", type=Path, default=Path("derivatives/brain_seg/manual"))
    parser.add_argument("--worklist", type=Path, default=None)
    parser.add_argument("--dashboard", type=Path, default=None)
    parser.add_argument("--nnunet-manifest", type=Path, default=Path("derivatives/brain_seg/nnunet_manifest.csv"))
    parser.add_argument(
        "--include-review-labels",
        action="store_true",
        help="include existing but not *_done manual masks as nnU-Net training rows",
    )
    return parser.parse_args(argv)


def main_build_workflow(argv: list[str] | None = None) -> int:
    args = parse_build_args(argv)
    qc_rows = read_csv_rows(args.qc_manifest)
    worklist_path = args.worklist or args.out_dir / "manual_mask_worklist.csv"
    dashboard_path = args.dashboard or args.out_dir / "manual_mask_dashboard.html"
    worklist_rows = build_manual_worklist_rows(qc_rows, manual_dir=args.manual_dir)
    nnunet_rows = build_nnunet_manifest_rows(
        qc_rows,
        include_review_labels=args.include_review_labels,
        include_unlabeled=True,
    )
    write_csv(worklist_path, worklist_rows, WORKLIST_FIELDS)
    write_manual_dashboard(dashboard_path, worklist_rows)
    write_csv(args.nnunet_manifest, nnunet_rows, NNUNET_MANIFEST_FIELDS)
    n_train = sum(1 for row in nnunet_rows if row["split"] == "train")
    n_test = sum(1 for row in nnunet_rows if row["split"] == "test")
    print(f"worklist rows: {len(worklist_rows)}")
    print(f"nnU-Net manifest train/test: {n_train}/{n_test}")
    print(f"worklist: {worklist_path}")
    print(f"dashboard: {dashboard_path}")
    print(f"nnU-Net manifest: {args.nnunet_manifest}")
    return 0


def parse_prepare_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create an nnU-Net raw Dataset501_MouseBrainMask folder from a manifest.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--manifest", type=Path, default=Path("derivatives/brain_seg/nnunet_manifest.csv"))
    parser.add_argument("--nnunet-raw", type=Path, default=Path("derivatives/brain_seg/nnUNet_raw"))
    parser.add_argument("--dataset-id", type=int, default=501)
    parser.add_argument("--dataset-name", default="MouseBrainMask")
    parser.add_argument("--summary-csv", type=Path, default=Path("reports/qc/nnunet_prepare_summary.csv"))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args(argv)


def main_prepare_nnunet(argv: list[str] | None = None) -> int:
    args = parse_prepare_args(argv)
    rows = read_csv_rows(args.manifest)
    records = prepare_nnunet_dataset(
        rows,
        nnunet_raw=args.nnunet_raw,
        dataset_id=args.dataset_id,
        dataset_name=args.dataset_name,
        dry_run=args.dry_run,
        overwrite=args.overwrite,
    )
    write_csv(args.summary_csv, records, NNUNET_PREP_FIELDS)
    failures = [row for row in records if row["status"] == "failed"]
    n_train = sum(1 for row in records if row["split"] == "train")
    n_test = sum(1 for row in records if row["split"] == "test")
    print(f"rows: {len(records)}")
    print(f"train/test: {n_train}/{n_test}")
    print(f"failures: {len(failures)}")
    print(f"summary: {args.summary_csv}")
    if not args.dry_run:
        root = dataset_dir(args.nnunet_raw, args.dataset_id, args.dataset_name)
        print(f"dataset: {root}")
    return 1 if failures else 0
