"""Typed provisional T1-weighted enhancement contract.

This module deliberately accepts an already registered post-Gd image.  Registration
is never recomputed here, which lets the desktop bind a result to the exact artifact a
reviewer approved.
"""

from __future__ import annotations

import csv
import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path

from lys_bbb.hashing import sha256_file

T1_ENHANCEMENT_METHOD_VERSION = "relative_t1w_enhancement_provisional_v1"


@dataclass(frozen=True)
class T1EnhancementConfig:
    bias_method: str = "smooth"
    bias_sigma_mm: float = 2.0
    normalization: str = "median"
    mask_slice_start: int | None = None
    mask_slice_stop: int | None = None
    save_all_maps: bool = False

    def __post_init__(self) -> None:
        if self.bias_method not in {"smooth", "none"}:
            raise ValueError(f"unknown bias method: {self.bias_method}")
        if self.normalization not in {"median", "none"}:
            raise ValueError(f"unknown normalization method: {self.normalization}")
        if self.bias_sigma_mm <= 0:
            raise ValueError("bias sigma must be positive")

    def method_spec(self) -> dict[str, object]:
        return {
            "method_version": T1_ENHANCEMENT_METHOD_VERSION,
            "scientific_status": "PROVISIONAL",
            "measurement": "semi-quantitative T1-weighted gadolinium enhancement",
            "registered_post_required": True,
            "config": asdict(self),
        }

    @property
    def method_spec_sha256(self) -> str:
        payload = json.dumps(
            self.method_spec(),
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()


@dataclass(frozen=True)
class T1EnhancementRequest:
    case_id: str
    pre_t1_path: Path
    registered_post_t1_path: Path
    approved_brain_mask_path: Path
    output_directory: Path
    config: T1EnhancementConfig = T1EnhancementConfig()
    expected_registered_post_sha256: str | None = None
    expected_brain_mask_sha256: str | None = None


@dataclass(frozen=True)
class T1EnhancementOutput:
    case_id: str
    percent_enhancement_map: Path
    percent_enhancement_sha256: str
    summary_csv: Path
    summary_sha256: str
    qc_preview_path: Path
    qc_preview_sha256: str
    metadata_path: Path
    metadata_sha256: str
    method_version: str
    method_spec_sha256: str
    metrics: tuple[dict[str, str], ...]
    metadata: dict[str, object]

def _verify_checksum(path: Path, expected: str | None, label: str) -> None:
    if expected is not None and sha256_file(path) != expected:
        raise ValueError(f"{label} changed after it was registered")


def run_t1_enhancement(request: T1EnhancementRequest) -> T1EnhancementOutput:
    """Calculate provisional enhancement from exact approved dependencies."""

    from lys_bbb.flash_pair import FlashPairRequest, process_pair_request

    _verify_checksum(
        request.registered_post_t1_path,
        request.expected_registered_post_sha256,
        "registered post-Gd image",
    )
    _verify_checksum(
        request.approved_brain_mask_path,
        request.expected_brain_mask_sha256,
        "approved brain mask",
    )
    pair_request = FlashPairRequest(
        pre=request.pre_t1_path,
        post=request.registered_post_t1_path,
        out_dir=request.output_directory,
        session_id=request.case_id,
        mask=request.approved_brain_mask_path,
        mask_slice_start=request.config.mask_slice_start,
        mask_slice_stop=request.config.mask_slice_stop,
        no_register=True,
        bias_method=request.config.bias_method,
        bias_sigma_mm=request.config.bias_sigma_mm,
        normalization=request.config.normalization,
        save_intermediates=False,
        save_all_maps=request.config.save_all_maps,
    )
    metadata = process_pair_request(pair_request)
    percent_map = request.output_directory / f"{request.case_id}_percent_enhancement.nii.gz"
    summary_csv = request.output_directory / f"{request.case_id}_summary.csv"
    qc_preview = request.output_directory / f"{request.case_id}_enhancement_qc.png"
    metadata_path = request.output_directory / f"{request.case_id}_metadata.json"
    with summary_csv.open(newline="") as handle:
        metrics = tuple(dict(row) for row in csv.DictReader(handle))
    typed_metadata = {
        **metadata,
        "method_version": T1_ENHANCEMENT_METHOD_VERSION,
        "method_spec_sha256": request.config.method_spec_sha256,
        "scientific_status": "PROVISIONAL",
        "registration_recomputed": False,
        "registered_post_sha256": sha256_file(request.registered_post_t1_path),
        "approved_brain_mask_sha256": sha256_file(request.approved_brain_mask_path),
    }
    metadata_path.write_text(
        json.dumps(typed_metadata, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return T1EnhancementOutput(
        case_id=request.case_id,
        percent_enhancement_map=percent_map,
        percent_enhancement_sha256=sha256_file(percent_map),
        summary_csv=summary_csv,
        summary_sha256=sha256_file(summary_csv),
        qc_preview_path=qc_preview,
        qc_preview_sha256=sha256_file(qc_preview),
        metadata_path=metadata_path,
        metadata_sha256=sha256_file(metadata_path),
        method_version=T1_ENHANCEMENT_METHOD_VERSION,
        method_spec_sha256=request.config.method_spec_sha256,
        metrics=metrics,
        metadata=typed_metadata,
    )
