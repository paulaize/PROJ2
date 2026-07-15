"""Manual T1 brain-mask review and nnU-Net dataset preparation helpers."""

from __future__ import annotations

import argparse
import csv
import html
import json
import os
import shlex
import shutil
import tempfile
from pathlib import Path
from typing import Any

import nibabel as nib
import numpy as np

_cache_root = Path(tempfile.gettempdir()) / "lys_bbb_mri_cache"
os.environ.setdefault("MPLCONFIGDIR", str(_cache_root / "matplotlib"))
os.environ.setdefault("XDG_CACHE_HOME", str(_cache_root / "xdg"))
for _cache_dir in (Path(os.environ["MPLCONFIGDIR"]), Path(os.environ["XDG_CACHE_HOME"])):
    _cache_dir.mkdir(parents=True, exist_ok=True)

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt


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
    "manual_vs_mbe_qc_png",
    "manual_vs_mbe_qc_error",
    "registration_qc_png",
    "registration_after_xcorr",
    "manual_mbe_dice",
    "manual_mbe_xor_voxels",
    "manual_mask_components",
    "manual_mask_largest_component_pct",
    "manual_mask_small_components",
    "qc_status",
    "qc_notes",
    "registration_review",
    "mask_review",
    "include_for_quantification",
    "include_for_nnunet",
    "review_notes",
    "editor_command",
]


PRESERVED_REVIEW_FIELDS = [
    "registration_review",
    "mask_review",
    "review_notes",
]


REVIEW_PASS_VALUES = {"pass", "passed", "approve", "approved", "accept", "accepted", "yes", "y"}
REVIEW_FAIL_VALUES = {"fail", "failed", "reject", "rejected", "exclude", "excluded", "no", "n"}
REVIEW_PENDING_VALUES = {"review", "pending", "revise", "revision", "needs_review", "needs review"}


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


def normalize_review(value: Any) -> str:
    """Normalize human review decisions while leaving unknown values visible."""
    text = str(value or "").strip().lower()
    if not text:
        return ""
    if text in REVIEW_PASS_VALUES:
        return "pass"
    if text in REVIEW_FAIL_VALUES:
        return "fail"
    if text in REVIEW_PENDING_VALUES:
        return "review"
    return text


def existing_review_rows(path: Path) -> dict[str, dict[str, str]]:
    """Read the editable review fields from a previous generated worklist."""
    if not path.exists():
        return {}
    rows = read_csv_rows(path)
    return {
        str(row.get("case_id", "")): {
            field: str(row.get(field, ""))
            for field in PRESERVED_REVIEW_FIELDS
        }
        for row in rows
        if str(row.get("case_id", "")).strip()
    }


def editor_command(case_id: str) -> str:
    return shlex.join([
        "conda",
        "run",
        "-n",
        "lys-bbb",
        "python",
        "scripts/masks/open_manual_mask_editor.py",
        "--case",
        case_id,
        "--limit",
        "1",
    ])


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
    previous_rows: dict[str, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    previous_rows = previous_rows or {}
    rows: list[dict[str, Any]] = []
    for row in qc_rows:
        case_id = row.get("case_id", "")
        previous = previous_rows.get(str(case_id), {})
        priority, manual_status, action = manual_status_and_action(row)
        converted = as_bool(row.get("pre_exists")) and as_bool(row.get("post_exists"))
        registration_ok = bool(row.get("registration_qc_png")) and as_bool(row.get("registration_source_match"))
        ready_mask = manual_status == "ready_candidate"
        registration_review = normalize_review(previous.get("registration_review", ""))
        mask_review = normalize_review(previous.get("mask_review", ""))
        human_mask_ok = mask_review == "pass"
        human_registration_ok = registration_review == "pass"
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
            "manual_vs_mbe_qc_png": "",
            "manual_vs_mbe_qc_error": "",
            "registration_qc_png": row.get("registration_qc_png", ""),
            "registration_after_xcorr": row.get("registration_after_xcorr", ""),
            "manual_mbe_dice": row.get("manual_mbe_dice", ""),
            "manual_mbe_xor_voxels": row.get("manual_mbe_xor_voxels", ""),
            "manual_mask_components": row.get("manual_mask_components", ""),
            "manual_mask_largest_component_pct": row.get("manual_mask_largest_component_pct", ""),
            "manual_mask_small_components": row.get("manual_mask_small_components", ""),
            "qc_status": row.get("qc_status", ""),
            "qc_notes": row.get("qc_notes", ""),
            "registration_review": registration_review,
            "mask_review": mask_review,
            "include_for_quantification": "yes" if ready_mask and registration_ok and human_mask_ok and human_registration_ok else "no",
            "include_for_nnunet": "yes" if ready_mask and human_mask_ok else "no",
            "review_notes": previous.get("review_notes", ""),
            "editor_command": editor_command(str(case_id)) if case_id else "",
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
    approved_case_ids: set[str] | None = None,
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
        if usable_label and approved_case_ids is not None:
            usable_label = case_id in approved_case_ids
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


def comparison_slices(
    manual: np.ndarray,
    prelabel: np.ndarray,
    *,
    n_slices: int = 6,
    slice_start: int = 50,
    slice_stop: int = 170,
) -> np.ndarray:
    """Choose changed-mask slices first, falling back to mask extent or the QC range."""
    start = max(0, int(slice_start))
    stop = min(manual.shape[2] - 1, int(slice_stop))
    if start > stop:
        raise ValueError(f"empty comparison slice range: {start}-{stop}")

    allowed = np.arange(start, stop + 1)
    changed = np.flatnonzero((manual ^ prelabel).any(axis=(0, 1)))
    active = changed[(changed >= start) & (changed <= stop)]
    if active.size == 0:
        union = np.flatnonzero((manual | prelabel).any(axis=(0, 1)))
        active = union[(union >= start) & (union <= stop)]
    if active.size == 0:
        active = allowed
    if active.size <= n_slices:
        return active.astype(int)
    positions = np.linspace(0, active.size - 1, n_slices).round().astype(int)
    return np.unique(active[positions]).astype(int)


def _comparison_window(image: np.ndarray, mask: np.ndarray) -> tuple[float, float]:
    values = image[mask & np.isfinite(image)]
    if values.size < 100:
        values = image[np.isfinite(image)]
    if values.size == 0:
        return 0.0, 1.0
    vmin, vmax = np.percentile(values, [1, 99.5])
    if vmax <= vmin:
        vmax = vmin + 1.0
    return float(vmin), float(vmax)


def _draw_comparison_base(
    ax: plt.Axes,
    image: np.ndarray,
    k: int,
    *,
    vmin: float,
    vmax: float,
    display_aspect: float,
) -> None:
    ax.imshow(
        np.rot90(image[:, :, k]),
        cmap="gray",
        vmin=vmin,
        vmax=vmax,
        aspect=display_aspect,
    )
    ax.set_xticks([])
    ax.set_yticks([])


def write_mask_comparison_qc(
    image_path: Path,
    manual_path: Path,
    prelabel_path: Path,
    output_path: Path,
    *,
    case_id: str,
    n_slices: int = 6,
    slice_start: int = 50,
    slice_stop: int = 170,
) -> dict[str, Any]:
    """Write an edit-focused manual-vs-prelabel montage without modifying either mask."""
    image_img, manual_img = validate_same_grid(image_path, manual_path)
    _, prelabel_img = validate_same_grid(image_path, prelabel_path)
    image = image_img.get_fdata(dtype=np.float32)
    manual = manual_img.get_fdata(dtype=np.float32) > 0
    prelabel = prelabel_img.get_fdata(dtype=np.float32) > 0
    added = manual & ~prelabel
    removed = prelabel & ~manual
    union = manual | prelabel
    voxel_sizes = np.linalg.norm(image_img.affine[:3, :3], axis=0)
    display_aspect = float(voxel_sizes[1] / max(voxel_sizes[0], 1e-6))
    ks = comparison_slices(
        manual,
        prelabel,
        n_slices=n_slices,
        slice_start=slice_start,
        slice_stop=slice_stop,
    )
    vmin, vmax = _comparison_window(image, union)

    manual_n = int(np.count_nonzero(manual))
    prelabel_n = int(np.count_nonzero(prelabel))
    intersection = int(np.count_nonzero(manual & prelabel))
    denominator = manual_n + prelabel_n
    dice = float(2.0 * intersection / denominator) if denominator else float("nan")
    added_n = int(np.count_nonzero(added))
    removed_n = int(np.count_nonzero(removed))

    fig, axes = plt.subplots(len(ks), 3, figsize=(9.6, max(3.0, 2.5 * len(ks))), squeeze=False)
    for row_index, k in enumerate(ks):
        overlay_ax, edit_ax, manual_ax = axes[row_index]
        for ax in (overlay_ax, edit_ax, manual_ax):
            _draw_comparison_base(
                ax,
                image,
                int(k),
                vmin=vmin,
                vmax=vmax,
                display_aspect=display_aspect,
            )

        manual_slice = np.rot90(manual[:, :, k])
        prelabel_slice = np.rot90(prelabel[:, :, k])
        if prelabel_slice.any():
            overlay_ax.contour(prelabel_slice, levels=[0.5], colors="magenta", linewidths=0.8)
        if manual_slice.any():
            overlay_ax.contour(manual_slice, levels=[0.5], colors="lime", linewidths=0.8)

        edit_rgba = np.zeros((*added[:, :, k].shape, 4), dtype=np.float32)
        edit_rgba[added[:, :, k]] = (0.0, 0.9, 1.0, 0.72)
        edit_rgba[removed[:, :, k]] = (1.0, 0.45, 0.0, 0.72)
        edit_ax.imshow(np.rot90(edit_rgba), aspect=display_aspect)

        manual_rgba = np.zeros((*manual[:, :, k].shape, 4), dtype=np.float32)
        manual_rgba[manual[:, :, k]] = (0.1, 1.0, 0.25, 0.32)
        manual_ax.imshow(np.rot90(manual_rgba), aspect=display_aspect)
        if manual_slice.any():
            manual_ax.contour(manual_slice, levels=[0.5], colors="lime", linewidths=0.7)

        overlay_ax.set_ylabel(f"k={int(k)}", fontsize=8)
        if row_index == 0:
            overlay_ax.set_title("Contours: manual lime / pre-label magenta", fontsize=9)
            edit_ax.set_title("Edits: added cyan / removed orange", fontsize=9)
            manual_ax.set_title("Current manual mask", fontsize=9)

    edit_summary = "no changed voxels" if not (added_n or removed_n) else f"added {added_n:,} / removed {removed_n:,} voxels"
    fig.suptitle(f"{case_id}: manual vs MouseBrainExtractor | Dice {dice:.4f} | {edit_summary}", fontsize=10)
    fig.tight_layout(rect=(0, 0, 1, 0.98))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return {
        "dice": dice,
        "added_voxels": added_n,
        "removed_voxels": removed_n,
        "slices": [int(k) for k in ks],
    }


def add_comparison_qc(
    rows: list[dict[str, Any]],
    *,
    output_dir: Path,
    cwd: Path,
    slice_start: int = 50,
    slice_stop: int = 170,
) -> None:
    """Attach manual-vs-prelabel comparison PNGs to eligible worklist rows."""
    for row in rows:
        image_text = str(row.get("pre_image", ""))
        manual_text = str(row.get("current_manual_mask", ""))
        prelabel_text = str(row.get("mbe_prelabel", ""))
        if not (image_text and manual_text and prelabel_text):
            continue
        case_id = str(row.get("case_id", ""))
        output_path = output_dir / f"{case_id}_manual_vs_mbe_qc.png"
        try:
            write_mask_comparison_qc(
                absolute_for_link(image_text, cwd=cwd),
                absolute_for_link(manual_text, cwd=cwd),
                absolute_for_link(prelabel_text, cwd=cwd),
                output_path,
                case_id=case_id,
                slice_start=slice_start,
                slice_stop=slice_stop,
            )
            row["manual_vs_mbe_qc_png"] = str(output_path)
            row["manual_vs_mbe_qc_error"] = ""
        except Exception as exc:
            row["manual_vs_mbe_qc_png"] = ""
            row["manual_vs_mbe_qc_error"] = f"{type(exc).__name__}: {exc}"


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


def write_manual_dashboard(
    path: Path,
    rows: list[dict[str, Any]],
    *,
    cwd: Path | None = None,
    worklist_path: Path | None = None,
) -> None:
    cwd = (cwd or Path.cwd()).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    base_dir = path.parent
    status_counts: dict[str, int] = {}
    mask_review_counts: dict[str, int] = {}
    for row in rows:
        status = str(row.get("manual_status", ""))
        status_counts[status] = status_counts.get(status, 0) + 1
        review = normalize_review(row.get("mask_review", "")) or "not_reviewed"
        mask_review_counts[review] = mask_review_counts.get(review, 0) + 1

    summary_items = "\n".join(
        f"<div><strong>{html.escape(status)}</strong><span>{count}</span></div>"
        for status, count in sorted(status_counts.items())
    )
    review_summary_items = "\n".join(
        f"<div><strong>mask review: {html.escape(status)}</strong><span>{count}</span></div>"
        for status, count in sorted(mask_review_counts.items())
    )
    table_rows = []
    for row in rows:
        status = str(row["manual_status"])
        status_class = html.escape(status.replace("_", "-"))
        case_id = str(row["case_id"])
        mask_review = normalize_review(row.get("mask_review", "")) or "not reviewed"
        registration_review = normalize_review(row.get("registration_review", "")) or "not reviewed"
        editor = str(row.get("editor_command", ""))
        editor_button = '<span class="muted">no pre-label</span>'
        if editor and row.get("mbe_prelabel"):
            editor_button = (
                f'<button class="copy-command" data-command="{html.escape(editor, quote=True)}">'
                "Copy editor command</button>"
            )
        component_text = (
            f"components {html.escape(str(row.get('manual_mask_components', '') or '—'))}; "
            f"largest {html.escape(str(row.get('manual_mask_largest_component_pct', '') or '—'))}%; "
            f"small {html.escape(str(row.get('manual_mask_small_components', '') or '—'))}"
        )
        comparison = thumb_html(
            str(row.get("manual_vs_mbe_qc_png", "")),
            base_dir=base_dir,
            cwd=cwd,
            label="manual versus MouseBrainExtractor",
        )
        comparison_error = str(row.get("manual_vs_mbe_qc_error", ""))
        if comparison_error:
            comparison += f'<br><span class="error">{html.escape(comparison_error)}</span>'
        table_rows.append(
            f'<tr data-case="{html.escape(case_id.lower(), quote=True)}" data-status="{html.escape(status, quote=True)}">'
            f'<td class="status {status_class}">{html.escape(str(row["mask_priority"]))}<br>'
            f'{html.escape(status)}</td>'
            f"<td><strong>{html.escape(case_id)}</strong><br>"
            f"{html.escape(str(row['animal_id']))} {html.escape(str(row['timepoint']))}<br>"
            f"{link_html(str(row.get('pre_image', '')), base_dir=base_dir, cwd=cwd, label='pre image')} · "
            f"{link_html(str(row.get('current_manual_mask', '')), base_dir=base_dir, cwd=cwd, label='manual mask')} · "
            f"{link_html(str(row.get('mbe_prelabel', '')), base_dir=base_dir, cwd=cwd, label='pre-label')}<br>"
            f"{editor_button}</td>"
            f"<td>{html.escape(str(row['manual_action']))}<br>"
            f'<span class="muted">{html.escape(str(row.get("qc_notes", "")))}</span><br>'
            f'<span class="metric">Dice {html.escape(str(row.get("manual_mbe_dice", "") or "—"))}; '
            f'changed {html.escape(str(row.get("manual_mbe_xor_voxels", "") or "—"))} voxels<br>{component_text}</span></td>'
            f"<td>{comparison}</td>"
            f"<td>{thumb_html(str(row.get('manual_mask_qc_png', '')), base_dir=base_dir, cwd=cwd, label='manual mask QC')}<br>"
            f"{link_html(str(row.get('mbe_mask_qc_png', '')), base_dir=base_dir, cwd=cwd, label='open pre-label QC')}</td>"
            f"<td>{thumb_html(str(row.get('registration_qc_png', '')), base_dir=base_dir, cwd=cwd, label='registration QC')}<br>"
            f'<span class="muted">xcorr {html.escape(str(row.get("registration_after_xcorr", "")))}</span></td>'
            f'<td><span class="review {html.escape(mask_review.replace(" ", "-"))}">mask: {html.escape(mask_review)}</span><br>'
            f'<span class="review {html.escape(registration_review.replace(" ", "-"))}">registration: {html.escape(registration_review)}</span><br>'
            f'<span class="muted">{html.escape(str(row.get("review_notes", "")))}</span></td>'
            f"<td>quant: <strong>{html.escape(str(row.get('include_for_quantification', '')))}</strong><br>"
            f"nnU-Net: <strong>{html.escape(str(row.get('include_for_nnunet', '')))}</strong></td>"
            "</tr>"
        )
    body_rows = "\n".join(table_rows)
    worklist_link = (
        link_html(str(worklist_path), base_dir=base_dir, cwd=cwd, label="manual_mask_worklist.csv")
        if worklist_path else "manual_mask_worklist.csv"
    )
    html_text = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>T1 Brain Mask Manual Review</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; margin: 24px; color: #1f2933; }}
    h1 {{ font-size: 24px; margin: 0 0 8px; }}
    p {{ max-width: 1100px; line-height: 1.45; }}
    .controls {{ align-items: end; display: flex; flex-wrap: wrap; gap: 12px; margin: 16px 0; }}
    .controls label {{ color: #485465; display: grid; font-size: 12px; gap: 4px; }}
    .controls input, .controls select {{ border: 1px solid #cbd5e1; border-radius: 5px; font-size: 14px; padding: 7px 9px; }}
    .summary {{ display: flex; flex-wrap: wrap; gap: 12px; margin: 18px 0; }}
    .summary div {{ border: 1px solid #d8dee9; border-radius: 6px; padding: 10px 12px; min-width: 170px; background: #f8fafc; }}
    .summary strong {{ display: block; font-size: 13px; color: #485465; }}
    .summary span {{ font-size: 24px; }}
    table {{ border-collapse: collapse; min-width: 1500px; width: 100%; table-layout: fixed; }}
    .table-wrap {{ max-height: calc(100vh - 250px); overflow: auto; }}
    th, td {{ border: 1px solid #d8dee9; padding: 8px; vertical-align: top; font-size: 12px; overflow-wrap: anywhere; }}
    th {{ background: #eef2f6; text-align: left; position: sticky; top: 0; z-index: 1; }}
    .muted {{ color: #667085; font-size: 11px; }}
    .thumb {{ width: 240px; height: auto; border: 1px solid #cbd5e1; background: #ffffff; }}
    .status {{ font-weight: 600; }}
    .metric {{ color: #344054; display: inline-block; font-size: 11px; margin-top: 6px; }}
    .error {{ color: #b42318; font-size: 11px; }}
    .review {{ border-radius: 999px; display: inline-block; font-size: 11px; margin: 2px 0; padding: 2px 7px; background: #f1f5f9; }}
    .review.pass {{ background: #dcfae6; color: #067647; }}
    .review.fail {{ background: #fee4e2; color: #b42318; }}
    .review.review {{ background: #fef0c7; color: #b54708; }}
    button {{ background: #175cd3; border: 0; border-radius: 5px; color: white; cursor: pointer; font-size: 11px; margin-top: 7px; padding: 5px 8px; }}
    button.copied {{ background: #067647; }}
    .needs-manual-mask, .needs-prelabel-or-manual-mask, .mask-grid-error {{ background: #fff1f2; }}
    .needs-correction-or-review {{ background: #fff7ed; }}
    .ready-candidate {{ background: #ecfdf3; }}
    .missing-conversion {{ background: #f1f5f9; }}
  </style>
</head>
<body>
  <h1>T1 Brain Mask Manual Review</h1>
  <p>
    MouseBrainExtractor outputs are pre-labels only. The comparison montage
    prioritizes edited slices: manual contours are lime, pre-label contours are
    magenta, added voxels are cyan, and removed voxels are orange. Corrected masks
    must stay on the native pre-contrast T1 grid.
  </p>
  <p>
    Human decisions live in {worklist_link}. Set <code>mask_review</code> and
    <code>registration_review</code> to <code>pass</code>, <code>review</code>, or
    <code>fail</code>, add <code>review_notes</code>, and rebuild. Those fields are
    preserved. The worklist quantification flag requires both reviews to pass;
    nnU-Net inclusion requires the mask review to pass.
  </p>
  <div class="summary">
    {summary_items}
    {review_summary_items}
  </div>
  <div class="controls">
    <label>Find case<input id="case-search" type="search" placeholder="C25S1_D1"></label>
    <label>Mask status<select id="status-filter"><option value="">all statuses</option>{''.join(f'<option value="{html.escape(status, quote=True)}">{html.escape(status)}</option>' for status in sorted(status_counts))}</select></label>
    <span id="visible-count" class="muted"></span>
  </div>
  <div class="table-wrap">
  <table id="review-table">
    <thead>
      <tr>
        <th>Priority / Status</th>
        <th>Case</th>
        <th>Action / Metrics</th>
        <th>Manual vs Pre-label</th>
        <th>Manual QC</th>
        <th>Registration QC</th>
        <th>Human Review</th>
        <th>Gates</th>
      </tr>
    </thead>
    <tbody>
      {body_rows}
    </tbody>
  </table>
  </div>
  <script>
    const search = document.getElementById("case-search");
    const statusFilter = document.getElementById("status-filter");
    const rows = Array.from(document.querySelectorAll("#review-table tbody tr"));
    const count = document.getElementById("visible-count");
    function applyFilters() {{
      const query = search.value.trim().toLowerCase();
      const status = statusFilter.value;
      let visible = 0;
      rows.forEach((row) => {{
        const show = (!query || row.dataset.case.includes(query)) && (!status || row.dataset.status === status);
        row.hidden = !show;
        if (show) visible += 1;
      }});
      count.textContent = `${{visible}} / ${{rows.length}} cases shown`;
    }}
    search.addEventListener("input", applyFilters);
    statusFilter.addEventListener("change", applyFilters);
    applyFilters();

    document.querySelectorAll(".copy-command").forEach((button) => {{
      button.addEventListener("click", async () => {{
        const command = button.dataset.command;
        try {{
          await navigator.clipboard.writeText(command);
        }} catch (_) {{
          const area = document.createElement("textarea");
          area.value = command;
          document.body.appendChild(area);
          area.select();
          document.execCommand("copy");
          area.remove();
        }}
        button.textContent = "Copied";
        button.classList.add("copied");
        setTimeout(() => {{ button.textContent = "Copy editor command"; button.classList.remove("copied"); }}, 1400);
      }});
    }});
  </script>
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
    parser.add_argument("--comparison-dir", type=Path, default=None)
    parser.add_argument("--nnunet-manifest", type=Path, default=Path("derivatives/brain_seg/nnunet_manifest.csv"))
    parser.add_argument("--mask-slice-start", type=int, default=50)
    parser.add_argument("--mask-slice-stop", type=int, default=170)
    parser.add_argument(
        "--no-comparison-qc",
        action="store_true",
        help="skip manual-vs-MouseBrainExtractor edit montages",
    )
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
    comparison_dir = args.comparison_dir or args.out_dir / "brain_masks" / "comparison"
    previous_rows = existing_review_rows(worklist_path)
    worklist_rows = build_manual_worklist_rows(
        qc_rows,
        manual_dir=args.manual_dir,
        previous_rows=previous_rows,
    )
    if not args.no_comparison_qc:
        add_comparison_qc(
            worklist_rows,
            output_dir=comparison_dir,
            cwd=Path.cwd().resolve(),
            slice_start=args.mask_slice_start,
            slice_stop=args.mask_slice_stop,
        )
    approved_case_ids = {
        str(row["case_id"])
        for row in worklist_rows
        if row.get("include_for_nnunet") == "yes"
    }
    nnunet_rows = build_nnunet_manifest_rows(
        qc_rows,
        include_review_labels=args.include_review_labels,
        include_unlabeled=True,
        approved_case_ids=approved_case_ids,
    )
    write_csv(worklist_path, worklist_rows, WORKLIST_FIELDS)
    write_manual_dashboard(
        dashboard_path,
        worklist_rows,
        worklist_path=worklist_path,
    )
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
