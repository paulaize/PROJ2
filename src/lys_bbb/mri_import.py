"""Backend contracts for reviewable MRI discovery and NIfTI conversion."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path


class ScanRole(str, Enum):
    """Subject-owned MRI input roles supported by the MVP."""

    IGNORE = "IGNORE"
    T1_PRE = "T1_PRE"
    T1_POST = "T1_POST"
    T2 = "T2"


class SourceFormat(str, Enum):
    BRUKER = "BRUKER"
    NIFTI = "NIFTI"


class ImportConfidence(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class OrientationPolicy(str, Enum):
    """Storage-orientation policy applied while creating the NIfTI artifact."""

    NATIVE = "NATIVE"
    T1_CORONAL = "T1_CORONAL"


@dataclass(frozen=True)
class DiscoveryIssue:
    code: str
    message: str
    severity: str = "warning"


@dataclass(frozen=True)
class DiscoveredScan:
    proposal_id: str
    session_id: str
    source_path: Path
    source_format: SourceFormat
    scan_id: int | None
    protocol: str
    method: str
    series_comment: str
    acquisition_orientation: str
    suggested_subject_code: str
    subject_confidence: ImportConfidence
    suggested_role: ScanRole
    role_confidence: ImportConfidence
    role_reason: str
    orientation_policy: OrientationPolicy
    issues: tuple[DiscoveryIssue, ...] = ()


@dataclass(frozen=True)
class ScanDiscoveryReport:
    source_root: Path
    scans: tuple[DiscoveredScan, ...]
    session_count: int
    ignored_scan_count: int
    failures: tuple[DiscoveryIssue, ...] = ()

    @property
    def proposed_subject_codes(self) -> tuple[str, ...]:
        return tuple(sorted({scan.suggested_subject_code for scan in self.scans}))


@dataclass(frozen=True)
class ScanImportAssignment:
    proposal_id: str
    subject_code: str
    role: ScanRole
    source_path: Path
    source_format: SourceFormat
    session_id: str
    scan_id: int | None
    protocol: str
    method: str
    acquisition_orientation: str
    confidence: ImportConfidence
    orientation_policy: OrientationPolicy
    flip_axes: tuple[int, ...] = ()


@dataclass(frozen=True)
class ScanConversionResult:
    output_path: Path
    output_sha256: str
    source_sha256: str
    shape: tuple[int, ...]
    spacing_mm: tuple[float, ...]
    axis_codes: tuple[str, ...]
    provenance_path: Path
