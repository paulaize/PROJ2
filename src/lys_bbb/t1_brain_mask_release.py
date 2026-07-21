"""Validated local release contract for RS2-Net T1 brain-mask inference."""

from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any


T1_BRAIN_MASK_RELEASE_SCHEMA_VERSION = 1
RS2_REPOSITORY_URL = "https://github.com/VitoLin21/Rodent-Skull-Stripping.git"
RS2_SOURCE_COMMIT = "144b032df4885a3da00e0d1824fdd777b3cd304f"
RS2_WEIGHTS_FOLDER_URL = (
    "https://drive.google.com/drive/folders/1cTlFFGL9iTUoZOT5Rgqi2ZAyqyPlXYd-"
)
RS2_WEIGHT_SHA256 = "f7fef315d77c8568cd6d19867445ff51587505586c19b273087b65ccf3659371"


@dataclass(frozen=True)
class FrozenT1BrainMaskRelease:
    """Exact upstream source and weight used by the reviewed RS2 experiment."""

    id: str
    root_path: Path
    source_path: Path
    weights_path: Path
    source_commit: str
    weights_sha256: str
    test_time_augmentation: bool


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    """Return the hexadecimal SHA-256 digest for one file."""

    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def validate_t1_brain_mask_release(root_path: Path) -> FrozenT1BrainMaskRelease:
    """Validate a local RS2 release without importing or executing upstream code."""

    root = root_path.expanduser().resolve()
    manifest_path = root / "release.json"
    if not manifest_path.is_file():
        raise FileNotFoundError(f"T1 brain-mask release manifest is missing: {manifest_path}")
    try:
        payload: dict[str, Any] = json.loads(manifest_path.read_text())
    except (json.JSONDecodeError, OSError) as exc:
        raise ValueError(f"Cannot read T1 brain-mask release manifest: {exc}") from exc
    if payload.get("schema_version") != T1_BRAIN_MASK_RELEASE_SCHEMA_VERSION:
        raise ValueError(
            "Unsupported T1 brain-mask release schema: "
            f"{payload.get('schema_version')!r}."
        )
    if payload.get("source_commit") != RS2_SOURCE_COMMIT:
        raise ValueError("The T1 release does not use the reviewed RS2 source commit.")
    if payload.get("weights_sha256") != RS2_WEIGHT_SHA256:
        raise ValueError("The T1 release does not declare the reviewed RS2 weight hash.")
    source_path = _resolve_release_path(root, payload.get("source_path"), "source_path")
    weights_path = _resolve_release_path(root, payload.get("weights_path"), "weights_path")
    required_source_files = (
        source_path / "RS2/inference/predict.py",
        source_path / "RS2/network/RSSNet.py",
        source_path / "RS2/jsons/dataset.json",
        source_path / "RS2/jsons/plans.json",
        source_path / "LICENSE",
    )
    missing = [path for path in required_source_files if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"Incomplete RS2 source release; missing: {missing[0]}")
    if not weights_path.is_file():
        raise FileNotFoundError(f"RS2 weight file is missing: {weights_path}")
    actual_hash = sha256_file(weights_path)
    if actual_hash != RS2_WEIGHT_SHA256:
        raise ValueError(
            "RS2 weight checksum mismatch. The model file is not the one reviewed in "
            "the frozen ten-case experiment."
        )
    actual_commit = _git_commit(source_path)
    if actual_commit != RS2_SOURCE_COMMIT:
        raise ValueError(
            f"RS2 source checkout is at {actual_commit}, expected {RS2_SOURCE_COMMIT}."
        )
    release_id = str(payload.get("id", "")).strip()
    if not release_id:
        raise ValueError("The T1 brain-mask release ID is empty.")
    if payload.get("human_review_required") is not True:
        raise ValueError("T1 brain-mask releases must require human review.")
    if payload.get("test_time_augmentation") is not True:
        raise ValueError("The reviewed T1 brain-mask release must declare eight-way TTA.")
    dirty_paths = _git_status(source_path)
    if dirty_paths:
        raise ValueError(
            "The RS2 source checkout has uncommitted changes and is not a frozen "
            f"release: {dirty_paths[0]}."
        )
    return FrozenT1BrainMaskRelease(
        id=release_id,
        root_path=root,
        source_path=source_path,
        weights_path=weights_path,
        source_commit=actual_commit,
        weights_sha256=actual_hash,
        test_time_augmentation=bool(payload.get("test_time_augmentation", True)),
    )


def release_manifest_payload(*, weights_path: Path, release_root: Path) -> dict[str, Any]:
    """Build the portable manifest written by the local setup command."""

    return {
        "schema_version": T1_BRAIN_MASK_RELEASE_SCHEMA_VERSION,
        "id": "rs2net-m-seam-local-v1",
        "model": "RS2-Net",
        "role": "automatic T1 brain-mask pre-label; human review required",
        "source_repository": RS2_REPOSITORY_URL,
        "source_commit": RS2_SOURCE_COMMIT,
        "source_path": "Rodent-Skull-Stripping",
        "weights_source": RS2_WEIGHTS_FOLDER_URL,
        "weights_path": str(weights_path.resolve().relative_to(release_root.resolve())),
        "weights_sha256": RS2_WEIGHT_SHA256,
        "test_time_augmentation": True,
        "postprocessing": "T1-guided M-seam plus conservative 3-D continuity cleanup",
        "human_review_required": True,
    }


def _resolve_release_path(root: Path, value: Any, field_name: str) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"T1 brain-mask release field {field_name!r} is missing.")
    declared = Path(value)
    if declared.is_absolute():
        raise ValueError(f"T1 brain-mask release field {field_name!r} must be relative.")
    resolved = (root / declared).resolve()
    if not resolved.is_relative_to(root):
        raise ValueError(f"T1 brain-mask release field {field_name!r} escapes its root.")
    return resolved


def _git_commit(source_path: Path) -> str:
    try:
        completed = subprocess.run(
            ["git", "-C", str(source_path), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ValueError(f"Cannot verify the RS2 source commit: {exc}") from exc
    return completed.stdout.strip()


def _git_status(source_path: Path) -> list[str]:
    try:
        completed = subprocess.run(
            ["git", "-C", str(source_path), "status", "--porcelain"],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ValueError(f"Cannot verify the RS2 source worktree: {exc}") from exc
    return [line for line in completed.stdout.splitlines() if line.strip()]
