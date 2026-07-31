"""Validate packaged T2 lesion-segmentation inference resources.

The legacy RatLesNetV2 bundle and the LYS v3 nnU-Net resources share one
inference-release record so study provenance remains stable across model choices.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from lys_bbb.hashing import sha256_file


EXPECTED_MODEL_COUNT = 5
EXPECTED_SPACING_MM = (0.07, 0.07, 0.5)
EXPECTED_ENSEMBLE = "unweighted mean lesion probability"
EXPECTED_POSTPROCESSING = "none"
NNUNET_DATASET = "Dataset701_LYSDevelopmentV1"
NNUNET_VERSION = "2.8.1"
NNUNET_TRAINER = "nnUNetTrainer_250epochs"
NNUNET_PLANS = "nnUNetPlans"
NNUNET_CONFIGURATION = "3d_fullres"
NNUNET_CHECKPOINT = "checkpoint_best.pth"
NNUNET_THRESHOLD = 0.20


@dataclass(frozen=True)
class FrozenT2ModelRelease:
    """Validated, runnable inference-only T2 model release."""

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
    runner: str = "ratlesnetv2"
    folds: tuple[int, ...] = ()
    checkpoint_name: str = ""


def validate_t2_model_release(root_path: Path | str) -> FrozenT2ModelRelease:
    """Validate either a packaged LYS v3 nnU-Net choice or the legacy release."""

    root = Path(root_path).expanduser().resolve()
    if (root / "model_metadata.json").is_file():
        return validate_nnunet_t2_model_release(root)
    return validate_frozen_t2_model_release(root)


def validate_nnunet_t2_model_release(
    root_path: Path | str,
) -> FrozenT2ModelRelease:
    """Validate a self-contained LYS v3 nnU-Net resource or packaged variant."""

    choice_root = Path(root_path).expanduser().resolve()
    metadata_path = choice_root / "model_metadata.json"
    if not metadata_path.is_file():
        raise FileNotFoundError(f"T2 model metadata is missing: {metadata_path}")
    metadata = _read_json(metadata_path)

    resource_relative = Path(str(metadata.get("resource_root", ".")))
    if resource_relative.is_absolute():
        raise ValueError("nnU-Net resource_root must be a relative path.")
    resource_root = (choice_root / resource_relative).resolve()
    models_root = _packaged_models_root(choice_root)
    if not resource_root.is_relative_to(models_root):
        raise ValueError("nnU-Net resource_root escapes the packaged models directory.")

    expected_values = {
        "dataset": NNUNET_DATASET,
        "nnunet_version": NNUNET_VERSION,
        "trainer": NNUNET_TRAINER,
        "plans": NNUNET_PLANS,
        "configuration": NNUNET_CONFIGURATION,
        "checkpoint": NNUNET_CHECKPOINT,
        "postprocessing": EXPECTED_POSTPROCESSING,
    }
    for key, expected in expected_values.items():
        if metadata.get(key) != expected:
            raise ValueError(
                f"nnU-Net metadata {key} must be {expected!r}, "
                f"not {metadata.get(key)!r}."
            )
    if metadata.get("architecture") != "standard PlainConvUNet":
        raise ValueError("nnU-Net metadata must declare standard PlainConvUNet.")
    if not np.isclose(
        float(metadata.get("probability_threshold", -1)),
        NNUNET_THRESHOLD,
        rtol=0,
        atol=1e-12,
    ):
        raise ValueError("LYS v3 nnU-Net probability threshold must be 0.20.")
    if metadata.get("predictions_are_drafts") is not True:
        raise ValueError("nnU-Net predictions must be declared as draft masks.")
    if metadata.get("human_review_required") is not True:
        raise ValueError("nnU-Net metadata must require human review.")

    folds_value = metadata.get("folds")
    if not isinstance(folds_value, list) or not folds_value:
        raise ValueError("nnU-Net metadata must declare at least one inference fold.")
    folds = tuple(int(value) for value in folds_value)
    if folds not in ((1,), (0, 1)):
        raise ValueError("Packaged LYS v3 choices support fold 1 or folds 0+1.")

    required = (resource_root / "dataset.json", resource_root / "plans.json")
    checkpoint_paths = tuple(
        resource_root / f"fold_{fold}" / NNUNET_CHECKPOINT for fold in folds
    )
    license_path = resource_root / str(metadata.get("license_notice", ""))
    for path in (*required, *checkpoint_paths, license_path):
        if not path.is_file():
            raise FileNotFoundError(f"Required nnU-Net model resource is missing: {path}")

    dataset = _read_json(required[0])
    plans = _read_json(required[1])
    if plans.get("dataset_name") != NNUNET_DATASET:
        raise ValueError("plans.json does not belong to Dataset701_LYSDevelopmentV1.")
    if plans.get("plans_name") != NNUNET_PLANS:
        raise ValueError("plans.json does not declare nnUNetPlans.")
    configuration = plans.get("configurations", {}).get(NNUNET_CONFIGURATION, {})
    network_class = configuration.get("architecture", {}).get("network_class_name")
    if network_class != (
        "dynamic_network_architectures.architectures.unet.PlainConvUNet"
    ):
        raise ValueError("plans.json is not the standard PlainConvUNet architecture.")
    if dataset.get("labels", {}).get("lesion") != 1:
        raise ValueError("dataset.json must map the lesion label to class 1.")

    sums_path = resource_root / "SHA256SUMS"
    expected_hashes = _read_sha256sums(sums_path)
    observed_hashes: dict[str, str] = {}
    for relative, expected_hash in expected_hashes.items():
        path = (resource_root / relative).resolve()
        if not path.is_relative_to(resource_root):
            raise ValueError(f"SHA256SUMS path escapes model resources: {relative}")
        if not path.is_file():
            raise FileNotFoundError(f"Hashed nnU-Net model resource is missing: {path}")
        observed = sha256_file(path)
        if observed != expected_hash:
            raise ValueError(f"nnU-Net model checksum mismatch: {relative}")
        observed_hashes[relative] = observed
    for path in (*required, *checkpoint_paths, metadata_path, license_path):
        relative = path.relative_to(resource_root).as_posix()
        if relative not in observed_hashes:
            raise ValueError(f"SHA256SUMS has no entry for required file: {relative}")

    return FrozenT2ModelRelease(
        id=str(metadata.get("id", "")),
        name=str(metadata.get("name", "")),
        version=str(metadata.get("version", "")),
        root_path=choice_root,
        architecture_path=resource_root,
        model_paths=checkpoint_paths,
        model_sha256=tuple(sha256_file(path) for path in checkpoint_paths),
        threshold=NNUNET_THRESHOLD,
        expected_spacing_mm=EXPECTED_SPACING_MM,
        project_git_commit="",
        ratlesnetv2_git_commit="",
        manifest_sha256=sha256_file(metadata_path),
        frozen_spec_sha256=sha256_file(required[1]),
        threshold_sha256=sha256_file(metadata_path),
        metadata={
            **metadata,
            "architecture": "PlainConvUNet",
            "runner": "nnunetv2",
            "folds": list(folds),
            "resource_sha256": observed_hashes,
        },
        runner="nnunetv2",
        folds=folds,
        checkpoint_name=NNUNET_CHECKPOINT,
    )


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

def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in T2 release file {path.name}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"T2 release file must contain a JSON object: {path.name}")
    return value


def _packaged_models_root(path: Path) -> Path:
    """Return the nearest containing resources/models (or installed models) root."""

    for candidate in (path, *path.parents):
        if candidate.name == "models":
            return candidate.resolve()
    return path.resolve()


def _read_sha256sums(path: Path) -> dict[str, str]:
    if not path.is_file():
        raise FileNotFoundError(f"Model checksum manifest is missing: {path}")
    hashes: dict[str, str] = {}
    for line_number, line in enumerate(path.read_text().splitlines(), start=1):
        if not line:
            continue
        try:
            digest, relative = line.split("  ", maxsplit=1)
        except ValueError as exc:
            raise ValueError(
                f"Invalid SHA256SUMS line {line_number}: expected two-space separator."
            ) from exc
        relative_path = Path(relative)
        if (
            len(digest) != 64
            or any(character not in "0123456789abcdef" for character in digest)
            or relative_path.is_absolute()
            or ".." in relative_path.parts
        ):
            raise ValueError(f"Invalid SHA256SUMS entry on line {line_number}.")
        hashes[relative_path.as_posix()] = digest
    return hashes
