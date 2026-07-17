#!/usr/bin/env python
"""Convert inventory-listed Bruker T1 FLASH scans into clean case folders."""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path

import brkraw

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from lys_bbb.conversion import process_scan  # noqa: E402


TARGET_ROLES = {
    "t1_flash_pre": "pre",
    "t1_flash_post": "post",
}


def case_id_from_session(session_id: str) -> str:
    animal_match = re.search(r"C\d+S\d+", session_id, re.IGNORECASE)
    day_match = re.search(r"(?:^|[_-])(D[17])(?:[_-]|$)", session_id, re.IGNORECASE)
    if animal_match is None or day_match is None:
        raise ValueError(f"Could not parse animal/day from session_id: {session_id}")

    animal = animal_match.group(0).upper()
    day = day_match.group(1).upper()
    suffix = "_bis" if re.search(r"(?:^|[_-])bis(?:[_-]|$)", session_id, re.IGNORECASE) else ""
    return f"{animal}_{day}{suffix}"


def read_inventory(path: Path) -> dict[str, dict]:
    sessions: dict[str, dict] = {}
    with path.open(newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            role = row.get("role", "").strip()
            if role not in TARGET_ROLES:
                continue

            session_id = row["session_id"].strip()
            session = sessions.setdefault(
                session_id,
                {
                    "session_id": session_id,
                    "session_path": Path(row["session_path"].strip()),
                    "roles": {},
                },
            )
            session["roles"][role] = row
    return sessions


def final_output_exists(case_dir: Path) -> bool:
    return all(
        (case_dir / name).exists()
        for name in (
            "pre_coronal.nii.gz",
            "post_coronal.nii.gz",
        )
    )


def move_output(src: Path, dst: Path, overwrite: bool) -> None:
    if not src.exists():
        raise FileNotFoundError(f"Expected converter output was not written: {src}")
    if dst.exists():
        if not overwrite:
            raise FileExistsError(f"Output already exists: {dst}")
        dst.unlink()
    src.replace(dst)


def convert_session(session: dict, out_root: Path, overwrite: bool) -> dict:
    session_id = session["session_id"]
    session_path = session["session_path"].expanduser()
    roles = session["roles"]

    missing = sorted(set(TARGET_ROLES) - set(roles))
    if missing:
        return {
            "session_id": session_id,
            "case_id": "",
            "status": "skipped_missing_roles",
            "message": ",".join(missing),
        }
    if not session_path.is_dir():
        return {
            "session_id": session_id,
            "case_id": "",
            "status": "failed",
            "message": f"missing raw folder: {session_path}",
        }

    case_id = case_id_from_session(session_id)
    case_dir = out_root / case_id
    case_dir.mkdir(parents=True, exist_ok=True)

    if final_output_exists(case_dir) and not overwrite:
        return {
            "session_id": session_id,
            "case_id": case_id,
            "status": "skipped_exists",
            "message": str(case_dir),
        }

    study = brkraw.load(str(session_path))
    metadata = {
        "case_id": case_id,
        "session_id": session_id,
        "session_path": str(session_path),
        "outputs": {},
    }

    for inventory_role, clean_role in TARGET_ROLES.items():
        row = roles[inventory_role]
        scan_id = int(row["scan_id"])
        result = process_scan(
            study=study,
            sid=scan_id,
            out_dir=case_dir,
            tag=f"{case_id}_{clean_role}",
            iso=None,
            do_qc=False,
            qc_slab_mm=0.4,
            write_slab_mm=None,
            write_fiji_display=False,
            fiji_display_xy_mm=None,
        )

        sag_path = case_dir / f"{result['stem']}_sag.nii.gz"
        cor_path = Path(result["cor_path"])
        final_cor = case_dir / f"{clean_role}_coronal.nii.gz"
        move_output(cor_path, final_cor, overwrite=overwrite)
        sag_path.unlink(missing_ok=True)

        metadata["outputs"][clean_role] = {
            "scan_id": scan_id,
            "source_role": inventory_role,
            "source_protocol": row.get("protocol", ""),
            "coronal": str(final_cor),
        }

    with (case_dir / "source_metadata.json").open("w") as f:
        json.dump(metadata, f, indent=2)
        f.write("\n")

    return {
        "session_id": session_id,
        "case_id": case_id,
        "status": "converted",
        "message": str(case_dir),
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Convert inventory-listed Bruker pre/post T1 FLASH scans into the clean "
            "output/<case>/{pre,post}_coronal.nii.gz layout."
        )
    )
    parser.add_argument(
        "--inventory",
        type=Path,
        default=Path("reports/inventory/scan_inventory.csv"),
        help="scan inventory CSV with session_path, scan_id, and role columns",
    )
    parser.add_argument(
        "--out-root",
        type=Path,
        default=Path("output/all_mice"),
        help="destination folder for clean case folders",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="replace existing case NIfTI outputs",
    )
    parser.add_argument(
        "--case-filter",
        action="append",
        default=[],
        help="optional case/session substring filter; can be passed multiple times",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=None,
        help="optional conversion manifest CSV path; default is <out-root>/conversion_manifest.csv",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    inventory = args.inventory.expanduser()
    out_root = args.out_root.expanduser()
    out_root.mkdir(parents=True, exist_ok=True)

    sessions = read_inventory(inventory)
    filters = [f.lower() for f in args.case_filter]
    records = []

    for session_id in sorted(sessions):
        session = sessions[session_id]
        case_id = case_id_from_session(session_id)
        if filters and not any(
            f in session_id.lower() or f in case_id.lower() for f in filters
        ):
            continue
        try:
            record = convert_session(session, out_root, overwrite=args.overwrite)
        except Exception as exc:
            record = {
                "session_id": session_id,
                "case_id": case_id,
                "status": "failed",
                "message": str(exc),
            }
        records.append(record)
        print(f"{record['status']:>22}  {record['case_id'] or '-':<14}  {record['session_id']}")
        if record["message"]:
            print(f"  {record['message']}")

    manifest = args.manifest.expanduser() if args.manifest else out_root / "conversion_manifest.csv"
    with manifest.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["case_id", "session_id", "status", "message"])
        writer.writeheader()
        writer.writerows(records)

    failed = [r for r in records if r["status"] == "failed"]
    converted = [r for r in records if r["status"] == "converted"]
    skipped = [r for r in records if r["status"].startswith("skipped")]
    print(f"\nmanifest: {manifest}")
    print(f"converted: {len(converted)}  skipped: {len(skipped)}  failed: {len(failed)}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
