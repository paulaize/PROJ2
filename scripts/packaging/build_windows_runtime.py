#!/usr/bin/env python3
"""Build, check, relocate and pack the T2 runtime on a Windows build machine."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import tempfile
import zipfile


def sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def run(command: list[str], *, env: dict[str, str] | None = None) -> str:
    result = subprocess.run(command, check=True, text=True, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, env=env)
    print(result.stdout, flush=True)
    return result.stdout


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--conda", required=True, type=Path)
    parser.add_argument("--output-directory", type=Path, default=Path("dist/runtime"))
    args = parser.parse_args()
    if sys.platform != "win32" or platform.machine().lower() not in {"amd64", "x86_64"}:
        parser.error("Build the Windows runtime on Windows x86-64, not on macOS/Linux.")
    source = Path(__file__).resolve().parents[2]
    specification = source / "packaging/windows-native/environment-win64.yml"
    output = args.output_directory.resolve()
    output.mkdir(parents=True, exist_ok=True)
    archive = output / "windows-runtime.zip"
    if archive.exists():
        parser.error(f"Refusing to overwrite {archive}; choose a new output directory.")
    env = dict(os.environ, PYTHONPATH=str(source / "src"),
               LYS_IRM_FEATURE_PROFILE="t2-only", QT_QPA_PLATFORM="offscreen",
               OMP_NUM_THREADS="2", MKL_NUM_THREADS="2",
               ITK_GLOBAL_DEFAULT_NUMBER_OF_THREADS="2", PYTHONNOUSERSITE="1")
    env["PYTHONUTF8"] = "1"
    env["QT_QPA_FONTDIR"] = str(Path(os.environ["WINDIR"]) / "Fonts")
    try:
        with tempfile.TemporaryDirectory(prefix="lys-win-build-") as temporary:
            prefix = Path(temporary) / "env"
            run([str(args.conda), "env", "create", "--yes", "--prefix", str(prefix),
                 "--file", str(specification)])
            python = str(prefix / "python.exe")
            env["PATH"] = f"{prefix};{prefix / 'Library/bin'};{env['PATH']}"
            run([python, "-m", "pip", "check"], env=env)
            run([python, "-m", "lys_bbb_app.windows_smoke"], env=env)
            (output / "pip-freeze.txt").write_text(
                run([python, "-m", "pip", "list", "--format=freeze"], env=env), encoding="utf-8")
            (output / "conda-explicit.txt").write_text(
                run([str(args.conda), "list", "--prefix", str(prefix), "--explicit"]),
                encoding="utf-8")
            # conda-pack belongs to the build host, never the colleague's install.
            import conda_pack

            conda_pack.pack(prefix=str(prefix), output=str(archive), format="zip")
            relocated = Path(temporary) / "relocated with spaces" / "env"
            with zipfile.ZipFile(archive) as packed:
                packed.extractall(relocated)
            moved_python = str(relocated / "python.exe")
            env["PATH"] = f"{relocated};{relocated / 'Library/bin'};{os.environ['PATH']}"
            run([moved_python, str(relocated / "Scripts/conda-unpack-script.py")], env=env)
            run([moved_python, "-m", "pip", "check"], env=env)
            run([moved_python, "-m", "lys_bbb_app.windows_smoke"], env=env)
        manifest = {
            "schema_version": 1, "platform": "win-64", "profile": "t2-only",
            "archive_sha256": sha256(archive),
            "environment_sha256": sha256(specification),
            "smoke_sha256": sha256(source / "src/lys_bbb_app/windows_smoke.py"),
            "relocation_test": "passed", "pip_check": "passed",
        }
        (output / "runtime-manifest.json").write_text(
            json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    except subprocess.CalledProcessError as exc:
        print(exc.stdout or str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
