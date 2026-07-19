"""Validate and review standardized Colab brain-extraction predictions."""

from __future__ import annotations

import csv
import json
import shutil
import zipfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import nibabel as nib
import numpy as np


RUN_MANIFEST = "run_manifest.csv"
REQUIRED_FIELDS = {"case_id", "model_id", "status", "image", "mask"}
MODEL_LABELS = {
    "mbe_invivo_iso": "MouseBrainExtractor — in-vivo isotropic",
    "mbe_invivo_aniso": "MouseBrainExtractor — in-vivo anisotropic sensitivity run",
    "rs2net": "RS2-Net",
    "rs2net_raw": "RS2-Net — immutable raw prediction",
    "rs2_m_seam": "RS2-Net + direct dark-gap M-seam correction (experimental)",
    "rs2_marker_watershed": "RS2-Net + marker watershed correction (experimental)",
    "rs2_random_walker": "RS2-Net + random-walker correction (experimental)",
    "rs2net_p050": "RS2-Net probability ≥ 0.50",
    "rs2net_p060": "RS2-Net probability ≥ 0.60",
    "rs2net_p070": "RS2-Net probability ≥ 0.70",
    "rs2net_p080": "RS2-Net probability ≥ 0.80",
    "rs2net_p090": "RS2-Net probability ≥ 0.90",
    "rs2net_p095": "RS2-Net probability ≥ 0.95",
    "camri_rodent_unet_t2": "CAMRI rodent U-Net — T2/EPI cross-contrast control",
    "deepbet_human_t1": "deepbet — human T1 control",
}
MODEL_ORDER = tuple(MODEL_LABELS)


@dataclass(frozen=True)
class ReviewPrediction:
    """One input T1 and model prediction declared by the Colab run manifest."""

    case_id: str
    model_id: str
    image: Path
    mask: Path
    metadata: Path | None = None
    log: Path | None = None


def _safe_extract(archive_path: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    destination_resolved = destination.resolve()
    with zipfile.ZipFile(archive_path) as archive:
        for member in archive.infolist():
            target = (destination / member.filename).resolve()
            if not target.is_relative_to(destination_resolved):
                raise ValueError(f"unsafe archive path: {member.filename}")
        archive.extractall(destination)


def locate_results_root(path: Path) -> Path:
    """Return the directory containing the unique Colab run manifest."""
    path = path.expanduser().resolve()
    if not path.exists():
        raise FileNotFoundError(f"results path does not exist: {path}")

    if path.is_file():
        if path.suffix.lower() != ".zip":
            raise ValueError(f"expected a results directory or .zip archive: {path}")
        extracted = path.with_suffix("")
        _safe_extract(path, extracted)
        path = extracted

    direct = path / RUN_MANIFEST
    if direct.is_file():
        return path
    manifests = sorted(
        candidate
        for candidate in path.rglob(RUN_MANIFEST)
        if "__MACOSX" not in candidate.parts
    )
    if len(manifests) != 1:
        raise ValueError(
            f"expected one {RUN_MANIFEST} under {path}, found {len(manifests)}"
        )
    return manifests[0].parent


def _resolve_declared_path(root: Path, value: str) -> Path:
    declared = Path(value)
    path = declared.resolve() if declared.is_absolute() else (root / declared).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError(f"manifest path escapes results root: {value}")
    return path


def _optional_path(root: Path, value: str | None) -> Path | None:
    return _resolve_declared_path(root, value) if value else None


def read_predictions(results_root: Path) -> list[ReviewPrediction]:
    """Read successful predictions and enforce one row per case and model."""
    results_root = results_root.resolve()
    manifest = results_root / RUN_MANIFEST
    with manifest.open(newline="") as stream:
        reader = csv.DictReader(stream)
        missing = REQUIRED_FIELDS - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"run manifest is missing fields: {', '.join(sorted(missing))}")
        rows = list(reader)

    predictions: list[ReviewPrediction] = []
    seen: set[tuple[str, str]] = set()
    for row in rows:
        if row["status"] != "ok":
            continue
        key = (row["case_id"], row["model_id"])
        if key in seen:
            raise ValueError(f"duplicate successful prediction: {key[0]} / {key[1]}")
        seen.add(key)
        predictions.append(
            ReviewPrediction(
                case_id=row["case_id"],
                model_id=row["model_id"],
                image=_resolve_declared_path(results_root, row["image"]),
                mask=_resolve_declared_path(results_root, row["mask"]),
                metadata=_optional_path(results_root, row.get("metadata")),
                log=_optional_path(results_root, row.get("log")),
            )
        )
    order = {model_id: index for index, model_id in enumerate(MODEL_ORDER)}
    return sorted(
        predictions,
        key=lambda item: (item.case_id, order.get(item.model_id, len(order)), item.model_id),
    )


def validate_prediction(prediction: ReviewPrediction) -> list[str]:
    """Return human-readable errors for missing, non-binary, or mismatched masks."""
    errors: list[str] = []
    if not prediction.image.is_file():
        errors.append(f"missing T1: {prediction.image}")
    if not prediction.mask.is_file():
        errors.append(f"missing mask: {prediction.mask}")
    if errors:
        return errors

    try:
        image = nib.load(str(prediction.image))
        mask = nib.load(str(prediction.mask))
        if image.shape != mask.shape:
            errors.append(f"shape mismatch: T1 {image.shape}, mask {mask.shape}")
        if not np.allclose(image.affine, mask.affine, rtol=1e-5, atol=1e-5):
            errors.append("affine mismatch between T1 and mask")
        values = np.unique(np.asanyarray(mask.dataobj))
        if not np.isfinite(values).all():
            errors.append("mask contains non-finite values")
        elif not set(values.tolist()).issubset({0, 1}):
            preview = ", ".join(str(value) for value in values[:8])
            errors.append(f"mask is not binary; values include {preview}")
        elif values.size == 1:
            errors.append(f"mask is constant ({values[0]})")
    except Exception as exc:
        errors.append(f"cannot read NIfTI pair: {type(exc).__name__}: {exc}")
    return errors


def group_predictions(
    predictions: list[ReviewPrediction],
) -> dict[str, list[ReviewPrediction]]:
    grouped: dict[str, list[ReviewPrediction]] = {}
    for prediction in predictions:
        grouped.setdefault(prediction.case_id, []).append(prediction)
    return grouped


def find_itksnap(explicit: Path | None = None) -> Path:
    """Find the ITK-SNAP executable from an argument, PATH, or common macOS path."""
    if explicit:
        candidate = explicit.expanduser().resolve()
        if not candidate.is_file():
            raise FileNotFoundError(f"ITK-SNAP executable not found: {candidate}")
        return candidate
    on_path = shutil.which("itksnap") or shutil.which("ITK-SNAP")
    if on_path:
        return Path(on_path).resolve()
    macos = Path("/Applications/ITK-SNAP.app/Contents/MacOS/ITK-SNAP")
    if macos.is_file():
        return macos
    raise FileNotFoundError(
        "ITK-SNAP was not found. Install it, add 'itksnap' to PATH, or pass "
        "--viewer /path/to/ITK-SNAP."
    )


def itksnap_command(viewer: Path, prediction: ReviewPrediction) -> list[str]:
    """Build one ITK-SNAP command containing a T1 and its corresponding mask."""
    return [str(viewer), "-g", str(prediction.image), "-s", str(prediction.mask)]


def upsert_case_review(
    path: Path,
    *,
    case_id: str,
    preferred_model: str,
    notes: str = "",
) -> None:
    fields = ["case_id", "preferred_model", "review_status", "notes", "reviewed_at"]
    rows: dict[str, dict[str, str]] = {}
    if path.is_file():
        with path.open(newline="") as stream:
            rows = {row["case_id"]: row for row in csv.DictReader(stream)}
    rows[case_id] = {
        "case_id": case_id,
        "preferred_model": preferred_model,
        "review_status": "selected" if preferred_model else "skipped",
        "notes": notes,
        "reviewed_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    }
    with path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows[key] for key in sorted(rows))


def write_overall_decision(path: Path, model_id: str, vote_counts: dict[str, int]) -> None:
    decision = {
        "selected_model": model_id,
        "selected_model_label": MODEL_LABELS.get(model_id, model_id),
        "decision_status": "provisional_visual_selection",
        "case_vote_counts": vote_counts,
        "decided_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "warning": "Visual selection is not a reviewed reference-mask accuracy study.",
    }
    path.write_text(json.dumps(decision, indent=2) + "\n")
