#!/usr/bin/env python
"""Run MouseBrainExtractor on a benchmark-package manifest."""

from __future__ import annotations

import argparse
import csv
import subprocess
import sys
import zipfile
from pathlib import Path


def read_manifest(path: Path) -> list[dict[str, str]]:
    with path.open(newline="") as f:
        return list(csv.DictReader(f))


def zip_dir(source_dir: Path, zip_path: Path) -> None:
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(source_dir.rglob("*")):
            if path.is_file():
                zf.write(path, path.relative_to(source_dir.parent))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run MouseBrainExtractor on all cases listed in a benchmark manifest. "
            "Outputs are pre-label masks for manual correction, not final analysis masks."
        )
    )
    parser.add_argument("--manifest", type=Path, default=Path("benchmark_manifest.csv"))
    parser.add_argument("--package-root", type=Path, default=None)
    parser.add_argument("--out-dir", type=Path,
                        default=Path("derivatives/brain_seg/external/mousebrainextractor"))
    parser.add_argument("--device", choices=["cuda", "cpu"], default="cuda")
    parser.add_argument("--batch-rois", type=int, default=1)
    parser.add_argument("--dstype", choices=["auto", "invivo_iso", "invivo_aniso", "exvivo"],
                        default="auto")
    parser.add_argument("--skip-existing", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--continue-on-error", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--zip-name", default="mousebrainextractor_prelabels.zip")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    manifest = args.manifest.expanduser().resolve()
    package_root = args.package_root.expanduser().resolve() if args.package_root else manifest.parent.resolve()
    script = Path(__file__).resolve().with_name("run_one.py")
    out_dir = args.out_dir.expanduser()
    out_dir.mkdir(parents=True, exist_ok=True)

    rows = read_manifest(manifest)
    statuses: list[dict[str, str]] = []
    for i, row in enumerate(rows, start=1):
        case_id = row["case_id"]
        image = package_root / row["image"]
        mask = out_dir / f"{case_id}_mousebrainextractor_mask.nii.gz"
        print(f"\n[{i}/{len(rows)}] {case_id}")
        if args.skip_existing and mask.exists():
            print(f"skip existing: {mask}")
            statuses.append({"case_id": case_id, "status": "skipped_existing", "message": str(mask)})
            continue

        cmd = [
            sys.executable,
            str(script),
            "--image", str(image),
            "--case-id", case_id,
            "--out-dir", str(out_dir),
            "--device", args.device,
            "--batch-rois", str(args.batch_rois),
            "--dstype", args.dstype,
        ]
        print(" ".join(cmd))
        try:
            subprocess.run(cmd, check=True)
        except subprocess.CalledProcessError as exc:
            message = f"exit status {exc.returncode}"
            statuses.append({"case_id": case_id, "status": "failed", "message": message})
            print(f"FAILED {case_id}: {message}", file=sys.stderr)
            if not args.continue_on_error:
                break
        else:
            statuses.append({"case_id": case_id, "status": "ok", "message": str(mask)})

    status_csv = out_dir / "batch_status.csv"
    with status_csv.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["case_id", "status", "message"])
        writer.writeheader()
        writer.writerows(statuses)

    zip_path = out_dir.parent / args.zip_name
    zip_dir(out_dir, zip_path)
    failed = [row for row in statuses if row["status"] == "failed"]
    print(f"\nstatus: {status_csv}")
    print(f"download pre-label zip: {zip_path}")
    print(f"ok/skipped: {len(statuses) - len(failed)}  failed: {len(failed)}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
