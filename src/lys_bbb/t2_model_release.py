"""Validate the frozen RatLesNetV2 inference bundle exported by LYS_PROJ1.

This module intentionally contains no training, model-selection, or evaluation logic.
It accepts only the immutable five-fold release that was selected and frozen upstream.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np


EXPECTED_MODEL_COUNT = 5
EXPECTED_SPACING_MM = (0.07, 0.07, 0.5)
EXPECTED_ENSEMBLE = "unweighted mean lesion probability"
EXPECTED_POSTPROCESSING = "none"


@dataclass(frozen=True)
class FrozenT2ModelRelease:
    """Validated, runnable inference-only RatLesNetV2 release."""

    id: str
    name: str
    version: str
    root_path: Path
    architecture_path: Path
    model_paths: tuple[Path, ...]
    model_sha256: tuple[str, ...]
    threshold: float
    expected_spacing_mm: tuple[float, float, float]
    project_git_commit: str
    ratlesnetv2_git_commit: str
    manifest_sha256: str
    frozen_spec_sha256: str
    threshold_sha256: str
    metadata: dict[str, Any]


def validate_frozen_t2_model_release(
    root_path: Path | str,
) -> FrozenT2ModelRelease:
    """Validate the known LYS v1 inference bundle without mutating it."""

    root = Path(root_path).expanduser().resolve()
    if not root.is_dir():
        raise FileNotFoundError(f"T2 model release directory not found: {root}")

    manifest_path = root / "bundle_manifest.json"
    frozen_path = root / "frozen_spec.json"
    threshold_path = root / "selected_threshold.json"
    architecture_path = root / "RatLesNetv2"
    required_runtime = (
        architecture_path / "LICENSE",
        architecture_path / "UPSTREAM_GIT_COMMIT.txt",
        architecture_path / "lib" / "RatLesNetv2.py",
        architecture_path / "lib" / "RatLesNetv2Blocks.py",
    )
    for path in (manifest_path, frozen_path, threshold_path, *required_runtime):
        if not path.is_file():
            raise FileNotFoundError(f"T2 model release file is missing: {path}")

    manifest = _read_json(manifest_path)
    frozen = _read_json(frozen_path)
    threshold_record = _read_json(threshold_path)

    if frozen.get("architecture") != "RatLesNetV2":
        raise ValueError("Frozen specification architecture is not RatLesNetV2.")
    if frozen.get("ensemble") != EXPECTED_ENSEMBLE:
        raise ValueError("Frozen release does not use mean-probability ensembling.")
    if manifest.get("ensemble") != EXPECTED_ENSEMBLE:
        raise ValueError("Bundle manifest and frozen ensemble contract disagree.")
    if frozen.get("postprocessing") != EXPECTED_POSTPROCESSING:
        raise ValueError("Frozen release must declare postprocessing=none.")
    if manifest.get("postprocessing") != EXPECTED_POSTPROCESSING:
        raise ValueError("Bundle manifest and frozen postprocessing contract disagree.")

    threshold = float(threshold_record.get("selected_threshold", 0.0))
    if not 0.0 < threshold < 1.0:
        raise ValueError("The selected T2 probability threshold is invalid.")
    if threshold_record.get("selection_data") != "out_of_fold_validation_only":
        raise ValueError("The T2 threshold was not selected from OOF validation data.")
    if threshold_record.get("locked_test_used") is not False:
        raise ValueError("The threshold record must confirm locked_test_used=false.")
    for source, label in ((frozen, "frozen specification"), (manifest, "manifest")):
        if not np.isclose(
            float(source.get("threshold", -1.0)), threshold, rtol=0, atol=1e-12
        ):
            raise ValueError(f"The {label} and selected threshold disagree.")

    manifest_models = sorted(
        manifest.get("models", ()), key=lambda item: int(item.get("fold", -1))
    )
    frozen_models = sorted(
        frozen.get("fold_models", ()), key=lambda item: int(item.get("fold", -1))
    )
    expected_folds = list(range(EXPECTED_MODEL_COUNT))
    if [int(item.get("fold", -1)) for item in manifest_models] != expected_folds:
        raise ValueError("Bundle manifest must contain exactly folds 0 through 4.")
    if [int(item.get("fold", -1)) for item in frozen_models] != expected_folds:
        raise ValueError("Frozen specification must contain exactly folds 0 through 4.")

    model_paths: list[Path] = []
    model_hashes: list[str] = []
    for manifest_model, frozen_model in zip(
        manifest_models, frozen_models, strict=True
    ):
        relative_path = Path(str(manifest_model.get("file", "")))
        if relative_path.is_absolute() or ".." in relative_path.parts:
            raise ValueError("A model path escapes the frozen release directory.")
        model_path = root / relative_path
        if not model_path.is_file():
            raise FileNotFoundError(f"Frozen T2 model is missing: {model_path}")
        expected_hash = str(manifest_model.get("sha256", ""))
        if expected_hash != str(frozen_model.get("sha256", "")):
            raise ValueError("Model hashes disagree between release records.")
        observed_hash = sha256_file(model_path)
        if observed_hash != expected_hash:
            raise ValueError(f"Frozen model checksum mismatch: {model_path.name}")
        model_paths.append(model_path)
        model_hashes.append(observed_hash)

    upstream_commit = (
        (architecture_path / "UPSTREAM_GIT_COMMIT.txt").read_text().strip()
    )
    declared_upstream_commit = str(frozen.get("ratlesnetv2_git_commit", ""))
    if upstream_commit != declared_upstream_commit:
        raise ValueError(
            "Bundled RatLesNetV2 source revision does not match frozen_spec.json."
        )
    if str(manifest.get("ratlesnetv2_git_commit", "")) != declared_upstream_commit:
        raise ValueError("Bundle manifest and frozen RatLesNetV2 revision disagree.")

    project_commit = str(frozen.get("project_git_commit", ""))
    dataset = str(frozen.get("dataset", "unknown"))
    version = f"{dataset}-{project_commit[:8]}"
    release_id = f"ratlesnetv2-{version}".casefold()
    return FrozenT2ModelRelease(
        id=release_id,
        name="RatLesNetV2 five-fold ensemble",
        version=version,
        root_path=root,
        architecture_path=architecture_path,
        model_paths=tuple(model_paths),
        model_sha256=tuple(model_hashes),
        threshold=threshold,
        expected_spacing_mm=EXPECTED_SPACING_MM,
        project_git_commit=project_commit,
        ratlesnetv2_git_commit=declared_upstream_commit,
        manifest_sha256=sha256_file(manifest_path),
        frozen_spec_sha256=sha256_file(frozen_path),
        threshold_sha256=sha256_file(threshold_path),
        metadata={
            "architecture": "RatLesNetV2",
            "dataset": dataset,
            "ensemble": EXPECTED_ENSEMBLE,
            "postprocessing": EXPECTED_POSTPROCESSING,
            "threshold_selection": threshold_record.get("selection_data"),
            "predictions_are_drafts": True,
            "human_review_required": True,
            "runtime_sha256": {
                path.relative_to(root).as_posix(): sha256_file(path)
                for path in required_runtime
            },
        },
    )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in T2 release file {path.name}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"T2 release file must contain a JSON object: {path.name}")
    return value
