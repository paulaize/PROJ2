"""Read-only discovery of Bruker sessions and MRI input candidates.

Discovery produces proposals, not scientific truth.  Subject identifiers and scan
roles are deliberately accompanied by confidence and issues so the desktop can require
an explicit human confirmation before it creates any NIfTI artifacts.
"""

from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path

from lys_bbb.inventory import ScanRecord, inventory_session, looks_like_bruker_session
from lys_bbb.mri_import import (
    DiscoveredScan,
    DiscoveryIssue,
    ImportConfidence,
    OrientationPolicy,
    ScanDiscoveryReport,
    ScanRole,
    SourceFormat,
)


_CASE_ANIMAL = re.compile(r"C\d+S\d+", re.IGNORECASE)
_CASE_DAY = re.compile(r"(?:^|[_-])(D\d+)(?:[_-]|$)", re.IGNORECASE)
_BD_ID = re.compile(r"BD[_-]\d+(?:[_-]\d+)?", re.IGNORECASE)
_PRE = re.compile(r"(?:pre[ _-]?gd|pre[ _-]?contrast|(?:^|[_-])pre(?:[_-]|$))", re.I)
_POST = re.compile(r"(?:post[ _-]?gd|post[ _-]?contrast|(?:^|[_-])post(?:[_-]|$))", re.I)
_T1 = re.compile(r"T1.*FLASH.*3D|T1[_ -]?FLASH", re.I)
_T2 = re.compile(r"(?:^|[^A-Za-z0-9])T2(?:W|[_ -]|$)", re.I)
_SKIP_DIRECTORIES = {
    ".git",
    "AdjResult",
    "derivatives",
    "exports",
    "logs",
    "outputs",
    "pdata",
    "reports",
    "work",
}


def discover_mri_source(source_root: str | Path, *, max_depth: int = 5) -> ScanDiscoveryReport:
    """Discover reviewable MRI candidates below one source root without writing to it."""

    root = Path(source_root).expanduser().resolve()
    if not root.is_dir():
        raise FileNotFoundError(f"MRI source folder not found: {root}")

    sessions = _discover_bruker_sessions(root, max_depth=max_depth)
    scans: list[DiscoveredScan] = []
    failures: list[DiscoveryIssue] = []
    for session in sessions:
        try:
            rows = inventory_session(root, session)
            scans.extend(_proposals_for_bruker_session(session, rows))
        except Exception as exc:
            failures.append(
                DiscoveryIssue(
                    "BRUKER_SESSION_UNREADABLE",
                    f"Could not inspect {session.name}: {exc}",
                    "error",
                )
            )

    nifti_scans = _discover_nifti_candidates(
        root,
        max_depth=max_depth,
        excluded_sessions=set(sessions),
    )
    scans.extend(nifti_scans)
    scans.sort(
        key=lambda scan: (
            scan.suggested_subject_code.casefold(),
            scan.session_id.casefold(),
            scan.scan_id if scan.scan_id is not None else 10_000,
            scan.source_path.name.casefold(),
        )
    )
    ignored = sum(scan.suggested_role is ScanRole.IGNORE for scan in scans)
    if not sessions and not nifti_scans:
        failures.append(
            DiscoveryIssue(
                "NO_MRI_INPUTS_FOUND",
                "No Bruker sessions or recognisable NIfTI MRI files were found below "
                f"{root}.",
                "error",
            )
        )
    return ScanDiscoveryReport(
        source_root=root,
        scans=tuple(scans),
        session_count=len(sessions) + len({scan.session_id for scan in nifti_scans}),
        ignored_scan_count=ignored,
        failures=tuple(failures),
    )


def infer_subject_code(name: str) -> tuple[str, ImportConfidence, tuple[DiscoveryIssue, ...]]:
    """Infer a case ID conservatively from a session or NIfTI name."""

    animal = _CASE_ANIMAL.search(name)
    day = _CASE_DAY.search(name)
    if animal is not None:
        code = animal.group(0).upper()
        confidence = ImportConfidence.MEDIUM
        if day is not None:
            code = f"{code}_{day.group(1).upper()}"
            confidence = ImportConfidence.HIGH
        if re.search(r"(?:^|[_-])bis(?:[_-]|$)", name, re.I):
            code += "_bis"
        return code, confidence, ()

    bd = _BD_ID.search(name)
    if bd is not None:
        code = re.sub(r"-", "_", bd.group(0).upper())
        if day is not None:
            code = f"{code}_{day.group(1).upper()}"
        return (
            code,
            ImportConfidence.MEDIUM,
            (
                DiscoveryIssue(
                    "SUBJECT_ID_REVIEW_REQUIRED",
                    "A BD-style identifier was inferred from the session name; confirm it "
                    "against the acquisition record.",
                ),
            ),
        )

    stem = _strip_nifti_suffix(Path(name).name)
    stem = re.sub(r"^\d{8}[_-]\d{6}[_-]*", "", stem)
    code = re.sub(r"[^A-Za-z0-9._-]+", "_", stem).strip("._-") or "subject"
    return (
        code,
        ImportConfidence.LOW,
        (
            DiscoveryIssue(
                "SUBJECT_ID_AMBIGUOUS",
                "No recognised mouse identifier was found. Edit the proposed subject ID "
                "before import.",
            ),
        ),
    )


def _discover_bruker_sessions(root: Path, *, max_depth: int) -> list[Path]:
    sessions: list[Path] = []
    for current, directory_names, _file_names in os.walk(root):
        path = Path(current)
        depth = len(path.relative_to(root).parts)
        directory_names[:] = [
            name
            for name in directory_names
            if name not in _SKIP_DIRECTORIES and not name.startswith(".")
        ]
        if looks_like_bruker_session(path):
            sessions.append(path)
            directory_names[:] = []
            continue
        if depth >= max_depth:
            directory_names[:] = []
    return sorted(sessions, key=lambda path: str(path).casefold())


def _proposals_for_bruker_session(
    session: Path,
    rows: list[ScanRecord],
) -> list[DiscoveredScan]:
    subject_code, subject_confidence, subject_issues = infer_subject_code(session.name)
    t2_roles = _rank_t2_candidates(rows)
    proposals: list[DiscoveredScan] = []
    for row in rows:
        role, confidence, reason, role_issues = _role_for_bruker_row(row, t2_roles)
        issues = subject_issues + role_issues
        proposals.append(
            DiscoveredScan(
                proposal_id=_proposal_id(session, row.scan_id),
                session_id=session.name,
                source_path=session,
                source_format=SourceFormat.BRUKER,
                scan_id=int(row.scan_id),
                protocol=row.protocol or "",
                method=row.method or "",
                series_comment=row.series_comment,
                acquisition_orientation=row.slice_orient,
                suggested_subject_code=subject_code,
                subject_confidence=subject_confidence,
                suggested_role=role,
                role_confidence=confidence,
                role_reason=reason,
                orientation_policy=(
                    OrientationPolicy.T1_CORONAL
                    if role in {ScanRole.T1_PRE, ScanRole.T1_POST}
                    else OrientationPolicy.NATIVE
                ),
                issues=issues,
            )
        )
    return proposals


def _rank_t2_candidates(rows: list[ScanRecord]) -> dict[int, tuple[bool, bool]]:
    candidates: list[tuple[int, int]] = []
    for row in rows:
        text = " ".join((row.protocol or "", row.method or "", row.series_comment or ""))
        if not _T2.search(text):
            continue
        score = 0
        if "rare" in (row.method or "").casefold():
            score += 5
        if re.search(r"haute[_ -]?resolution|high[_ -]?resolution|t2w", text, re.I):
            score += 4
        if re.search(r"t2s|t2\*|t2star", text, re.I):
            score -= 8
        if "fcflash" in (row.method or "").casefold():
            score -= 4
        candidates.append((int(row.scan_id), score))
    if not candidates:
        return {}
    candidates.sort(key=lambda item: (-item[1], item[0]))
    best_score = candidates[0][1]
    best = [scan_id for scan_id, score in candidates if score == best_score and score > 0]
    selected = min(best) if best else None
    ambiguous = len(best) > 1
    return {
        scan_id: (scan_id == selected, ambiguous)
        for scan_id, _score in candidates
    }


def _role_for_bruker_row(
    row: ScanRecord,
    t2_roles: dict[int, tuple[bool, bool]],
) -> tuple[ScanRole, ImportConfidence, str, tuple[DiscoveryIssue, ...]]:
    text = " ".join((row.protocol or "", row.series_comment or ""))
    if _T1.search(text):
        if _PRE.search(text):
            return ScanRole.T1_PRE, ImportConfidence.HIGH, "pre-Gd acquisition metadata", ()
        if _POST.search(text):
            return ScanRole.T1_POST, ImportConfidence.HIGH, "post-Gd acquisition metadata", ()
        if row.role == "t1_flash_pre":
            return (
                ScanRole.T1_PRE,
                ImportConfidence.MEDIUM,
                "earlier scan in the detected T1 FLASH pair",
                (
                    DiscoveryIssue(
                        "T1_ROLE_FROM_ORDER",
                        "Pre/post was inferred from scan order; confirm contrast timing.",
                    ),
                ),
            )
        if row.role == "t1_flash_post":
            return (
                ScanRole.T1_POST,
                ImportConfidence.MEDIUM,
                "later scan in the detected T1 FLASH pair",
                (
                    DiscoveryIssue(
                        "T1_ROLE_FROM_ORDER",
                        "Pre/post was inferred from scan order; confirm contrast timing.",
                    ),
                ),
            )
        return (
            ScanRole.IGNORE,
            ImportConfidence.LOW,
            "unpaired T1 FLASH candidate",
            (
                DiscoveryIssue(
                    "T1_PAIR_AMBIGUOUS",
                    "A T1 FLASH scan was found but its pre/post role is ambiguous.",
                ),
            ),
        )

    selected, ambiguous = t2_roles.get(int(row.scan_id), (False, False))
    if selected:
        issues: tuple[DiscoveryIssue, ...] = ()
        confidence = ImportConfidence.HIGH
        if ambiguous:
            confidence = ImportConfidence.LOW
            issues = (
                DiscoveryIssue(
                    "MULTIPLE_T2_RARE_CANDIDATES",
                    "More than one equally ranked high-resolution T2 RARE scan was found; "
                    "confirm the intended acquisition.",
                ),
            )
        return ScanRole.T2, confidence, "highest-ranked T2-weighted RARE acquisition", issues

    if int(row.scan_id) in t2_roles:
        return (
            ScanRole.IGNORE,
            ImportConfidence.MEDIUM,
            "alternative T2/T2* acquisition",
            (
                DiscoveryIssue(
                    "ALTERNATIVE_T2_SCAN",
                    "This T2-named scan was not selected as the native T2w input. It can "
                    "be assigned manually if the proposal is wrong.",
                    "info",
                ),
            ),
        )
    return ScanRole.IGNORE, ImportConfidence.HIGH, "not an MVP T1/T2 input", ()


def _discover_nifti_candidates(
    root: Path,
    *,
    max_depth: int,
    excluded_sessions: set[Path],
) -> list[DiscoveredScan]:
    proposals: list[DiscoveredScan] = []
    for current, directory_names, file_names in os.walk(root):
        path = Path(current)
        depth = len(path.relative_to(root).parts)
        directory_names[:] = [
            name
            for name in directory_names
            if name not in _SKIP_DIRECTORIES and not name.startswith(".")
        ]
        if any(path == session or session in path.parents for session in excluded_sessions):
            directory_names[:] = []
            continue
        if depth >= max_depth:
            directory_names[:] = []
        for filename in sorted(file_names):
            if not (filename.casefold().endswith(".nii") or filename.casefold().endswith(".nii.gz")):
                continue
            role, confidence, reason = _nifti_role(filename)
            if role is ScanRole.IGNORE:
                continue
            source = path / filename
            subject_code, subject_confidence, issues = infer_subject_code(
                f"{path.name}_{filename}"
            )
            proposals.append(
                DiscoveredScan(
                    proposal_id=_proposal_id(source, None),
                    session_id=path.name,
                    source_path=source,
                    source_format=SourceFormat.NIFTI,
                    scan_id=None,
                    protocol="NIfTI file",
                    method="NIfTI",
                    series_comment="",
                    acquisition_orientation="from NIfTI affine",
                    suggested_subject_code=subject_code,
                    subject_confidence=subject_confidence,
                    suggested_role=role,
                    role_confidence=confidence,
                    role_reason=reason,
                    orientation_policy=(
                        OrientationPolicy.T1_CORONAL
                        if role in {ScanRole.T1_PRE, ScanRole.T1_POST}
                        else OrientationPolicy.NATIVE
                    ),
                    issues=issues,
                )
            )
    return proposals


def _nifti_role(filename: str) -> tuple[ScanRole, ImportConfidence, str]:
    stem = _strip_nifti_suffix(filename)
    if _PRE.search(stem) and re.search(r"t1|coronal", stem, re.I):
        return ScanRole.T1_PRE, ImportConfidence.MEDIUM, "pre-T1 filename token"
    if _POST.search(stem) and re.search(r"t1|coronal", stem, re.I):
        return ScanRole.T1_POST, ImportConfidence.MEDIUM, "post-T1 filename token"
    if re.search(r"(?:^|[_-])t2w?(?:[_-]|$)|scan(?:[_-]|$)", stem, re.I):
        if not re.search(r"mask|lesion|label|prob", stem, re.I):
            return ScanRole.T2, ImportConfidence.MEDIUM, "T2 filename token"
    return ScanRole.IGNORE, ImportConfidence.LOW, "unrecognised NIfTI role"


def _strip_nifti_suffix(name: str) -> str:
    return name[:-7] if name.casefold().endswith(".nii.gz") else Path(name).stem


def _proposal_id(path: Path, scan_id: int | str | None) -> str:
    value = f"{path.resolve()}::{scan_id if scan_id is not None else ''}"
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:20]
