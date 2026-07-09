"""Raw Bruker session inventory utilities for the LYS BBB pipeline."""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


T1_FLASH_PATTERN = re.compile(r"T1[_ -]?FLASH[_ -]?3D", re.IGNORECASE)
RARE_VTR_PATTERN = re.compile(r"(RARE.*VTR|VTR.*RARE|RARE[-_ ]?VTR)", re.IGNORECASE)
EXPECTED_RARE_VTR_TR_MS = (8000.0, 3600.0, 2400.0, 1480.0, 940.0, 650.0, 501.1)
NUMBER_PATTERN = re.compile(r"[-+]?(?:\d+\.\d*|\.\d+|\d+)(?:[eE][-+]?\d+)?")
TOKEN_PATTERN = re.compile(r"<[^>]*>|[-+]?(?:\d+\.\d*|\.\d+|\d+)(?:[eE][-+]?\d+)?|[A-Za-z_][A-Za-z0-9_:+.-]*")
ACQP_KEYS = {
    "ACQ_method",
    "ACQ_protocol_name",
}
METHOD_KEYS = {
    "Method",
    "PVM_EchoTime",
    "PVM_Fov",
    "PVM_Matrix",
    "PVM_NAverages",
    "PVM_NRepetitions",
    "PVM_RepetitionTime",
    "PVM_SPackArrReadOrient",
    "PVM_SPackArrSliceDistance",
    "PVM_SPackArrSliceOrient",
}
VISU_KEYS = {
    "VisuAcqEchoTime",
    "VisuAcqFlipAngle",
    "VisuAcqNumberOfAverages",
    "VisuAcqRepetitionTime",
    "VisuAcqSequenceName",
    "VisuAcquisitionProtocol",
    "VisuCoreDim",
    "VisuCoreExtent",
    "VisuCoreFrameCount",
    "VisuCoreSize",
    "VisuSeriesComment",
}
KEYS_BY_FILE = {
    "acqp": ACQP_KEYS,
    "method": METHOD_KEYS,
    "visu_pars": VISU_KEYS,
}


@dataclass
class ScanRecord:
    dataset_root: str
    session_id: str
    session_path: str
    scan_id: int | str
    method: str | None
    protocol: str | None
    role: str
    tr_ms: str
    te_ms: str
    flip_angle_degree: str
    matrix: str
    visu_size: str
    visu_extent_mm: str
    visu_dim: str
    frame_count: str
    slice_orient: str
    read_orient: str
    slice_distance_mm: str
    averages: str
    repetitions: str
    series_comment: str
    notes: str


def clean_value(value: Any) -> Any:
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="replace")
    if isinstance(value, str):
        value = value.strip()
        if len(value) >= 2 and value[0] == "<" and value[-1] == ">":
            value = value[1:-1]
        return value
    if isinstance(value, (list, tuple)):
        return [clean_value(v) for v in value]
    if isinstance(value, dict):
        return {k: clean_value(v) for k, v in value.items()}
    return value


def parse_scalar(token: str) -> Any:
    token = clean_value(token)
    if not isinstance(token, str):
        return token
    if NUMBER_PATTERN.fullmatch(token):
        number = float(token)
        return int(number) if number.is_integer() else number
    return token


def parse_jcamp_value(raw_value: str) -> Any:
    raw_value = " ".join(raw_value.split()).strip()
    if not raw_value:
        return ""

    if raw_value.startswith("("):
        close = raw_value.find(")")
        if close >= 0:
            raw_value = raw_value[close + 1:].strip()
            if not raw_value:
                return ""

    tokens = TOKEN_PATTERN.findall(raw_value)
    if not tokens:
        return clean_value(raw_value)
    parsed = [parse_scalar(token) for token in tokens]
    return parsed[0] if len(parsed) == 1 else parsed


def parse_param_file(path: Path, selected_keys: set[str]) -> dict[str, Any]:
    params: dict[str, Any] = {}
    if not path.exists():
        return params

    current_key: str | None = None
    current_value: list[str] = []

    def flush() -> None:
        nonlocal current_key, current_value
        if current_key is not None:
            params[current_key] = parse_jcamp_value("\n".join(current_value))
        current_key = None
        current_value = []

    for line in path.read_text(errors="replace").splitlines():
        if line.startswith("##$") and "=" in line:
            flush()
            key, value = line[3:].split("=", 1)
            if key in selected_keys:
                current_key = key
                current_value = [value]
            else:
                current_key = None
                current_value = []
        elif line.startswith("##") or line.startswith("$$"):
            flush()
        elif current_key is not None:
            current_value.append(line)
        if selected_keys.issubset(params.keys()):
            flush()
            break
    flush()
    return params


def read_scan_params(scan_dir: Path) -> dict[str, Any]:
    params: dict[str, Any] = {}
    for filename, keys in KEYS_BY_FILE.items():
        parsed = parse_param_file(scan_dir / filename, keys)
        for key, value in parsed.items():
            params.setdefault(key, value)
    return params


def param(params: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = params.get(key)
        if value not in (None, ""):
            return clean_value(value)
    return None


def text_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, tuple, dict)):
        return json.dumps(value, separators=(",", ":"))
    return str(clean_value(value))


def scan_dirs(session_dir: Path) -> list[Path]:
    return sorted(
        (p for p in session_dir.iterdir() if p.is_dir() and p.name.isdigit()),
        key=lambda path: int(path.name),
    )


def classify_role(scan_id: int | str, method: str | None, protocol: str | None) -> str:
    protocol_text = protocol or ""
    method_text = method or ""
    if RARE_VTR_PATTERN.search(protocol_text) or RARE_VTR_PATTERN.search(method_text):
        return "rare_vtr_candidate"
    if T1_FLASH_PATTERN.search(protocol_text):
        if str(scan_id) == "3":
            return "t1_flash_pre_candidate"
        if str(scan_id) == "6":
            return "t1_flash_post_candidate"
        return "t1_flash_candidate"
    if "localizer" in protocol_text.lower():
        return "localizer"
    if "tof" in protocol_text.lower():
        return "tof_candidate"
    if "t2" in protocol_text.lower():
        return "t2_candidate"
    return "other"


def inventory_session(dataset_root: Path, session_dir: Path) -> list[ScanRecord]:
    rows: list[ScanRecord] = []
    for scan_dir in scan_dirs(session_dir):
        sid = int(scan_dir.name)
        params = read_scan_params(scan_dir)
        method = param(params, "Method", "ACQ_method", "VisuAcqSequenceName")
        protocol = param(params, "ACQ_protocol_name", "VisuAcquisitionProtocol")
        role = classify_role(sid, method, protocol)
        rows.append(
            ScanRecord(
                dataset_root=str(dataset_root),
                session_id=session_dir.name,
                session_path=str(session_dir),
                scan_id=sid,
                method=method,
                protocol=protocol,
                role=role,
                tr_ms=text_value(param(params, "PVM_RepetitionTime", "VisuAcqRepetitionTime")),
                te_ms=text_value(param(params, "PVM_EchoTime", "VisuAcqEchoTime")),
                flip_angle_degree=text_value(param(params, "VisuAcqFlipAngle")),
                matrix=text_value(param(params, "PVM_Matrix")),
                visu_size=text_value(param(params, "VisuCoreSize")),
                visu_extent_mm=text_value(param(params, "VisuCoreExtent")),
                visu_dim=text_value(param(params, "VisuCoreDim")),
                frame_count=text_value(param(params, "VisuCoreFrameCount")),
                slice_orient=text_value(param(params, "PVM_SPackArrSliceOrient")),
                read_orient=text_value(param(params, "PVM_SPackArrReadOrient")),
                slice_distance_mm=text_value(param(params, "PVM_SPackArrSliceDistance")),
                averages=text_value(param(params, "PVM_NAverages", "VisuAcqNumberOfAverages")),
                repetitions=text_value(param(params, "PVM_NRepetitions")),
                series_comment=text_value(param(params, "VisuSeriesComment")),
                notes="",
            )
        )

    t1_rows = [row for row in rows if row.role.startswith("t1_flash")]
    if len(t1_rows) == 2:
        t1_rows = sorted(t1_rows, key=lambda row: int(row.scan_id))
        t1_rows[0].role = "t1_flash_pre"
        t1_rows[1].role = "t1_flash_post"
    elif t1_rows:
        note = f"expected 2 T1 FLASH scans, found {len(t1_rows)}"
        for row in t1_rows:
            row.notes = note

    return rows


def looks_like_bruker_session(path: Path) -> bool:
    if not path.is_dir():
        return False
    return any((p / "acqp").exists() and (p / "method").exists() for p in scan_dirs(path))


def session_dirs(raw_root: Path) -> list[Path]:
    return sorted(
        (p for p in raw_root.iterdir() if looks_like_bruker_session(p)),
        key=lambda p: p.name,
    )


def summarize(rows: list[ScanRecord], failures: list[dict[str, str]]) -> dict[str, Any]:
    sessions = sorted({row.session_id for row in rows})
    protocols: dict[str, int] = {}
    roles: dict[str, int] = {}
    rare_vtr_trs: list[float] = []
    for row in rows:
        protocols[row.protocol or ""] = protocols.get(row.protocol or "", 0) + 1
        roles[row.role] = roles.get(row.role, 0) + 1
        if row.role == "rare_vtr_candidate":
            try:
                rare_vtr_trs.append(float(row.tr_ms))
            except ValueError:
                pass
    missing_rare_vtr = [
        tr for tr in EXPECTED_RARE_VTR_TR_MS
        if not any(abs(found - tr) < 0.2 for found in rare_vtr_trs)
    ]
    return {
        "session_count": len(sessions),
        "scan_count": len(rows),
        "failure_count": len(failures),
        "sessions": sessions,
        "role_counts": dict(sorted(roles.items())),
        "protocol_counts": dict(sorted(protocols.items())),
        "rare_vtr_tr_ms_found": sorted(rare_vtr_trs),
        "rare_vtr_tr_ms_expected": list(EXPECTED_RARE_VTR_TR_MS),
        "rare_vtr_tr_ms_missing": missing_rare_vtr,
        "failures": failures,
    }


def write_csv(rows: list[ScanRecord], out_csv: Path) -> None:
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(asdict(rows[0]).keys()) if rows else list(ScanRecord.__dataclass_fields__)
    with out_csv.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(asdict(row))


def write_json(data: dict[str, Any], out_json: Path) -> None:
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(data, indent=2) + "\n")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Inventory Bruker sessions for the LYS BBB MRI V1 pipeline.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("raw_root", type=Path, help="folder containing Bruker session folders")
    parser.add_argument(
        "-o", "--out-dir", type=Path, default=Path("reports/inventory"),
        help="directory for inventory CSV and summary JSON",
    )
    parser.add_argument("--csv-name", default="scan_inventory.csv")
    parser.add_argument("--summary-name", default="scan_inventory_summary.json")
    parser.add_argument("--fail-fast", action="store_true")
    parser.add_argument(
        "--limit-sessions", type=int, default=None,
        help="process only the first N detected sessions; useful for smoke tests",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    raw_root = args.raw_root.expanduser()
    if not raw_root.is_dir():
        print(f"raw root is not a directory: {raw_root}", file=sys.stderr)
        return 2

    rows: list[ScanRecord] = []
    failures: list[dict[str, str]] = []
    sessions = session_dirs(raw_root)
    if not sessions:
        print(f"no Bruker session directories found under: {raw_root}", file=sys.stderr)
        return 2
    if args.limit_sessions is not None:
        sessions = sessions[:args.limit_sessions]

    for session_dir in sessions:
        try:
            rows.extend(inventory_session(raw_root, session_dir))
        except Exception as exc:
            failure = {"session_id": session_dir.name, "error": repr(exc)}
            failures.append(failure)
            print(f"FAILED {session_dir.name}: {exc}", file=sys.stderr)
            if args.fail_fast:
                break

    out_csv = args.out_dir / args.csv_name
    out_summary = args.out_dir / args.summary_name
    write_csv(rows, out_csv)
    write_json(summarize(rows, failures), out_summary)
    print(f"sessions: {len({row.session_id for row in rows})}/{len(sessions)}")
    print(f"scans: {len(rows)}")
    print(f"failures: {len(failures)}")
    print(f"csv: {out_csv}")
    print(f"summary: {out_summary}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
