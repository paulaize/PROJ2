"""Persistent application state for reviewed MRI inputs."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from lys_bbb.mri_import import (
    DiscoveredScan,
    DiscoveryIssue,
    ImportConfidence,
    OrientationPolicy,
    ScanConversionResult,
    ScanDiscoveryReport,
    ScanImportAssignment,
    ScanRole,
    SourceFormat,
)


__all__ = [
    "DiscoveredScan",
    "DiscoveryIssue",
    "ImportConfidence",
    "OrientationPolicy",
    "ScanConversionResult",
    "ScanDiscoveryReport",
    "ScanImportAssignment",
    "ScanImportState",
    "ScanInputRecord",
    "ScanRole",
    "SourceFormat",
]


class ScanImportState(str, Enum):
    QUEUED = "QUEUED"
    CONVERTING = "CONVERTING"
    CONVERTED = "CONVERTED"
    FAILED = "FAILED"
    SUPERSEDED = "SUPERSEDED"


@dataclass(frozen=True)
class ScanInputRecord:
    id: str
    proposal_id: str
    subject_id: str
    subject_code: str
    role: ScanRole
    version: int
    active: bool
    state: ScanImportState
    source_path: Path
    source_format: SourceFormat
    session_id: str
    scan_id: int | None
    protocol: str
    method: str
    acquisition_orientation: str
    confidence: ImportConfidence
    orientation_policy: OrientationPolicy
    flip_axes: tuple[int, ...]
    output_path: Path | None
    output_sha256: str | None
    source_sha256: str | None
    output_shape: tuple[int, ...]
    output_spacing_mm: tuple[float, ...]
    output_axis_codes: tuple[str, ...]
    error_message: str | None
    created_at: str
    updated_at: str
